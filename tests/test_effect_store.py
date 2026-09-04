from pathlib import Path

from reliable_agents.digest import (
    action_request_digest,
    effect_idempotency_key,
)
from reliable_agents.models import ActionRequest, WorkerOutput
from reliable_agents.storage import JsonlEffectStore, StorageLayout


def make_request(
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


def make_store(tmp_path: Path) -> JsonlEffectStore:
    layout = StorageLayout.create(
        project_path=Path.cwd(),
        base_directory=tmp_path,
    )

    return JsonlEffectStore(layout)


def test_effect_is_missing_initially(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    request = make_request(
        goal_id="goal-1",
        effect_id="write:1",
        value=4,
    )

    assert store.lookup(request.idempotency_key) is None


def test_intent_is_persisted(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    request = make_request(
        goal_id="goal-1",
        effect_id="write:1",
        value=4,
    )

    digest = action_request_digest(request)

    store.record_intent(
        request=request,
        request_digest=digest,
    )

    effect = store.lookup(request.idempotency_key)

    assert effect is not None
    assert effect["status"] == "INTENT"
    assert effect["effect_id"] == "write:1"
    assert effect["request_digest"] == digest
    assert effect["result"] is None


def test_completed_effect_replaces_intent_as_latest_state(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    request = make_request(
        goal_id="goal-1",
        effect_id="write:1",
        value=4,
    )

    digest = action_request_digest(request)

    store.record_intent(
        request=request,
        request_digest=digest,
    )

    store.record_success(
        request=request,
        request_digest=digest,
        output=WorkerOutput(
            value=4,
            summary="Stored value 4",
        ),
    )

    effect = store.lookup(request.idempotency_key)

    assert effect is not None
    assert effect["status"] == "COMPLETED"
    assert effect["request_digest"] == digest
    assert effect["result"] == {
        "value": 4,
        "summary": "Stored value 4",
    }


def test_repeated_effect_occurrences_have_different_keys() -> None:
    first = make_request(
        goal_id="goal-1",
        effect_id="replace-first:1",
        value=4,
    )

    second = make_request(
        goal_id="goal-1",
        effect_id="replace-first:2",
        value=4,
    )

    assert first.idempotency_key != second.idempotency_key
