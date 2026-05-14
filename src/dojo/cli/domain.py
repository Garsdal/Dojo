"""`dojo domain` — manage research domains and their frozen task contract.

A **domain** is a frozen research contract: one `load_data` + one `evaluate`
+ one workspace. Many experiments live inside it. Create a new domain when
the data source, target variable, or evaluation metric changes — not when
you want to try a new model or feature.

The user-facing surface:
  - `dojo domain setup`     — generate `load_data` + `evaluate` from
                              SETUP.md, verify, and freeze the task.
  - `dojo domain unfreeze`  — unfreeze the task to allow regeneration.
  - `dojo domain show`      — print domain metadata + task state.
  - `dojo domain use NAME`  — switch active domain.

Creating a new domain is `dojo onboard` (interactive) or
`dojo onboard --non-interactive --name X` (scripted).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console

from dojo.agents.factory import create_agent_backend
from dojo.cli._lab import build_cli_lab
from dojo.cli.state import (
    CLIStateError,
    get_current_domain_id,
    resolve_domain,
    set_current_domain_id,
)
from dojo.core.domain import Domain, DomainTool
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.setup_loader import load_setup, resolve_setup_path
from dojo.runtime.task_service import (
    TaskFrozenError,
    TaskService,
    TaskVerificationError,
)
from dojo.runtime.tool_verifier import verify_required_tools
from dojo.tools.tool_generation import (
    build_task_generation_prompt,
    dicts_to_domain_tools,
    parse_generated_tools,
)

console = Console()

DOMAIN_HELP = (
    "Manage research domains. A domain is a frozen `load_data` + `evaluate` "
    "contract plus a workspace; many experiments live inside one. Create "
    "domains with `dojo onboard`."
)

app = typer.Typer(help=DOMAIN_HELP)

EXIT_USER_ERROR = 1
EXIT_SYSTEM_ERROR = 2
EXIT_GATE = 3

DEFAULT_VERIFICATION_TIMEOUT_HELP = (
    "Override the per-tool verification timeout (seconds). Defaults to "
    "settings.sandbox.verification_timeout (10 min) — bump it when "
    "load_data has a slow first-time fetch and a smaller timeout would "
    "trip during cache warm-up."
)


# --- Resolve helper ---------------------------------------------------------


async def _resolve(*, override: str | None) -> tuple[LabEnvironment, Domain, Path]:
    lab, settings = build_cli_lab()
    base_dir = Path(settings.storage.base_dir)
    try:
        d = await resolve_domain(lab, base_dir=base_dir, override=override)
    except CLIStateError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=EXIT_USER_ERROR) from e
    return lab, d, base_dir


# --- Commands --------------------------------------------------------------


@app.command("setup")
def setup(
    hint: str = typer.Option("", "--hint", help="Natural-language hint for generation"),
    domain: str | None = typer.Option(None, "--domain", "-d", help="Domain id or name"),
    unsafe_skip_verify: bool = typer.Option(
        False,
        "--unsafe-skip-verify",
        help="Freeze even if verification fails (rare — accepts the risk)",
    ),
    timeout: float | None = typer.Option(None, "--timeout", help=DEFAULT_VERIFICATION_TIMEOUT_HELP),
) -> None:
    """Generate tools from SETUP.md, verify them, and freeze the task."""

    async def _run() -> None:
        lab, d, _ = await _resolve(override=domain)
        await _do_generate(lab, d, hint=hint, verify=True, save=True, timeout=timeout)
        # Reload so freeze sees the just-saved tools
        d_after = await lab.domain_store.load(d.id)
        assert d_after is not None
        await _do_freeze(lab, d_after, unsafe_skip_verify=unsafe_skip_verify)

    asyncio.run(_run())


@app.command("unfreeze")
def unfreeze(
    domain: str | None = typer.Option(None, "--domain", "-d", help="Domain id or name"),
) -> None:
    """Unfreeze the task to allow tool changes.

    Warning: prior experiment metrics may not be comparable to new ones if
    tool code changes.
    """

    async def _run() -> None:
        lab, d, _ = await _resolve(override=domain)
        try:
            await TaskService(lab).unfreeze(d.id)
        except (ValueError, TaskFrozenError) as e:
            console.print(f"[red]error:[/red] {e}")
            raise typer.Exit(code=EXIT_USER_ERROR) from e
        console.print(
            f"[yellow]⚠[/yellow] task unfrozen on domain {d.name} — "
            "prior metrics may not be comparable."
        )

    asyncio.run(_run())


@app.command("show")
def show(
    domain: str | None = typer.Option(None, "--domain", "-d", help="Domain id or name"),
) -> None:
    """Print current domain metadata + task state.

    With no `--domain`, shows the active domain set by `dojo onboard` or
    `dojo domain use`.
    """

    async def _run() -> None:
        _, d, _base = await _resolve(override=domain)
        # Domain metadata
        console.print(f"[bold]domain[/bold] {d.id}  [cyan]{d.name}[/cyan]")
        if d.description:
            console.print(f"  description: {d.description}")
        console.print(f"  status: {d.status.value}")
        if d.workspace:
            ws = d.workspace
            ws_descriptor = ws.path or ws.git_url or "(empty)"
            console.print(f"  workspace: [{ws.source.value}] {ws_descriptor}")

        # Task state
        if d.task is None:
            console.print(
                "\n[yellow]no task on this domain[/yellow]\n"
                "Run [bold]dojo onboard[/bold] to create one (or "
                "[bold]dojo domain setup[/bold] if PROGRAM.md + SETUP.md "
                "already exist)."
            )
            return
        t = d.task
        frozen_label = "[green]frozen[/green]" if t.frozen else "[yellow]not frozen[/yellow]"
        console.print(f"\n[bold]task[/bold] {t.id}  {frozen_label}")
        console.print(f"  type: {t.type.value}")
        console.print(f"  primary_metric: {t.primary_metric} ({t.direction.value})")
        if t.config:
            console.print("  config:")
            for k, v in t.config.items():
                console.print(f"    {k}: {v}")
        console.print(f"  tools ({len(t.tools)}):")
        for tool in t.tools:
            kind = tool.type.value
            mark = _verify_marker(tool)
            console.print(f"    {mark} {tool.name} [{kind}] — {tool.description[:60]}")

    asyncio.run(_run())


@app.command("use")
def use(
    name_or_id: str = typer.Argument(..., help="Domain name or id"),
    config_dir: Path = typer.Option(  # noqa: B008
        Path(".dojo"), "--config-dir", help="Dojo state directory"
    ),
) -> None:
    """Set the current domain (analogous to `git checkout`)."""

    async def _run() -> None:
        lab, _ = build_cli_lab()
        target = await lab.domain_store.load(name_or_id)
        if target is None:
            for d in await lab.domain_store.list():
                if d.name == name_or_id:
                    target = d
                    break
        if target is None:
            typer.echo(f"error: no domain matches {name_or_id!r}", err=True)
            sys.exit(EXIT_USER_ERROR)
        set_current_domain_id(config_dir, target.id)
        typer.echo(f"✓ current domain → {target.name} ({target.id})")

    asyncio.run(_run())


# --- Internal helpers (shared with `dojo onboard`) -------------------------
#
# `_do_generate` and `_do_freeze` are imported by `dojo onboard` so its
# auto-install-retry loop can drive the same tool generation + freeze
# pipeline as `dojo domain setup`. Keep them as plain async functions —
# typer commands can't be called as Python functions safely.


async def _do_generate(
    lab: LabEnvironment,
    d: Domain,
    *,
    hint: str,
    verify: bool,
    save: bool,
    timeout: float | None = None,
) -> list[DomainTool]:
    """Generate (and optionally verify + persist) tools for the domain's task."""
    if d.task is None:
        console.print(
            "[red]error:[/red] domain has no task — create one first with `dojo onboard`."
        )
        raise typer.Exit(code=EXIT_USER_ERROR)
    if d.task.frozen:
        console.print("[red]error:[/red] task is frozen. Run `dojo domain unfreeze` first.")
        raise typer.Exit(code=EXIT_USER_ERROR)

    base_dir = Path(lab.settings.storage.base_dir)
    setup_path = resolve_setup_path(d, base_dir=base_dir)
    setup_md = load_setup(d, base_dir=base_dir)
    prompt = build_task_generation_prompt(d, d.task, hint, setup_md=setup_md)
    backend = create_agent_backend(
        lab.settings.agent.backend,
        model=lab.settings.agent.tool_generation_model,
    )

    console.print(f"[dim]reading[/dim] [cyan]{setup_path}[/cyan]")
    label = f"{backend.name} ({backend.model})" if backend.model else backend.name
    console.print(
        f"[dim]using[/dim] [bold]{label}[/bold] [dim]to generate load_data + evaluate"
        " (this normally takes 15-30s)[/dim]"
    )
    with console.status(
        f"[bold]asking {label}...[/bold]",
        spinner="dots",
    ):
        try:
            raw = await backend.complete(prompt)
        except (AttributeError, NotImplementedError) as e:
            console.print(
                "[red]backend does not support tool generation:[/red] "
                f"{lab.settings.agent.backend} ({e})"
            )
            raise typer.Exit(code=EXIT_SYSTEM_ERROR) from e

    try:
        tool_dicts = parse_generated_tools(raw)
    except ValueError as e:
        console.print(f"[red]could not parse generated tools:[/red] {e}")
        console.print(f"\n[dim]raw output:[/dim]\n{raw[:500]}")
        raise typer.Exit(code=EXIT_SYSTEM_ERROR) from e

    new_tools = dicts_to_domain_tools(tool_dicts)
    console.print(f"[green]generated {len(new_tools)} tools[/green]")

    sources_dir = TaskService(lab).sources_dir(d.id)
    if save:
        _write_modules_to_sources(sources_dir, new_tools)

    if verify:
        effective_timeout = (
            timeout if timeout is not None else lab.settings.sandbox.verification_timeout
        )
        console.print(
            "[dim]note: verification runs load_data in full — first-time data downloads "
            "and cache builds happen here (this can take several minutes)[/dim]"
        )
        with console.status(
            f"[bold]verifying tools against the regression contract "
            f"(timeout {effective_timeout:.0f}s) — running load_data first...[/bold]",
            spinner="dots",
        ):
            await verify_required_tools(
                new_tools,
                d.task,
                sandbox=lab.sandbox,
                workspace=d.workspace,
                timeout=effective_timeout,
                module_dir=sources_dir if save else None,
            )

    for t in new_tools:
        kind = t.type.value
        mark = _verify_marker(t)
        console.print(f"  {mark} {t.name} [{kind}] — {t.description[:60]}")
        if t.verification and not t.verification.verified:
            for err in t.verification.errors:
                console.print(f"      [red]·[/red] {err}")

    if not save:
        return new_tools

    d.task.tools = new_tools
    await lab.domain_store.save(d)
    console.print(f"[green]✓[/green] saved to domain {d.id}")
    return new_tools


