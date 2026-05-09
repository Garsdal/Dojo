"""LLM-driven knowledge linker — alternative ``KnowledgeLinker`` backend.

Same atom shape as ``KeywordKnowledgeLinker``; the only difference is how
``RELATED_TO`` candidates are picked. One ``AgentBackend.complete()`` call
per write asks an LLM which prior atoms in the same domain are
semantically related to the new one. Falls back to the keyword overlap
heuristic on any LLM error so writes never fail.

Search semantics are unchanged — text overlap on
``claim`` / ``context`` / ``action`` regardless of which linker created
the atoms (see CLAUDE.md "Knowledge linking" + MASTER_PLAN.md §3.5).
"""

from __future__ import annotations

import json

from dojo.agents.backend import AgentBackend
from dojo.core.knowledge import KnowledgeAtom
from dojo.core.knowledge_link import KnowledgeLink
from dojo.interfaces.knowledge_link_store import KnowledgeLinkStore
from dojo.interfaces.knowledge_linker import KnowledgeLinker, LinkingResult
from dojo.interfaces.memory_store import MemoryStore
from dojo.runtime.keyword_linker import _write_links, is_keyword_match
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

# Cap candidates shown to the LLM. Beyond ~30 the prompt grows fast and
# adds little — recent atoms in the same domain dominate relevance.
_MAX_CANDIDATES = 30
# Per-claim character cap when rendering candidates into the prompt.
_CANDIDATE_CLAIM_CHARS = 240


class LLMKnowledgeLinker(KnowledgeLinker):
    """Knowledge linker that uses an LLM to pick RELATED_TO candidates."""

    def __init__(
        self,
        memory_store: MemoryStore,
        link_store: KnowledgeLinkStore,
        backend: AgentBackend,
    ) -> None:
        self._memory = memory_store
        self._links = link_store
        self._backend = backend

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
        atom = KnowledgeAtom(
            domain_id=domain_id,
            source_experiment_id=experiment_id,
            context=context,
            claim=claim,
            action=action,
            confidence=confidence,
            evidence_ids=list(evidence_ids or []),
        )
        await self._memory.add(atom)
        logger.info(
            "knowledge_atom_created",
            atom_id=atom.id,
            domain_id=domain_id,
            experiment_id=experiment_id,
            confidence=confidence,
            linker="llm",
        )

        candidates = await self._candidates(atom)
        related = await self._pick_related(atom, candidates)

        related_ids = await _write_links(
            self._links,
            atom=atom,
            domain_id=domain_id,
            experiment_id=experiment_id,
            related=related,
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
        # Used by callers outside the write path (none today). Reuse the
        # keyword path here — find_similar isn't on the LLM-call hot path.
        query = f"{context} {claim}"
        candidates = await self._memory.search(query, limit=5)
        return [c for c in candidates if c.id != exclude_id and is_keyword_match(context, claim, c)]

    async def get_domain_knowledge(self, domain_id: str) -> list[KnowledgeAtom]:
        return await self._memory.list_for_domain(domain_id)

    async def get_atom_links(self, atom_id: str) -> list[KnowledgeLink]:
        return await self._links.get_links_for_atom(atom_id)

    # ----------------------------------------------------------- private

    async def _candidates(self, atom: KnowledgeAtom) -> list[KnowledgeAtom]:
        """Pick candidates by text relevance, not recency.

        We re-use the same keyword search the agent's `search_knowledge`
        tool runs, so a relevant atom from a year ago and a recent one are
        treated equally — recency only matters when keywords match. This
        keeps the LLM's prompt focused on plausible relatedness candidates
        instead of "the last N atoms in the domain regardless of topic".
        """
        if not atom.domain_id:
            return []
        query = f"{atom.claim} {atom.context} {atom.action}".strip()
        if not query:
            return []
        # Over-fetch by 1: `produce_knowledge` already wrote `atom` into
        # the store before this runs, so it shows up as a self-match.
        hits = await self._memory.search(
            query,
            limit=_MAX_CANDIDATES + 1,
            domain_id=atom.domain_id,
        )
        return [h for h in hits if h.id != atom.id][:_MAX_CANDIDATES]

    async def _pick_related(
        self, atom: KnowledgeAtom, candidates: list[KnowledgeAtom]
    ) -> list[KnowledgeAtom]:
        if not candidates:
            return []
        try:
            picked = await self._llm_pick(atom, candidates)
        except Exception as e:
            logger.warning(
                "llm_linker_fallback_to_keyword",
                atom_id=atom.id,
                error=str(e),
            )
            return [c for c in candidates if is_keyword_match(atom.context, atom.claim, c)]
        # Filter to ids that actually exist in the candidate set.
        candidate_ids = {c.id for c in candidates}
        valid_ids = [cid for cid in picked if cid in candidate_ids]
        by_id = {c.id: c for c in candidates}
        return [by_id[cid] for cid in valid_ids]

    async def _llm_pick(self, atom: KnowledgeAtom, candidates: list[KnowledgeAtom]) -> list[str]:
        prompt = _build_prompt(atom, candidates)
        raw = await self._backend.complete(prompt)
        return _parse_ids(raw)


def _build_prompt(atom: KnowledgeAtom, candidates: list[KnowledgeAtom]) -> str:
    candidate_lines = []
    for i, c in enumerate(candidates):
        snippet = (c.claim or "").replace("\n", " ").strip()[:_CANDIDATE_CLAIM_CHARS]
        candidate_lines.append(f'{i + 1}. id="{c.id}" claim={snippet!r}')
    candidates_block = "\n".join(candidate_lines)

    new_claim = (atom.claim or "").replace("\n", " ").strip()
    new_context = (atom.context or "").replace("\n", " ").strip()

    return (
        "You are linking a new knowledge atom into a domain's prior findings. "
        "Pick which of the candidate atoms below are SEMANTICALLY RELATED — "
        "i.e. a future agent reading either should also see the other. Use "
        "topic / subject overlap as the criterion, not just shared words.\n\n"
        f"NEW atom:\n  claim: {new_claim!r}\n  context: {new_context!r}\n\n"
        f"CANDIDATES (most-recent {len(candidates)} in this domain):\n"
        f"{candidates_block}\n\n"
        'Output ONLY a JSON array of the candidate ids that are related, e.g. ["01HX...", "01HY..."]. '
        "Empty array `[]` is fine if none are related. No prose, no code fences."
    )


def _parse_ids(raw: str) -> list[str]:
    raw = raw.strip()
    # Strip code fences if the model added them despite instructions.
    if raw.startswith("```"):
        lines = [line for line in raw.split("\n") if not line.startswith("```")]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"non-JSON LLM output: {raw[:200]!r}") from e
    if not isinstance(parsed, list):
        raise ValueError(f"expected JSON array, got {type(parsed).__name__}")
    return [str(x) for x in parsed if isinstance(x, str)]
