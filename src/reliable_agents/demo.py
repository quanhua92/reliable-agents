import uuid_utils.compat as uuid

from reliable_agents.evidence import create_evidence
from reliable_agents.models import (
    Decision,
    DoneContract,
    FinalState,
    Goal,
    RunOutcome,
)
from reliable_agents.policy import StaticPolicyEngine
from reliable_agents.tool import WriteValueTool
from reliable_agents.verifier import IndependentVerifier
from reliable_agents.worker import EvidenceGuidedWorker


def execute(
    goal: Goal, contract: DoneContract, authoritative_tier: int, retry_budget: int = 2
) -> RunOutcome:
    verifier = IndependentVerifier()
    tool = WriteValueTool()
    policy = StaticPolicyEngine()
    worker = EvidenceGuidedWorker()

    previous_failure = None
    run_id = str(uuid.uuid7())
    checks = []
    tools_used = set()

    admission = policy.admit(goal=goal, authoritative_tier=authoritative_tier)
    print("admission", admission)

    if admission.decision is not Decision.ALLOW:
        return RunOutcome(
            state=FinalState.BLOCKED, evidence=None, last_verification=None
        )

    for attempt in range(1, retry_budget + 1):
        print("=" * 80)
        print(f"attempt {attempt}")

        turn = worker.run(
            goal=goal, contract=contract, previous_failure=previous_failure
        )
        print("worker turn:", turn)

        authorization = policy.authorize(
            request=turn.action, authoritative_tier=authoritative_tier
        )
        print("authorization:", authorization)
        if authorization.decision is not Decision.ALLOW:
            return RunOutcome(
                state=FinalState.BLOCKED,
                evidence=None,
                last_verification=previous_failure,
            )

        output = tool.execute(turn.action)
        tools_used.add(tool.version)

        verification = verifier.verify(goal=goal, contract=contract, output=output)
        checks.append(verification.check)

        print("tool output summary:", output.summary)
        print("tool output value:", output.value)
        print("verification:", verification)

        if verification.passed:
            evidence = create_evidence(
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
            return RunOutcome(
                state=FinalState.VERIFIED,
                evidence=evidence,
                last_verification=verification,
            )
        if not verification.retryable:
            return RunOutcome(
                state=FinalState.ESCALATED,
                evidence=None,
                last_verification=verification,
            )

        previous_failure = verification

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
