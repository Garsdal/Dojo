"""`dojo run` — start an agent run on the current domain (in-process, no server)."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path

import typer
from rich.console import Console

from dojo.agents.factory import create_agent_backend
from dojo.agents.orchestrator import AgentOrchestrator
from dojo.agents.types import AgentEvent, AgentRun, RunStatus
from dojo.cli._lab import build_cli_lab
from dojo.cli.state import CLIStateError, resolve_domain, set_current_run_id
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.program_loader import load_program
from dojo.runtime.task_service import TaskNotReadyError
from dojo.utils.logging import get_logger

console = Console()
logger = get_logger(__name__)


# Exit codes per docs/NEXT_STEPS.md CLI conventions
EXIT_USER_ERROR = 1
EXIT_SYSTEM_ERROR = 2
EXIT_TASK_NOT_READY = 3


def run(
    domain: str | None = typer.Option(None, "--domain", "-d", help="Domain id or name"),
    max_turns: int = typer.Option(
        50, "--max-turns", help="Cumulative max agent turns across continuations"
    ),
    max_budget_usd: float | None = typer.Option(
        None, "--max-budget-usd", help="Cumulative max spend cap in USD"
    ),
    max_wall_clock_s: float | None = typer.Option(
        None,
        "--max-wall-clock-s",
        help="Wall-clock cap (seconds) for the whole run. Checked between continuations.",
    ),
    no_continue: bool = typer.Option(
        False,
        "--no-continue",
        help="Disable the continuation loop; one backend invocation then stop",
    ),
    no_watch: bool = typer.Option(
        False, "--no-watch", help="Start the run and exit without streaming events"
    ),
    prompt: str | None = typer.Option(
        None, "--prompt", help="Override prompt (defaults to PROGRAM.md / domain.prompt)"
    ),
) -> None:
    """Start an agent run on the current domain (no server required).

    Stop with Ctrl-C: the orchestrator is interrupted, the framework asks the
    backend to summarise any durable findings as knowledge atoms, then prints
    a final cost line. A second Ctrl-C during cleanup hard-exits.
    """
    asyncio.run(
        _run_async(
            domain_override=domain,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            max_wall_clock_s=max_wall_clock_s,
            auto_continue=not no_continue,
            no_watch=no_watch,
            prompt_override=prompt,
        )
    )


async def _run_async(
    *,
    domain_override: str | None,
    max_turns: int,
    max_budget_usd: float | None,
    max_wall_clock_s: float | None,
    auto_continue: bool,
    no_watch: bool,
    prompt_override: str | None,
) -> None:
    lab, settings = build_cli_lab()
    base_dir = Path(settings.storage.base_dir)

    try:
        d = await resolve_domain(lab, base_dir=base_dir, override=domain_override)
    except CLIStateError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=EXIT_USER_ERROR) from e

    # Pick prompt: explicit override > PROGRAM.md > domain.prompt > friendly default
    prompt = prompt_override or load_program(d, base_dir=base_dir)
    if not prompt:
        prompt = f"Make progress on the {d.name} research domain."

    backend = create_agent_backend(settings.agent.backend)
    orchestrator = AgentOrchestrator(
        lab,
        backend,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        max_wall_clock_s=max_wall_clock_s
        if max_wall_clock_s is not None
        else settings.agent.max_wall_clock_s,
        auto_continue=auto_continue and settings.agent.auto_continue,
        permission_mode=settings.agent.permission_mode,
        cwd=settings.agent.cwd,
    )

    with console.status("[dim]starting agent run…[/dim]") as status:

        def _on_phase(label: str) -> None:
            status.update(f"[dim]{label}…[/dim]")

        try:
            run_obj = await orchestrator.start(
                prompt=prompt,
                domain_id=d.id,
                progress=_on_phase,
            )
        except TaskNotReadyError as e:
            console.print(f"[red]✗ task not ready:[/red] {e}")
            console.print("\n  fix: run [bold]dojo domain setup[/bold].")
            raise typer.Exit(code=EXIT_TASK_NOT_READY) from e
        except Exception as e:
            console.print(f"[red]failed to start run:[/red] {e}")
            raise typer.Exit(code=EXIT_SYSTEM_ERROR) from e

    set_current_run_id(base_dir, run_obj.id)

    console.print(
        f"[green]▶[/green] run [bold]{run_obj.id}[/bold] started "
        f"on domain [cyan]{d.name}[/cyan] (backend={backend.name})"
    )
    console.print(
        "  [dim]graceful stop:[/dim] [bold]dojo stop[/bold] "
        "[dim](in another terminal — preserves cost & turn data)[/dim]"
    )
    console.print(
        "  [dim]forceful stop:[/dim] [bold]Ctrl-C[/bold] "
        "[dim](still recovers knowledge, may lose cost data)[/dim]\n"
    )

    if no_watch:
        # Fire-and-forget: kick off execute() and return. The run is persisted
        # via run_store so other processes can observe it. The task runs to
        # completion before asyncio.run() exits because we await it briefly
        # below — long-running runs should use the server, not --no-watch.
        bg = asyncio.create_task(orchestrator.execute(run_obj))
        # Give the orchestrator a tick to write the initial run state.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(bg, timeout=0.5)
        console.print(
            f"Watching disabled. Stream later with `dojo runs show {run_obj.id}` or via the API."
        )
        return

    execute_task = asyncio.create_task(orchestrator.execute(run_obj))

    # Install a SIGINT handler so the first Ctrl-C requests a graceful stop and
    # a second Ctrl-C aborts. We can't replace KeyboardInterrupt entirely on
    # all platforms, but `loop.add_signal_handler` works on POSIX (incl. macOS).
    stop_requested = asyncio.Event()
    sigint_count = {"n": 0}

    def _on_sigint() -> None:
        sigint_count["n"] += 1
        if sigint_count["n"] == 1:
            console.print(
                "\n[yellow]■[/yellow] stop requested — finishing up (Ctrl-C again to abort cleanup)"
            )
            stop_requested.set()
            # Flip the orchestrator's intent flag synchronously: SIGINT
            # propagates to the backend's subprocess too, and the resulting
            # error event will reach the orchestrator before _graceful_stop
            # can call stop(). Without this, the run would be marked FAILED.
            orchestrator.mark_stop_requested()
        else:
            console.print("\n[red]✗[/red] hard stop")

    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGINT, _on_sigint)

    try:
        seen = await _stream_events(run_obj, execute_task, stop_requested)
    finally:
        with contextlib.suppress(NotImplementedError):
            loop.remove_signal_handler(signal.SIGINT)

    # Run cleanup whenever the user asked to stop, even if the backend's
    # subprocess died first and execute() already transitioned to STOPPED —
    # we still want knowledge extraction.
    if stop_requested.is_set() and run_obj.status in (RunStatus.RUNNING, RunStatus.STOPPED):
        await _graceful_stop(orchestrator, run_obj, lab, sigint_count)
        # Drain the execute task so any final writes land before we return.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(execute_task, timeout=2.0)
        # Render any events emitted by the flush / finalization that
        # arrived after _stream_events returned on stop_requested.
        for ev in run_obj.events[seen:]:
            _print_event(ev)

    _print_final_summary(run_obj)

    if run_obj.status == RunStatus.FAILED:
        raise typer.Exit(code=EXIT_SYSTEM_ERROR)


async def _stream_events(
    run_obj: AgentRun,
    execute_task: asyncio.Task,
    stop_requested: asyncio.Event,
) -> int:
    """Print agent events to the terminal as they're produced.

    Polls `run_obj.events` (the same list orchestrator.execute() appends to).
    The orchestrator runs in the background task; we read the shared list.
    Returns early if `stop_requested` is set so the caller can run cleanup.

    Returns the number of events already rendered, so the caller's post-stop
    cleanup block can drain remaining events without double-printing.
    """
    seen = 0
    terminal_states = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.STOPPED}

    while True:
        while seen < len(run_obj.events):
            _print_event(run_obj.events[seen])
            seen += 1

        if execute_task.done() and run_obj.status in terminal_states:
            # Drain any final events that landed after the loop's last read
            while seen < len(run_obj.events):
                _print_event(run_obj.events[seen])
                seen += 1
            return seen

        if stop_requested.is_set():
            return seen

        await asyncio.sleep(0.1)


def _print_event(event: AgentEvent) -> None:
    """Render a single agent event in human-readable form."""
    et = event.event_type
    data = event.data

    if et == "text":
        console.print(data.get("text", ""), style="white")
    elif et == "tool_call":
        tool = data.get("tool", "?")
        console.print(f"  [blue]→[/blue] [bold]{tool}[/bold]", style="blue")
    elif et == "tool_result":
        tool = data.get("tool", "?")
        console.print(f"  [green]←[/green] {tool}", style="dim green")
    elif et == "error":
        console.print(f"  [red]error:[/red] {data.get('error', 'unknown')}")
    elif et == "result":
        cost = data.get("cost_usd")
        turns = data.get("turns", 0)
        bits = [f"turns={turns}"]
        if cost is not None:
            bits.append(f"cost=${cost:.4f}")
        console.print(f"\n[dim]result: {', '.join(bits)}[/dim]")
    elif et == "continuation_started":
        iteration = data.get("iteration", "?")
        rem_turns = data.get("remaining_turns")
        rem_budget = data.get("remaining_budget_usd")
        bits: list[str] = []
        if rem_turns is not None:
            bits.append(f"{rem_turns} turns")
        if rem_budget is not None:
            bits.append(f"${rem_budget:.2f}")
        budget_str = f" (remaining: {', '.join(bits)})" if bits else ""
        console.print(f"[dim]↻ continuing — iteration {iteration}{budget_str}[/dim]")
    elif et == "knowledge_flush_started":
        console.print("[dim]saving durable knowledge from this session…[/dim]")
    elif et == "knowledge_flush_completed":
        if "error" in data:
            console.print(f"[dim]knowledge extraction skipped: {data['error']}[/dim]")
        else:
            count = int(data.get("count", 0))
            if count:
                console.print(f"[green]✓[/green] saved {count} knowledge atom(s) from this session")
            else:
                console.print("[dim]no durable findings worth saving[/dim]")
    elif et == "run_finalized":
        # Sentinel — drives SSE termination, no terminal output needed.
        pass
    else:
        console.print(f"  [dim]{et}[/dim]")


# --- Graceful stop -----------------------------------------------------------


async def _graceful_stop(
    orchestrator: AgentOrchestrator,
    run_obj: AgentRun,
    lab: LabEnvironment,
    sigint_count: dict,
) -> None:
    """Interrupt the agent, then extract durable findings as knowledge atoms.

    The flush itself emits ``knowledge_flush_started`` / ``knowledge_flush_completed``
    events into ``run_obj.events``; ``_print_event`` renders them. We don't
    print here — that would duplicate the indicator on dual-flush paths.

    A second Ctrl-C during this window short-circuits the cleanup so the
    user is never trapped waiting on the LLM.
    """
    try:
        await orchestrator.stop()
    except Exception as e:
        logger.warning("graceful_stop_interrupt_error", error=str(e))

    if sigint_count["n"] >= 2:
        return

    try:
        await orchestrator.flush_knowledge(run_obj)
    except (asyncio.CancelledError, Exception) as e:
        logger.warning("graceful_stop_extract_failed", error=str(e))


def _print_final_summary(run_obj: AgentRun) -> None:
    """One-line summary at the end of the run, with cost when available."""
    cost = (
        run_obj.result.total_cost_usd
        if run_obj.result and run_obj.result.total_cost_usd is not None
        else None
    )
    cost_str = f" — cost ${cost:.4f}" if cost is not None else ""
    events = len(run_obj.events)

    if run_obj.status == RunStatus.COMPLETED:
        console.print(f"\n[green]✓[/green] run completed ({events} events){cost_str}")
    elif run_obj.status == RunStatus.FAILED:
        console.print(f"\n[red]✗[/red] run failed: {run_obj.error or 'unknown error'}{cost_str}")
    elif run_obj.status == RunStatus.STOPPED:
        console.print(f"\n[yellow]■[/yellow] run stopped ({events} events){cost_str}")
