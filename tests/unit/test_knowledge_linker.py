"""Unit tests for KnowledgeLinker — the immutable knowledge linking service."""

from pathlib import Path

import pytest
import structlog.testing

from dojo.runtime.keyword_linker import KeywordKnowledgeLinker
from dojo.storage.local import LocalKnowledgeLinkStore, LocalMemoryStore


@pytest.fixture
def memory_store(tmp_dir: Path):
    return LocalMemoryStore(base_dir=tmp_dir / "memory")


@pytest.fixture
def link_store(tmp_dir: Path):
    return LocalKnowledgeLinkStore(base_dir=tmp_dir / "knowledge_links")


@pytest.fixture
def linker(memory_store, link_store):
    return KeywordKnowledgeLinker(memory_store, link_store)


async def test_produce_creates_new_atom(linker: KeywordKnowledgeLinker, memory_store):
    result = await linker.produce_knowledge(
        context="Housing price prediction experiment",
        claim="Random forests outperform linear regression on tabular housing data",
        confidence=0.85,
        experiment_id="exp-001",
        domain_id="domain-001",
    )

    assert result.action == "created"
    assert result.confidence == 0.85
    assert result.related_to is None

    # Atom should exist in memory store with self-describing scope
    atoms = await memory_store.list()
    assert len(atoms) == 1
    assert atoms[0].id == result.atom_id
    assert atoms[0].domain_id == "domain-001"
    assert atoms[0].source_experiment_id == "exp-001"


async def test_similar_atoms_are_not_merged(linker: KeywordKnowledgeLinker, memory_store):
    """Similar findings create separate atoms with RELATED_TO links, not merges."""
    # Create an initial atom
    result1 = await linker.produce_knowledge(
        context="Housing price prediction experiment with gradient boosting",
        claim="Random forests outperform linear regression on tabular housing data",
        confidence=0.8,
        experiment_id="exp-001",
        domain_id="domain-001",
    )

    # Produce a similar finding — should NOT merge, should create a new atom
    result2 = await linker.produce_knowledge(
        context="Extended housing price prediction experiment with cross-validation",
        claim="Random forests outperform linear regression on tabular housing data significantly",
        confidence=0.9,
        experiment_id="exp-002",
        domain_id="domain-001",
    )

    # Both should be "created", never "merged"
    assert result1.action == "created"
    assert result2.action == "created"

    # Two separate atoms in store
    atoms = await memory_store.list()
    assert len(atoms) == 2

    # Second atom should have a RELATED_TO link to the first
    assert result2.related_to is not None
    assert result1.atom_id in result2.related_to


async def test_produce_distinct_atoms_not_related(linker: KeywordKnowledgeLinker, memory_store):
    result1 = await linker.produce_knowledge(
        context="Image classification with convolutional neural networks",
        claim="CNNs achieve 95% accuracy on CIFAR-10 with data augmentation enabled",
        confidence=0.9,
        experiment_id="exp-001",
        domain_id="domain-001",
    )

    result2 = await linker.produce_knowledge(
        context="Natural language processing with transformers",
        claim="BERT fine-tuning achieves state-of-the-art on sentiment analysis benchmarks",
        confidence=0.85,
        experiment_id="exp-002",
        domain_id="domain-001",
    )

    atoms = await memory_store.list()
    assert len(atoms) == 2

    # No RELATED_TO links for distinct atoms
    assert result1.related_to is None
    assert result2.related_to is None


async def test_links_created_for_new_atom(linker: KeywordKnowledgeLinker, link_store):
    result = await linker.produce_knowledge(
        context="Testing link creation for classification experiments",
        claim="Gradient boosting consistently outperforms decision trees on structured data",
        experiment_id="exp-001",
        domain_id="domain-001",
    )

    links = await link_store.get_links_for_atom(result.atom_id)
    assert len(links) == 1
    assert links[0].experiment_id == "exp-001"
    assert links[0].domain_id == "domain-001"
    assert links[0].link_type == "created_by"


