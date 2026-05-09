"""Local knowledge atom store — one markdown file per atom.

Atoms live at ``.dojo/knowledge/{domain_id}/{atom_id}.md`` with YAML
frontmatter + body. Atoms with no ``domain_id`` go to ``_global/``. The
on-disk format is grep-friendly for humans and external tooling; the
in-process search uses a pure-Python keyword scan over the same files.

Search semantics: text overlap on ``claim`` / ``context`` / ``action``.
Both linkers (keyword + LLM) write atoms here identically — the linker
choice only affects which ``RELATED_TO`` edges land in the link store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from dojo.core.knowledge import KnowledgeAtom
from dojo.interfaces.memory_store import MemoryStore

_GLOBAL_BUCKET = "_global"


class LocalMemoryStore(MemoryStore):
    """Stores knowledge atoms as one ``.md`` file per atom under ``base_dir``."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".dojo/knowledge")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, KnowledgeAtom] = {}
        self._cache_loaded = False

    # ------------------------------------------------------------------ I/O

    def _bucket_for(self, domain_id: str) -> Path:
        return self.base_dir / (domain_id or _GLOBAL_BUCKET)

    def _path_for(self, atom: KnowledgeAtom) -> Path:
        return self._bucket_for(atom.domain_id) / f"{atom.id}.md"

    def _load_all(self) -> None:
        """Walk the tree and parse every atom into the cache."""
        if self._cache_loaded:
            return
        for md in self.base_dir.rglob("*.md"):
            try:
                atom = self._parse_file(md)
            except Exception:
                # Skip malformed files rather than killing startup. Bad files
                # are user-recoverable (delete or fix).
                continue
            self._cache[atom.id] = atom
        self._cache_loaded = True

    def _parse_file(self, path: Path) -> KnowledgeAtom:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)
        sections = _split_body_sections(body)
        return KnowledgeAtom(
            id=frontmatter.get("id", path.stem),
            domain_id=frontmatter.get("domain_id", "") or "",
            source_experiment_id=frontmatter.get("source_experiment_id", "") or "",
            context=sections.get("context", "") or frontmatter.get("context", "") or "",
            claim=sections.get("claim", "") or frontmatter.get("claim", "") or "",
            action=sections.get("action", "") or frontmatter.get("action", "") or "",
            confidence=float(frontmatter.get("confidence", 0.0) or 0.0),
            evidence_ids=list(frontmatter.get("evidence_ids", []) or []),
            created_at=_parse_dt(frontmatter.get("created_at")),
            updated_at=_parse_dt(frontmatter.get("updated_at")),
        )

    def _serialize(self, atom: KnowledgeAtom) -> str:
        frontmatter: dict[str, Any] = {
            "id": atom.id,
            "domain_id": atom.domain_id,
            "source_experiment_id": atom.source_experiment_id,
            "confidence": atom.confidence,
            "evidence_ids": list(atom.evidence_ids),
            "created_at": atom.created_at.isoformat(),
            "updated_at": atom.updated_at.isoformat(),
        }
        fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip()
        body_parts: list[str] = []
        if atom.claim:
            body_parts.append(f"# Claim\n\n{atom.claim.strip()}")
        if atom.context:
            body_parts.append(f"# Context\n\n{atom.context.strip()}")
        if atom.action:
            body_parts.append(f"# Action\n\n{atom.action.strip()}")
        body = "\n\n".join(body_parts)
        return f"---\n{fm_yaml}\n---\n\n{body}\n" if body else f"---\n{fm_yaml}\n---\n"

    def _write(self, atom: KnowledgeAtom) -> None:
        path = self._path_for(atom)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._serialize(atom), encoding="utf-8")

    # ----------------------------------------------------------- MemoryStore

    async def add(self, atom: KnowledgeAtom) -> str:
        self._load_all()
        self._write(atom)
        self._cache[atom.id] = atom
        return atom.id

    async def list(self) -> list[KnowledgeAtom]:
        self._load_all()
        return list(self._cache.values())

    async def list_for_domain(self, domain_id: str) -> list[KnowledgeAtom]:
        self._load_all()
        return [a for a in self._cache.values() if a.domain_id == domain_id]

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        domain_id: str | None = None,
    ) -> list[KnowledgeAtom]:
        self._load_all()
        keywords = query.lower().split()
        if not keywords:
            return []

        candidates = self._cache.values()
        if domain_id is not None:
            candidates = (a for a in candidates if a.domain_id == domain_id)

        scored: list[tuple[int, KnowledgeAtom]] = []
        for atom in candidates:
            text = f"{atom.claim} {atom.context} {atom.action}".lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((score, atom))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [atom for _, atom in scored[:limit]]

    async def get(self, atom_id: str) -> KnowledgeAtom | None:
        self._load_all()
        return self._cache.get(atom_id)

    async def delete(self, atom_id: str) -> bool:
        self._load_all()
        atom = self._cache.get(atom_id)
        if atom is None:
            return False
        path = self._path_for(atom)
        if path.exists():
            path.unlink()
        del self._cache[atom_id]
        return True

    async def update(self, atom: KnowledgeAtom) -> str:
        # Atoms are immutable-append in normal flows, but the interface allows
        # update() (used by tests / future supersession). Round-trip through
        # disk to keep the cache consistent.
        self._load_all()
        self._write(atom)
        self._cache[atom.id] = atom
        return atom.id


# ---------------------------------------------------------------- helpers


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a ``---\\n...\\n---\\n`` YAML frontmatter block at the top of *text*."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_text = parts[1].strip()
    body = parts[2].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, body


def _split_body_sections(body: str) -> dict[str, str]:
    """Split a markdown body into ``{section_name_lower: text}`` by ``# Heading``.

    Returns claim/context/action as separate strings. Tolerant of missing
    sections, extra whitespace, and case.
    """
    sections: dict[str, str] = {}
    if not body.strip():
        return sections
    current_key: str | None = None
    current_lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and len(stripped) > 2:
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = stripped[2:].strip().lower()
            current_lines = []
        else:
            if current_key is not None:
                current_lines.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()
    return sections


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)
