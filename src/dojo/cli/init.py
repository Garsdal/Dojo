"""`dojo init` — single entrypoint that walks a user from empty dir to ready-to-run.

Interactive by default; every prompt has a flag for non-interactive use.
Steps:
  1. Bootstrap config (.dojo/config.yaml)
  2. Create the Domain + workspace
  3. Create the Task (regression-only today)
  4. Scaffold PROGRAM.md (steering prompt, agent reads at run-time)
  4b. Scaffold SETUP.md  (data + eval spec, read once by `dojo task setup`)
  5. Set current_domain_id
  6. Print next steps

Tool generation is intentionally NOT part of init — the user edits SETUP.md
to describe the dataset and evaluation, then runs `dojo task setup` to
generate and verify tools against that description. PROGRAM.md is steering-
only (research goal/target/success/notes) and is read by the agent at
run-time.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console

from dojo.cli._lab import build_cli_lab
from dojo.cli.config import config_init
from dojo.cli.state import set_current_domain_id
from dojo.core.domain import (
    Domain,
    DomainStatus,
    Workspace,
    WorkspaceSource,
)
from dojo.core.task import TaskType
from dojo.runtime.program_loader import default_program_template, write_program
from dojo.runtime.setup_loader import default_setup_template, write_setup
from dojo.runtime.task_service import TaskService
from dojo.runtime.workspace_service import WorkspaceService

console = Console()

EXIT_USER_ERROR = 1


def init(
    name: str | None = typer.Option(None, "--name", help="Domain name"),
    description: str = typer.Option("", "--description", help="One-line description"),
    workspace: str = typer.Option(
        ".", "--workspace", help="Local workspace path (or 'empty' for a fresh dir)"
    ),
    task_type: str = typer.Option("regression", "--task-type", help="Task type"),
    data_path: str | None = typer.Option(
        None,
        "--data-path",
        help="Optional dataset path hint (the AI prefers PROGRAM.md if not given)",
    ),
    target_column: str | None = typer.Option(
        None,
        "--target-column",
        help="Optional target column name (only relevant for tabular CSV datasets)",
    ),
    test_split: float = typer.Option(0.2, "--test-split", help="Test split ratio for regression"),
    tracking: str | None = typer.Option(
        None, "--tracking", help="Tracking backend (file | mlflow)"
    ),
    agent_backend: str | None = typer.Option(
        None, "--agent-backend", help="Agent backend (claude | stub)"
    ),
    skip_setup: bool = typer.Option(
        False, "--no-setup", help="Skip workspace setup (no venv install)"
    ),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Fail (don't prompt) if any value is missing"
    ),
    config_dir: Path = typer.Option(  # noqa: B008
        Path(".dojo"), "--config-dir", help="Dojo state directory"
    ),
) -> None:
    """Set up a new domain. Edit PROGRAM.md after, then `dojo task setup`."""
    asyncio.run(
        _init_async(
            name=name,
            description=description,
            workspace_arg=workspace,
            task_type_str=task_type,
            data_path=data_path,
            target_column=target_column,
            test_split=test_split,
            tracking=tracking,
            agent_backend=agent_backend,
            skip_setup=skip_setup,
            non_interactive=non_interactive,
            config_dir=config_dir,
        )
    )


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def _ask(prompt: str, *, default: str | None = None, non_interactive: bool) -> str:
    if non_interactive:
        if default is None:
            console.print(f"[red]error:[/red] missing value for {prompt!r}")
            sys.exit(EXIT_USER_ERROR)
        return default
    return typer.prompt(prompt, default=default if default is not None else "")


async def _init_async(
    *,
    name: str | None,
    description: str,
    workspace_arg: str,
    task_type_str: str,
    data_path: str | None,
    target_column: str | None,
    test_split: float,
    tracking: str | None,
    agent_backend: str | None,
    skip_setup: bool,
    non_interactive: bool,
    config_dir: Path,
) -> None:
    # ---- 1. Config bootstrap -------------------------------------------------
    with console.status("[bold]bootstrapping config...[/bold]", spinner="dots"):
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        if not config_path.exists():
            config_init()

        if tracking or agent_backend:
            _patch_config(config_path, tracking=tracking, agent_backend=agent_backend)

        lab, settings = build_cli_lab()
    console.print(f"[green]✓[/green] config ready at {config_path}")

    # ---- 2. Domain + workspace ----------------------------------------------
    # Prompts must run OUTSIDE console.status (the spinner suppresses input).
    if name is None:
        name = _ask("Domain name", default=None, non_interactive=non_interactive)

    if not description:
        description = _ask("Description (optional)", default="", non_interactive=non_interactive)

    workspace_obj = _build_workspace(workspace_arg)
    with console.status(
        f"[bold]creating domain {name!r}...[/bold]",
        spinner="dots",
    ):
        domain = Domain(
            name=name,
            description=description,
            status=DomainStatus.ACTIVE,
            workspace=workspace_obj,
        )
        await lab.domain_store.save(domain)
    console.print(f"[green]✓[/green] domain created: {domain.id} ({domain.name})")

    if (
        not skip_setup
        and workspace_obj is not None
        and workspace_obj.source != WorkspaceSource.EMPTY
        and workspace_obj.path
    ):
        ws_service = WorkspaceService(Path(settings.storage.base_dir))
        try:
            with console.status(
                "[bold]setting up workspace (venv + deps, can take a few minutes)...[/bold]",
                spinner="dots",
            ):
                updated = await ws_service.setup(domain)
                domain.workspace = updated
                await lab.domain_store.save(domain)
            console.print(f"[green]✓[/green] workspace ready: {updated.path}")
        except Exception as e:
            console.print(f"[yellow]warning:[/yellow] workspace setup failed: {e}")
            console.print(
                f"Continuing — fix manually or rerun `POST /domains/{domain.id}/workspace/setup`"
            )

    # ---- 3. Task creation ---------------------------------------------------
    try:
        ttype = TaskType(task_type_str)
    except ValueError as e:
        console.print(
            f"[red]error:[/red] unsupported task type {task_type_str!r}. Supported: regression"
        )
        raise typer.Exit(code=EXIT_USER_ERROR) from e

    task_config = _build_task_config(
        ttype, data_path=data_path, target_column=target_column, test_split=test_split
    )

    with console.status(
        f"[bold]creating {ttype.value} task...[/bold]",
        spinner="dots",
    ):
        task_svc = TaskService(lab)
        task = await task_svc.create(
            domain.id, task_type=ttype, name=f"{ttype.value} task", config=task_config
        )

        # Reload so domain.task is populated for the template
        domain = await lab.domain_store.load(domain.id)
        assert domain is not None  # just saved
    console.print(f"[green]✓[/green] task created: {task.id} ({task.type.value})")

    # ---- 4. PROGRAM.md scaffold ---------------------------------------------
    with console.status("[bold]scaffolding PROGRAM.md...[/bold]", spinner="dots"):
        program_path = write_program(
            domain,
            default_program_template(domain),
            base_dir=Path(settings.storage.base_dir),
        )
        domain.program_path = str(program_path)
        await lab.domain_store.save(domain)
    console.print(f"[green]✓[/green] PROGRAM.md scaffolded at {program_path}")

    # ---- 4b. SETUP.md scaffold (data + eval spec, read by `dojo task setup`) -
    with console.status("[bold]scaffolding SETUP.md...[/bold]", spinner="dots"):
        setup_path = write_setup(
            domain,
            default_setup_template(domain),
            base_dir=Path(settings.storage.base_dir),
        )
        domain.setup_path = str(setup_path)
        await lab.domain_store.save(domain)
    console.print(f"[green]✓[/green] SETUP.md scaffolded at {setup_path}")

    # ---- 5. Set current_domain_id -------------------------------------------
    set_current_domain_id(Path(settings.storage.base_dir), domain.id)

    # ---- 6. Next steps -------------------------------------------------------
    console.print()
    console.print("[bold green]ready[/bold green] — next steps:")
    console.print(
        f"  1. edit [cyan]{program_path}[/cyan] — research goal, target, "
        "and what success looks like"
    )
    console.print(
        f"  2. edit [cyan]{setup_path}[/cyan] — describe the dataset and "
        "evaluation (read once by `dojo task setup`)"
    )
    console.print(
        "  3. run [bold]dojo task setup[/bold] — generates `load_data` + "
        "`evaluate` from SETUP.md, verifies them, and freezes the task"
    )
    console.print("  4. run [bold]dojo run[/bold] — start the agent")
    console.print(
        "\n[dim]artifacts: anything `evaluate()` saves is archived every run; "
        "`train()` may save the model when worth comparing across experiments. "
        "See README §Artifacts.[/dim]"
    )


def _build_task_config(
    ttype: TaskType,
    *,
    data_path: str | None,
    target_column: str | None,
    test_split: float,
) -> dict:
    """Translate optional CLI hints into the task.config dict.

    For regression, every field is optional — when missing, the AI generator
    falls back to whatever the user wrote in PROGRAM.md (e.g. a sklearn loader,
    a URL, a description in plain English).
    """
    if ttype != TaskType.REGRESSION:
        return {}

    cfg: dict = {"test_split_ratio": test_split}
    if data_path:
        cfg["data_path"] = str(Path(data_path).expanduser())
    if target_column:
        cfg["target_column"] = target_column
    return cfg


def _build_workspace(arg: str) -> Workspace | None:
    """Convert the --workspace flag into a Workspace dataclass."""
    if arg.lower() == "empty":
        return Workspace(source=WorkspaceSource.EMPTY)
    path = Path(arg).expanduser().resolve()
    if not path.exists():
        console.print(f"[red]error:[/red] workspace path does not exist: {path}")
        raise typer.Exit(code=EXIT_USER_ERROR)
    return Workspace(source=WorkspaceSource.LOCAL, path=str(path))


def _patch_config(config_path: Path, *, tracking: str | None, agent_backend: str | None) -> None:
    """Patch tracking backend / agent backend in the YAML config."""
    import yaml

    data = yaml.safe_load(config_path.read_text()) or {}
    if tracking:
        data.setdefault("tracking", {})["backend"] = tracking
    if agent_backend:
        data.setdefault("agent", {})["backend"] = agent_backend
    config_path.write_text(yaml.safe_dump(data, sort_keys=True))
