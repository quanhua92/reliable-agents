import argparse

from reliable_agents.models import DoneContract, Goal, WorkerOutput
from reliable_agents.tool import WriteValueTool
from reliable_agents.verifier import IndependentVerifier
from reliable_agents.worker import EvidenceGuidedWorker


def main():
    """Worker Output -> Verifier -> VerificationResult"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["evidence"], default="evidence")

    args = parser.parse_args()

    goal = Goal(
        goal_id="goal-1",
        task_class="code_change",
        description="Write the required value",
    )

    contract = DoneContract(
        contract_id="value-contract", version="0.1.0", required_value=4
    )

    output = WorkerOutput(value=3, summary="Done! Everything is correct")

    verifier = IndependentVerifier()
    tool = WriteValueTool()

    worker = EvidenceGuidedWorker()

    retry_budget = 2
    previous_failure = None

    for attempt in range(1, retry_budget + 1):
        print("===" * 20)
        print(f"attempt {attempt}")

        turn = worker.run(
            goal=goal, contract=contract, previous_failure=previous_failure
        )
        print("worker turn:", turn)

        output = tool.execute(turn.action)

        result = verifier.verify(goal=goal, contract=contract, output=output)

        print("tool output summary:", output.summary)
        print("tool output value:", output.value)
        print("verification:", result)

        if result.passed:
            print("VERIFIED")
            break
        if not result.retryable:
            print("ESCALATED")
            break

        previous_failure = result

    else:
        print("ESCALATED")


if __name__ == "__main__":
    main()