def _write_modules_to_sources(sources_dir: Path, tools: list[DomainTool]) -> None:
    """Write each tool's source to ``<sources_dir>/<module_filename>``."""
    sources_dir.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        if not tool.module_filename or not tool.code:
            continue
        target = sources_dir / tool.module_filename
        target.write_text(tool.code)
        console.print(f"  [dim]wrote[/dim] {target}")


async def _do_freeze(lab: LabEnvironment, d: Domain, *, unsafe_skip_verify: bool) -> None:
    """Freeze a domain's task with proper error surfacing."""
    if d.task is None:
        console.print("[red]error:[/red] domain has no task")
        raise typer.Exit(code=EXIT_USER_ERROR)

    try:
        await TaskService(lab).freeze(d.id, skip_verification=unsafe_skip_verify)
    except TaskVerificationError as exc:
        console.print("[red]✗ task cannot be frozen — verification gate failed:[/red]")
        for err in exc.errors:
            console.print(f"  · {err}")
        setup_path = resolve_setup_path(d, base_dir=Path(lab.settings.storage.base_dir))
        console.print(
            "\n  [dim]how to read these errors:[/dim]\n"
            "    [cyan]·[/cyan] [dim]if a message says[/dim] "
            "[yellow]<file>.py:<line>[/yellow][dim], the bug is in the AI-generated "
            "tool — edit SETUP.md (or pass --hint) to steer it differently[/dim]\n"
            "    [cyan]·[/cyan] [dim]messages mentioning[/dim] "
            "[yellow]0 rows / dataset window / cache[/yellow][dim] are about "
            "your data setup — fix the dataset spec in SETUP.md[/dim]\n"
            "    [cyan]·[/cyan] [dim]messages like[/dim] "
            "[yellow]verifier cannot JSON-encode / no result marker[/yellow]"
            "[dim] are framework bugs — please open a dojo issue[/dim]"
        )
        console.print(
            f"\n  fix: edit [cyan]{setup_path}[/cyan] (or pass --hint), then re-run "
            "[bold]dojo domain setup[/bold]."
        )
        raise typer.Exit(code=EXIT_GATE) from exc
    except (ValueError, TaskFrozenError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=EXIT_USER_ERROR) from exc

    if unsafe_skip_verify:
        console.print(
            f"[yellow]⚠[/yellow] task frozen on domain {d.name} "
            "[bold]without verification[/bold] (--unsafe-skip-verify)"
        )
    else:
        console.print(f"[green]✓[/green] task frozen on domain {d.name}")


def _verify_marker(tool: DomainTool | object) -> str:
    """Return a coloured marker for a tool's verification status."""
    v = getattr(tool, "verification", None)
    if v is None:
        return "[dim]?[/dim]"
    return "[green]✓[/green]" if v.verified else "[red]✗[/red]"


# `get_current_domain_id` re-export kept for callers that imported it from
# this module historically. New code should import from `dojo.cli.state`.
__all__ = ["app", "get_current_domain_id"]
