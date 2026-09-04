from dataclasses import dataclass

from reliable_agents.models import ActionRequest, WorkerOutput
from reliable_agents.storage import JsonlEffectStore
from reliable_agents.tool import WriteValueTool


@dataclass(frozen=True, slots=True)
class EffectResult:
    output: WorkerOutput
    reused: bool


@dataclass(frozen=True, slots=True)
class EffectEscalation:
    reason: str
    effect_id: str
    idempotency_key: str


def resolve_effect(
    effects: JsonlEffectStore,
    tool: WriteValueTool,
    action: ActionRequest,
    request_digest: str,
) -> EffectResult | EffectEscalation:
    """Resolve the effect for an action request.

    Returns an EffectResult with the output if the effect was executed or
    reused, or an EffectEscalation if the effect requires escalation.

    This function owns the effect state machine:
        NONE           -> record INTENT -> execute -> record COMPLETED
        COMPLETED      + same digest -> reuse result
        INTENT         -> ambiguous -> escalate
        same key       + different digest -> escalate
    """
    existing_effect = effects.lookup(action.idempotency_key)

    if existing_effect is None:
        effects.record_intent(request=action, request_digest=request_digest)
        output = tool.execute(action)
        effects.record_success(
            request=action, request_digest=request_digest, output=output
        )
        return EffectResult(output=output, reused=False)

    stored_digest = str(existing_effect["request_digest"])
    if stored_digest != request_digest:
        return EffectEscalation(
            reason="idempotency key reused with different request",
            effect_id=action.effect_id,
            idempotency_key=action.idempotency_key,
        )

    status = str(existing_effect["status"])

    if status == "INTENT":
        return EffectEscalation(
            reason="effect requires reconciliation",
            effect_id=action.effect_id,
            idempotency_key=action.idempotency_key,
        )

    if status == "COMPLETED":
        result = existing_effect["result"]

        if not isinstance(result, dict):
            raise RuntimeError("Completed effect has no result")

        output = WorkerOutput(
            value=int(result["value"]), summary=str(result["summary"])
        )
        return EffectResult(output=output, reused=True)

    raise RuntimeError(f"Unknown effect status: {status}")
