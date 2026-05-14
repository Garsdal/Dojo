"""Lab environment — dependency injection container for all backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dojo.interfaces.artifact_store import ArtifactStore
from dojo.interfaces.domain_store import DomainStore
from dojo.interfaces.experiment_store import ExperimentStore
from dojo.interfaces.knowledge_link_store import KnowledgeLinkStore
from dojo.interfaces.knowledge_linker import KnowledgeLinker
from dojo.interfaces.memory_store import MemoryStore
from dojo.interfaces.run_store import RunStore
from dojo.interfaces.sandbox import Sandbox
from dojo.interfaces.tracking import TrackingConnector


@dataclass
class LabEnvironment:
    """Holds all injected backends — the DI container for Dojo.ml."""

    sandbox: Sandbox
    experiment_store: ExperimentStore
    artifact_store: ArtifactStore
    memory_store: MemoryStore
    tracking: TrackingConnector
    domain_store: DomainStore
    knowledge_link_store: KnowledgeLinkStore
    knowledge_linker: KnowledgeLinker
    run_store: RunStore
    settings: Any | None = field(default=None)
