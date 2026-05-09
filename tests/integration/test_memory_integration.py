"""Integration tests: memory store wired through LabEnvironment via AgentOrchestrator."""

import pytest

from dojo.agents.backends.stub import StubAgentBackend
from dojo.agents.orchestrator import AgentOrchestrator
from dojo.api.deps import build_lab
from dojo.config.settings import MemorySettings, Settings, StorageSettings, TrackingSettings


@pytest.fixture
def lab(tmp_path):
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(backend="file", enabled=True),
        memory=MemorySettings(backend="local"),
    )
    return build_lab(settings)


async def _run_stub(lab, prompt: str) -> None:
    """Helper: run the stub backend through the orchestrator pipeline.

    The Phase 3 contract requires a frozen task with verified tools at run start.
    These tests aren't about the gate — they test memory wiring — so we bypass
    via `require_ready_task=False`.
    """
    backend = StubAgentBackend()
    orchestrator = AgentOrchestrator(lab, backend)
    run = await orchestrator.start(prompt, domain_id="test-domain", require_ready_task=False)
    await orchestrator.execute(run)


async def test_stub_agent_creates_knowledge(lab) -> None:
    """StubAgentBackend should create a knowledge atom in the memory store."""
    await _run_stub(lab, "Test memory integration")

    atoms = await lab.memory_store.list()
    assert len(atoms) >= 1
    assert any("Test memory integration" in a.context for a in atoms)


async def test_knowledge_searchable_after_creation(lab) -> None:
    """Knowledge atoms created by the agent should be searchable."""
    await _run_stub(lab, "classification on tabular data")

    results = await lab.memory_store.search("classification")
    assert len(results) >= 1


async def test_knowledge_persists_across_tasks(lab) -> None:
    """Atoms accumulate across runs — never merge.

    The keyword linker is immutable-append: every ``write_knowledge`` call
    creates a new atom, with ``RELATED_TO`` links connecting similar ones.
    Two runs that each produce a finding therefore yield two atoms, not a
    single revised one.
    """
    await _run_stub(lab, "classification problem")
    await _run_stub(lab, "regression problem")

    atoms = await lab.memory_store.list()
    assert len(atoms) == 2
