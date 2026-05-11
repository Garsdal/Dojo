"""Unit tests for AgentOrchestrator — uses StubAgentBackend, no SDK needed."""

import asyncio
import json

import pytest

from dojo.agents.backends.stub import StubAgentBackend
from dojo.agents.orchestrator import AgentOrchestrator
from dojo.agents.types import AgentEvent, AgentRunConfig, RunStatus, ToolHint
from dojo.core.domain import Domain, DomainTool, ToolType, VerificationResult
from dojo.core.task import TaskType
from dojo.runtime.task_service import TaskNotReadyError, TaskService


def _verified(name: str) -> DomainTool:
    return DomainTool(
        name=name,
        description=name,
        type=ToolType.DATA_LOADER if name == "load_data" else ToolType.EVALUATOR,
        code="print('{}')",
        verification=VerificationResult(verified=True),
    )


async def _make_ready_domain(lab) -> Domain:
    """Create a domain with a frozen task and verified required tools."""
    domain = Domain(name="ready")
    await lab.domain_store.save(domain)
    svc = TaskService(lab)
    await svc.create(domain.id, task_type=TaskType.REGRESSION)
    domain = await lab.domain_store.load(domain.id)
    domain.task.tools = [_verified("load_data"), _verified("evaluate")]
    await lab.domain_store.save(domain)
    await svc.freeze(domain.id)
    return await lab.domain_store.load(domain.id)


