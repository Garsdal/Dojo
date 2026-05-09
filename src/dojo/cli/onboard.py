"""`dojo onboard` — guided, all-in-one setup that gets a user from zero to runnable.

Composes existing services (`DomainService`, `WorkspaceService`, `TaskService`,
`_do_generate` / `_do_freeze` from cli/task.py) behind a single interactive
prompt flow. The dominant target user is **already inside their existing
Python project** — `cd path/to/my/project && dojo onboard` — so the flow
biases toward "use cwd, reuse pyproject.toml, ask only what's necessary".

Sklearn presets are explicitly opt-in via `--preset` for users without an
existing project who want to see the framework run end-to-end.

For non-interactive / scripted use, `dojo init` is still the right command.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.prompt import Confirm, Prompt

from dojo.cli._lab import build_cli_lab
from dojo.cli.config import config_init
from dojo.cli.init import _patch_config
from dojo.cli.state import set_current_domain_id
from dojo.cli.task import _do_freeze, _do_generate
from dojo.core.domain import Domain, Workspace
from dojo.core.task import TaskType
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.onboard_helpers import (
    PRESETS,
    fill_program_template,
    fill_setup_template,
    is_path_inside_dojo_repo,
    parse_module_not_found,
)
from dojo.runtime.program_loader import default_program_template, write_program
from dojo.runtime.setup_loader import default_setup_template, write_setup
from dojo.runtime.setup_orchestrator import (
    build_task_config,
    build_workspace_from_arg,
    create_domain_with_workspace,
    create_regression_task,
)
from dojo.runtime.task_service import TaskFrozenError, TaskVerificationError

console = Console()

EXIT_USER_ERROR = 1
EXIT_GATE = 3

MAX_INSTALL_RETRIES = 3


def _stdin_is_tty() -> bool:
    """Indirection so tests can patch the TTY check (CliRunner replaces stdin)."""
    return sys.stdin.isatty()


def onboard(
    workspace: str = typer.Option(
        ".",
        "--workspace",
        help="Local workspace path (defaults to cwd; pass 'empty' for a fresh dir).",
    ),
    preset: str | None = typer.Option(
        None,
        "--preset",
        help=(
            "Use a canned sklearn preset (e.g. 'california_housing'). Skips "
            "the 'describe your dataset' prompts and pre-installs preset deps."
        ),
    ),
    name: str | None = typer.Option(None, "--name", help="Domain name (default: cwd basename)."),
    config_dir: Path = typer.Option(  # noqa: B008
        Path(".dojo"), "--config-dir", help="Dojo state directory."
    ),
) -> None:
    """Guided, all-in-one setup. Run inside your Python project."""
    if preset is not None and preset not in PRESETS:
        console.print(
            f"[red]error:[/red] unknown preset {preset!r}. "
            f"Available: {', '.join(sorted(PRESETS.keys())) or '(none)'}"
        )
        raise typer.Exit(code=EXIT_USER_ERROR)

    if not _stdin_is_tty() and preset is None:
        console.print(
            "[red]error:[/red] `dojo onboard` is interactive and stdin is not a TTY. "
            "Use [cyan]dojo onboard --preset <key>[/cyan] for non-interactive preset "
            "setup, or [cyan]dojo init --non-interactive[/cyan] for scripted use."
        )
        raise typer.Exit(code=EXIT_USER_ERROR)

    asyncio.run(
        _onboard_async(
            workspace_arg=workspace,
            preset_key=preset,
            name=name,
            config_dir=config_dir,
        )
    )


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


async def _onboard_async(
    *,
    workspace_arg: str,
    preset_key: str | None,
    name: str | None,
    config_dir: Path,
) -> None:
    cwd = Path.cwd().resolve()

    # ---- 1. Footgun check (silent unless triggered) --------------------------
    _check_cwd_footgun(cwd)

    # ---- 2. Existing .dojo/ check -------------------------------------------
    if not _handle_existing_dojo_dir(config_dir):
        raise typer.Exit(code=0)

    # ---- 3. Workspace + dep-source preview (no prompt) ----------------------
    try:
        workspace_obj = build_workspace_from_arg(workspace_arg)
    except FileNotFoundError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=EXIT_USER_ERROR) from e
    _preview_workspace(workspace_obj, cwd)

    # ---- 4. Config decisions ------------------------------------------------
    config_path = _bootstrap_config(config_dir)
    _prompt_config_choices(config_path)

    lab, settings = build_cli_lab()
    console.print(f"[green]✓[/green] config ready at {config_path}")

    # ---- 5. Domain name + description ---------------------------------------
    domain_name = name or cwd.name or "research"
    domain_name = Prompt.ask("[bold]Domain name[/bold]", default=domain_name)
    description = Prompt.ask("[bold]Description (optional)[/bold]", default="")

    # ---- 6. Preset vs. custom branch ---------------------------------------
    program_md, setup_md, preset = _resolve_program_and_setup(
        preset_key=preset_key, domain_name=domain_name, description=description
    )

    # ---- 7. Create domain + workspace + task --------------------------------
    with console.status(
        f"[bold]creating domain {domain_name!r}...[/bold]",
        spinner="dots",
    ):
        domain, workspace_warning = await create_domain_with_workspace(
            lab=lab,
            name=domain_name,
            description=description,
            workspace=workspace_obj,
            storage_base_dir=Path(settings.storage.base_dir),
        )
    console.print(f"[green]✓[/green] domain created: {domain.id} ({domain.name})")

    if workspace_warning is not None:
        console.print(f"[yellow]warning:[/yellow] workspace setup failed: {workspace_warning}")
        console.print(
            f"Continuing — fix manually or rerun `POST /domains/{domain.id}/workspace/setup`"
        )
    elif domain.workspace and domain.workspace.path:
        console.print(f"[green]✓[/green] workspace ready: {domain.workspace.path}")

    with console.status("[bold]creating regression task...[/bold]", spinner="dots"):
        domain, task = await create_regression_task(
            lab=lab,
            domain=domain,
            task_type=TaskType.REGRESSION,
            config=build_task_config(TaskType.REGRESSION),
        )
    console.print(f"[green]✓[/green] task created: {task.id} ({task.type.value})")

    # ---- Write PROGRAM.md + SETUP.md ----------------------------------------
    program_path = write_program(domain, program_md, base_dir=Path(settings.storage.base_dir))
    domain.program_path = str(program_path)
    setup_path = write_setup(domain, setup_md, base_dir=Path(settings.storage.base_dir))
    domain.setup_path = str(setup_path)
    await lab.domain_store.save(domain)
    console.print(f"[green]✓[/green] PROGRAM.md scaffolded at {program_path}")
    console.print(f"[green]✓[/green] SETUP.md scaffolded at {setup_path}")

    # ---- 8. Preset-only: pre-install preset deps ----------------------------
    if preset is not None and domain.workspace and domain.workspace.python_path:
        _pip_install_into_workspace(
            python_path=domain.workspace.python_path,
            modules=list(preset.pip_deps),
            label=f"installing preset deps ({', '.join(preset.pip_deps)})",
        )

    # ---- 9. Tool generation + verification with retry-on-missing-import -----
    set_current_domain_id(Path(settings.storage.base_dir), domain.id)
    success = await _generate_and_verify_with_retries(lab=lab, domain=domain)
    if not success:
        # _generate_and_verify_with_retries already printed the user-facing
        # error help. Match `dojo task setup`'s exit code semantics.
        raise typer.Exit(code=EXIT_GATE)

    # Reload — domain.task.tools are now persisted with verification.
    domain = await lab.domain_store.load(domain.id)
    assert domain is not None

    # ---- 10. Freeze ---------------------------------------------------------
    try:
        await _do_freeze(lab, domain, unsafe_skip_verify=False)
    except (typer.Exit, TaskVerificationError, TaskFrozenError):
        # _do_freeze already printed the help block; surface its exit code.
        raise

    # ---- Done ---------------------------------------------------------------
    console.print()
    console.print("[bold green]onboarding complete[/bold green] — next steps:")
    console.print(f"  1. (optional) edit [cyan]{program_path}[/cyan] to refine the steering prompt")
    console.print("  2. run [bold]dojo run[/bold] — start the agent")
    console.print(
        "\n[dim]if you re-edit SETUP.md later, run "
        "[bold]dojo task setup[/bold] to regenerate + re-freeze the task.[/dim]"
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _check_cwd_footgun(cwd: Path) -> None:
    """Warn if cwd is the cloned Dojo repo itself."""
    if is_path_inside_dojo_repo(cwd):
        console.print(
            "[yellow]warning:[/yellow] this directory looks like the cloned Dojo repo "
            "itself — running `dojo onboard` here will create `.dojo/` inside the Dojo "
            "source tree, which is almost certainly not what you want. "
            "Cd into your own project (or a fresh empty dir) and rerun."
        )
        if not Confirm.ask("Continue anyway?", default=False):
            raise typer.Exit(code=0)


def _handle_existing_dojo_dir(config_dir: Path) -> bool:
    """Return True to proceed, False to abort (caller exits)."""
    if not config_dir.exists() or not any(config_dir.iterdir()):
        return True
    console.print(
        f"[yellow]existing[/yellow] [cyan]{config_dir}[/cyan] directory found "
        "with Dojo state in it."
    )
    choice = Prompt.ask(
        "[U]se existing / [O]verwrite / [A]bort",
        choices=["u", "o", "a"],
        default="u",
    ).lower()
    if choice == "a":
        console.print("aborted.")
        return False
    if choice == "o":
        if not Confirm.ask(f"[red]Delete {config_dir} and start fresh?[/red]", default=False):
            console.print("aborted.")
            return False
        shutil.rmtree(config_dir)
    return True


def _preview_workspace(workspace: Workspace | None, cwd: Path) -> None:
    """Print a one-line preview of what dep source we'll detect."""
    if workspace is None or workspace.path is None:
        console.print(f"[dim]Workspace: empty (no project detected at {cwd}).[/dim]")
        return

    ws_path = Path(workspace.path)
    detected: list[str] = []
    if (ws_path / "pyproject.toml").is_file():
        detected.append("pyproject.toml")
    if (ws_path / "requirements.txt").is_file():
        detected.append("requirements.txt")
    if (ws_path / ".venv").is_dir() or (ws_path / "venv").is_dir():
        detected.append("existing venv")
    if detected:
        console.print(
            f"[dim]Workspace: {ws_path} — detected {', '.join(detected)}; "
            "Dojo will reuse them.[/dim]"
        )
    else:
        console.print(
            f"[dim]Workspace: {ws_path} — no Python project files detected; "
            "Dojo will create a fresh venv.[/dim]"
        )


