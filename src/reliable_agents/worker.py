from reliable_agents.models import DoneContract, Goal, VerificationResult, WorkerOutput


class EvidenceGuidedWorker:
    def run(
        self,
        goal: Goal,
        contract: DoneContract,
        previous_failure: VerificationResult | None,
    ) -> WorkerOutput:
        if previous_failure is None:
            value = contract.required_value - 1
        else:
            value = contract.required_value

        return WorkerOutput(value=value, summary=f"Proposed value {value}")


class AlwaysWrongWorker:
    def run(
        self,
        goal: Goal,
        contract: DoneContract,
        previous_failure: VerificationResult | None,
    ) -> WorkerOutput:
        return WorkerOutput(value=3, summary="I am certain this is correct")
