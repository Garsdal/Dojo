"""Integration tests: full MLflow tracking flow through the LabEnvironment.

Phase 4: ``run_experiment`` calls ``tracking.log_metrics`` on success. This
test sets up a frozen domain with real load_data + evaluate modules, runs the
stub agent through the orchestrator, and verifies metrics land in MLflow.
"""

from __future__ import annotations

import pytest

from dojo.agents.backends.stub import StubAgentBackend
from dojo.agents.orchestrator import AgentOrchestrator
from dojo.api.deps import build_lab
from dojo.config.settings import MemorySettings, Settings, StorageSettings, TrackingSettings
from dojo.core.domain import Domain, DomainTool, ToolType, VerificationResult, Workspace
from dojo.core.task import TaskType
from dojo.runtime.task_service import TaskService

_LOAD_DATA = """\
def load_data():
    return [[1.0]], [[2.0]], [1.0], [2.0]
"""

_EVALUATE = """\
def evaluate(y_pred, *, X_train, X_test, y_train, y_test, artifacts_dir=None):
    diffs = [a - b for a, b in zip(y_pred, y_test)]
    return {
        "rmse": (sum(d * d for d in diffs) / len(diffs)) ** 0.5,
        "r2": 1.0,
        "mae": sum(abs(d) for d in diffs) / len(diffs),
    }
"""


@pytest.fixture
def lab(tmp_path):
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(
            backend="mlflow",
            enabled=True,
            mlflow_tracking_uri=f"file:{tmp_path / 'mlruns'}",
            mlflow_experiment_name="integration-test",
        ),
        memory=MemorySettings(backend="local"),
    )
    return build_lab(settings)


async def _make_frozen_domain(lab, tmp_path) -> Domain:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir(exist_ok=True)
    domain = Domain(
        name="track-test",
        workspace=Workspace(path=str(workspace_dir), ready=True),
    )
    await lab.domain_store.save(domain)

    svc = TaskService(lab)
    await svc.create(domain.id, task_type=TaskType.REGRESSION)
    domain = await lab.domain_store.load(domain.id)
    domain.task.tools = [
        DomainTool(
            name="load_data",
            type=ToolType.DATA_LOADER,
            module_filename="load_data.py",
            entrypoint="load_data",
            code=_LOAD_DATA,
            verification=VerificationResult(verified=True),
        ),
        DomainTool(
            name="evaluate",
            type=ToolType.EVALUATOR,
            module_filename="evaluate.py",
            entrypoint="evaluate",
            code=_EVALUATE,
            verification=VerificationResult(verified=True),
        ),
    ]
    await lab.domain_store.save(domain)
    await svc.freeze(domain.id)
    return await lab.domain_store.load(domain.id)


async def _run_stub(lab, domain: Domain, prompt: str) -> None:
    backend = StubAgentBackend()
    orchestrator = AgentOrchestrator(lab, backend, auto_continue=False)
    run = await orchestrator.start(prompt, domain_id=domain.id)
    await orchestrator.execute(run)


async def test_stub_agent_logs_to_mlflow(lab, tmp_path) -> None:
    """StubAgentBackend run should log regression metrics to MLflow."""
    domain = await _make_frozen_domain(lab, tmp_path)
    await _run_stub(lab, domain, "Test MLflow integration")

    experiments = await lab.experiment_store.list(domain_id=domain.id)
    assert len(experiments) == 1
    exp = experiments[0]
    assert exp.result is not None
    assert set(exp.result.metrics) == {"rmse", "r2", "mae"}

    tracked = await lab.tracking.get_metrics(exp.id)
    assert set(tracked) == {"rmse", "r2", "mae"}


async def test_multiple_experiments_tracked_separately(lab, tmp_path) -> None:
    """Each experiment gets its own MLflow run."""
    domain = await _make_frozen_domain(lab, tmp_path)
    await _run_stub(lab, domain, "Task 1")
    await _run_stub(lab, domain, "Task 2")

    experiments = await lab.experiment_store.list(domain_id=domain.id)
    assert len(experiments) == 2

    m1 = await lab.tracking.get_metrics(experiments[0].id)
    m2 = await lab.tracking.get_metrics(experiments[1].id)
    assert "rmse" in m1
    assert "rmse" in m2

    from dojo.tracking.mlflow_tracker import MlflowTracker

    assert isinstance(lab.tracking, MlflowTracker)
    assert experiments[0].id != experiments[1].id
