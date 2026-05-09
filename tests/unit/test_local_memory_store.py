"""Round-trip tests for the file-per-atom ``LocalMemoryStore``."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from dojo.core.knowledge import KnowledgeAtom
from dojo.storage.local.memory import LocalMemoryStore


@pytest.fixture
def store(tmp_path: Path) -> LocalMemoryStore:
    return LocalMemoryStore(base_dir=tmp_path / "knowledge")


def _atom(**kwargs) -> KnowledgeAtom:
    defaults = dict(
        domain_id="dom-1",
        source_experiment_id="exp-1",
        context="ctx",
        claim="claim",
        action="",
        confidence=0.5,
        evidence_ids=[],
    )
    defaults.update(kwargs)
    return KnowledgeAtom(**defaults)


async def test_add_writes_file_in_domain_bucket(store: LocalMemoryStore, tmp_path: Path) -> None:
    atom = _atom(domain_id="dom-A", claim="Hello world")
    await store.add(atom)

    expected = tmp_path / "knowledge" / "dom-A" / f"{atom.id}.md"
    assert expected.exists()
    text = expected.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "Hello world" in text


async def test_atom_with_no_domain_lands_in_global_bucket(
    store: LocalMemoryStore, tmp_path: Path
) -> None:
    atom = _atom(domain_id="", claim="domainless")
    await store.add(atom)

    expected = tmp_path / "knowledge" / "_global" / f"{atom.id}.md"
    assert expected.exists()


async def test_round_trip_preserves_fields(store: LocalMemoryStore) -> None:
    atom = _atom(
        domain_id="dom-A",
        source_experiment_id="exp-7",
        context="housing baseline",
        claim="Random forests beat linear regression by ~12% RMSE",
        action="Use HistGradientBoosting as default",
        confidence=0.85,
        evidence_ids=["exp-7", "exp-8"],
    )
    await store.add(atom)

    # Force a fresh read by clearing the cache.
    store._cache.clear()
    store._cache_loaded = False

    loaded = await store.get(atom.id)
    assert loaded is not None
    assert loaded.id == atom.id
    assert loaded.domain_id == "dom-A"
    assert loaded.source_experiment_id == "exp-7"
    assert loaded.context == "housing baseline"
    assert loaded.claim.startswith("Random forests beat")
    assert loaded.action == "Use HistGradientBoosting as default"
    assert loaded.confidence == 0.85
    assert loaded.evidence_ids == ["exp-7", "exp-8"]


async def test_list_walks_all_buckets(store: LocalMemoryStore) -> None:
    await store.add(_atom(domain_id="dom-A", claim="A"))
    await store.add(_atom(domain_id="dom-B", claim="B"))
    await store.add(_atom(domain_id="", claim="C"))

    atoms = await store.list()
    assert len(atoms) == 3
    assert {a.claim for a in atoms} == {"A", "B", "C"}


async def test_list_for_domain_scopes_correctly(store: LocalMemoryStore) -> None:
    await store.add(_atom(domain_id="dom-A", claim="A1"))
    await store.add(_atom(domain_id="dom-A", claim="A2"))
    await store.add(_atom(domain_id="dom-B", claim="B1"))

    in_a = await store.list_for_domain("dom-A")
    assert len(in_a) == 2
    assert {a.claim for a in in_a} == {"A1", "A2"}

    in_b = await store.list_for_domain("dom-B")
    assert len(in_b) == 1


async def test_search_text_overlap_on_claim_context_action(
    store: LocalMemoryStore,
) -> None:
    await store.add(_atom(claim="Random forests beat linear regression"))
    await store.add(_atom(claim="BERT fine-tuning improves sentiment classification"))

    hits = await store.search("forests")
    assert len(hits) == 1
    assert "Random forests" in hits[0].claim


async def test_search_with_domain_id_scopes_results(store: LocalMemoryStore) -> None:
    await store.add(_atom(domain_id="dom-A", claim="forests beat linear in domain A"))
    await store.add(_atom(domain_id="dom-B", claim="forests beat linear in domain B"))

    hits = await store.search("forests", domain_id="dom-A")
    assert len(hits) == 1
    assert hits[0].domain_id == "dom-A"


async def test_search_empty_query_returns_empty(store: LocalMemoryStore) -> None:
    await store.add(_atom(claim="anything"))
    assert await store.search("") == []


async def test_delete_removes_file_and_cache(store: LocalMemoryStore, tmp_path: Path) -> None:
    atom = _atom(domain_id="dom-A", claim="byebye")
    await store.add(atom)
    path = tmp_path / "knowledge" / "dom-A" / f"{atom.id}.md"
    assert path.exists()

    assert await store.delete(atom.id) is True
    assert not path.exists()
    assert await store.get(atom.id) is None
    assert await store.delete(atom.id) is False


async def test_frontmatter_handles_missing_keys(store: LocalMemoryStore, tmp_path: Path) -> None:
    """A handwritten file with only required fields parses cleanly."""
    bucket = tmp_path / "knowledge" / "dom-A"
    bucket.mkdir(parents=True)
    path = bucket / "01HX_handwritten.md"
    path.write_text(
        "---\nid: 01HX_handwritten\ndomain_id: dom-A\n---\n\n# Claim\n\nHand-typed atom.\n",
        encoding="utf-8",
    )

    loaded = await store.get("01HX_handwritten")
    assert loaded is not None
    assert loaded.domain_id == "dom-A"
    assert loaded.source_experiment_id == ""
    assert loaded.claim == "Hand-typed atom."
    assert loaded.confidence == 0.0


async def test_malformed_yaml_is_skipped_not_fatal(store: LocalMemoryStore, tmp_path: Path) -> None:
    bucket = tmp_path / "knowledge" / "dom-A"
    bucket.mkdir(parents=True)
    bad = bucket / "broken.md"
    bad.write_text("---\n: not valid yaml: : :\n---\n", encoding="utf-8")

    good = _atom(domain_id="dom-A", claim="still works")
    await store.add(good)

    atoms = await store.list()
    # Broken file is skipped; good atom is present.
    assert any(a.id == good.id for a in atoms)


async def test_serialised_yaml_is_human_readable(store: LocalMemoryStore, tmp_path: Path) -> None:
    """Frontmatter is canonical YAML — external tooling can grep + parse it."""
    atom = _atom(
        domain_id="dom-A",
        source_experiment_id="exp-7",
        evidence_ids=["exp-1", "exp-2"],
        confidence=0.9,
        created_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
    )
    await store.add(atom)
    path = tmp_path / "knowledge" / "dom-A" / f"{atom.id}.md"
    text = path.read_text(encoding="utf-8")
    fm_text = text.split("---", 2)[1]
    parsed = yaml.safe_load(fm_text)
    assert parsed["id"] == atom.id
    assert parsed["domain_id"] == "dom-A"
    assert parsed["source_experiment_id"] == "exp-7"
    assert parsed["evidence_ids"] == ["exp-1", "exp-2"]
    assert parsed["confidence"] == 0.9
