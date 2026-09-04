from reliable_agents.digest import effect_idempotency_key
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
        effect_sequence: int,
    ) -> WorkerTurn:
        if previous_failure is None:
            value = contract.required_value - 1
        else:
            value = contract.required_value

        effect_id = f"write-required-value:{effect_sequence}"

        idempotency_key = effect_idempotency_key(
            goal_id=goal.goal_id, effect_id=effect_id
        )

        return WorkerTurn(
            action=ActionRequest(
                effect_id=effect_id,
                tool_name="write_value",
                arguments={"value": value},
                mutating=True,
                idempotency_key=idempotency_key,
                claimed_tier=4,
            ),
            summary=f"Proposed value {value}",
        )
