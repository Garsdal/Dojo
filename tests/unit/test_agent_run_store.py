"""Tests for LocalAgentRunStore — CRUD round-trips and edge cases."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dojo.agents.types import (
    AgentEvent,
    AgentRun,
    AgentRunConfig,
    AgentRunResult,
    RunStatus,
    ToolHint,
)
from dojo.storage.local.agent_run import LocalAgentRunStore


@pytest.fixture
def store(tmp_dir: Path):
    return LocalAgentRunStore(base_dir=tmp_dir / "agent_runs")


def _make_run(**kwargs) -> AgentRun:
    """Helper to build an AgentRun with sensible defaults."""
    defaults = dict(
        domain_id="domain-1",
        prompt="Train a model",
        status=RunStatus.COMPLETED,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return AgentRun(**defaults)


# --- Basic CRUD ---


async def test_save_and_load(store: LocalAgentRunStore):
    run = _make_run()
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert loaded.id == run.id
    assert loaded.domain_id == "domain-1"
    assert loaded.prompt == "Train a model"
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.started_at is not None
    assert loaded.completed_at is not None


async def test_load_nonexistent(store: LocalAgentRunStore):
    assert await store.load("does-not-exist") is None


async def test_list_empty(store: LocalAgentRunStore):
    assert await store.list() == []


async def test_list_returns_all(store: LocalAgentRunStore):
    r1 = _make_run(prompt="run 1")
    r2 = _make_run(prompt="run 2")
    await store.save(r1)
    await store.save(r2)

    runs = await store.list()
    assert len(runs) == 2
    prompts = {r.prompt for r in runs}
    assert prompts == {"run 1", "run 2"}


async def test_delete(store: LocalAgentRunStore):
    run = _make_run()
    await store.save(run)
    assert await store.delete(run.id) is True
    assert await store.load(run.id) is None


async def test_delete_nonexistent(store: LocalAgentRunStore):
    assert await store.delete("nope") is False


# --- Overwrite (save twice) ---


async def test_save_overwrites(store: LocalAgentRunStore):
    run = _make_run(status=RunStatus.RUNNING)
    await store.save(run)

    run.status = RunStatus.COMPLETED
    run.result = AgentRunResult(num_turns=10, total_cost_usd=0.42)
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.result is not None
    assert loaded.result.num_turns == 10
    assert loaded.result.total_cost_usd == pytest.approx(0.42)


# --- Events round-trip ---


async def test_events_persisted(store: LocalAgentRunStore):
    run = _make_run()
    run.events = [
        AgentEvent(event_type="text", data={"text": "Hello"}),
        AgentEvent(event_type="tool_call", data={"tool": "search", "input": {"q": "test"}}),
        AgentEvent(event_type="tool_result", data={"tool_use_id": "abc", "content": "found it"}),
    ]
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert len(loaded.events) == 3
    assert loaded.events[0].event_type == "text"
    assert loaded.events[0].data["text"] == "Hello"
    assert loaded.events[1].event_type == "tool_call"
    assert loaded.events[1].data["tool"] == "search"
    assert loaded.events[2].event_type == "tool_result"


# --- Result round-trip ---


async def test_result_persisted(store: LocalAgentRunStore):
    run = _make_run()
    run.result = AgentRunResult(
        session_id="sess-1",
        total_cost_usd=1.23,
        num_turns=15,
        duration_ms=60000,
        is_error=False,
    )
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert loaded.result is not None
    assert loaded.result.session_id == "sess-1"
    assert loaded.result.total_cost_usd == pytest.approx(1.23)
    assert loaded.result.num_turns == 15
    assert loaded.result.duration_ms == 60000
    assert loaded.result.is_error is False


async def test_no_result_loads_as_none(store: LocalAgentRunStore):
    run = _make_run()
    run.result = None
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert loaded.result is None


# --- Config round-trip ---


async def test_config_persisted(store: LocalAgentRunStore):
    run = _make_run()
    run.config = AgentRunConfig(
        system_prompt="You are a researcher",
        max_turns=25,
        max_budget_usd=5.0,
        permission_mode="bypassPermissions",
        cwd="/tmp/work",
        python_path="/usr/bin/python3",
        domain_id="d-42",
    )
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert loaded.config.system_prompt == "You are a researcher"
    assert loaded.config.max_turns == 25
    assert loaded.config.max_budget_usd == pytest.approx(5.0)
    assert loaded.config.permission_mode == "bypassPermissions"
    assert loaded.config.cwd == "/tmp/work"
    assert loaded.config.python_path == "/usr/bin/python3"
    assert loaded.config.domain_id == "d-42"


# --- Tool hints round-trip ---


async def test_tool_hints_persisted(store: LocalAgentRunStore):
    run = _make_run()
    run.tool_hints = [
        ToolHint(name="load_csv", description="Load a CSV", source="file.py", code_template="..."),
    ]
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert len(loaded.tool_hints) == 1
    assert loaded.tool_hints[0].name == "load_csv"
    assert loaded.tool_hints[0].source == "file.py"


# --- All statuses round-trip ---


@pytest.mark.parametrize("status", list(RunStatus))
async def test_all_statuses_round_trip(store: LocalAgentRunStore, status: RunStatus):
    run = _make_run(status=status)
    await store.save(run)

    loaded = await store.load(run.id)
    assert loaded is not None
    assert loaded.status == status


# --- Corrupt file is skipped in list() ---


async def test_corrupt_file_skipped(store: LocalAgentRunStore):
    # Save a valid run
    run = _make_run()
    await store.save(run)

    # Write a corrupt file
    (store.base_dir / "bad.json").write_text("{invalid json")

    runs = await store.list()
    assert len(runs) == 1
    assert runs[0].id == run.id