def _bootstrap_config(config_dir: Path) -> Path:
    """Ensure `.dojo/config.yaml` exists; return its path."""
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    if not config_path.exists():
        config_init()
    return config_path


def _prompt_config_choices(config_path: Path) -> None:
    """Walk the user through the config knobs that meaningfully change behaviour.

    Each prompt has a sensible default the user can accept by hitting enter.
    Updates `.dojo/config.yaml` only for non-default choices to keep the
    file readable.
    """
    console.print()
    console.print("[bold]Config[/bold] — press enter to accept the default in [dim]parens[/dim].")

    agent_backend = Prompt.ask("Agent backend", choices=["claude", "stub"], default="claude")
    tracking_backend = Prompt.ask("Tracking backend", choices=["file", "mlflow"], default="file")
    mlflow_uri: str | None = None
    mlflow_experiment: str | None = None
    if tracking_backend == "mlflow":
        mlflow_uri = Prompt.ask("MLflow tracking URI", default="file:./mlruns")
        mlflow_experiment = Prompt.ask("MLflow experiment name", default="dojo")
    linker = Prompt.ask("Knowledge linker", choices=["keyword", "llm"], default="keyword")

    # Only patch when the user changed something away from defaults.
    _patch_config_full(
        config_path,
        agent_backend=agent_backend if agent_backend != "claude" else None,
        tracking=tracking_backend if tracking_backend != "file" else None,
        mlflow_uri=mlflow_uri,
        mlflow_experiment=mlflow_experiment,
        linker=linker if linker != "keyword" else None,
    )


