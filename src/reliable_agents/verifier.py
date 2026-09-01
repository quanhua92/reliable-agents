from reliable_agents.models import DoneContract, Goal, VerificationResult, WorkerOutput


class IndependentVerifier:
    def verify(
        self, goal: Goal, contract: DoneContract, output: WorkerOutput
    ) -> VerificationResult:
        if output.value == contract.required_value:
            return VerificationResult(
                passed=True,
                check="required_value",
                category="passed",
                evidence=(f"Observed required value {contract.required_value}"),
                retryable=False,
            )
        return VerificationResult(
            passed=False,
            check="required_value",
            category="incorrect_value",
            evidence=(f"Expected {contract.required_value} observed {output.value}"),
            retryable=True,
        )
