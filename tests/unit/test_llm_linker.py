"""Unit tests for ``LLMKnowledgeLinker`` with a fake completion backend."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from dojo.agents.backend import AgentBackend
from dojo.agents.types import AgentEvent, AgentRunConfig
from dojo.runtime.llm_linker import LLMKnowledgeLinker
from dojo.storage.local import LocalKnowledgeLinkStore, LocalMemoryStore
from dojo.tools.base import ToolDef


class _FakeBackend(AgentBackend):
    """Stub-style backend that returns canned ``complete()`` output."""

    def __init__(self, response: str | Exception) -> None:
        self._response = response
        self.prompts: list[str] = []

    async def configure(self, tool_defs: list[ToolDef], config: AgentRunConfig) -> None:
        return None

    async def execute(self, prompt: str) -> AsyncIterator[AgentEvent]:
        if False:  # pragma: no cover — we never call execute() in these tests
            yield AgentEvent(event_type="result", data={})

    async def stop(self) -> None:
        return None

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    @property
    def name(self) -> str:
        return "fake"


@pytest.fixture
def memory_store(tmp_path: Path) -> LocalMemoryStore:
    return LocalMemoryStore(base_dir=tmp_path / "knowledge")


@pytest.fixture
def link_store(tmp_path: Path) -> LocalKnowledgeLinkStore:
    return LocalKnowledgeLinkStore(base_dir=tmp_path / "knowledge_links")


def _make_linker(
    memory_store, link_store, response: str | Exception
) -> tuple[LLMKnowledgeLinker, _FakeBackend]:
    backend = _FakeBackend(response)
    return LLMKnowledgeLinker(memory_store, link_store, backend=backend), backend


async def _seed(linker: LLMKnowledgeLinker, *claims: str, domain_id: str = "dom-A") -> list[str]:
    ids: list[str] = []
    for claim in claims:
        result = await linker.produce_knowledge(
            context=f"context for {claim}",
            claim=claim,
            domain_id=domain_id,
            experiment_id="exp-seed",
        )
        ids.append(result.atom_id)
    return ids


async def test_happy_path_links_to_returned_candidate(memory_store, link_store) -> None:
    """LLM picks a valid candidate id → RELATED_TO link is written."""
    # Seed one atom; the second produce will be linked back to it.
    seed_linker, _ = _make_linker(memory_store, link_store, response="[]")
    [seed_id] = await _seed(seed_linker, "First finding about regression")

    # Fresh linker that returns the seed id.
    linker, backend = _make_linker(memory_store, link_store, response=json.dumps([seed_id]))
    result = await linker.produce_knowledge(
        context="follow-up context",
        claim="Second related finding",
        domain_id="dom-A",
        experiment_id="exp-2",
    )

    assert result.related_to == [seed_id]
    assert backend.prompts, "the LLM should have been asked"
    links = await link_store.get_links_for_atom(result.atom_id)
    related_links = [lk for lk in links if lk.link_type.value == "related_to"]
    assert len(related_links) == 1
    assert related_links[0].related_atom_id == seed_id


async def test_malformed_json_falls_back_to_keyword_overlap(memory_store, link_store) -> None:
    """LLM returns garbage → keyword fallback decides RELATED_TO."""
    # Seed an atom whose claim shares many words with the new finding.
    seed_linker, _ = _make_linker(memory_store, link_store, response="[]")
    [seed_id] = await _seed(
        seed_linker,
        "Random forests outperform linear regression on tabular housing data",
    )

    linker, _ = _make_linker(memory_store, link_store, response="not valid json at all { ] }")
    result = await linker.produce_knowledge(
        context="follow-up housing experiment with cross-validation",
        claim="Random forests outperform linear regression on tabular housing data again",
        domain_id="dom-A",
        experiment_id="exp-2",
    )

    # Fallback should match because both atoms share overlapping keywords.
    assert result.related_to == [seed_id]


async def test_empty_candidate_list_short_circuits(memory_store, link_store) -> None:
    """No prior atoms in the domain → no LLM call, no related links."""
    linker, backend = _make_linker(memory_store, link_store, response="[]")

    result = await linker.produce_knowledge(
        context="ctx",
        claim="first ever atom",
        domain_id="dom-A",
        experiment_id="exp-1",
    )

    assert result.related_to is None
    assert backend.prompts == [], "no candidates → no LLM call"


async def test_ids_outside_candidate_set_are_filtered(memory_store, link_store) -> None:
    """LLM hallucinates an unknown id → it's silently dropped.

    The seed claim shares keywords with the new finding so it lands in the
    candidate set; the hallucinated id does not, so it must be filtered.
    """
    seed_linker, _ = _make_linker(memory_store, link_store, response="[]")
    await _seed(seed_linker, "Existing finding about regression baselines")

    linker, _ = _make_linker(
        memory_store,
        link_store,
        response=json.dumps(["01XX_DOES_NOT_EXIST"]),
    )
    result = await linker.produce_knowledge(
        context="ctx",
        claim="New finding about regression baselines",
        domain_id="dom-A",
        experiment_id="exp-2",
    )

    assert result.related_to is None
    links = await link_store.get_links_for_atom(result.atom_id)
    assert all(lk.link_type.value != "related_to" for lk in links)


async def test_llm_exception_falls_back_to_keyword(memory_store, link_store) -> None:
    """``backend.complete()`` raises → keyword overlap kicks in."""
    seed_linker, _ = _make_linker(memory_store, link_store, response="[]")
    [seed_id] = await _seed(
        seed_linker,
        "Boosting models outperform linear baselines on tabular data with engineered features",
    )

    linker, _ = _make_linker(memory_store, link_store, response=RuntimeError("boom"))
    result = await linker.produce_knowledge(
        context="follow-up tabular experiment with engineered features",
        claim="Boosting models outperform linear baselines on tabular data with engineered features again",
        domain_id="dom-A",
        experiment_id="exp-2",
    )

    assert result.related_to == [seed_id]


async def test_atom_records_domain_and_source_experiment(memory_store, link_store) -> None:
    linker, _ = _make_linker(memory_store, link_store, response="[]")
    result = await linker.produce_knowledge(
        context="ctx",
        claim="self-describing atom",
        domain_id="dom-A",
        experiment_id="exp-7",
    )
    atom = await memory_store.get(result.atom_id)
    assert atom is not None
    assert atom.domain_id == "dom-A"
    assert atom.source_experiment_id == "exp-7"


async def test_code_fenced_response_is_parsed(memory_store, link_store) -> None:
    """Tolerate the model returning ```json [...] ``` despite instructions."""
    seed_linker, _ = _make_linker(memory_store, link_store, response="[]")
    [seed_id] = await _seed(seed_linker, "Earlier finding")

    fenced = f"```json\n{json.dumps([seed_id])}\n```"
    linker, _ = _make_linker(memory_store, link_store, response=fenced)
    result = await linker.produce_knowledge(
        context="ctx",
        claim="Later finding",
        domain_id="dom-A",
        experiment_id="exp-2",
    )
    assert result.related_to == [seed_id]
