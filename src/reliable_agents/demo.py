from pathlib import Path

import uuid_utils.compat as uuid

from reliable_agents.evidence import create_run_evidence
from reliable_agents.models import (
    Decision,
    DoneContract,
    FinalState,
    Goal,
    RunOutcome,
)
from reliable_agents.policy import StaticPolicyEngine
from reliable_agents.storage import JsonlEventStore
from reliable_agents.tool import WriteValueTool
from reliable_agents.verifier import IndependentVerifier
from reliable_agents.worker import EvidenceGuidedWorker


def execute(
    goal: Goal, contract: DoneContract, authoritative_tier: int, retry_budget: int = 2
) -> RunOutcome:
    run_id = str(uuid.uuid7())

    events = JsonlEventStore(project_path=Path.cwd())

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
            state=FinalState.BLOCKED, evidence=None, last_verification=None
        )

    for attempt in range(1, retry_budget + 1):
        print("=" * 80)
        print(f"attempt {attempt}")

        events.append(
            run_id=run_id, kind="AttemptStarted", payload={"attempt": attempt}
        )

        turn = worker.run(
            goal=goal, contract=contract, previous_failure=previous_failure
        )
        print("worker turn:", turn)

        events.append(
            run_id=run_id,
            kind="WorkerTurnCreated",
            payload={
                "attempt": attempt,
                "tool_name": turn.action.tool_name,
                "arguments": turn.action.arguments,
                "mutating": turn.action.mutating,
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
                state=FinalState.BLOCKED,
                evidence=None,
                last_verification=previous_failure,
            )

        output = tool.execute(turn.action)
        tools_used.add(tool.version)

        events.append(
            run_id,
            "ToolCompleted",
            {
                "attempt": attempt,
                "tool": tool.version,
                "value": output.value,
                "summary": output.summary,
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

    outcome = execute(goal, contract, authoritative_tier, retry_budget)

    print("=" * 80)
    print("FINAL OUTCOME")
    print("state:", outcome.state)
    print("evidence:", outcome.evidence)
    print("last verification:", outcome.last_verification)


if __name__ == "__main__":
    main()