class TestAgentOrchestrator:
    """Tests for Agent Orchestrator."""

    async def test_start_creates_running_run(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start(
            "test prompt", domain_id="test-domain", require_ready_task=False
        )

        assert run.status == RunStatus.RUNNING
        assert run.prompt == "test prompt"
        assert run.started_at is not None
        assert run.domain_id == "test-domain"

    async def test_start_with_custom_domain_id(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("test", domain_id="custom-id", require_ready_task=False)

        assert run.domain_id == "custom-id"

    async def test_start_with_tool_hints(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        hints = [ToolHint(name="fetch_data", description="Load dataset", source="http://test")]
        run = await orchestrator.start(
            "test", domain_id="test-domain", require_ready_task=False, tool_hints=hints
        )

        assert len(run.tool_hints) == 1
        assert run.tool_hints[0].name == "fetch_data"
        # System prompt should contain the hint
        assert "fetch_data" in run.config.system_prompt

    async def test_execute_completes_successfully(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start(
            "test prompt", domain_id="test-domain", require_ready_task=False
        )
        await orchestrator.execute(run)

        assert run.status == RunStatus.COMPLETED
        assert run.completed_at is not None
        assert len(run.events) > 0

    async def test_execute_captures_result(self, lab):
        events = [
            AgentEvent(event_type="text", data={"text": "working"}),
            AgentEvent(
                event_type="result",
                data={
                    "session_id": "test-session",
                    "turns": 5,
                    "cost_usd": 0.25,
                    "duration_ms": 3000,
                    "is_error": False,
                },
            ),
        ]
        backend = StubAgentBackend(events=events)
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)
        await orchestrator.execute(run)

        assert run.result is not None
        assert run.result.session_id == "test-session"
        assert run.result.num_turns == 5
        assert run.result.total_cost_usd == pytest.approx(0.25)
        assert run.result.duration_ms == 3000

    async def test_execute_handles_error_event(self, lab):
        events = [
            AgentEvent(event_type="error", data={"error": "Something broke"}),
        ]
        backend = StubAgentBackend(events=events)
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)
        await orchestrator.execute(run)

        assert run.status == RunStatus.FAILED
        assert run.error == "Something broke"

    async def test_execute_handles_is_error_result(self, lab):
        events = [
            AgentEvent(
                event_type="result",
                data={"is_error": True, "turns": 1, "cost_usd": 0.01},
            ),
        ]
        backend = StubAgentBackend(events=events)
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)
        await orchestrator.execute(run)

        assert run.status == RunStatus.FAILED

    async def test_stop_sets_stopped_status(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)
        await orchestrator.stop()

        assert run.status == RunStatus.STOPPED
        assert run.completed_at is not None

    async def test_error_event_after_stop_request_marks_stopped(self, lab):
        """SIGINT kills the backend's subprocess too — the resulting error
        event must not flip an in-progress stop into FAILED."""
        events = [
            AgentEvent(event_type="tool_call", data={"tool": "run_experiment", "input": {}}),
            AgentEvent(event_type="error", data={"error": "Command failed with exit code -2"}),
        ]
        backend = StubAgentBackend(events=events)
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)
        orchestrator.mark_stop_requested()
        await orchestrator.execute(run)

        assert run.status == RunStatus.STOPPED
        assert run.error is None
        assert run.result is not None
        assert run.result.num_turns == 1  # one tool_call observed

    async def test_external_stop_signal_triggers_graceful_stop(self, lab):
        """A stop sentinel written to run_store mid-run should make the
        orchestrator interrupt the backend and finish in STOPPED."""
        import asyncio

        from dojo.agents.backend import AgentBackend

        class _SlowBackend(AgentBackend):
            def __init__(self) -> None:
                self.stopped = False

            async def configure(self, tool_defs, config):
                pass

            async def execute(self, prompt: str):
                # Yield a tool_call event then loop forever until interrupted.
                yield AgentEvent(event_type="tool_call", data={"tool": "x", "input": {}})
                while not self.stopped:
                    await asyncio.sleep(0.05)
                # Treat the user's stop as a graceful end-of-stream.

            async def stop(self) -> None:
                self.stopped = True

            @property
            def name(self) -> str:
                return "slow"

        backend = _SlowBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)
        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)

        async def _signal_after_a_moment():
            await asyncio.sleep(1.2)  # slightly above the 1s poll interval
            await lab.run_store.request_stop(run.id)

        await asyncio.gather(_signal_after_a_moment(), orchestrator.execute(run))

        assert run.status == RunStatus.STOPPED
        assert backend.stopped is True
        assert run.error is None
        # Sentinel must be cleaned up so future runs aren't poisoned.
        assert await lab.run_store.is_stop_requested(run.id) is False

    async def test_exception_after_stop_request_marks_stopped(self, lab):
        """If the backend raises (rather than yielding an error event) after a
        stop was requested, still treat as STOPPED."""

        class _RaisingBackend(StubAgentBackend):
            async def execute(self, prompt: str):  # type: ignore[override]
                yield AgentEvent(event_type="tool_call", data={"tool": "x", "input": {}})
                raise RuntimeError("Command failed with exit code -2")

        orchestrator = AgentOrchestrator(lab, _RaisingBackend())
        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)
        orchestrator.mark_stop_requested()
        await orchestrator.execute(run)

        assert run.status == RunStatus.STOPPED
        assert run.error is None
        assert run.result is not None
        assert run.result.num_turns == 1

    async def test_config_respects_params(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(
            lab,
            backend,
            max_turns=10,
            max_budget_usd=1.5,
            permission_mode="plan",
            cwd="/tmp/test",
        )

        run = await orchestrator.start("test", domain_id="test-domain", require_ready_task=False)

        assert run.config.max_turns == 10
        assert run.config.max_budget_usd == pytest.approx(1.5)
        assert run.config.permission_mode == "plan"
        assert run.config.cwd == "/tmp/test"

    async def test_config_includes_domain_id(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("test", domain_id="my-domain", require_ready_task=False)

        assert run.config.domain_id == "my-domain"

    async def test_full_pipeline_creates_experiment(self, lab, tmp_path):
        """Phase 4: with a frozen domain + workspace, the stub's run_experiment
        actually creates an experiment record on disk."""
        from dojo.core.domain import Workspace

        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()

        domain = await _make_ready_domain(lab)
        domain.workspace = Workspace(path=str(workspace_dir), ready=True)
        await lab.domain_store.save(domain)

        # Re-freeze with the workspace set so canonical files are copied to
        # `.dojo/domains/{id}/tools/` for the runner to import.
        svc = TaskService(lab)
        load_code = "def load_data():\n    return [[1.0]], [[2.0]], [1.0], [2.0]\n"
        eval_code = (
            "from load_data import load_data\n"
            "def evaluate(y_pred):\n"
            "    return {'rmse': 0.0, 'r2': 1.0, 'mae': 0.0}\n"
        )
        domain = await lab.domain_store.load(domain.id)
        domain.task.frozen = False
        domain.task.tools[0].code = load_code
        domain.task.tools[0].module_filename = "load_data.py"
        domain.task.tools[0].entrypoint = "load_data"
        domain.task.tools[1].code = eval_code
        domain.task.tools[1].module_filename = "evaluate.py"
        domain.task.tools[1].entrypoint = "evaluate"
        await lab.domain_store.save(domain)
        await svc.freeze(domain.id)

        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("pipeline test", domain_id=domain.id)
        await orchestrator.execute(run)

        assert run.status == RunStatus.COMPLETED
        experiments = await lab.experiment_store.list(domain_id=domain.id)
        assert len(experiments) >= 1

    async def test_full_pipeline_event_types(self, lab):
        """The default stub flow should produce the expected event types."""
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start(
            "event types test", domain_id="test-domain", require_ready_task=False
        )
        await orchestrator.execute(run)

        event_types = [e.event_type for e in run.events]
        assert event_types[0] == "text"
        assert "tool_call" in event_types
        assert "tool_result" in event_types
        assert "result" in event_types
        # After the run completes, the knowledge flush appends its own events,
        # then the run_finalized sentinel is appended last.
        assert "knowledge_flush_completed" in event_types
        assert event_types[-1] == "run_finalized"


class TestOrchestratorTaskGate:
    """The Phase 3 contract: start() refuses to run unless the task is ready."""

    async def test_start_rejects_unknown_domain(self, lab):
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)
        with pytest.raises(TaskNotReadyError, match="not found"):
            await orchestrator.start("p", domain_id="ghost")

    async def test_start_rejects_domain_without_task(self, lab):
        domain = Domain(name="no-task")
        await lab.domain_store.save(domain)
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)
        with pytest.raises(TaskNotReadyError, match="no task"):
            await orchestrator.start("p", domain_id=domain.id)

    async def test_start_rejects_unfrozen_task(self, lab):
        domain = Domain(name="unfrozen")
        await lab.domain_store.save(domain)
        await TaskService(lab).create(domain.id)
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)
        with pytest.raises(TaskNotReadyError, match="not frozen"):
            await orchestrator.start("p", domain_id=domain.id)

    async def test_start_rejects_unverified_tools(self, lab):
        domain = Domain(name="unverified")
        await lab.domain_store.save(domain)
        await TaskService(lab).create(domain.id)
        # Force-freeze without verification (simulates --unsafe-skip-verify
        # path) — assert_ready should still flag the missing verification.
        await TaskService(lab).freeze(domain.id, skip_verification=True)
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)
        with pytest.raises(TaskNotReadyError, match="unverified"):
            await orchestrator.start("p", domain_id=domain.id)

    async def test_start_passes_when_task_is_ready(self, lab):
        domain = await _make_ready_domain(lab)
        backend = StubAgentBackend()
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)
        run = await orchestrator.start("p", domain_id=domain.id)
        assert run.status == RunStatus.RUNNING


