"""Agent orchestrator — manages an agent run lifecycle, SDK-agnostic."""

from __future__ import annotations

import asyncio
import contextlib
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
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.program_loader import load_program
from dojo.runtime.task_service import TaskNotReadyError, TaskService
from dojo.tools.server import collect_all_tools
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

# How often the orchestrator polls run_store for an out-of-process stop signal.
# 1s feels responsive enough for `dojo stop` while keeping disk noise minimal.
_STOP_POLL_INTERVAL_S = 1.0


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
        permission_mode: str = "acceptEdits",
        cwd: str | None = None,
    ) -> None:
        self.lab = lab
        self.backend = backend
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.permission_mode = permission_mode
        self.cwd = cwd
        self._run: AgentRun | None = None
        self._stop_requested = False
        self._knowledge_flushed = False

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
                    f"Domain {domain_id!r} not found. Create one with `dojo init`."
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

        # Collect tool definitions (framework-agnostic)
        tool_defs = collect_all_tools(self.lab, domain=domain)

        # Configure the backend with tools and config
        _emit("configuring agent backend")
        await self.backend.configure(tool_defs, config)

        return run

    async def execute(self, run: AgentRun) -> None:
        """Execute the agent run (blocking). Call in a background task.

        Consumes the event stream from the backend and appends events to
        run.events. Writes through to run_store every _PERSIST_EVERY events
        and on every status change so other processes can observe progress.
        """
        _PERSIST_EVERY = 10
        _event_count = 0

        # Watch the run_store for out-of-process stop signals (e.g. `dojo stop`
        # in another terminal). When the sentinel appears we flip our intent
        # flag and ask the backend to interrupt — the SDK then has a chance to
        # emit ResultMessage so cost/turn data is preserved.
        stop_watcher = asyncio.create_task(self._watch_for_stop_signal(run.id))

        try:
            async for event in self.backend.execute(run.prompt):
                run.events.append(event)
                _event_count += 1

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
                        else:
                            run.status = (
                                RunStatus.FAILED
                                if event.data.get("is_error")
                                else RunStatus.COMPLETED
                            )
                    await self.lab.run_store.save(run)
                    _event_count = 0

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
                    _event_count = 0

                # Periodic write-through (cross-process visibility)
                elif _event_count >= _PERSIST_EVERY:
                    await self.lab.run_store.save(run)
                    _event_count = 0

            if run.status == RunStatus.RUNNING:
                run.status = RunStatus.STOPPED if self._stop_requested else RunStatus.COMPLETED
            if run.status == RunStatus.STOPPED and run.result is None:
                self._populate_partial_result(run)
            run.completed_at = datetime.now(UTC)
            await self.lab.run_store.save(run)

        except Exception as e:
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
            with contextlib.suppress(Exception):
                await self.flush_knowledge(run)
            # Sentinel: SSE consumers wait for this before sending `done`,
            # so the flush events written above reach the frontend.
            run.events.append(AgentEvent(event_type="run_finalized", data={}))
            with contextlib.suppress(Exception):
                await self.lab.run_store.save(run)

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
