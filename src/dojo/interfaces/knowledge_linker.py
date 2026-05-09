"""Knowledge linker port — ABC for knowledge-linking strategies."""

from abc import ABC, abstractmethod

from dojo.core.knowledge import KnowledgeAtom
from dojo.core.knowledge_link import KnowledgeLink


class LinkingResult:
    """Result of the knowledge linking process."""

    __slots__ = ("action", "atom_id", "confidence", "related_to")

    def __init__(
        self,
        *,
        atom_id: str,
        action: str = "created",
        confidence: float = 0.5,
        related_to: list[str] | None = None,
    ) -> None:
        self.atom_id = atom_id
        self.action = action
        self.confidence = confidence
        self.related_to = related_to


class KnowledgeLinker(ABC):
    """Port for knowledge-linking strategies.

    Every knowledge write flows through a linker. The linker stores a new
    immutable atom and creates relational links (CREATED_BY, RELATED_TO).
    Different implementations can use different similarity strategies, but
    must produce identical atom shapes — search semantics are uniform across
    linkers (text over claim/context/action).
    """

    @abstractmethod
    async def produce_knowledge(
        self,
        *,
        context: str,
        claim: str,
        action: str = "",
        confidence: float = 0.5,
        evidence_ids: list[str] | None = None,
        experiment_id: str = "",
        domain_id: str = "",
    ) -> LinkingResult:
        """Store a new atom and link it to related knowledge."""

    @abstractmethod
    async def find_similar(self, context: str, claim: str) -> list[KnowledgeAtom]:
        """Find atoms semantically similar to the given context/claim."""

    @abstractmethod
    async def get_domain_knowledge(self, domain_id: str) -> list[KnowledgeAtom]:
        """All atoms linked to a domain."""

    @abstractmethod
    async def get_atom_links(self, atom_id: str) -> list[KnowledgeLink]:
        """All links for an atom."""
