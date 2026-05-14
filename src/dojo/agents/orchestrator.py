"""Agent orchestrator — manages an agent run lifecycle, SDK-agnostic."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from dojo.agents.backend import AgentBackend
from dojo.agents.prompts import build_system_prompt
from dojo.agents.summarizer import flush_run_knowledge
from dojo.agents.types import (
    AgentEvent,
    AgentRun,
    AgentRunConfig,
    AgentRunResult,
    RunStatus,
    ToolHint,
)
from dojo.core.domain import Domain
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.program_loader import load_program
from dojo.runtime.task_service import TaskNotReadyError, TaskService
from dojo.tools.base import ToolDef
from dojo.tools.server import collect_all_tools
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

# How often the orchestrator polls run_store for an out-of-process stop signal.
# 1s feels responsive enough for `dojo stop` while keeping disk noise minimal.
_STOP_POLL_INTERVAL_S = 1.0

# When fewer than this many turns remain we don't bother starting a new
# continuation — there isn't enough budget left for even one experiment, so
# the loop terminates rather than firing up the SDK for a near-empty window.
_MIN_TURNS_TO_CONTINUE = 5


class AgentOrchestrator:
    """Manages one agent run using a pluggable AgentBackend.

    The orchestrator is responsible for:
    - Building the AgentRunConfig (system prompt, limits)
    - Collecting ToolDefs from v1
    - Passing tools + config to the backend
    - Driving the execute loop and appending events to AgentRun
    - Error handling and status transitions

    It does NOT know about Claude, Copilot, or any specific SDK.
    """

    def __init__(
        self,
        lab: LabEnvironment,
        backend: AgentBackend,
        *,
        max_turns: int = 50,
        max_budget_usd: float | None = None,
        max_wall_clock_s: float | None = None,
        auto_continue: bool = True,
        permission_mode: str = "acceptEdits",
        cwd: str | None = None,
    ) -> None:
        self.lab = lab
        self.backend = backend
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.max_wall_clock_s = max_wall_clock_s
        self.auto_continue = auto_continue
        self.permission_mode = permission_mode
        self.cwd = cwd
        self._run: AgentRun | None = None
        self._stop_requested = False
        self._knowledge_flushed = False
        # Cached at start() so continuation iterations can rebuild
        # AgentRunConfig + reconfigure the backend without re-walking the
        # tool registry. domain_id lets us reload the latest domain (which
        # may have grown new knowledge atoms mid-run via write_knowledge).
        self._tool_defs: list[ToolDef] = []
        self._domain_id: str | None = None
        self._workspace_cwd: str | None = None
        self._workspace_python_path: str | None = None

    async def start(
        self,
        prompt: str,
        *,
        domain_id: str,
        tool_hints: list[ToolHint] | None = None,
        require_ready_task: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> AgentRun:
        """Prepare an agent run: validate the task contract, configure backend.

        Phase 3 gate: the domain must exist, have a task, the task must be
        frozen, and every required tool must be verified. Pass
        ``require_ready_task=False`` only for tests / debug flows that
        intentionally bypass the gate.

        ``progress`` is an optional sync callback that receives short
        human-readable phase labels. The CLI uses it to render a phased
        spinner during the otherwise-silent setup window before SSE events
        begin flowing. When ``progress=None`` behaviour is identical to
        before this hook existed.

        Does not start execution — call execute() separately (usually in a
        background task).
        """

        def _emit(label: str) -> None:
            if progress is not None:
                progress(label)

        # Load domain first so we can run the contract check before persisting
        # any run state. Failing fast keeps disk clean.
        _emit("loading domain context")
        domain = await self.lab.domain_store.load(domain_id)
        if require_ready_task:
            if domain is None:
                raise TaskNotReadyError(
                    f"Domain {domain_id!r} not found. Create one with `dojo onboard`."
                )
            _emit("checking task readiness")
            TaskService(self.lab).assert_ready(domain_id, domain.task)

        run = AgentRun(
            domain_id=domain_id,
            prompt=prompt,
            status=RunStatus.RUNNING,
            started_at=datetime.now(UTC),
            tool_hints=tool_hints or [],
        )
        self._run = run
        await self.lab.run_store.save(run)

        accumulated_knowledge: list[str] = []

        if domain is not None:
            _emit("indexing prior knowledge")
            atoms = await self.lab.knowledge_linker.get_domain_knowledge(domain_id)
            accumulated_knowledge = []
            for a in atoms[:20]:
                accumulated_knowledge.append(f"- [{a.confidence:.1f}] {a.claim}")
                if a.context:
                    accumulated_knowledge.append(f"    ↳ {a.context}")

            # PROGRAM.md (if present) overrides domain.prompt for this run.
            base_dir: Path | None = None
            if self.lab.settings is not None:
                base_dir = Path(self.lab.settings.storage.base_dir)
            program = load_program(domain, base_dir=base_dir)
            if program:
                domain.prompt = program

        # Build system prompt with domain context
        system_prompt = build_system_prompt(
            run,
            domain=domain,
            accumulated_knowledge=accumulated_knowledge,
        )

        # Build config
        config = AgentRunConfig(
            system_prompt=system_prompt,
            max_turns=self.max_turns,
            max_budget_usd=self.max_budget_usd,
            max_wall_clock_s=self.max_wall_clock_s,
            permission_mode=self.permission_mode,
            cwd=self.cwd,
            domain_id=run.domain_id,
        )
        if domain is not None and domain.workspace is not None and domain.workspace.ready:
            ws = domain.workspace
            if ws.path:
                config.cwd = ws.path
            if ws.python_path:
                config.python_path = ws.python_path
        run.config = config
        # Cache the workspace plumbing so continuation iterations rebuild
        # AgentRunConfig with the same cwd / python without re-resolving the
        # domain's workspace.
        self._workspace_cwd = config.cwd
        self._workspace_python_path = config.python_path
        self._domain_id = run.domain_id

        # Collect tool definitions (framework-agnostic)
        tool_defs = collect_all_tools(self.lab, domain=domain)
        self._tool_defs = tool_defs

        # Configure the backend with tools and config
        _emit("configuring agent backend")
        await self.backend.configure(tool_defs, config)

        return run

    async def execute(self, run: AgentRun) -> None:
        """Execute the agent run, driving the continuation loop.

        Each iteration calls the backend once. When the SDK stream ends
        naturally (no error, no stop, ``is_error=False``) and budget remains,
        the orchestrator reconfigures the backend with the latest accumulated
        knowledge + remaining budget and runs another iteration. The loop
        terminates on any of:

        - ``self._stop_requested`` (``dojo stop`` or SIGINT)
        - The backend emitting an ``error`` event or an ``is_error=True`` result
        - Cumulative turns / dollars / wall-clock hitting the configured caps
        - ``auto_continue=False`` (legacy single-iteration behaviour)

        The end-of-run knowledge flush runs **once per run**, not per
        iteration: ``run.events`` accumulates across iterations and the final
        flush summarises the entire overnight session. This keeps atom +
        linker cost flat regardless of iteration count.
        """
        run_started_at = time.monotonic()

        # Watch the run_store for out-of-process stop signals (e.g. `dojo stop`
        # in another terminal). When the sentinel appears we flip our intent
        # flag and ask the backend to interrupt — the SDK then has a chance to
        # emit ResultMessage so cost/turn data is preserved.
        stop_watcher = asyncio.create_task(self._watch_for_stop_signal(run.id))

        try:
            while True:
                run.iteration_count += 1
                await self._run_one_iteration(run)
                self._absorb_iteration_budget(run)

                if not self._should_continue(run, run_started_at):
                    # The iteration may have ended naturally (RUNNING) but
                    # budget is exhausted (or auto_continue is off) — finalise
                    # the run status here rather than leaving it RUNNING.
                    if run.status == RunStatus.RUNNING:
                        run.status = (
                            RunStatus.STOPPED if self._stop_requested else RunStatus.COMPLETED
                        )
                    break

                try:
                    await self._prepare_continuation(run)
                except Exception as e:
                    # If we can't set up the next iteration, treat the prior
                    # iteration's terminal status as final rather than
                    # silently exiting RUNNING. The agent has already produced
                    # useful work; surface the prep failure as a FAILED run.
                    logger.error("continuation_prepare_failed", run_id=run.id, error=str(e))
                    run.status = RunStatus.FAILED
                    run.error = f"continuation setup failed: {e}"
                    break

                run.events.append(
                    AgentEvent(
                        event_type="continuation_started",
                        data={
                            "iteration": run.iteration_count + 1,
                            "remaining_turns": self._remaining_turns(),
                            "remaining_budget_usd": self._remaining_budget(),
                            "elapsed_s": time.monotonic() - run_started_at,
                            "cumulative_turns": run.cumulative_turns,
                            "cumulative_cost_usd": run.cumulative_cost_usd,
                        },
                    )
                )
                # Re-enter RUNNING so _run_one_iteration's terminal-state
                # branches behave the same way they did on the first iteration.
                run.status = RunStatus.RUNNING
                await self.lab.run_store.save(run)

            run.completed_at = datetime.now(UTC)
            await self.lab.run_store.save(run)

        except Exception as e:
            # Catch-all so a bug in the loop driver still leaves the run in a
            # terminal state. Per-iteration exceptions are already handled
            # inside _run_one_iteration.
            if self._stop_requested:
                run.status = RunStatus.STOPPED
                if run.result is None:
                    self._populate_partial_result(run)
                logger.info("agent_run_stopped", run_id=run.id, error=str(e))
            else:
                run.status = RunStatus.FAILED
                run.error = str(e)
                logger.error("agent_run_failed", run_id=run.id, error=str(e))
            run.completed_at = datetime.now(UTC)
            await self.lab.run_store.save(run)

        finally:
            stop_watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await stop_watcher
            with contextlib.suppress(Exception):
                await self.lab.run_store.clear_stop_request(run.id)
            # Best-effort: extract durable findings now that the run is done.
            # Idempotent — the CLI graceful-stop path may already have flushed.
            # Runs **once per run** over the full multi-iteration transcript,
            # not per iteration, so atom/linker cost stays flat.
            with contextlib.suppress(Exception):
                await self.flush_knowledge(run)
            # Sentinel: SSE consumers wait for this before sending `done`,
            # so the flush events written above reach the frontend.
            run.events.append(AgentEvent(event_type="run_finalized", data={}))
            with contextlib.suppress(Exception):
                await self.lab.run_store.save(run)

    async def _run_one_iteration(self, run: AgentRun) -> None:
        """Consume one backend.execute() stream and update run state.

        Single-iteration semantics that used to live inline in ``execute()``.
        Sets ``run.status`` to a terminal value (COMPLETED / FAILED / STOPPED)
        if the iteration terminates the run; leaves it RUNNING if the stream
        ended naturally with no terminal signal (the outer loop then decides
        whether to continue).
        """
        _PERSIST_EVERY = 10
        event_count = 0

        try:
            async for event in self.backend.execute(run.prompt):
                run.events.append(event)
                event_count += 1

                # Handle the result event
                if event.event_type == "result":
                    result = _result_from_event(event)
                    run.result = result
                    if run.status == RunStatus.RUNNING:
                        # If a stop was requested, the SDK may emit a final
                        # result with is_error=True (the interrupt looks like
                        # an error to it). Treat that as STOPPED, not FAILED —
                        # mirrors the error-event branch below.
                        if self._stop_requested:
                            run.status = RunStatus.STOPPED
                        elif event.data.get("is_error"):
                            run.status = RunStatus.FAILED
                        # else: leave RUNNING so the outer loop can decide
                        # whether to continue. A clean result is the
                        # "naturally ended" signal — not yet COMPLETED.
                    await self.lab.run_store.save(run)
                    event_count = 0

                # Handle error events. A SIGINT to the foreground group kills
                # the backend's subprocess too, which surfaces here as an error
                # event — so if a stop was requested, treat it as STOPPED.
                elif event.event_type == "error" and run.status == RunStatus.RUNNING:
                    if self._stop_requested:
                        run.status = RunStatus.STOPPED
                    else:
                        run.status = RunStatus.FAILED
                        run.error = event.data.get("error", "Unknown error")
                    await self.lab.run_store.save(run)
                    event_count = 0

                # Periodic write-through (cross-process visibility)
                elif event_count >= _PERSIST_EVERY:
                    await self.lab.run_store.save(run)
                    event_count = 0

            if run.status == RunStatus.RUNNING and self._stop_requested:
                # Stream ended while a stop was pending — graceful stop path.
                run.status = RunStatus.STOPPED
            if run.status == RunStatus.STOPPED and run.result is None:
                self._populate_partial_result(run)

        except Exception as e:
            if self._stop_requested:
                run.status = RunStatus.STOPPED
                if run.result is None:
                    self._populate_partial_result(run)
                logger.info("agent_iteration_stopped", run_id=run.id, error=str(e))
            else:
                run.status = RunStatus.FAILED
                run.error = str(e)
                logger.error("agent_iteration_failed", run_id=run.id, error=str(e))
            await self.lab.run_store.save(run)

    def _absorb_iteration_budget(self, run: AgentRun) -> None:
        """Roll the latest iteration's result into the cumulative counters.

        Called after each iteration regardless of how it ended — even failed
        iterations may have spent turns / dollars worth recording.
        """
        if run.result is None:
            return
        run.cumulative_turns += int(run.result.num_turns or 0)
        if run.result.total_cost_usd is not None:
            run.cumulative_cost_usd += float(run.result.total_cost_usd)

    def _should_continue(self, run: AgentRun, run_started_at: float) -> bool:
        """Whether to run another iteration after the current one ended.

        Returns False when the prior iteration set a terminal status (FAILED /
        STOPPED), the user asked to stop, ``auto_continue`` is off, or any
        cumulative budget has been exhausted. Returns True only when the
        prior iteration ended on a clean ``result`` event with no error and
        budget remains.
        """
        if not self.auto_continue:
            return False
        if self._stop_requested:
            return False
        if run.status != RunStatus.RUNNING:
            # Terminal status already set by the iteration (FAILED, STOPPED,
            # COMPLETED if a future code path ever sets it directly).
            return False
        # Budget exhaustion checks are cumulative across iterations.
        remaining = self._remaining_turns()
        if remaining is not None and remaining < _MIN_TURNS_TO_CONTINUE:
            return False
        if self.max_budget_usd is not None and run.cumulative_cost_usd >= self.max_budget_usd:
            return False
        return not (
            self.max_wall_clock_s is not None
            and (time.monotonic() - run_started_at) >= self.max_wall_clock_s
        )

    def _remaining_turns(self) -> int | None:
        """Turns left before the cumulative cap is hit. None means unbounded."""
        if self._run is None:
            return None
        if self.max_turns is None:
            return None
        return max(0, self.max_turns - self._run.cumulative_turns)

    def _remaining_budget(self) -> float | None:
        """Dollars left before the cumulative cap is hit. None means unbounded."""
        if self._run is None or self.max_budget_usd is None:
            return None
        return max(0.0, self.max_budget_usd - self._run.cumulative_cost_usd)

    async def _prepare_continuation(self, run: AgentRun) -> None:
        """Reconfigure the backend for the next continuation iteration.

        Reloads the domain so the agent sees any knowledge atoms it wrote
        via ``write_knowledge`` mid-run, rebuilds the system prompt, and
        reconfigures the backend with the *remaining* budget so the SDK
        enforces the cumulative cap mid-iteration as well.
        """
        domain: Domain | None = None
        accumulated_knowledge: list[str] = []
        if self._domain_id:
            domain = await self.lab.domain_store.load(self._domain_id)
            if domain is not None:
                atoms = await self.lab.knowledge_linker.get_domain_knowledge(self._domain_id)
                for a in atoms[:20]:
                    accumulated_knowledge.append(f"- [{a.confidence:.1f}] {a.claim}")
                    if a.context:
                        accumulated_knowledge.append(f"    ↳ {a.context}")
                base_dir: Path | None = None
                if self.lab.settings is not None:
                    base_dir = Path(self.lab.settings.storage.base_dir)
                program = load_program(domain, base_dir=base_dir)
                if program:
                    domain.prompt = program

        system_prompt = build_system_prompt(
            run,
            domain=domain,
            accumulated_knowledge=accumulated_knowledge,
        )

        remaining_turns = self._remaining_turns()
        config = AgentRunConfig(
            system_prompt=system_prompt,
            # Fall back to the original max_turns when we're not capping
            # turns (None case is unreachable today but cheap to handle).
            max_turns=remaining_turns if remaining_turns is not None else self.max_turns,
            max_budget_usd=self._remaining_budget(),
            max_wall_clock_s=self.max_wall_clock_s,
            permission_mode=self.permission_mode,
            cwd=self._workspace_cwd or self.cwd,
            python_path=self._workspace_python_path,
            domain_id=run.domain_id,
        )
        run.config = config

        await self.backend.configure(self._tool_defs, config)

    async def flush_knowledge(self, run: AgentRun) -> int:
        """Extract durable findings from this run's transcript and write atoms.

        Idempotent: subsequent calls are no-ops. Called automatically at the
        end of ``execute()`` and explicitly by the CLI graceful-stop path so
        SIGINT users still get the cleanup.
        """
        if self._knowledge_flushed:
            return 0
        self._knowledge_flushed = True
        return await flush_run_knowledge(
            self.backend,
            self.lab,
            events=run.events,
            domain_id=run.domain_id,
            run_id=run.id,
        )

    async def _watch_for_stop_signal(self, run_id: str) -> None:
        """Poll the run store for a stop sentinel and trigger a graceful stop.

        Used to honour ``dojo stop`` from a separate terminal. Cancelled by
        ``execute()``'s finally block once the run terminates for any reason.
        """
        while True:
            await asyncio.sleep(_STOP_POLL_INTERVAL_S)
            try:
                requested = await self.lab.run_store.is_stop_requested(run_id)
            except Exception as e:
                logger.warning("stop_signal_poll_failed", run_id=run_id, error=str(e))
                continue
            if not requested:
                continue
            logger.info("stop_signal_received", run_id=run_id)
            self._stop_requested = True
            with contextlib.suppress(Exception):
                await self.backend.stop()
            return

    def mark_stop_requested(self) -> None:
        """Sync flag-flip so signal handlers can declare stop intent.

        Why: SIGINT propagates to the backend's subprocess too, surfacing as a
        backend error event before ``stop()`` can run. ``execute()`` checks this
        flag to distinguish a user-initiated stop from a real backend failure.
        Idempotent.
        """
        self._stop_requested = True

    async def stop(self) -> None:
        """Stop the running agent by interrupting the backend."""
        self._stop_requested = True
        await self.backend.stop()
        if self._run:
            self._run.status = RunStatus.STOPPED
            self._run.completed_at = datetime.now(UTC)
            if not self._run.result:
                self._populate_partial_result(self._run)

    @staticmethod
    def _populate_partial_result(run: AgentRun) -> None:
        """Fill run.result from observed events when no ResultMessage arrived.

        Used on stop paths where the backend died before emitting its summary —
        we lose cost data, but at least record turn count from tool calls.
        """
        tool_calls = sum(1 for e in run.events if e.event_type == "tool_call")
        run.result = AgentRunResult(session_id=None, num_turns=tool_calls)


def _result_from_event(event: AgentEvent) -> AgentRunResult:
    """Extract AgentRunResult from a result event's data dict."""
    return AgentRunResult(
        session_id=event.data.get("session_id"),
        total_cost_usd=event.data.get("cost_usd"),
        num_turns=event.data.get("turns", 0),
        duration_ms=event.data.get("duration_ms"),
        is_error=event.data.get("is_error", False),
    )
