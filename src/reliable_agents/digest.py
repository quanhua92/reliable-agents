import hashlib
import json
from typing import Any

from reliable_agents.models import ActionRequest


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effect_idempotency_key(goal_id: str, effect_id: str) -> str:
    return sha256_json({"goal_id": goal_id, "effect_id": effect_id})


def action_request_digest(request: ActionRequest) -> str:
    return sha256_json(
        {
            "tool_name": request.tool_name,
            "arguments": request.arguments,
            "mutating": request.mutating,
        }
    )
