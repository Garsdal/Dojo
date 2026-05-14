"""TaskService — manages the Task lifecycle on a Domain."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dojo.core.domain import Domain, DomainTool
from dojo.core.task import TASK_TYPE_REGISTRY, Task, TaskType
from dojo.runtime.lab import LabEnvironment
from dojo.utils.logging import get_logger

logger = get_logger(__name__)


class TaskNotReadyError(Exception):
    """Raised when an agent run is attempted against a domain without a frozen task."""


class TaskFrozenError(Exception):
    """Raised when a modification is attempted on a frozen task."""


class TaskVerificationError(Exception):
    """Raised when freezing a task whose required tools haven't been verified.

    Carries `errors` so callers can surface specific failures (e.g.
    "load_data: missing required key 'y_test'").
    """

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class TaskService:
    """Creates, configures, freezes, and retrieves Tasks on Domains."""

    def __init__(self, lab: LabEnvironment) -> None:
        self.lab = lab

    async def create(
        self,
        domain_id: str,
        *,
        task_type: TaskType = TaskType.REGRESSION,
        name: str = "",
        description: str = "",
        config: dict[str, Any] | None = None,
    ) -> Task:
        """Create and attach a Task to a Domain.

        Raises ValueError if the domain already has a task (unfreeze + remove first).
        """
        domain = await self.lab.domain_store.load(domain_id)
        if domain is None:
            raise ValueError(f"Domain {domain_id!r} not found")

        spec = TASK_TYPE_REGISTRY[task_type]
        task_config = {**{k: v for k, v in spec.config_schema.get("optional", {}).items()}}
        # Seed expected_metrics from the evaluator contract — `complete_experiment`
        # validates that recorded metric keys are a subset of these.
        evaluator = next((c for c in spec.required_tools if c.name == "evaluate"), None)
        if evaluator is not None:
            task_config.setdefault("expected_metrics", list(evaluator.returns_schema.keys()))
        if config:
            task_config.update(config)

        task = Task(
            type=task_type,
            name=name or f"{task_type.value} task",
            description=description,
            primary_metric=spec.default_metric,
            direction=spec.default_direction,
            config=task_config,
        )
        domain.task = task
        domain.updated_at = datetime.now(UTC)
        await self.lab.domain_store.save(domain)

        logger.info("task_created", domain_id=domain_id, task_id=task.id, type=task_type)
        return task

    async def get(self, domain_id: str) -> Task | None:
        """Return the Task for a Domain, or None if none is set."""
        domain = await self.lab.domain_store.load(domain_id)
        return domain.task if domain else None

    async def update_config(self, domain_id: str, config_updates: dict[str, Any]) -> Task:
        """Update the task config. Raises TaskFrozenError if the task is frozen."""
        domain = await self.lab.domain_store.load(domain_id)
        if domain is None:
            raise ValueError(f"Domain {domain_id!r} not found")
        if domain.task is None:
            raise ValueError(f"Domain {domain_id!r} has no task")
        if domain.task.frozen:
            raise TaskFrozenError("Cannot update config on a frozen task — unfreeze first")

        domain.task.config.update(config_updates)
        domain.task.updated_at = datetime.now(UTC)
        domain.updated_at = datetime.now(UTC)
        await self.lab.domain_store.save(domain)
        return domain.task

    async def freeze(self, domain_id: str, *, skip_verification: bool = False) -> Task:
        """Freeze the task so agent runs are permitted.

        Every required tool (per `TASK_TYPE_REGISTRY`) must be present *and*
        have `verification.verified is True`. Pass ``skip_verification=True``
        only for explicit user overrides (e.g. CLI ``--unsafe-skip-verify``).

        Phase 4: copies each tool's module file into a canonical, immutable
        directory (``<base>/domains/{id}/tools/<filename>``) and stores the
        SHA-256 of each file on ``task.config["tool_hashes"]``. The runner
        imports from this canonical dir at experiment time, so the workspace
        copy can be edited or deleted without affecting frozen runs.
        """
        domain = await self.lab.domain_store.load(domain_id)
        if domain is None:
            raise ValueError(f"Domain {domain_id!r} not found")
        if domain.task is None:
            raise ValueError(f"Domain {domain_id!r} has no task — create one first")

        if not skip_verification:
            errors = _verification_errors(domain.task)
            if errors:
                raise TaskVerificationError(
                    "Task cannot be frozen — verification gate failed.",
                    errors=errors,
                )

        hashes = self._copy_tools_to_canonical(domain)
        if hashes:
            domain.task.config["tool_hashes"] = hashes

        spec = TASK_TYPE_REGISTRY.get(domain.task.type)
        if spec is not None:
            domain.task.config["contract_version"] = spec.contract_version

        domain.task.frozen = True
        domain.task.updated_at = datetime.now(UTC)
        domain.updated_at = datetime.now(UTC)
        await self.lab.domain_store.save(domain)

        logger.info(
            "task_frozen",
            domain_id=domain_id,
            task_id=domain.task.id,
            canonical_files=list(hashes),
        )
        return domain.task

    async def unfreeze(self, domain_id: str) -> Task:
        """Unfreeze the task to allow tool changes.

        Note: unfreezing invalidates metric comparisons across experiments
        if tool code changes — callers should surface this warning.
        """
        domain = await self.lab.domain_store.load(domain_id)
        if domain is None:
            raise ValueError(f"Domain {domain_id!r} not found")
        if domain.task is None:
            raise ValueError(f"Domain {domain_id!r} has no task")

        domain.task.frozen = False
        domain.task.updated_at = datetime.now(UTC)
        domain.updated_at = datetime.now(UTC)
        await self.lab.domain_store.save(domain)

        logger.info("task_unfrozen", domain_id=domain_id, task_id=domain.task.id)
        return domain.task

    async def delete(self, domain_id: str) -> None:
        """Remove the task from a domain (only allowed if not frozen)."""
        domain = await self.lab.domain_store.load(domain_id)
        if domain is None:
            raise ValueError(f"Domain {domain_id!r} not found")
        if domain.task and domain.task.frozen:
            raise TaskFrozenError("Cannot delete a frozen task — unfreeze first")

        domain.task = None
        domain.updated_at = datetime.now(UTC)
        await self.lab.domain_store.save(domain)

    def assert_ready(self, domain_id: str, task: Task | None) -> None:
        """Raise TaskNotReadyError if the task is missing, unfrozen, has
        unverified required tools, or canonical tool files are tampered.

        Called by the orchestrator before starting a run.
        """
        if task is None:
            raise TaskNotReadyError(
                f"Domain {domain_id!r} has no task. "
                "Create one with `dojo onboard` or POST /domains/{id}/task."
            )
        if not task.frozen:
            raise TaskNotReadyError(
                f"Domain {domain_id!r} task is not frozen. "
                "Freeze it with `dojo domain setup` or POST /domains/{id}/task/freeze."
            )
        spec = TASK_TYPE_REGISTRY.get(task.type)
        if spec is not None:
            stored = task.config.get("contract_version")
            if stored != spec.contract_version:
                raise TaskNotReadyError(
                    f"Domain {domain_id!r} task was frozen against "
                    f"contract version {stored!r}, but the current contract is "
                    f"version {spec.contract_version}. Regenerate, re-verify, "
                    f"and re-freeze: `dojo domain unfreeze` then `dojo domain setup`."
                )
        errors = _verification_errors(task)
        if errors:
            raise TaskNotReadyError(
                f"Domain {domain_id!r} has unverified tools: " + "; ".join(errors)
            )
        tamper = self._tamper_errors(domain_id, task)
        if tamper:
            raise TaskNotReadyError(
                f"Domain {domain_id!r} canonical tool files have been tampered: "
                + "; ".join(tamper)
            )

    def canonical_tools_dir(self, domain_id: str) -> Path:
        """Return ``<storage_base>/domains/{id}/tools``."""
        return self._domain_dir(domain_id) / "tools"

    def sources_dir(self, domain_id: str) -> Path:
        """Return ``<storage_base>/domains/{id}/sources`` — editable pre-freeze
        copies of the generated tool modules.

        These are the user-facing files for `dojo domain setup` and
        the working dir for verification (so any cache files written by
        `load_data` persist next to the module across runs).
        """
        return self._domain_dir(domain_id) / "sources"

    def runs_dir(self, domain_id: str, experiment_id: str) -> Path:
        """Return ``<storage_base>/domains/{id}/runs/{experiment_id}`` —
        per-experiment scratch dir for agent-generated train code and the
        runner stub, so they don't pollute the user's workspace.

        The artifact archive at ``experiments/{id}/__dojo_train_{id}.py``
        remains the canonical, durable copy.
        """
        return self._domain_dir(domain_id) / "runs" / experiment_id

    def _domain_dir(self, domain_id: str) -> Path:
        base = (
            Path(self.lab.settings.storage.base_dir)
            if self.lab.settings is not None
            else Path(".dojo")
        )
        return base / "domains" / domain_id

    def _copy_tools_to_canonical(self, domain: Domain) -> dict[str, str]:
        """Copy each tool's module file to the canonical dir; return SHA-256 hashes.

        Source preference: ``<sources_dir>/<module_filename>`` (the user-facing,
        editable copy). Falls back to ``tool.code`` (the in-memory source from
        generation) when the sources copy is missing — keeps tests, in-memory
        flows, and forced freezes working.
        """
        if domain.task is None:
            return {}

        canonical_dir = self.canonical_tools_dir(domain.id)
        canonical_dir.mkdir(parents=True, exist_ok=True)

        sources_path = self.sources_dir(domain.id)

        hashes: dict[str, str] = {}
        for tool in domain.task.tools:
            if not tool.module_filename:
                continue
            source = _read_tool_source(tool, sources_path)
            if source is None:
                continue
            target = canonical_dir / tool.module_filename
            target.write_text(source)
            hashes[tool.module_filename] = hashlib.sha256(source.encode()).hexdigest()
            tool.code = source  # in-memory source mirrors the canonical bytes
        return hashes

    def _tamper_errors(self, domain_id: str, task: Task) -> list[str]:
        """Return per-file tamper messages, or an empty list when no hashes
        are stored (legacy / forced freezes) or the canonical dir is intact."""
        recorded: dict[str, str] = task.config.get("tool_hashes") or {}
        if not recorded:
            return []
        canonical_dir = self.canonical_tools_dir(domain_id)
        out: list[str] = []
        for filename, expected in recorded.items():
            path = canonical_dir / filename
            if not path.exists():
                out.append(f"{filename} missing from canonical dir")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                out.append(f"{filename} hash mismatch (canonical edited?)")
        return out


def _read_tool_source(tool: DomainTool, sources_path: Path | None) -> str | None:
    """Pick the source bytes to copy to the canonical dir.

    Sources file wins (the user-edited, pre-freeze copy under
    ``.dojo/domains/{id}/sources/``). Falls back to in-memory ``tool.code``
    so unit tests and in-memory flows still work. Returns ``None`` when
    neither source has bytes — caller decides whether that's fatal.
    """
    if sources_path is not None:
        candidate = sources_path / tool.module_filename
        if candidate.exists():
            return candidate.read_text()
    if tool.code:
        return tool.code
    return None


def _verification_errors(task: Task) -> list[str]:
    """Return human-readable problems with the task's required tool verifications.

    Empty list means the task is ready to freeze / run.
    """
    spec = TASK_TYPE_REGISTRY.get(task.type)
    if spec is None:
        return []

    by_name = {t.name: t for t in task.tools}
    out: list[str] = []
    for contract in spec.required_tools:
        tool = by_name.get(contract.name)
        if tool is None:
            out.append(f"required tool {contract.name!r} is missing")
            continue
        if tool.verification is None:
            out.append(f"{contract.name}: not yet verified — run `dojo domain setup`")
            continue
        if not tool.verification.verified:
            details = "; ".join(tool.verification.errors) or "verification failed"
            out.append(f"{contract.name}: {details}")
    return out
