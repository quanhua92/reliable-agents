from reliable_agents.supervisor import execute
from reliable_agents.digest import action_request_digest, effect_idempotency_key
from reliable_agents.models import (
    ActionRequest,
    DoneContract,
    FinalState,
    Goal,
    VerificationResult,
    WorkerOutput,
)
from reliable_agents.storage import JsonlEffectStore, JsonlEventStore, StorageLayout
from reliable_agents.tool import WriteValueTool
from reliable_agents.verifier import IndependentVerifier


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


def test_success_claim_does_not_override_wrong_value(
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

    def dishonest_execute(
        self,
        request: ActionRequest,
    ) -> WorkerOutput:
        return WorkerOutput(
            value=3,
            summary="Success. Required value was written.",
        )

    monkeypatch.setattr(
        WriteValueTool,
        "execute",
        dishonest_execute,
    )

    run_id = "dishonest-success-claim"

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=1,
        base_directory=tmp_path,
        run_id=run_id,
    )

    layout = StorageLayout.create(
        project_path=tmp_path,
        base_directory=tmp_path,
    )
    events = JsonlEventStore(layout).load(run_id)

    tool_completed = next(event for event in events if event["kind"] == "ToolCompleted")

    assert tool_completed["payload"]["summary"] == (
        "Success. Required value was written."
    )
    assert tool_completed["payload"]["value"] == 3

    assert outcome.state is FinalState.ESCALATED
    assert outcome.evidence is None
    assert outcome.last_verification is not None
    assert outcome.last_verification.passed is False


def test_correct_output_is_not_verified_when_verifier_fails(
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

    def correct_execute(
        self,
        request: ActionRequest,
    ) -> WorkerOutput:
        return WorkerOutput(
            value=4,
            summary="Stored value 4",
        )

    def rejecting_verify(
        self,
        goal: Goal,
        contract: DoneContract,
        output: WorkerOutput,
    ) -> VerificationResult:
        return VerificationResult(
            passed=False,
            check="forced_failure",
            category="verification_failed",
            evidence="Verifier rejected the result",
            retryable=False,
        )

    monkeypatch.setattr(
        WriteValueTool,
        "execute",
        correct_execute,
    )

    monkeypatch.setattr(
        IndependentVerifier,
        "verify",
        rejecting_verify,
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=1,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.ESCALATED
    assert outcome.evidence is None
    assert outcome.last_verification is not None
    assert outcome.last_verification.passed is False


def test_nonretryable_verification_failure_escalates_immediately(
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

    verification_calls = 0

    def nonretryable_verify(
        self,
        goal: Goal,
        contract: DoneContract,
        output: WorkerOutput,
    ) -> VerificationResult:
        nonlocal verification_calls
        verification_calls += 1

        return VerificationResult(
            passed=False,
            check="fatal_check",
            category="fatal_verification_failure",
            evidence="Failure cannot be repaired by retrying",
            retryable=False,
        )

    monkeypatch.setattr(
        IndependentVerifier,
        "verify",
        nonretryable_verify,
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=5,
        base_directory=tmp_path,
    )

    assert outcome.state is FinalState.ESCALATED
    assert outcome.evidence is None
    assert outcome.last_verification is not None
    assert outcome.last_verification.retryable is False

    assert verification_calls == 1


def test_unfinished_run_resumes_from_next_attempt(
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

    run_id = "resume-after-failed-verification"

    layout = StorageLayout.create(
        project_path=tmp_path,
        base_directory=tmp_path,
    )
    events = JsonlEventStore(layout)

    events.append(
        run_id,
        "GoalCreated",
        {
            "goal_id": goal.goal_id,
            "task_class": goal.task_class,
            "description": goal.description,
        },
    )

    events.append(
        run_id,
        "DoneContractBound",
        {
            "contract_id": contract.contract_id,
            "version": contract.version,
            "required_value": contract.required_value,
        },
    )

    events.append(
        run_id,
        "AdmissionDecided",
        {
            "decision": "ALLOW",
            "reason": "admission allowed",
            "authoritative_tier": 2,
        },
    )

    events.append(
        run_id,
        "AttemptStarted",
        {
            "attempt": 1,
        },
    )

    events.append(
        run_id,
        "VerificationCompleted",
        {
            "attempt": 1,
            "passed": False,
            "check": "required_value",
            "category": "incorrect_value",
            "evidence": "Expected 4 observed 3",
            "retryable": True,
        },
    )

    events.append(
        run_id,
        "RecoveryStarted",
        {
            "attempt": 1,
            "category": "incorrect_value",
            "evidence": "Expected 4 observed 3",
        },
    )

    outcome = execute(
        goal=goal,
        contract=contract,
        authoritative_tier=2,
        retry_budget=2,
        run_id=run_id,
        base_directory=tmp_path,
    )

    history = events.load(run_id)

    assert outcome.state is FinalState.VERIFIED
    assert outcome.evidence is not None
    assert outcome.evidence.attempts == 2

    assert sum(event["kind"] == "GoalCreated" for event in history) == 1

    assert sum(event["kind"] == "DoneContractBound" for event in history) == 1

    attempts = [
        event["payload"]["attempt"]
        for event in history
        if event["kind"] == "AttemptStarted"
    ]

    assert attempts == [1, 2]
