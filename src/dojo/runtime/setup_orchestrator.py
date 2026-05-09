"""Shared lifecycle orchestrator used by both `dojo init` and `dojo onboard`.

Encapsulates the "create a Domain + run WorkspaceService.setup + create a
Task" sequence so both CLI entry points stay in lockstep.

This module deliberately has no Typer / console dependency — callers wrap
its calls in their own status spinners and error rendering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dojo.core.domain import Domain, DomainStatus, Workspace, WorkspaceSource
from dojo.core.task import Task, TaskType
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.task_service import TaskService
from dojo.runtime.workspace_service import WorkspaceService


def build_workspace_from_arg(arg: str) -> Workspace | None:
    """Convert a `--workspace` style string into a Workspace dataclass.

    Raises FileNotFoundError if a local path is given but doesn't exist —
    callers translate this to a CLI error with appropriate exit code.
    """
    if arg.lower() == "empty":
        return Workspace(source=WorkspaceSource.EMPTY)
    path = Path(arg).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"workspace path does not exist: {path}")
    return Workspace(source=WorkspaceSource.LOCAL, path=str(path))


def build_task_config(
    ttype: TaskType,
    *,
    data_path: str | None = None,
    target_column: str | None = None,
    test_split: float = 0.2,
) -> dict[str, Any]:
    """Translate optional CLI hints into a `task.config` dict.

    For regression, every field is optional — when missing, the AI generator
    falls back to whatever the user wrote in PROGRAM.md / SETUP.md.
    """
    if ttype != TaskType.REGRESSION:
        return {}

    cfg: dict[str, Any] = {"test_split_ratio": test_split}
    if data_path:
        cfg["data_path"] = str(Path(data_path).expanduser())
    if target_column:
        cfg["target_column"] = target_column
    return cfg


async def create_domain_with_workspace(
    *,
    lab: LabEnvironment,
    name: str,
    description: str,
    workspace: Workspace | None,
    storage_base_dir: Path,
    skip_workspace_setup: bool = False,
) -> tuple[Domain, str | None]:
    """Persist a fresh `Domain` and (optionally) prep its workspace.

    Returns the saved domain and an optional warning string — non-None when
    workspace setup failed (callers print the warning; the domain is still
    saved so the user can retry workspace setup later).
    """
    domain = Domain(
        name=name,
        description=description,
        status=DomainStatus.ACTIVE,
        workspace=workspace,
    )
    await lab.domain_store.save(domain)

    workspace_warning: str | None = None
    if (
        not skip_workspace_setup
        and workspace is not None
        and workspace.source != WorkspaceSource.EMPTY
        and workspace.path
    ):
        ws_service = WorkspaceService(storage_base_dir)
        try:
            updated = await ws_service.setup(domain)
            domain.workspace = updated
            await lab.domain_store.save(domain)
        except Exception as e:
            workspace_warning = str(e)

    return domain, workspace_warning


async def create_regression_task(
    *,
    lab: LabEnvironment,
    domain: Domain,
    task_type: TaskType,
    config: dict[str, Any] | None = None,
) -> tuple[Domain, Task]:
    """Create the Task for a freshly-saved domain.

    Reloads the domain afterwards so callers see `domain.task` populated.
    """
    task_svc = TaskService(lab)
    task = await task_svc.create(
        domain.id,
        task_type=task_type,
        name=f"{task_type.value} task",
        config=config or {},
    )
    refreshed = await lab.domain_store.load(domain.id)
    assert refreshed is not None  # just saved
    return refreshed, task
