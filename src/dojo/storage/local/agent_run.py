"""Local agent run store — one JSON file per run in .dojo/agent_runs/."""

import json
from datetime import datetime
from pathlib import Path

from dojo.agents.types import (
    AgentEvent,
    AgentRun,
    AgentRunConfig,
    AgentRunResult,
    RunStatus,
    ToolHint,
)
from dojo.interfaces.agent_run_store import AgentRunStore
from dojo.utils.logging import get_logger
from dojo.utils.serialization import to_json

logger = get_logger(__name__)


class LocalAgentRunStore(AgentRunStore):
    """Persists agent runs as JSON files in a local directory."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".dojo/agent_runs")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self.base_dir / f"{run_id}.json"

    async def save(self, run: AgentRun) -> str:
        self._path(run.id).write_text(to_json(run))
        return run.id

    async def load(self, run_id: str) -> AgentRun | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return self._from_dict(data)

    async def list(self) -> list[AgentRun]:
        runs = []
        for path in sorted(self.base_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                runs.append(self._from_dict(data))
            except (json.JSONDecodeError, ValueError, KeyError, OSError):
                logger.warning("agent_run_load_failed", path=str(path))
        return runs

    async def delete(self, run_id: str) -> bool:
        path = self._path(run_id)
        if path.exists():
            path.unlink()
            return True
        return False

    @staticmethod
    def _from_dict(data: dict) -> AgentRun:
        def _dt(val: str | None) -> datetime | None:
            return datetime.fromisoformat(val) if val else None

        events = [
            AgentEvent(
                id=e["id"],
                timestamp=datetime.fromisoformat(e["timestamp"]),
                event_type=e["event_type"],
                data=e.get("data", {}),
            )
            for e in data.get("events", [])
        ]

        cfg = data.get("config", {})
        config = AgentRunConfig(
            system_prompt=cfg.get("system_prompt", ""),
            max_turns=cfg.get("max_turns", 50),
            max_budget_usd=cfg.get("max_budget_usd"),
            permission_mode=cfg.get("permission_mode", "acceptEdits"),
            cwd=cfg.get("cwd"),
            python_path=cfg.get("python_path"),
            domain_id=cfg.get("domain_id", ""),
        )

        result = None
        if data.get("result"):
            r = data["result"]
            result = AgentRunResult(
                session_id=r.get("session_id"),
                total_cost_usd=r.get("total_cost_usd"),
                num_turns=r.get("num_turns", 0),
                duration_ms=r.get("duration_ms"),
                is_error=r.get("is_error", False),
                error_message=r.get("error_message"),
            )

        tool_hints = [
            ToolHint(
                name=t.get("name", ""),
                description=t.get("description", ""),
                source=t.get("source", ""),
                code_template=t.get("code_template", ""),
            )
            for t in data.get("tool_hints", [])
        ]

        return AgentRun(
            id=data["id"],
            domain_id=data.get("domain_id", ""),
            prompt=data.get("prompt", ""),
            status=RunStatus(data.get("status", "completed")),
            events=events,
            started_at=_dt(data.get("started_at")),
            completed_at=_dt(data.get("completed_at")),
            config=config,
            result=result,
            error=data.get("error"),
            tool_hints=tool_hints,
        )
