"""Unit tests for end-of-run knowledge flush."""

from __future__ import annotations

import json

from dojo.agents.backend import AgentBackend
from dojo.agents.summarizer import extract_knowledge_atoms, flush_run_knowledge
from dojo.agents.types import AgentEvent


class _FakeBackend(AgentBackend):
    """Test double whose `complete` returns whatever JSON we ask for."""

    name = "fake"

    def __init__(self, response: str) -> None:
        self._response = response

    async def configure(self, tools, config) -> None:  # pragma: no cover - unused
        pass

    async def execute(self, prompt: str):  # pragma: no cover - unused
        if False:
            yield  # type: ignore[unreachable]

    async def stop(self) -> None:  # pragma: no cover - unused
        pass

    async def complete(self, prompt: str) -> str:
        return self._response


async def test_low_confidence_atoms_dropped():
    """Atoms with confidence < 0.5 must not survive parsing."""
    backend = _FakeBackend(
        json.dumps(
            [
                {"claim": "high signal lesson", "confidence": 0.8},
                {"claim": "weak hunch", "confidence": 0.3},
                {"claim": "borderline", "confidence": 0.49},
            ]
        )
    )
    atoms = await extract_knowledge_atoms(backend, transcript="x", domain_id="d")
    assert [a["claim"] for a in atoms] == ["high signal lesson"]


async def test_atoms_without_explicit_confidence_kept():
    """If the model omits confidence, default 0.5 keeps the atom (the floor is < 0.5, not <= 0.5)."""
    backend = _FakeBackend(json.dumps([{"claim": "no-confidence atom"}]))
    atoms = await extract_knowledge_atoms(backend, transcript="x", domain_id="d")
    assert len(atoms) == 1


async def test_prompt_rejects_dataset_shape_examples():
    """The prompt must explicitly tell the model not to emit dataset-shape facts."""
    captured: dict[str, str] = {}

    class _Capture(_FakeBackend):
        async def complete(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return "[]"

    backend = _Capture("[]")
    await extract_knowledge_atoms(backend, transcript="x", domain_id="d")
    assert "dataset shape" in captured["prompt"].lower()
    assert "transferable" in captured["prompt"].lower()
    # Cap is part of the prompt the model sees.
    assert "3-7 atoms" in captured["prompt"]


async def test_more_than_seven_atoms_truncated():
    """Backstop: if the model returns more than 7 atoms, we keep at most 7."""
    backend = _FakeBackend(
        json.dumps([{"claim": f"finding {i}", "confidence": 0.8} for i in range(10)])
    )
    atoms = await extract_knowledge_atoms(backend, transcript="x", domain_id="d")
    assert len(atoms) <= 7


async def test_non_numeric_confidence_treated_as_default():
    """LLM returning non-numeric or null confidence must not lose the whole batch.

    Falls back to default 0.5, which passes the strict-less-than floor.
    """
    backend = _FakeBackend(
        json.dumps(
            [
                {"claim": "string-confidence atom", "confidence": "high"},
                {"claim": "null-confidence atom", "confidence": None},
                {"claim": "good atom", "confidence": 0.9},
            ]
        )
    )
    atoms = await extract_knowledge_atoms(backend, transcript="x", domain_id="d")
    claims = [a["claim"] for a in atoms]
    assert "string-confidence atom" in claims
    assert "null-confidence atom" in claims
    assert "good atom" in claims
    # Non-numeric confidences must be normalized so downstream float() casts
    # in flush_run_knowledge don't silently drop the atom.
    by_claim = {a["claim"]: a for a in atoms}
    assert by_claim["string-confidence atom"]["confidence"] == 0.5
    assert by_claim["null-confidence atom"]["confidence"] == 0.5
    assert by_claim["good atom"]["confidence"] == 0.9


class _LabStub:
    """Minimal lab stub exposing only what flush_run_knowledge touches."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

        class _Linker:
            async def produce_knowledge(_self, **kwargs):
                self.calls.append(kwargs)
                return None

        self.knowledge_linker = _Linker()


async def test_flush_emits_start_and_completed_events_on_success():
    backend = _FakeBackend(json.dumps([{"claim": "good lesson", "confidence": 0.8}]))
    events: list[AgentEvent] = [AgentEvent(event_type="text", data={"text": "transcript content"})]
    lab = _LabStub()

    written = await flush_run_knowledge(backend, lab, events=events, domain_id="d", run_id="r")

    types = [e.event_type for e in events]
    assert "knowledge_flush_started" in types
    assert "knowledge_flush_completed" in types
    completed = next(e for e in events if e.event_type == "knowledge_flush_completed")
    assert completed.data == {"count": written}
    assert written == 1


async def test_flush_emits_completed_with_error_on_extract_failure():
    class _Boom(_FakeBackend):
        async def complete(self, prompt: str) -> str:
            raise RuntimeError("model unavailable")

    backend = _Boom("")
    events: list[AgentEvent] = [AgentEvent(event_type="text", data={"text": "transcript content"})]
    lab = _LabStub()

    written = await flush_run_knowledge(backend, lab, events=events, domain_id="d", run_id="r")
    assert written == 0
    completed = next(e for e in events if e.event_type == "knowledge_flush_completed")
    assert "error" in completed.data
    assert "model unavailable" in completed.data["error"]


async def test_flush_emits_no_events_when_transcript_empty():
    """An empty transcript skips the flush entirely — no user-visible events."""
    backend = _FakeBackend("[]")
    events: list[AgentEvent] = []  # empty transcript
    lab = _LabStub()

    written = await flush_run_knowledge(backend, lab, events=events, domain_id="d", run_id="r")
    assert written == 0
    assert events == []  # untouched