async def test_related_to_links_created(linker: KeywordKnowledgeLinker, link_store):
    """When a similar atom exists, RELATED_TO links are created."""
    result1 = await linker.produce_knowledge(
        context="Housing price prediction experiment with gradient boosting models",
        claim="Random forests outperform linear regression on tabular housing data",
        confidence=0.8,
        experiment_id="exp-001",
        domain_id="domain-001",
    )

    result2 = await linker.produce_knowledge(
        context="Extended housing price prediction experiment with cross-validation",
        claim="Random forests outperform linear regression on tabular housing data significantly",
        confidence=0.9,
        experiment_id="exp-002",
        domain_id="domain-001",
    )

    links = await link_store.get_links_for_atom(result2.atom_id)
    # Should have CREATED_BY + RELATED_TO
    link_types = [lk.link_type for lk in links]
    assert "created_by" in link_types
    assert "related_to" in link_types

    related_link = next(lk for lk in links if lk.link_type == "related_to")
    assert related_link.related_atom_id == result1.atom_id


async def test_get_domain_knowledge(linker: KeywordKnowledgeLinker):
    await linker.produce_knowledge(
        context="Domain knowledge retrieval test with image experiments",
        claim="CNNs require significant GPU memory for large batch training sizes",
        domain_id="domain-001",
    )
    await linker.produce_knowledge(
        context="Separate domain test for text classification comparison",
        claim="BERT models need extensive fine-tuning on small labeled text datasets",
        domain_id="domain-002",
    )

    d1_atoms = await linker.get_domain_knowledge("domain-001")
    assert len(d1_atoms) == 1

    d2_atoms = await linker.get_domain_knowledge("domain-002")
    assert len(d2_atoms) == 1


async def test_get_atom_links(linker: KeywordKnowledgeLinker):
    result = await linker.produce_knowledge(
        context="Atom links test for experimental results tracking",
        claim="XGBoost with tuned hyperparameters beats default random forest configuration",
        confidence=0.7,
        experiment_id="exp-001",
        domain_id="domain-001",
    )

    links = await linker.get_atom_links(result.atom_id)
    assert len(links) >= 1
    assert links[0].atom_id == result.atom_id


async def test_emits_atom_created_and_link_created_events(
    linker: KeywordKnowledgeLinker,
):
    """produce_knowledge emits one knowledge_atom_created event always,
    and one knowledge_link_created per link written."""
    with structlog.testing.capture_logs() as cap:
        # First atom — no prior atoms so only CREATED_BY link.
        await linker.produce_knowledge(
            context="ctx-A",
            claim="claim about gradient boosting on tabular data",
            experiment_id="exp-1",
            domain_id="dom-1",
        )

    events = [r["event"] for r in cap]
    assert "knowledge_atom_created" in events
    # CREATED_BY is the only link for the first atom.
    assert events.count("knowledge_link_created") == 1
    # Old aggregate event is gone.
    assert "knowledge_linked" not in events


async def test_link_created_event_per_related_link(
    linker: KeywordKnowledgeLinker,
):
    """A second similar atom triggers an additional knowledge_link_created
    event for the RELATED_TO link."""
    # Produce a first atom (not under capture — we only care about the second).
    await linker.produce_knowledge(
        context="housing price prediction with gradient boosting",
        claim="random forests outperform linear regression on tabular housing data",
        experiment_id="exp-1",
        domain_id="dom-1",
    )

    with structlog.testing.capture_logs() as cap:
        await linker.produce_knowledge(
            context="extended housing price prediction with cross-validation",
            claim="random forests outperform linear regression on tabular housing data again",
            experiment_id="exp-2",
            domain_id="dom-1",
        )

    events = [r["event"] for r in cap]
    assert events.count("knowledge_atom_created") == 1
    # CREATED_BY + 1 RELATED_TO = 2 link events.
    assert events.count("knowledge_link_created") == 2
