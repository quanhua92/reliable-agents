from pathlib import Path

from reliable_agents.models import DoneContract, Goal
from reliable_agents.run_state import reconstruct_final_state
from reliable_agents.storage import JsonlEventStore, StorageLayout
from reliable_agents.supervisor import execute


def main() -> None:
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