def _patch_config_full(
    config_path: Path,
    *,
    agent_backend: str | None,
    tracking: str | None,
    mlflow_uri: str | None,
    mlflow_experiment: str | None,
    linker: str | None,
) -> None:
    """Patch the YAML config with whatever the user chose. No-ops on full defaults."""
    if not any([agent_backend, tracking, mlflow_uri, mlflow_experiment, linker]):
        return

    # Reuse `_patch_config` for the simple knobs init already supports.
    if agent_backend or tracking:
        _patch_config(config_path, tracking=tracking, agent_backend=agent_backend)

    if not (mlflow_uri or mlflow_experiment or linker):
        return

    data = yaml.safe_load(config_path.read_text()) or {}
    if mlflow_uri:
        data.setdefault("tracking", {})["mlflow_tracking_uri"] = mlflow_uri
    if mlflow_experiment:
        data.setdefault("tracking", {})["mlflow_experiment_name"] = mlflow_experiment
    if linker:
        data.setdefault("memory", {})["linker"] = linker
    config_path.write_text(yaml.safe_dump(data, sort_keys=True))


def _resolve_program_and_setup(
    *, preset_key: str | None, domain_name: str, description: str
) -> tuple[str, str, object | None]:
    """Return (program_md, setup_md, preset_or_None).

    If `preset_key` is given, return that preset's content directly.
    Otherwise: offer the user a side-prompt to opt in to a preset, and
    fall back to filling the default templates with line-by-line input.
    """
    if preset_key is not None:
        preset = PRESETS[preset_key]
        console.print(f"[green]✓[/green] using preset: {preset.label}")
        return preset.program_md, preset.setup_md, preset

    # Side-prompt — default no.
    options = sorted(PRESETS.keys())
    if options:
        console.print()
        console.print(
            "[bold]PROGRAM.md + SETUP.md[/bold] — describe your dataset + evaluation, "
            "or use a preset to try the framework on a canned sklearn dataset."
        )
        choice = Prompt.ask(
            f"Use a preset? [n / {' / '.join(options)}]",
            choices=["n", *options],
            default="n",
        )
        if choice != "n":
            preset = PRESETS[choice]
            console.print(f"[green]✓[/green] using preset: {preset.label}")
            return preset.program_md, preset.setup_md, preset

    # Custom path — fill in the default templates' TODOs.
    console.print()
    console.print("[dim]Tell me about your research goal (PROGRAM.md):[/dim]")
    target = Prompt.ask("  Target — what is the model predicting?", default="")
    success = Prompt.ask("  Success — how will you know it worked?", default="")

    console.print("[dim]Tell me about your data + evaluation (SETUP.md):[/dim]")
    dataset = Prompt.ask("  Dataset — where does the data live?", default="")
    evaluate = Prompt.ask("  Evaluate — how should the metrics be computed?", default="")

    fake_domain = _FakeDomain(name=domain_name, description=description)
    program_md = fill_program_template(
        default_program_template(fake_domain),  # type: ignore[arg-type]
        target=target,
        success=success,
    )
    setup_md = fill_setup_template(
        default_setup_template(fake_domain),  # type: ignore[arg-type]
        dataset=dataset,
        evaluate=evaluate,
    )
    return program_md, setup_md, None


