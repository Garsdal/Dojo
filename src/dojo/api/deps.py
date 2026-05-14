"""Dependency builder — constructs LabEnvironment from settings."""

from pathlib import Path

from dojo.agents.backend import AgentBackend
from dojo.agents.factory import create_agent_backend
from dojo.compute.local import LocalCompute
from dojo.config.settings import Settings
from dojo.interfaces.knowledge_link_store import KnowledgeLinkStore
from dojo.interfaces.knowledge_linker import KnowledgeLinker
from dojo.interfaces.memory_store import MemoryStore
from dojo.interfaces.sandbox import Sandbox
from dojo.interfaces.tracking import TrackingConnector
from dojo.runtime.keyword_linker import KeywordKnowledgeLinker
from dojo.runtime.lab import LabEnvironment
from dojo.runtime.llm_linker import LLMKnowledgeLinker
from dojo.sandbox.local import LocalSandbox
from dojo.storage.local import (
    LocalArtifactStore,
    LocalDomainStore,
    LocalExperimentStore,
    LocalKnowledgeLinkStore,
    LocalRunStore,
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


def _build_sandbox(settings: Settings) -> Sandbox:
    """Build sandbox from settings.

    `local` runs each script in a host subprocess; `docker` runs it inside an
    ephemeral container with `--memory`/`--cpus` limits so an OOM kills the
    container, not the host. Per CLAUDE.md "No silent fallbacks", unknown
    backends fail at `build_lab()` time.
    """
    backend = settings.sandbox.backend

    if backend == "local":
        logger.info("sandbox_backend", backend="local", timeout=settings.sandbox.timeout)
        return LocalSandbox(timeout=settings.sandbox.timeout)

    if backend == "docker":
        from dojo.sandbox.docker import DockerSandbox

        logger.info(
            "sandbox_backend",
            backend="docker",
            image=settings.sandbox.image,
            memory_limit=settings.sandbox.memory_limit,
            cpu_limit=settings.sandbox.cpu_limit,
            network=settings.sandbox.network,
            auto_rebuild_venv=settings.sandbox.auto_rebuild_venv,
        )
        return DockerSandbox(
            image=settings.sandbox.image,
            timeout=settings.sandbox.timeout,
            memory_limit=settings.sandbox.memory_limit,
            cpu_limit=settings.sandbox.cpu_limit,
            network=settings.sandbox.network,
            auto_rebuild_venv=settings.sandbox.auto_rebuild_venv,
        )

    raise ValueError(f"Unknown sandbox backend: {backend!r}")


def _build_memory(settings: Settings) -> MemoryStore:
    """Build memory store from settings."""
    backend = settings.memory.backend

    if backend == "local":
        from dojo.storage.local import LocalMemoryStore

        base = Path(settings.storage.base_dir) / "knowledge"
        logger.info("memory_backend", backend="local", path=str(base))
        return LocalMemoryStore(base_dir=base)

    raise ValueError(f"Unknown memory backend: {backend!r}")


def _build_linker(
    settings: Settings,
    memory_store: MemoryStore,
    link_store: KnowledgeLinkStore,
) -> KnowledgeLinker:
    """Build the knowledge linker. Atom shape + search semantics are
    identical across linkers; the choice only affects how RELATED_TO links
    are picked at write time (see CLAUDE.md "Knowledge linking")."""
    linker = settings.memory.linker

    if linker == "keyword":
        logger.info("knowledge_linker", linker="keyword")
        return KeywordKnowledgeLinker(memory_store, link_store)

    if linker == "llm":
        model = settings.memory.llm_linker_model or settings.agent.tool_generation_model
        backend = create_agent_backend(settings.agent.backend, model=model)
        # Surface the misconfiguration at lab-build time per the project's
        # "no silent fallbacks" rule: a backend that doesn't override
        # `complete()` will raise NotImplementedError on every linker write,
        # and we'd rather fail loud now than mid-run.
        if type(backend).complete is AgentBackend.complete:
            raise ValueError(
                f"memory.linker='llm' requires an AgentBackend that implements "
                f"complete(); the configured agent.backend={settings.agent.backend!r} "
                f"does not. Use memory.linker='keyword' or switch agent.backend."
            )
        logger.info(
            "knowledge_linker",
            linker="llm",
            agent_backend=settings.agent.backend,
            model=model,
        )
        return LLMKnowledgeLinker(memory_store, link_store, backend=backend)

    raise ValueError(f"Unknown memory.linker: {linker!r}")


def build_lab(settings: Settings) -> LabEnvironment:
    """Construct the full LabEnvironment from application settings."""
    base = Path(settings.storage.base_dir)

    memory_store = _build_memory(settings)
    knowledge_link_store = LocalKnowledgeLinkStore(base_dir=base / "knowledge_links")
    knowledge_linker = _build_linker(settings, memory_store, knowledge_link_store)

    return LabEnvironment(
        compute=LocalCompute(),
        sandbox=_build_sandbox(settings),
        experiment_store=LocalExperimentStore(base_dir=base / "experiments"),
        artifact_store=LocalArtifactStore(base_dir=base / "artifacts"),
        memory_store=memory_store,
        tracking=_build_tracking(settings),
        domain_store=LocalDomainStore(base_dir=base / "domains"),
        knowledge_link_store=knowledge_link_store,
        knowledge_linker=knowledge_linker,
        run_store=LocalRunStore(base_dir=base / "runs"),
        settings=settings,
    )