class _CompletingStubBackend(StubAgentBackend):
    """Stub that supports backend.complete() — required to test the flush hook.

    StubAgentBackend inherits the default ``AgentBackend.complete`` which raises
    NotImplementedError, so the orchestrator silently skips its flush hook for
    plain stubs. This subclass returns a scripted JSON payload so the orchestrator
    actually walks the produce_knowledge path.
    """

    def __init__(
        self,
        events=None,
        atoms: list[dict] | None = None,
        wrap_in_fences: bool = False,
        raise_on_complete: Exception | None = None,
    ) -> None:
        super().__init__(events=events)
        self._atoms = atoms if atoms is not None else []
        self._wrap_in_fences = wrap_in_fences
        self._raise_on_complete = raise_on_complete
        self.complete_calls = 0

    async def complete(self, prompt: str) -> str:
        self.complete_calls += 1
        if self._raise_on_complete is not None:
            raise self._raise_on_complete
        body = json.dumps(self._atoms)
        if self._wrap_in_fences:
            return f"```json\n{body}\n```"
        return body


class TestEndOfRunKnowledgeFlush:
    """The orchestrator should flush durable findings after every run, regardless
    of terminal status. This is the safety net for agents that under-write
    in-loop. See agents/summarizer.py for the extraction logic."""

    @staticmethod
    def _events_with_text(
        text: str = "tried xgboost, beat baseline by 12% MAE",
    ) -> list[AgentEvent]:
        return [
            AgentEvent(event_type="text", data={"text": text}),
            AgentEvent(
                event_type="result",
                data={"is_error": False, "turns": 1, "cost_usd": 0.01},
            ),
        ]

    async def test_flush_writes_atoms_via_linker(self, lab):
        atoms = [
            {"claim": "xgboost beats baseline by 12%", "context": "early runs", "confidence": 0.8},
            {"claim": "lightgbm not installed", "confidence": 0.95},
        ]
        backend = _CompletingStubBackend(events=self._events_with_text(), atoms=atoms)
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d1", require_ready_task=False)
        await orchestrator.execute(run)

        assert backend.complete_calls == 1
        stored = await lab.knowledge_linker.get_domain_knowledge("d1")
        assert {a.claim for a in stored} == {a["claim"] for a in atoms}

    async def test_flush_handles_markdown_fences(self, lab):
        atoms = [{"claim": "fenced finding", "confidence": 0.6}]
        backend = _CompletingStubBackend(
            events=self._events_with_text(),
            atoms=atoms,
            wrap_in_fences=True,
        )
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d2", require_ready_task=False)
        await orchestrator.execute(run)

        stored = await lab.knowledge_linker.get_domain_knowledge("d2")
        assert [a.claim for a in stored] == ["fenced finding"]

    async def test_flush_skips_for_unsupported_backend(self, lab):
        """Plain StubAgentBackend's complete() raises NotImplementedError;
        the flush should swallow it and write nothing."""
        backend = StubAgentBackend(events=self._events_with_text())
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d3", require_ready_task=False)
        await orchestrator.execute(run)

        assert run.status == RunStatus.COMPLETED
        assert await lab.knowledge_linker.get_domain_knowledge("d3") == []

    async def test_flush_runs_for_failed_status(self, lab):
        events = [
            AgentEvent(event_type="text", data={"text": "tried xgboost; OOM at 10M rows"}),
            AgentEvent(event_type="error", data={"error": "OOMKilled"}),
        ]
        atoms = [{"claim": "xgboost OOMs at 10M rows on this box", "confidence": 0.9}]
        backend = _CompletingStubBackend(events=events, atoms=atoms)
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d4", require_ready_task=False)
        await orchestrator.execute(run)

        assert run.status == RunStatus.FAILED
        stored = await lab.knowledge_linker.get_domain_knowledge("d4")
        assert [a.claim for a in stored] == ["xgboost OOMs at 10M rows on this box"]

    async def test_flush_is_idempotent(self, lab):
        """Calling flush_knowledge again after execute() must not double-write."""
        atoms = [{"claim": "only-once", "confidence": 0.7}]
        backend = _CompletingStubBackend(events=self._events_with_text(), atoms=atoms)
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d5", require_ready_task=False)
        await orchestrator.execute(run)
        # The CLI graceful-stop path calls this explicitly; it must be a no-op
        # here because execute()'s finally-block already flushed.
        written = await orchestrator.flush_knowledge(run)

        assert written == 0
        assert backend.complete_calls == 1
        stored = await lab.knowledge_linker.get_domain_knowledge("d5")
        assert len(stored) == 1

    async def test_flush_skips_when_no_transcript(self, lab):
        """If only non-transcript events fired (e.g. just a result), there's
        nothing to summarize and we shouldn't burn an LLM call on it."""
        result_only = [
            AgentEvent(
                event_type="result",
                data={"is_error": False, "turns": 0, "cost_usd": 0.0},
            ),
        ]
        backend = _CompletingStubBackend(events=result_only, atoms=[{"claim": "x"}])
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d6", require_ready_task=False)
        await orchestrator.execute(run)

        assert backend.complete_calls == 0
        assert await lab.knowledge_linker.get_domain_knowledge("d6") == []

    async def test_flush_swallows_complete_failures(self, lab):
        """If backend.complete() raises (network blip, parse error, etc.) the
        run must still complete cleanly — flushing is best-effort."""
        backend = _CompletingStubBackend(
            events=self._events_with_text(),
            raise_on_complete=RuntimeError("network down"),
        )
        orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d7", require_ready_task=False)
        await orchestrator.execute(run)

        assert run.status == RunStatus.COMPLETED
        assert await lab.knowledge_linker.get_domain_knowledge("d7") == []


