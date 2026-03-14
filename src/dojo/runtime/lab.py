"""Lab environment — dependency injection container for all backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dojo.interfaces.agent_run_store import AgentRunStore
from dojo.interfaces.artifact_store import ArtifactStore
from dojo.interfaces.compute import ComputeBackend
from dojo.interfaces.domain_store import DomainStore
from dojo.interfaces.experiment_store import ExperimentStore
from dojo.interfaces.knowledge_link_store import KnowledgeLinkStore
from dojo.interfaces.knowledge_linker import KnowledgeLinker
from dojo.interfaces.memory_store import MemoryStore
from dojo.interfaces.sandbox import Sandbox
from dojo.interfaces.tracking import TrackingConnector


@dataclass
class LabEnvironment:
    """Holds all injected backends — the DI container for Dojo.ml."""

    compute: ComputeBackend
    sandbox: Sandbox
    experiment_store: ExperimentStore
    artifact_store: ArtifactStore
    memory_store: MemoryStore
    tracking: TrackingConnector
    domain_store: DomainStore
    knowledge_link_store: KnowledgeLinkStore
    knowledge_linker: KnowledgeLinker
    agent_run_store: AgentRunStore
    settings: Any | None = field(default=None)