class _FakeDomain:
    """Tiny duck-typed stand-in for `Domain` — the template fns only read .name + .description."""

    def __init__(self, *, name: str, description: str) -> None:
        self.name = name
        self.description = description


def _pip_install_into_workspace(*, python_path: str, modules: list[str], label: str) -> None:
    """Install modules into the workspace's venv. Warn (don't raise) on failure."""
    if not modules:
        return
    console.print(f"[dim]{label}...[/dim]")
    cmd = [python_path, "-m", "pip", "install", *modules]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        console.print(f"[yellow]warning:[/yellow] pip install failed to start: {e}")
        return
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        console.print(
            f"[yellow]warning:[/yellow] pip install exited {result.returncode}; "
            f"continuing. Last lines:\n  " + "\n  ".join(tail)
        )
        return
    console.print(f"[green]✓[/green] installed: {', '.join(modules)}")


async def _generate_and_verify_with_retries(*, lab: LabEnvironment, domain: Domain) -> bool:
    """Run `_do_generate` up to MAX_INSTALL_RETRIES times, auto-installing on import errors.

    Returns True on success (every required tool verified), False on failure
    after exhausting retries or user declining the install offer.
    """
    last_errors: list[str] = []
    for attempt in range(MAX_INSTALL_RETRIES):
        try:
            tools = await _do_generate(lab, domain, hint="", verify=True, save=True, timeout=None)
        except typer.Exit:
            # _do_generate exits on hard generator errors (parse failure, backend
            # not supporting completion). Surface as a hard failure here.
            return False

        # Inspect each tool's verification.
        missing: list[str] = []
        last_errors = []
        all_verified = True
        for t in tools:
            if t.verification is None or not t.verification.verified:
                all_verified = False
                for err in t.verification.errors if t.verification else []:
                    last_errors.append(err)
                    mod = parse_module_not_found(err)
                    if mod:
                        missing.append(mod)
        if all_verified:
            return True

        deduped = sorted(set(missing))
        if not deduped:
            # Failure isn't a missing-import — no auto-fix possible.
            break

        if attempt == MAX_INSTALL_RETRIES - 1:
            console.print(
                f"[yellow]still missing modules after {MAX_INSTALL_RETRIES} attempts; "
                "giving up auto-install.[/yellow]"
            )
            break

        console.print(
            f"[yellow]verification failed[/yellow] — missing module(s): {', '.join(deduped)}"
        )
        if not Confirm.ask("Install into the workspace venv?", default=True):
            break

        # Refresh domain to read the latest workspace.python_path.
        refreshed = await lab.domain_store.load(domain.id)
        assert refreshed is not None
        if not (refreshed.workspace and refreshed.workspace.python_path):
            console.print(
                "[yellow]warning:[/yellow] workspace has no python_path — "
                "cannot auto-install. Install the modules manually and rerun "
                "[cyan]dojo task setup[/cyan]."
            )
            break
        _pip_install_into_workspace(
            python_path=refreshed.workspace.python_path,
            modules=deduped,
            label=f"installing {', '.join(deduped)}",
        )
        domain = refreshed

    # All retries exhausted — surface the verifier's last errors and the
    # standard help block so the user knows where to look.
    console.print()
    console.print("[red]✗ tool verification failed:[/red]")
    for err in last_errors[:10]:
        console.print(f"  · {err}")
    console.print(
        "\n  [dim]how to read these errors:[/dim]\n"
        "    [cyan]·[/cyan] [dim]if a message says[/dim] "
        "[yellow]<file>.py:<line>[/yellow][dim], the bug is in the AI-generated "
        "tool — edit SETUP.md to steer it differently and rerun "
        "[cyan]dojo task setup[/cyan][/dim]\n"
        "    [cyan]·[/cyan] [dim]messages mentioning[/dim] "
        "[yellow]0 rows / dataset window / cache[/yellow][dim] are about "
        "your data setup — fix SETUP.md[/dim]"
    )
    return False
