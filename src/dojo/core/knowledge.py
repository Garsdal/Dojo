"""Knowledge atom domain model."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from dojo.utils.ids import generate_id


@dataclass
class KnowledgeAtom:
    """A single unit of knowledge extracted from experiments.

    Atoms are immutable once written. ``domain_id`` and
    ``source_experiment_id`` are first-class so each on-disk atom is
    self-describing and the abstract data model maps cleanly to a single row
    in any future remote store (e.g. Postgres + jsonb for ``evidence_ids``).
    """

    id: str = field(default_factory=generate_id)
    domain_id: str = ""
    source_experiment_id: str = ""
    context: str = ""
    claim: str = ""
    action: str = ""
    confidence: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
