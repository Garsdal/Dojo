"""Memory store interface for knowledge atoms."""

from abc import ABC, abstractmethod

from dojo.core.knowledge import KnowledgeAtom


class MemoryStore(ABC):
    """Abstract base class for knowledge atom persistence and search.

    Implementations must produce identical atom shapes regardless of how
    they're persisted. Search semantics are uniform across implementations:
    text overlap on ``claim`` / ``context`` / ``action``. The optional
    ``domain_id`` filter on ``search`` is the dominant scoping query.
    """

    @abstractmethod
    async def add(self, atom: KnowledgeAtom) -> str:
        """Add a knowledge atom. Returns the atom ID."""
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domain_id: str | None = None,
    ) -> list[KnowledgeAtom]:
        """Search for relevant atoms by keyword overlap on claim/context/action.

        When ``domain_id`` is given, results are scoped to that domain.
        """
        ...

    @abstractmethod
    async def list(self) -> list[KnowledgeAtom]:
        """List all knowledge atoms."""
        ...

    @abstractmethod
    async def list_for_domain(self, domain_id: str) -> list[KnowledgeAtom]:
        """All atoms scoped to a single domain."""
        ...

    @abstractmethod
    async def delete(self, atom_id: str) -> bool:
        """Delete an atom. Returns True if deleted, False if not found."""
        ...

    async def get(self, atom_id: str) -> KnowledgeAtom | None:
        """Get a single atom by ID. Default walks ``list()``; override for speed."""
        for atom in await self.list():
            if atom.id == atom_id:
                return atom
        return None

    async def update(self, atom: KnowledgeAtom) -> str:
        """Update an existing atom. Default deletes + re-adds; override for speed."""
        await self.delete(atom.id)
        return await self.add(atom)
