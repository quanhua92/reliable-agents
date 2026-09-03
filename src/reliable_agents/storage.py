import json
import os
import time
from functools import partial
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".reliable_agents"
PROJECTS_DIR = STATE_DIR / "projects"


def project_slug(path: Path) -> str:
    resolved = path.resolve()

    parts = [part for part in resolved.parts if part != resolved.anchor]

    prefix = resolved.anchor.rstrip("\\/").replace(":", "")
    slug_parts: list[str] = []
    if prefix:
        slug_parts.append(prefix)
    slug_parts.extend(parts)
    return "-" + "-".join(slug_parts)


class JsonlEventStore:
    version = "jsonl-event-store@0.1.0"

    def __init__(
        self, project_path: Path, projects_directory: Path = PROJECTS_DIR
    ) -> None:
        self.project_path = project_path.resolve()
        self.projects_directory = projects_directory

    def project_directory(self) -> Path:
        return self.projects_directory / project_slug(self.project_path)

    def runs_directory(self) -> Path:
        return self.project_directory() / "runs"

    def run_directory(self, run_id: str) -> Path:
        return self.runs_directory() / run_id

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

    def append(self, run_id: str, kind: str, payload: dict[str, Any]) -> None:
        path = self.events_path(run_id)
        self._append_event(path=path, stream_id=run_id, kind=kind, payload=payload)

    def append_subagent(
        self, run_id: str, agent_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        path = self.subagent_events_path(run_id=run_id, agent_id=agent_id)
        self._append_event(path=path, stream_id=agent_id, kind=kind, payload=payload)

    def _append_event(
        self, path: Path, stream_id: str, kind: str, payload: dict[str, Any]
    ) -> None:

        path.parent.mkdir(parents=True, exist_ok=True)

        events = self._load_events(path)

        event = {
            "stream_id": stream_id,
            "sequence": len(events) + 1,
            "kind": kind,
            "payload": payload,
            "created_at": time.time(),
        }

        encoded = json.dumps(
            event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

        with path.open("a", encoding="utf-8") as file:
            file.write(encoded)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

    def load(self, run_id: str) -> list[dict[str, Any]]:
        path = self.events_path(run_id)
        return self._load_events(path)

    def load_subagent(self, run_id: str, agent_id: str) -> list[dict[str, Any]]:
        path = self.subagent_events_path(run_id=run_id, agent_id=agent_id)
        return self._load_events(path)

    def _load_events(self, path: Path) -> list[dict[str, Any]]:

        if not path.exists():
            return []

        events: list[dict[str, Any]] = []

        with path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.endswith("\n"):
                    raise RuntimeError(
                        "Incomplete event record: {path} line {line_number}"
                    )
                line = line.strip()

                if not line:
                    continue

                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        "Corrupted event log: {path} line {line_number}"
                    ) from error

        return events
