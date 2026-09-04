from reliable_agents.demo import execute
from reliable_agents.digest import action_request_digest, effect_idempotency_key
from reliable_agents.models import (
    ActionRequest,
    DoneContract,
    FinalState,
    Goal,
    WorkerOutput,
)
from reliable_agents.storage import JsonlEffectStore, StorageLayout
from reliable_agents.tool import WriteValueTool


def make_effect_request(
    goal_id: str,
    effect_id: str,
    value: int,
) -> ActionRequest:
    return ActionRequest(
        effect_id=effect_id,
        tool_name="write_value",
        arguments={"value": value},
        mutating=True,
        idempotency_key=effect_idempotency_key(
            goal_id=goal_id,
            effect_id=effect_id,
        ),
    )


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


def test_completed_effect_is_reused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

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

    layout = StorageLayout.create(
        project_path=tmp_path,
        base_directory=tmp_path,
    )
    effects = JsonlEffectStore(layout)

    request = make_effect_request(
        goal_id=goal.goal_id,
        effect_id="write-required-value:1",
        value=3,
    )
    request_digest = action_request_digest(request)

    effects.record_intent(
        request=request,
        request_digest=request_digest,
    )
    effects.record_success(
        request=request,
        request_digest=request_digest,
        output=WorkerOutput(
            value=3,
            summary="Stored value 3",
        ),
    )

    executed_values: list[int] = []

    original_execute = WriteValueTool.execute

    def tracking_execute(
        self,
        request: ActionRequest,
    ) -> WorkerOutput:
        executed_values.append(int(request.arguments["value"]))
        return original_execute(self, request)

    monkeypatch.setattr(
        WriteValueTool,
        "execute",
        tracking_execute,
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=2,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.VERIFIED

    # Effect #1 was reused.
    # Only the new corrective effect #2 executed.
    assert executed_values == [4]


def test_intent_effect_escalates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

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

    layout = StorageLayout.create(
        project_path=tmp_path,
        base_directory=tmp_path,
    )
    effects = JsonlEffectStore(layout)

    request = make_effect_request(
        goal_id=goal.goal_id,
        effect_id="write-required-value:1",
        value=3,
    )

    effects.record_intent(
        request=request,
        request_digest=action_request_digest(request),
    )

    def fail_if_executed(
        self,
        request: ActionRequest,
    ) -> WorkerOutput:
        raise AssertionError("ambiguous effect must not execute again")

    monkeypatch.setattr(
        WriteValueTool,
        "execute",
        fail_if_executed,
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=2,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.ESCALATED
    assert outcome.evidence is None


def test_effect_digest_mismatch_escalates(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

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

    layout = StorageLayout.create(
        project_path=tmp_path,
        base_directory=tmp_path,
    )
    effects = JsonlEffectStore(layout)

    # Same logical effect identity that execute() will generate,
    # but a different concrete request.
    conflicting_request = make_effect_request(
        goal_id=goal.goal_id,
        effect_id="write-required-value:1",
        value=999,
    )

    effects.record_intent(
        request=conflicting_request,
        request_digest=action_request_digest(conflicting_request),
    )

    def fail_if_executed(
        self,
        request: ActionRequest,
    ) -> WorkerOutput:
        raise AssertionError("digest mismatch must not execute")

    monkeypatch.setattr(
        WriteValueTool,
        "execute",
        fail_if_executed,
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=2,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.ESCALATED
    assert outcome.evidence is None
