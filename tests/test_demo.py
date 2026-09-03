from reliable_agents.demo import execute
from reliable_agents.models import DoneContract, FinalState, Goal


def test_successful_run_is_verified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    goal = Goal(
        goal_id="goal-1",
        task_class="code_change",
        description="Write the required value",
    )
    contract = DoneContract(
        contract_id="value-contract", version="0.1.0", required_value=4
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=2,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.VERIFIED
    assert outcome.evidence is not None
    assert outcome.evidence.attempts == 2


def test_run_is_blocked_when_admission_is_denied(tmp_path):
    goal = Goal(
        goal_id="goal-1",
        task_class="code_change",
        description="Write the required value",
    )
    contract = DoneContract(
        contract_id="value-contract",
        version="0.1.0",
        required_value=4,
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=0,
        retry_budget=2,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.BLOCKED
    assert outcome.evidence is None
    assert outcome.last_verification is None


def test_run_is_blocked_when_action_requires_approval(tmp_path):
    goal = Goal(
        goal_id="goal-1",
        task_class="code_change",
        description="Write the required value",
    )
    contract = DoneContract(
        contract_id="value-contract",
        version="0.1.0",
        required_value=4,
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=1,
        retry_budget=2,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.BLOCKED
    assert outcome.evidence is None
