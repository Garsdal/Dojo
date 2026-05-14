"""CLI state — persisted under `.dojo/state.yaml`.

Tracks the user's "current" selections (domain, last run) so most CLI commands
can operate without an explicit `--domain` flag. This is the analogue of git's
`HEAD` — a single pointer per working directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dojo.core.domain import Domain
from dojo.runtime.lab import LabEnvironment

_STATE_FILENAME = "state.yaml"


class CLIStateError(Exception):
    """Raised for state-related user errors (no current domain, etc.)."""


@dataclass
class CLIState:
    current_domain_id: str | None = None
    current_run_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CLIState:
        return cls(
            current_domain_id=data.get("current_domain_id"),
            current_run_id=data.get("current_run_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_domain_id": self.current_domain_id,
            "current_run_id": self.current_run_id,
        }


def state_path(base_dir: Path) -> Path:
    return Path(base_dir) / _STATE_FILENAME


def load_state(base_dir: Path) -> CLIState:
    """Load CLI state from `<base_dir>/state.yaml`. Returns empty state if missing."""
    path = state_path(base_dir)
    if not path.exists():
        return CLIState()
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise CLIStateError(f"Malformed state file at {path}: expected a mapping")
    return CLIState.from_dict(raw)


def save_state(base_dir: Path, state: CLIState) -> None:
    """Persist CLI state. Creates the parent directory if needed."""
    path = state_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(state.to_dict(), sort_keys=True))


def set_current_domain_id(base_dir: Path, domain_id: str | None) -> None:
    state = load_state(base_dir)
    state.current_domain_id = domain_id
    save_state(base_dir, state)


def set_current_run_id(base_dir: Path, run_id: str | None) -> None:
    state = load_state(base_dir)
    state.current_run_id = run_id
    save_state(base_dir, state)


def get_current_domain_id(base_dir: Path) -> str | None:
    return load_state(base_dir).current_domain_id


async def resolve_domain(
    lab: LabEnvironment,
    *,
    base_dir: Path,
    override: str | None = None,
) -> Domain:
    """Resolve the active Domain for a CLI command.

    If `override` is provided, it is treated as either a domain id or a domain
    name. Otherwise the current_domain_id from state.yaml is used.

    Raises CLIStateError with an actionable message if no domain can be resolved.
    """
    if override:
        domain = await lab.domain_store.load(override)
        if domain is not None:
            return domain
        domains = await lab.domain_store.list()
        for d in domains:
            if d.name == override:
                return d
        raise CLIStateError(f"No domain matches {override!r} (tried by id and by name).")

    domain_id = get_current_domain_id(base_dir)
    if domain_id is None:
        raise CLIStateError(
            "No current domain is set. Run `dojo onboard` to create one, "
            "or `dojo domain use <name>` to switch."
        )
    domain = await lab.domain_store.load(domain_id)
    if domain is None:
        raise CLIStateError(
            f"Current domain {domain_id!r} no longer exists. "
            "Run `dojo domain use <name>` to pick a different one."
        )
    return domain
