import hashlib

from reliable_agents.models import (
    ActionRequest,
    DoneContract,
    Goal,
    VerificationResult,
    WorkerTurn,
)


class EvidenceGuidedWorker:
    version = "evidience-guided-worker@0.1.0"

    def run(
        self,
        goal: Goal,
        contract: DoneContract,
        previous_failure: VerificationResult | None,
    ) -> WorkerTurn:
        if previous_failure is None:
            value = contract.required_value - 1
        else:
            value = contract.required_value

        key_material = f"{goal.goal_id}:write_value:{value}"

        idempotency_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()

        return WorkerTurn(
            action=ActionRequest(
                tool_name="write_value",
                arguments={"value": value},
                mutating=True,
                idempotency_key=idempotency_key,
                claimed_tier=4,
            ),
            summary=f"Proposed value {value}",
        )