async def test_execute_emits_run_finalized_as_last_event(lab):
    """run.events ends with a run_finalized sentinel after flush completes."""
    backend = StubAgentBackend()
    orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

    run = await orchestrator.start("test", domain_id="d", require_ready_task=False)
    await orchestrator.execute(run)

    assert run.events, "expected at least one event"
    assert run.events[-1].event_type == "run_finalized"


class _ScriptedIterationsBackend(StubAgentBackend):
    """Stub whose execute() yields a different scripted batch per call.

    Safety: once the scripted list is exhausted the backend yields a halt
    (is_error result) so a test that miscomputes its termination condition
    fails fast instead of looping forever.
    """

    def __init__(self, iterations: list[list[AgentEvent]]) -> None:
        super().__init__()
        self._iterations = iterations
        self.execute_calls = 0
        self.configure_calls = 0
        self.last_config: AgentRunConfig | None = None

    async def configure(self, tool_defs, config):  # type: ignore[override]
        self.configure_calls += 1
        self.last_config = config
        await super().configure(tool_defs, config)

    async def execute(self, prompt: str):  # type: ignore[override]
        idx = self.execute_calls
        self.execute_calls += 1
        if idx >= len(self._iterations):
            yield AgentEvent(
                event_type="result",
                data={"is_error": True, "turns": 0, "cost_usd": 0.0},
            )
            return
        for event in self._iterations[idx]:
            yield event


