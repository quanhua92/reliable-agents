import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reliable_agents.models import ActionRequest, WorkerOutput


def project_slug(path: Path) -> str:
    resolved = path.resolve()

    parts = [part for part in resolved.parts if part != resolved.anchor]

    prefix = resolved.anchor.rstrip("\\/").replace(":", "")
    slug_parts: list[str] = []
    if prefix:
        slug_parts.append(prefix)
    slug_parts.extend(parts)
    return "-" + "-".join(slug_parts)


@dataclass(frozen=True, slots=True)
class StorageLayout:
    project_path: Path
    base_directory: Path
    state_directory: Path
    project_directory: Path
    runs_directory: Path

    @classmethod
    def create(
        cls, project_path: Path, base_directory: Path | None = None
    ) -> "StorageLayout":
        resolved_project_path = project_path.resolve()

        resolved_base_directory = (
            Path.home() if base_directory is None else base_directory.resolve()
        )

        state_directory = resolved_base_directory / ".reliable_agents"
        projects_directory = state_directory / "projects"
        project_directory = projects_directory / project_slug(resolved_project_path)
        runs_directory = project_directory / "runs"
        runs_directory.mkdir(parents=True, exist_ok=True)

        return cls(
            project_path=resolved_project_path,
            base_directory=resolved_base_directory,
            state_directory=state_directory,
            project_directory=project_directory,
            runs_directory=runs_directory,
        )

    def run_directory(self, run_id: str) -> Path:
        path = self.runs_directory / run_id
        return path

    def effects_path(self) -> Path:
        return self.project_directory / "effects.jsonl"

    def events_path(self, run_id: str) -> Path:
        return self.run_directory(run_id) / "events.jsonl"

    def artifacts_directory(self, run_id: str) -> Path:
        path = self.run_directory(run_id) / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def subagents_directory(self, run_id: str) -> Path:
        path = self.run_directory(run_id) / "subagents"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def subagent_events_path(self, run_id: str, agent_id: str) -> Path:
        return self.subagents_directory(run_id) / f"agent-{agent_id}.jsonl"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    encoded = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(encoded)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.endswith("\n"):
                raise RuntimeError(
                    f"Incomplete JSONL record: {path} line {line_number}"
                )
            line = line.strip()

            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"Corrupted JSONL record: {path} line {line_number}"
                ) from error

    return records


class JsonlEventStore:
    version = "jsonl-event-store@0.1.0"

    def __init__(self, layout: StorageLayout) -> None:
        self.layout = layout

    def append(self, run_id: str, kind: str, payload: dict[str, Any]) -> None:
        path = self.layout.events_path(run_id)
        self._append_event(path, run_id, kind, payload)

    def append_subagent(
        self, run_id: str, agent_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        path = self.layout.subagent_events_path(run_id=run_id, agent_id=agent_id)
        stream_id = f"{run_id}/{agent_id}"
        self._append_event(path, stream_id, kind, payload)

    def _append_event(
        self, path: Path, stream_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        events = _load_jsonl(path)

        event = {
            "stream_id": stream_id,
            "sequence": len(events) + 1,
            "kind": kind,
            "payload": payload,
            "created_at": time.time(),
        }
        _append_jsonl(path, event)

    def load(self, run_id: str) -> list[dict[str, Any]]:
        path = self.layout.events_path(run_id)
        return _load_jsonl(path)

    def load_subagent(self, run_id: str, agent_id: str) -> list[dict[str, Any]]:
        path = self.layout.subagent_events_path(run_id=run_id, agent_id=agent_id)
        return _load_jsonl(path)


class JsonlEffectStore:
    version = "jsonl-effect-store@0.1.0"

    def __init__(self, layout: StorageLayout) -> None:
        self.layout = layout

    def lookup(self, idempotency_key: str) -> dict[str, Any] | None:
        records = _load_jsonl(self.layout.effects_path())
        latest: dict[str, Any] | None = None

        for record in records:
            if record["idempotency_key"] == idempotency_key:
                latest = record

        return latest

    def record_intent(self, request: ActionRequest, request_digest: str) -> None:
        _append_jsonl(
            self.layout.effects_path(),
            {
                "idempotency_key": request.idempotency_key,
                "effect_id": request.effect_id,
                "request_digest": request_digest,
                "status": "INTENT",
                "result": None,
                "created_at": time.time(),
            },
        )

    def record_success(
        self, request: ActionRequest, request_digest: str, output: WorkerOutput
    ) -> None:
        _append_jsonl(
            self.layout.effects_path(),
            {
                "idempotency_key": request.idempotency_key,
                "effect_id": request.effect_id,
                "request_digest": request_digest,
                "status": "COMPLETED",
                "result": {"value": output.value, "summary": output.summary},
                "created_at": time.time(),
            },
        )
