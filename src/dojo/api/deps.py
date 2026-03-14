"""Dependency builder — constructs LabEnvironment from settings."""

from pathlib import Path

from dojo.compute.local import LocalCompute
from dojo.config.settings import Settings
from dojo.interfaces.memory_store import MemoryStore
from dojo.interfaces.tracking import TrackingConnector
from dojo.runtime.keyword_linker import KeywordKnowledgeLinker
from dojo.runtime.lab import LabEnvironment
from dojo.sandbox.local import LocalSandbox
from dojo.storage.local import (
    LocalAgentRunStore,
    LocalArtifactStore,
    LocalDomainStore,
    LocalExperimentStore,
    LocalKnowledgeLinkStore,
)
from dojo.utils.logging import get_logger

logger = get_logger(__name__)


def _build_tracking(settings: Settings) -> TrackingConnector:
    """Build tracking connector from settings."""
    if not settings.tracking.enabled:
        from dojo.tracking.noop_tracker import NoopTracker

        logger.info("tracking_disabled")
        return NoopTracker()

    backend = settings.tracking.backend

    if backend == "mlflow":
        try:
            from dojo.tracking.mlflow_tracker import MlflowTracker
        except ImportError as e:
            raise ImportError(
                "MLflow is required for tracking.backend='mlflow'. "
                "Install it with: pip install dojo[mlflow]"
            ) from e
        logger.info("tracking_backend", backend="mlflow", uri=settings.tracking.mlflow_tracking_uri)
        return MlflowTracker(
            tracking_uri=settings.tracking.mlflow_tracking_uri,
            experiment_name=settings.tracking.mlflow_experiment_name,
            artifact_location=settings.tracking.mlflow_artifact_location,
        )

    if backend == "file":
        from dojo.tracking.file_tracker import FileTracker

        base = Path(settings.storage.base_dir) / "tracking"
        logger.info("tracking_backend", backend="file", path=str(base))
        return FileTracker(base_dir=base)

    raise ValueError(f"Unknown tracking backend: {backend!r}")


def _build_memory(settings: Settings) -> MemoryStore:
    """Build memory store from settings."""
    backend = settings.memory.backend

    if backend == "local":
        from dojo.storage.local import LocalMemoryStore

        base = Path(settings.storage.base_dir) / "memory"
        logger.info("memory_backend", backend="local", path=str(base))
        return LocalMemoryStore(base_dir=base)

    raise ValueError(f"Unknown memory backend: {backend!r}")


def build_lab(settings: Settings) -> LabEnvironment:
    """Construct the full LabEnvironment from application settings.

    Args:
        settings: Application settings.

    Returns:
        A fully wired LabEnvironment.
    """
    base = Path(settings.storage.base_dir)

    memory_store = _build_memory(settings)
    knowledge_link_store = LocalKnowledgeLinkStore(base_dir=base / "knowledge_links")

    return LabEnvironment(
        compute=LocalCompute(),
        sandbox=LocalSandbox(timeout=settings.sandbox.timeout),
        experiment_store=LocalExperimentStore(base_dir=base / "experiments"),
        artifact_store=LocalArtifactStore(base_dir=base / "artifacts"),
        memory_store=memory_store,
        tracking=_build_tracking(settings),
        domain_store=LocalDomainStore(base_dir=base / "domains"),
        knowledge_link_store=knowledge_link_store,
        knowledge_linker=KeywordKnowledgeLinker(memory_store, knowledge_link_store),
        agent_run_store=LocalAgentRunStore(base_dir=base / "agent_runs"),
        settings=settings,
    )
