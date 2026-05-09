"""Keyword-overlap knowledge linker — default implementation.

Picks RELATED_TO candidates via keyword overlap (≥40% of the smaller word
set, ≥3 overlapping words). Atoms are immutable; every write creates a
new atom and links it to similar prior atoms in the same domain.

The atom shape produced here is identical to ``LLMKnowledgeLinker``'s —
the linker only affects which RELATED_TO edges land on disk. Search over
atoms is text-only and uniform across linkers.
"""

from __future__ import annotations

from dojo.core.knowledge import KnowledgeAtom
from dojo.core.knowledge_link import KnowledgeLink, LinkType
from dojo.interfaces.knowledge_link_store import KnowledgeLinkStore
from dojo.interfaces.knowledge_linker import KnowledgeLinker, LinkingResult
from dojo.interfaces.memory_store import MemoryStore
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

# Minimum keyword overlap ratio to consider a match
_MATCH_THRESHOLD = 0.4
# Minimum number of overlapping words required
_MIN_OVERLAP_WORDS = 3


class KeywordKnowledgeLinker(KnowledgeLinker):
    """Knowledge linker using keyword-overlap heuristic."""

    def __init__(
        self,
        memory_store: MemoryStore,
        link_store: KnowledgeLinkStore,
    ) -> None:
        self._memory = memory_store
        self._links = link_store

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
        evidence = evidence_ids or []

        atom = KnowledgeAtom(
            domain_id=domain_id,
            source_experiment_id=experiment_id,
            context=context,
            claim=claim,
            action=action,
            confidence=confidence,
            evidence_ids=evidence,
        )
        await self._memory.add(atom)
        logger.info(
            "knowledge_atom_created",
            atom_id=atom.id,
            domain_id=domain_id,
            experiment_id=experiment_id,
            confidence=confidence,
        )

        similar = await self.find_similar(context, claim, exclude_id=atom.id)
        related_ids = await _write_links(
            self._links,
            atom=atom,
            domain_id=domain_id,
            experiment_id=experiment_id,
            related=similar,
        )

        return LinkingResult(
            atom_id=atom.id,
            action="created",
            confidence=confidence,
            related_to=related_ids or None,
        )

    async def find_similar(
        self, context: str, claim: str, *, exclude_id: str = ""
    ) -> list[KnowledgeAtom]:
        query = f"{context} {claim}"
        candidates = await self._memory.search(query, limit=5)
        return [c for c in candidates if c.id != exclude_id and is_keyword_match(context, claim, c)]

    async def get_domain_knowledge(self, domain_id: str) -> list[KnowledgeAtom]:
        return await self._memory.list_for_domain(domain_id)

    async def get_atom_links(self, atom_id: str) -> list[KnowledgeLink]:
        return await self._links.get_links_for_atom(atom_id)


def is_keyword_match(context: str, claim: str, candidate: KnowledgeAtom) -> bool:
    """Whether *candidate* shares enough keywords with the new finding."""
    new_words = set(f"{context} {claim}".lower().split())
    existing_words = set(f"{candidate.context} {candidate.claim}".lower().split())

    if not new_words or not existing_words:
        return False

    overlap = new_words & existing_words
    if len(overlap) < _MIN_OVERLAP_WORDS:
        return False
    smaller = min(len(new_words), len(existing_words))
    ratio = len(overlap) / smaller if smaller > 0 else 0.0
    return ratio >= _MATCH_THRESHOLD


async def _write_links(
    link_store: KnowledgeLinkStore,
    *,
    atom: KnowledgeAtom,
    domain_id: str,
    experiment_id: str,
    related: list[KnowledgeAtom],
) -> list[str]:
    """Write CREATED_BY + one RELATED_TO per *related* atom. Shared by linkers."""
    if experiment_id or domain_id:
        link = KnowledgeLink(
            atom_id=atom.id,
            experiment_id=experiment_id or "",
            domain_id=domain_id,
            link_type=LinkType.CREATED_BY,
        )
        await link_store.link(link)
        logger.info(
            "knowledge_link_created",
            atom_id=atom.id,
            link_type=LinkType.CREATED_BY.value,
            domain_id=domain_id,
            experiment_id=experiment_id,
        )

    related_ids: list[str] = []
    for existing in related:
        rel_link = KnowledgeLink(
            atom_id=atom.id,
            experiment_id=experiment_id or "",
            domain_id=domain_id,
            link_type=LinkType.RELATED_TO,
            related_atom_id=existing.id,
        )
        await link_store.link(rel_link)
        logger.info(
            "knowledge_link_created",
            atom_id=atom.id,
            link_type=LinkType.RELATED_TO.value,
            related_atom_id=existing.id,
            domain_id=domain_id,
            experiment_id=experiment_id,
        )
        related_ids.append(existing.id)
    return related_ids