def _clean_result(turns: int = 5, cost: float = 0.1) -> AgentEvent:
    return AgentEvent(
        event_type="result",
        data={
            "session_id": "s",
            "turns": turns,
            "cost_usd": cost,
            "duration_ms": 100,
            "is_error": False,
        },
    )


def _text(t: str = "did things") -> AgentEvent:
    return AgentEvent(event_type="text", data={"text": t})


def _halt() -> AgentEvent:
    """Result event that halts the continuation loop (is_error=True)."""
    return AgentEvent(
        event_type="result",
        data={"is_error": True, "turns": 1, "cost_usd": 0.0},
    )


class TestContinuationLoop:
    """The orchestrator drives `backend.execute()` repeatedly until a real
    budget (turns / dollars / wall-clock) is hit or stop is requested. See
    issue #6: prior behaviour terminated as soon as the agent emitted a
    "done" message.

    Stop-signal mid-loop behaviour is covered by
    ``test_external_stop_signal_triggers_graceful_stop`` above — the
    continuation loop respects the same ``_stop_requested`` flag, so
    duplicating the 1s-poll wait here would only add latency to the suite.
    """

    async def test_continues_when_budget_remains_and_records_event(self, lab):
        """Clean iteration → continues → emits continuation_started with remaining caps.

        Bundles three checks (continues, event emitted, remaining budgets correct)
        in one scripted run so the loop only fires twice — keeps the test fast.
        """
        backend = _ScriptedIterationsBackend(
            iterations=[
                [_text("iter 1"), _clean_result(turns=5, cost=0.1)],
                [_halt()],  # halt iter 2 deterministically
            ],
        )
        orchestrator = AgentOrchestrator(lab, backend, max_turns=100, max_budget_usd=1.0)

        run = await orchestrator.start("p", domain_id="d", require_ready_task=False)
        await orchestrator.execute(run)

        assert backend.execute_calls == 2
        assert run.iteration_count == 2
        assert run.cumulative_turns == 6  # 5 + 1
        cont_events = [e for e in run.events if e.event_type == "continuation_started"]
        assert len(cont_events) == 1
        assert cont_events[0].data["iteration"] == 2
        assert cont_events[0].data["remaining_turns"] == 95
        assert cont_events[0].data["remaining_budget_usd"] == pytest.approx(0.9)
        # The reconfigure for iter 2 saw the remaining (not full) caps.
        assert backend.last_config is not None
        assert backend.last_config.max_turns == 95
        assert backend.last_config.max_budget_usd == pytest.approx(0.9)

    @pytest.mark.parametrize(
        "axis,kwargs,iter_event",
        [
            ("turns", {"max_turns": 10}, _clean_result(turns=10, cost=0.1)),
            (
                "budget",
                {"max_turns": 1000, "max_budget_usd": 0.5},
                _clean_result(turns=5, cost=0.5),
            ),
            (
                "wall_clock",
                {"max_turns": 1000, "max_wall_clock_s": 0.0},
                _clean_result(turns=5, cost=0.1),
            ),
        ],
    )
    async def test_terminates_on_each_budget_axis(self, lab, axis, kwargs, iter_event):
        """Each cumulative cap (turns / dollars / wall-clock) halts the loop alone."""
        backend = _ScriptedIterationsBackend(
            iterations=[[_text(f"iter for {axis}"), iter_event]],
        )
        orchestrator = AgentOrchestrator(lab, backend, **kwargs)

        run = await orchestrator.start("p", domain_id="d", require_ready_task=False)
        await orchestrator.execute(run)

        assert backend.execute_calls == 1
        assert run.status == RunStatus.COMPLETED

    async def test_error_event_halts_loop(self, lab):
        """An error event in iter N halts the loop — no iter N+1 fires."""
        backend = _ScriptedIterationsBackend(
            iterations=[
                [AgentEvent(event_type="error", data={"error": "boom"})],
                [_clean_result(turns=5, cost=0.05)],  # would loop forever if reached
            ],
        )
        orchestrator = AgentOrchestrator(lab, backend, max_turns=1000)

        run = await orchestrator.start("p", domain_id="d", require_ready_task=False)
        await orchestrator.execute(run)

        assert backend.execute_calls == 1
        assert run.status == RunStatus.FAILED
        assert run.error == "boom"

    async def test_knowledge_flushed_exactly_once_across_iterations(self, lab):
        """End-of-run flush runs **once** across N iterations, not per iteration.

        The scalability fix from issue #6: each flush extracts up to 7 atoms
        and writes N link rows, so per-iteration flushing would multiply
        knowledge growth by iteration count.
        """

        class _MultiIterCompletingBackend(_CompletingStubBackend):
            def __init__(self, iterations):
                super().__init__(atoms=[{"claim": "session lesson", "confidence": 0.8}])
                self._iterations = iterations
                self.execute_calls = 0

            async def execute(self, prompt: str):  # type: ignore[override]
                idx = min(self.execute_calls, len(self._iterations) - 1)
                self.execute_calls += 1
                for event in self._iterations[idx]:
                    await asyncio.sleep(0)
                    yield event

        backend = _MultiIterCompletingBackend(
            iterations=[
                [_text("iter 1"), _clean_result(turns=5, cost=0.1)],
                [_text("iter 2"), _clean_result(turns=5, cost=0.1)],
                [_halt()],
            ],
        )
        orchestrator = AgentOrchestrator(lab, backend, max_turns=1000)

        run = await orchestrator.start("p", domain_id="d-flush", require_ready_task=False)
        await orchestrator.execute(run)

        assert backend.execute_calls == 3
        assert backend.complete_calls == 1  # one flush at end-of-run
        stored = await lab.knowledge_linker.get_domain_knowledge("d-flush")
        assert len(stored) == 1

    async def test_auto_continue_false_runs_once(self, lab):
        """Kill switch: legacy single-iteration behaviour even when budget remains."""
        backend = _ScriptedIterationsBackend(
            iterations=[[_clean_result(turns=5, cost=0.1)], [_clean_result(turns=5, cost=0.1)]],
        )
        orchestrator = AgentOrchestrator(lab, backend, max_turns=1000, auto_continue=False)

        run = await orchestrator.start("p", domain_id="d", require_ready_task=False)
        await orchestrator.execute(run)

        assert backend.execute_calls == 1
        assert run.status == RunStatus.COMPLETED
