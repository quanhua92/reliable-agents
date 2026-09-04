from pathlib import Path

import uuid_utils.compat as uuid

from reliable_agents.digest import action_request_digest
from reliable_agents.evidence import create_run_evidence
from reliable_agents.models import (
    Decision,
    DoneContract,
    FinalState,
    Goal,
    RunOutcome,
    WorkerOutput,
)
from reliable_agents.policy import StaticPolicyEngine
from reliable_agents.storage import JsonlEffectStore, JsonlEventStore, StorageLayout
from reliable_agents.tool import WriteValueTool
from reliable_agents.verifier import IndependentVerifier
from reliable_agents.worker import EvidenceGuidedWorker


def reconstruct_final_state(events: list[dict]) -> FinalState | None:
    for event in reversed(events):
        match event["kind"]:
            case "RunCompleted":
                return FinalState.VERIFIED
            case "RunBlocked":
                return FinalState.BLOCKED
            case "RunEscalated":
                return FinalState.ESCALATED
    return None


def execute(
    goal: Goal,
    contract: DoneContract,
    authoritative_tier: int,
    retry_budget: int = 2,
    run_id: str | None = None,
    base_directory: Path | None = None,
) -> RunOutcome:
    if run_id is None:
        run_id = str(uuid.uuid7())

    layout = StorageLayout.create(
        project_path=Path.cwd(), base_directory=base_directory
    )
    events = JsonlEventStore(layout)
    effects = JsonlEffectStore(layout)

    history = events.load(run_id)
    existing_state = reconstruct_final_state(history)

    if existing_state is not None:
        raise RuntimeError(f"Run {run_id} is already terminal: {existing_state.value}")

    verifier = IndependentVerifier()
    tool = WriteValueTool()
    policy = StaticPolicyEngine()
    worker = EvidenceGuidedWorker()

    previous_failure = None
    checks = []
    tools_used = set()

    events.append(
        run_id=run_id,
        kind="GoalCreated",
        payload={
            "goal_id": goal.goal_id,
            "task_class": goal.task_class,
            "description": goal.description,
        },
    )
    events.append(
        run_id=run_id,
        kind="DoneContractBound",
        payload={
            "contract_id": contract.contract_id,
            "version": contract.version,
            "required_value": contract.required_value,
        },
    )

    admission = policy.admit(goal=goal, authoritative_tier=authoritative_tier)

    print("run_id", run_id)
    print("admission", admission)

    events.append(
        run_id=run_id,
        kind="AdmissionDecided",
        payload={
            "decision": admission.decision.value,
            "reason": admission.reason,
            "authoritative_tier": authoritative_tier,
        },
    )

    if admission.decision is not Decision.ALLOW:
        events.append(
            run_id,
            "RunBlocked",
            {
                "reason": admission.reason,
            },
        )
        return RunOutcome(
            run_id=run_id,
            state=FinalState.BLOCKED,
            evidence=None,
            last_verification=None,
        )

    for attempt in range(1, retry_budget + 1):
        print("=" * 80)
        print(f"attempt {attempt}")

        events.append(
            run_id=run_id, kind="AttemptStarted", payload={"attempt": attempt}
        )

        turn = worker.run(
            goal=goal,
            contract=contract,
            previous_failure=previous_failure,
            effect_sequence=attempt,
        )
        print("worker turn:", turn)

        request_digest = action_request_digest(turn.action)

        events.append(
            run_id=run_id,
            kind="WorkerTurnCreated",
            payload={
                "attempt": attempt,
                "tool_name": turn.action.tool_name,
                "arguments": turn.action.arguments,
                "mutating": turn.action.mutating,
                "effect_id": turn.action.effect_id,
                "request_digest": request_digest,
                "idempotency_key": turn.action.idempotency_key,
                "claimed_tier": turn.action.claimed_tier,
                "summary": turn.summary,
            },
        )

        authorization = policy.authorize(
            request=turn.action, authoritative_tier=authoritative_tier
        )
        print("authorization:", authorization)

        events.append(
            run_id,
            "AuthorizationDecided",
            {
                "attempt": attempt,
                "decision": authorization.decision.value,
                "reason": authorization.reason,
                "authoritative_tier": authoritative_tier,
            },
        )

        if authorization.decision is not Decision.ALLOW:
            events.append(
                run_id,
                "RunBlocked",
                {
                    "attempt": attempt,
                    "reason": authorization.reason,
                },
            )
            return RunOutcome(
                run_id=run_id,
                state=FinalState.BLOCKED,
                evidence=None,
                last_verification=previous_failure,
            )

        existing_effect = effects.lookup(turn.action.idempotency_key)
        effect_reused = False

        # === TOOL EFFECT ===
        # NONE
        #   -> record INTENT
        #   -> execute
        #   -> record COMPLETED
        #
        # COMPLETED + same digest
        #   -> reuse result
        #
        # INTENT
        #   -> ambiguous
        #   -> ESCALATE
        #
        # same key + different digest
        #   -> ESCALATE
        if existing_effect is None:
            effects.record_intent(request=turn.action, request_digest=request_digest)
            output = tool.execute(turn.action)
            effects.record_success(
                request=turn.action, request_digest=request_digest, output=output
            )
        else:
            stored_digest = str(existing_effect["request_digest"])
            if stored_digest != request_digest:
                events.append(
                    run_id,
                    "RunEscalated",
                    {
                        "reason": "idempotency key reused with different request",
                        "effect_id": turn.action.effect_id,
                        "idempotency_key": turn.action.idempotency_key,
                    },
                )
                return RunOutcome(
                    run_id=run_id,
                    state=FinalState.ESCALATED,
                    evidence=None,
                    last_verification=previous_failure,
                )
            status = str(existing_effect["status"])

            if status == "INTENT":
                events.append(
                    run_id,
                    "RunEscalated",
                    {
                        "reason": "effect requires reconciliation",
                        "effect_id": turn.action.effect_id,
                        "idempotency_key": turn.action.idempotency_key,
                    },
                )
                return RunOutcome(
                    run_id=run_id,
                    state=FinalState.ESCALATED,
                    evidence=None,
                    last_verification=previous_failure,
                )
            if status == "COMPLETED":
                result = existing_effect["result"]

                if not isinstance(result, dict):
                    raise RuntimeError("Completed effect has no result")

                output = WorkerOutput(
                    value=int(result["value"]), summary=str(result["summary"])
                )
                effect_reused = True
            else:
                raise RuntimeError(f"Unknown effect status: {status}")

        tools_used.add(tool.version)

        events.append(
            run_id,
            "ToolCompleted",
            {
                "attempt": attempt,
                "tool": tool.version,
                "value": output.value,
                "summary": output.summary,
                "effect_id": turn.action.effect_id,
                "idempotency_key": turn.action.idempotency_key,
                "reused": effect_reused,
            },
        )

        verification = verifier.verify(goal=goal, contract=contract, output=output)
        checks.append(verification.check)

        events.append(
            run_id,
            "VerificationCompleted",
            {
                "attempt": attempt,
                "passed": verification.passed,
                "check": verification.check,
                "category": verification.category,
                "evidence": verification.evidence,
                "retryable": verification.retryable,
            },
        )

        print("tool output summary:", output.summary)
        print("tool output value:", output.value)
        print("verification:", verification)

        if verification.passed:
            evidence = create_run_evidence(
                run_id=run_id,
                goal=goal,
                contract=contract,
                attempts=attempt,
                checks=tuple(checks),
                tools_used=tools_used,
                runtime_components={
                    "worker": worker.version,
                    "verifier": verifier.version,
                    "policy": policy.version,
                },
            )
            events.append(
                run_id,
                "RunEvidenceCreated",
                {
                    "state": FinalState.VERIFIED.value,
                    "evidence_digest": evidence.evidence_digest,
                    "attempts": attempt,
                },
            )

            events.append(
                run_id,
                "RunCompleted",
                {
                    "state": FinalState.VERIFIED.value,
                    "attempts": attempt,
                    "evidence_digest": evidence.evidence_digest,
                },
            )
            return RunOutcome(
                run_id=run_id,
                state=FinalState.VERIFIED,
                evidence=evidence,
                last_verification=verification,
            )
        if not verification.retryable:
            events.append(
                run_id,
                "RunEscalated",
                {
                    "attempt": attempt,
                    "reason": verification.category,
                },
            )
            return RunOutcome(
                run_id=run_id,
                state=FinalState.ESCALATED,
                evidence=None,
                last_verification=verification,
            )

        if attempt < retry_budget:
            events.append(
                run_id,
                "RecoveryStarted",
                {
                    "attempt": attempt,
                    "category": verification.category,
                    "evidence": verification.evidence,
                },
            )
        previous_failure = verification

    events.append(
        run_id,
        "RunEscalated",
        {
            "attempt": retry_budget,
            "reason": "retry_budget_exhausted",
        },
    )
    return RunOutcome(
        run_id=run_id,
        state=FinalState.ESCALATED,
        evidence=None,
        last_verification=previous_failure,
    )


def main():
    """Worker Output -> Verifier -> VerificationResult"""

    goal = Goal(
        goal_id="goal-1",
        task_class="code_change",
        description="Write the required value",
    )

    contract = DoneContract(
        contract_id="value-contract", version="0.1.0", required_value=4
    )

    authoritative_tier = 2
    retry_budget = 2

    run_id = None
    outcome = execute(goal, contract, authoritative_tier, retry_budget, run_id)

    layout = StorageLayout.create(project_path=Path.cwd())
    events = JsonlEventStore(layout)
    history = events.load(outcome.run_id)

    reconstructed_state = reconstruct_final_state(history)

    print("=" * 80)
    print("FINAL OUTCOME")
    print("run_id:", outcome.run_id)
    print("state:", outcome.state)
    print("reconstructed_state:", reconstructed_state)
    print("evidence:", outcome.evidence)
    print("last verification:", outcome.last_verification)

    assert reconstructed_state is outcome.state


if __name__ == "__main__":
    main()
