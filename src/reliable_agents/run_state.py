from dataclasses import dataclass

from reliable_agents.models import (
    FinalState,
    VerificationResult,
    WorkerOutput,
)


@dataclass(frozen=True, slots=True)
class ResumeState:
    next_attempt: int
    previous_failure: VerificationResult | None
    checks: tuple[str, ...]
    pending_verification_attempt: int | None
    pending_output: WorkerOutput | None


def reconstruct_resume_state(events: list[dict]) -> ResumeState:
    last_attempt = 0
    previous_failure: VerificationResult | None = None
    checks: list[str] = []

    tool_outputs: dict[int, WorkerOutput] = {}
    verified_attempts: set[int] = set()

    for event in events:
        payload = event["payload"]

        match event["kind"]:
            case "AttemptStarted":
                last_attempt = int(payload["attempt"])

            case "ToolCompleted":
                attempt = int(payload["attempt"])

                tool_outputs[attempt] = WorkerOutput(
                    value=int(payload["value"]), summary=str(payload["summary"])
                )
            case "VerificationCompleted":
                attempt = int(payload["attempt"])

                verification = VerificationResult(
                    passed=bool(payload["passed"]),
                    check=str(payload["check"]),
                    category=str(payload["category"]),
                    evidence=str(payload["evidence"]),
                    retryable=bool(payload["retryable"]),
                )

                verified_attempts.add(attempt)
                previous_failure = verification
                checks.append(verification.check)

    pending_output = tool_outputs.get(last_attempt)
    if pending_output is not None and last_attempt not in verified_attempts:
        return ResumeState(
            next_attempt=last_attempt,
            previous_failure=previous_failure,
            checks=tuple(checks),
            pending_verification_attempt=last_attempt,
            pending_output=pending_output,
        )

    return ResumeState(
        next_attempt=last_attempt + 1,
        previous_failure=previous_failure,
        checks=tuple(checks),
        pending_verification_attempt=None,
        pending_output=None,
    )


def reconstruct_final_state(events: list[dict]) -> FinalState | None:
    for event in reversed(events):
        match event["kind"]:
            case "RunCompleted":
                return FinalState.VERIFIED
            case "RunBlocked":
                return FinalState.BLOCKED
            case "RunEscalated":
                return FinalState.ESCALATED
    return None
