import hashlib
import json
import time

from reliable_agents.models import DoneContract, FinalState, Goal, RunEvidence


def create_evidence(
    run_id: str,
    goal: Goal,
    contract: DoneContract,
    attempts: int,
    checks: tuple[str, ...],
    runtime_components: dict[str, str],
    tools_used: set[str],
) -> RunEvidence:
    unsigned = {
        "run_id": run_id,
        "goal_id": goal.goal_id,
        "done_contract_version": contract.version,
        "final_state": FinalState.VERIFIED.value,
        "attempts": attempts,
        "checks": checks,
        "runtime_components": runtime_components,
        "tools_used": tuple(sorted(tools_used)),
        "created_at": time.time(),
    }

    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return RunEvidence(**unsigned, evidence_digest=digest)
