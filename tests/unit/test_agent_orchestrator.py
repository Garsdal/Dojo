"""Unit tests for AgentOrchestrator.start() progress callback (Task 8)."""

import pytest

from dojo.agents.factory import create_agent_backend
from dojo.agents.orchestrator import AgentOrchestrator
from dojo.core.domain import Domain, DomainTool, ToolType, VerificationResult
from dojo.core.task import TaskType
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.task_service import TaskService


def _verified(name: str) -> DomainTool:
    return DomainTool(
        name=name,
        description=name,
        type=ToolType.DATA_LOADER if name == "load_data" else ToolType.EVALUATOR,
        code="print('{}')",
        verification=VerificationResult(verified=True),
    )


async def _make_ready_domain(lab: LabEnvironment) -> Domain:
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


@pytest.mark.asyncio
async def test_start_invokes_progress_callback_in_order(lab: LabEnvironment):
    domain = await _make_ready_domain(lab)

    backend = create_agent_backend("stub")
    orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)

    labels: list[str] = []
    await orchestrator.start(
        prompt="go",
        domain_id=domain.id,
        progress=labels.append,
    )

    # Order matters: load -> readiness -> knowledge -> backend
    assert labels == [
        "loading domain context",
        "checking task readiness",
        "indexing prior knowledge",
        "configuring agent backend",
    ]


@pytest.mark.asyncio
async def test_start_no_progress_callback_works(lab: LabEnvironment):
    """Default behaviour (progress=None) is unchanged."""
    domain = await _make_ready_domain(lab)
    orchestrator = AgentOrchestrator(lab, create_agent_backend("stub"), auto_continue=False)
    run = await orchestrator.start(prompt="go", domain_id=domain.id)
    assert run.domain_id == domain.id
