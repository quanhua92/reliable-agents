from dataclasses import dataclass


@dataclass(frozen=True)
class Goal:
    goal_id: str
    task_class: str
    description: str


@dataclass(frozen=True)
class DoneContract:
    contract_id: str
    version: str
    required_value: int


@dataclass(frozen=True)
class WorkerOutput:
    value: int
    summary: str


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    check: str
    category: str
    evidence: str
    retryable: bool
