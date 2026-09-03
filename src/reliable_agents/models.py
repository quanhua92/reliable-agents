from dataclasses import dataclass
from enum import Enum
from typing import Any


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class FinalState(str, Enum):
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


@dataclass(frozen=True, slots=True)
class Goal:
    goal_id: str
    task_class: str
    description: str


@dataclass(frozen=True, slots=True)
class DoneContract:
    contract_id: str
    version: str
    required_value: int


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: Decision
    reason: str


@dataclass(frozen=True, slots=True)
class ActionRequest:
    tool_name: str
    arguments: dict[str, Any]
    mutating: bool
    idempotency_key: str
    claimed_tier: int | None = None


@dataclass(frozen=True, slots=True)
class WorkerTurn:
    action: ActionRequest
    summary: str


@dataclass(frozen=True, slots=True)
class WorkerOutput:
    value: int
    summary: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    check: str
    category: str
    evidence: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class RunEvidence:
    run_id: str
    goal_id: str
    done_contract_version: str
    final_state: str
    attempts: int
    checks: tuple[str, ...]
    runtime_components: dict[str, str]
    tools_used: tuple[str, ...]
    created_at: float
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: str
    state: FinalState
    evidence: RunEvidence | None
    last_verification: VerificationResult | None
