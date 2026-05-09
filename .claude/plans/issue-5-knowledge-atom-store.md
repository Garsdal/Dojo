# Issue #5: Properly build the knowledge atom store + LLMLinker (grep-friendly structure)

**Issue:** https://github.com/Garsdal/Dojo/issues/5
**Branch (will be created in Phase 2):** `feat/issue-5-knowledge-atom-store`
**Status:** awaiting review

---

## Summary

Three intertwined, deliberately-narrow changes to the knowledge subsystem:

1. **File-per-atom storage.** Replace the single-blob `LocalMemoryStore` (`.dojo/memory/atoms.json`) with one markdown file per atom under `.dojo/knowledge/{domain_id}/{atom_id}.md`, each with YAML frontmatter + body. Grep-friendly, human-readable, scoped by domain on disk.
2. **`LLMKnowledgeLinker`** as a selectable alternative to `KeywordKnowledgeLinker` behind the existing `KnowledgeLinker` interface. Same `produce_knowledge` contract — only the `RELATED_TO`-link selection step changes (LLM call instead of keyword-overlap heuristic). KeywordLinker stays the default.
3. **Atom schema cleanup.** Lift `domain_id` and `source_experiment_id` onto `KnowledgeAtom` (so each file is self-describing). Drop unused fields: `version`, `supersedes`. Keep `evidence_ids` (actively used by frontend). No `tags` — keep it simple, don't anticipate access patterns we haven't validated.

**One load-bearing constraint, anchored in MASTER_PLAN.md and CLAUDE.md as part of this PR:** search stays text-only over `claim` / `context` / `action`, regardless of which linker created the atoms. The two linkers produce identical atoms searched identically — they only differ in how `RELATED_TO` links are picked. Following `RELATED_TO` to expand search results, embedding/vector search, and faceted queries are all explicit non-goals here.

The user-visible contract (`write_knowledge` / `search_knowledge` / `list_knowledge` MCP tools, `/knowledge` HTTP API, frontend atom card) keeps working — additive fields only. No CompletionClient abstraction; the linker just takes an `AgentBackend` and calls its existing `complete()` method, same pattern the summarizer and tool-generation flow already use.

---

## Files to change

### Core domain + interfaces

| File | Change |
|---|---|
| [src/dojo/core/knowledge.py](src/dojo/core/knowledge.py) | Add `domain_id: str = ""` and `source_experiment_id: str = ""` to `KnowledgeAtom`. **Drop** `version` and `supersedes` (vestigial — never read or written meaningfully). Keep `evidence_ids`. |
| [src/dojo/interfaces/memory_store.py](src/dojo/interfaces/memory_store.py) | Add `list_for_domain(domain_id) -> list[KnowledgeAtom]`. Extend `search(query, *, domain_id=None, limit=10)`. The default `update()`/`get()` helpers stay valid. |

### Storage layer

| File | Change |
|---|---|
| [src/dojo/storage/local/memory.py](src/dojo/storage/local/memory.py) | **Rewrite.** One `.md` file per atom under `.dojo/knowledge/{domain_id}/{atom_id}.md`, YAML frontmatter + body. Atoms with empty `domain_id` go under `_global/`. `list()` walks the tree; `list_for_domain()` reads one bucket. `search()` scores keyword overlap on `claim` + `context` + `action`. Lazy in-memory cache, invalidated on writes. |
| [src/dojo/storage/local/__init__.py](src/dojo/storage/local/__init__.py) | No export change — class name stays `LocalMemoryStore` (rename is a follow-up; see Risk B). |
| [src/dojo/storage/local/knowledge_link.py](src/dojo/storage/local/knowledge_link.py) | Unchanged. Still records `CREATED_BY` + `RELATED_TO` in `links.json`. |

### Linkers

| File | Change |
|---|---|
| [src/dojo/runtime/keyword_linker.py](src/dojo/runtime/keyword_linker.py) | Set `atom.domain_id` / `atom.source_experiment_id` from kwargs before persisting. Otherwise unchanged — same overlap heuristic, same link writes. |
| **`src/dojo/runtime/llm_linker.py` (new)** | New `LLMKnowledgeLinker` implementing `KnowledgeLinker`. Takes an `AgentBackend` (only `.complete()` is called on it). Persists atom, fetches up to `_MAX_CANDIDATES = 30` recent atoms in the same domain, asks the LLM to pick which are semantically related, writes `CREATED_BY` + `RELATED_TO` links. Falls back to keyword overlap on any LLM error or malformed output. |

### DI + factory

| File | Change |
|---|---|
| [src/dojo/api/deps.py](src/dojo/api/deps.py) | New `_build_linker(settings, memory_store, link_store)`. When `memory.linker == "llm"`, instantiates a second `AgentBackend` via the existing `create_agent_backend(settings.agent.backend, model=...)` factory and hands it to the linker. Move `LocalMemoryStore` base dir from `base / "memory"` → `base / "knowledge"`. |
| [src/dojo/config/settings.py](src/dojo/config/settings.py) | Add `MemorySettings.linker: str = "keyword"` (`"keyword" \| "llm"`) and `MemorySettings.llm_linker_model: str \| None = None` (falls back to `agent.tool_generation_model`). |
| [src/dojo/agents/factory.py](src/dojo/agents/factory.py) | No change. We deliberately reuse `create_agent_backend(...)` as-is — the user's call: don't introduce a separate completion-client abstraction. |

### Tools (MCP surface — agent-visible)

| File | Change |
|---|---|
| [src/dojo/tools/knowledge.py](src/dojo/tools/knowledge.py) | `search_knowledge` and `list_knowledge` responses include `domain_id` and `source_experiment_id`. No new request fields. Tool descriptions: minor wording tweak only — agent behaviour unchanged. |

### API + frontend (light touch)

| File | Change |
|---|---|
| [src/dojo/api/routers/knowledge.py](src/dojo/api/routers/knowledge.py) | Add `domain_id`, `source_experiment_id` to `KnowledgeResponse`. Drop `version` and `supersedes` from the response. |
| [frontend/src/types.ts](frontend/src/types.ts) | Mirror: add `domain_id`, `source_experiment_id` to `KnowledgeAtom`; drop `version`, `supersedes` if they're referenced. |
| [frontend/src/components/domains/knowledge-atom-card.tsx](frontend/src/components/domains/knowledge-atom-card.tsx) | Audit: if `version` or `supersedes` is rendered, remove that branch. No new UI. |

### Tests

| File | Change |
|---|---|
| **`tests/unit/test_local_memory_store.py` (new)** | Round-trip the file-per-atom layout: write, read, `list`, `list_for_domain`, `search` (keyword + with `domain_id` filter), `delete`. Verify YAML frontmatter parses cleanly with extra/missing keys. |
| **`tests/unit/test_llm_linker.py` (new)** | Fake `AgentBackend` returning canned JSON. Cases: happy path (LLM returns valid related-ids subset), malformed JSON → keyword fallback, empty candidate list, LLM returns ids not in candidate set (must filter), LLM raises → keyword fallback. |
| [tests/unit/test_knowledge_linker.py](tests/unit/test_knowledge_linker.py) | Existing tests stay green. Add one assertion that `atom.domain_id` / `atom.source_experiment_id` are populated through the linker. Drop the leftover misleading "version >= 2" comment in the integration test (see below). |
| [tests/unit/test_knowledge_tools.py](tests/unit/test_knowledge_tools.py) | Update response-shape assertions for the new fields. |
| [tests/integration/test_memory_integration.py](tests/integration/test_memory_integration.py) | Confirm a `.md` file exists at the expected path after a stub run. **Drop the stale comment** about merging incrementing `version` (`assert atoms[0].version >= 2`) — the test passes today only because the branch never fires. |

### Docs (planning + reference)

These three updates land in **this PR**, not as a follow-up — the user wants the design constraint anchored before implementation:

| File | Change |
|---|---|
| [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) §3.5 | Replace "no changes for now" with the new direction: file-per-atom storage, LLMLinker option, **search remains text-only** even when LLMLinker is on. Update the §13 "Embedding-based knowledge retrieval" non-goal bullet to also list `RELATED_TO`-graph traversal as deferred. |
| [CLAUDE.md](CLAUDE.md) "Knowledge linking" section | Rewrite for the new file layout + selectable linker. Add an explicit sentence: *"Search is text-search over claim/context/action regardless of which linker created the atoms. The linkers differ only in how `RELATED_TO` links are chosen."* |
| [CHANGELOG.md](CHANGELOG.md) | New `[Unreleased]` entries — see Release notes section below. |

---

## Approach

In implementation order. Each step is a single commit unless noted.

### 1. Atom schema + tests for the cleanup

- Edit `KnowledgeAtom`: add `domain_id`, `source_experiment_id`; remove `version`, `supersedes`.
- Update tests that referenced removed fields. Drop the stale "version >= 2" comment.
- Update `KnowledgeResponse` (API) and `KnowledgeAtom` (frontend type) to match.

### 2. Rewrite `LocalMemoryStore` to file-per-atom

- New on-disk layout: `.dojo/knowledge/{domain_id}/{atom_id}.md`. No-domain atoms → `.dojo/knowledge/_global/{atom_id}.md`.
- File format:
  ```markdown
  ---
  id: 01HXY...
  domain_id: 01HXX...
  source_experiment_id: 01HXZ...
  confidence: 0.85
  evidence_ids: [exp-001]
  created_at: 2026-05-09T10:00:00Z
  updated_at: 2026-05-09T10:00:00Z
  ---

  # Claim

  Random forests outperform linear regression on tabular housing data by ~12% RMSE.

  # Context

  Housing baseline experiments, after initial linear models established a benchmark.

  # Action

  Use HistGradientBoosting as the default; fall back to linear only when interpretability is required.
  ```
- `add()`: serialise + write + cache. `list()` / `list_for_domain()`: walk tree, parse on demand. `search()`: keyword overlap on body fields, optionally filtered by `domain_id`. `get()` / `delete()`: cache-first, walk fallback.
- YAML via the existing `pyyaml` dep.
- **No migration of `atoms.json`.** Old data is orphaned; CHANGELOG documents the workaround (delete `.dojo/memory/`). Pre-1.0 single-tenant tool — migration is overkill.

Implementation choice: **pure-Python text scan**, no shelling out to `grep`/`rg`. The on-disk format is grep-friendly for humans and external tooling (the load-bearing requirement); the in-process search just walks the tree. Avoids subprocess overhead and platform variance.

### 3. Update `KeywordKnowledgeLinker`

- Populate `atom.domain_id` / `atom.source_experiment_id` from `produce_knowledge` kwargs before calling `memory_store.add()`.
- Behaviour otherwise identical: same overlap heuristic, same `CREATED_BY` + `RELATED_TO` writes.

### 4. Implement `LLMKnowledgeLinker`

```python
class LLMKnowledgeLinker(KnowledgeLinker):
    def __init__(
        self,
        memory_store: MemoryStore,
        link_store: KnowledgeLinkStore,
        backend: AgentBackend,
    ) -> None:
        self._memory = memory_store
        self._links = link_store
        self._backend = backend  # only .complete() is used

    async def produce_knowledge(self, *, context, claim, ..., domain_id, source_experiment_id, ...):
        atom = KnowledgeAtom(
            context=context, claim=claim, ...,
            domain_id=domain_id,
            source_experiment_id=source_experiment_id,
        )
        await self._memory.add(atom)

        candidates = await self._memory.list_for_domain(domain_id)
        candidates = [c for c in candidates if c.id != atom.id][-_MAX_CANDIDATES:]

        try:
            related_ids = await self._llm_pick_related(atom, candidates)
        except Exception:
            related_ids = self._fallback_keyword_related(atom, candidates)

        # Write CREATED_BY + one RELATED_TO per related_id (same shape as KeywordLinker).
        ...
        return LinkingResult(...)
```

LLM prompt is short and schema-constrained: *"Given this new finding and these candidate findings (id + claim), return a JSON array of candidate IDs that are semantically related — i.e. a future agent reading either should also see the other. Empty list is fine."* Returned IDs not in the candidate set are filtered out.

`find_similar`, `get_domain_knowledge`, `get_atom_links` reuse the same logic as `KeywordLinker` via shared helper functions (no base class — one base class for two implementations is over-abstracting).

**Backend constraint:** if the configured `agent.backend` doesn't implement `complete()` (e.g. `StubAgentBackend`), `_build_linker` raises at lab build time when `memory.linker == "llm"`. Fail-loud is the project convention ("No silent fallbacks").

### 5. Settings + dispatch

- `MemorySettings.linker: str = "keyword"`. Default keeps cost at zero and tests pass without change.
- `MemorySettings.llm_linker_model: str | None = None` — when None, falls back to `agent.tool_generation_model`.
- `_build_linker(settings, memory_store, link_store)` in `api/deps.py`:
  - `keyword` → `KeywordKnowledgeLinker(memory_store, link_store)`
  - `llm` → `LLMKnowledgeLinker(memory_store, link_store, backend=create_agent_backend(settings.agent.backend, model=settings.memory.llm_linker_model or settings.agent.tool_generation_model))`
- Same call site relocates `LocalMemoryStore` from `base / "memory"` → `base / "knowledge"`.

### 6. Tool surface + API + frontend (additive)

- `search_knowledge` / `list_knowledge` responses include `domain_id`, `source_experiment_id`.
- HTTP `KnowledgeResponse` mirrors them.
- Frontend types updated; any reference to `version` / `supersedes` removed (audit the atom card).
- No new MCP tool parameters. The agent's behaviour is unchanged — the prompt's "Knowledge" section doesn't need updating in this PR.

### 7. Doc updates (this PR)

- **MASTER_PLAN.md §3.5** — rewrite to describe the new direction:
  - File-per-atom storage at `.dojo/knowledge/{domain_id}/{atom_id}.md`.
  - Selectable `KeywordKnowledgeLinker` (default) vs. `LLMKnowledgeLinker`.
  - Explicit constraint: search remains text over `claim`/`context`/`action`. Linker only affects RELATED_TO selection.
  - Keep §13's "Embedding-based knowledge retrieval" non-goal; add a sibling bullet that `RELATED_TO`-graph traversal during search is also deferred.
- **CLAUDE.md "Knowledge linking" section** — rewrite for the new file layout + selectable linker, with the explicit text-search-only sentence.
- **CHANGELOG.md** — new `[Unreleased]` block (Phase 2's version-bump step renames it).

### 8. Run the gates

- `just test && just lint`. Existing tests must stay green; new ones cover the new code paths.

---

## Tests

Acceptance criteria from the issue, mapped to verifications:

| Criterion | How verified |
|---|---|
| `LLMLinker` lands as a selectable backend with tests | `tests/unit/test_llm_linker.py` covers happy path, malformed-JSON fallback, empty candidates, candidate-set filtering, LLM exception → keyword fallback. `MemorySettings.linker` toggles dispatch. |
| Atoms on disk follow a documented, stable structure | `tests/unit/test_local_memory_store.py` round-trips `.dojo/knowledge/{domain_id}/{atom_id}.md`. Frontmatter shape documented in CLAUDE.md. |
| Agent run can grep prior knowledge for a domain and get useful hits via the MCP tool | `tests/integration/test_memory_integration.py` extended: stub run writes an atom; `search_knowledge({"query": ..., "domain_id": ...})` returns it; the on-disk file exists at the expected path. |
| `KeywordKnowledgeLinker` remains as a fallback / cheap default | `MemorySettings.linker` defaults to `"keyword"`. All existing keyword tests stay green untouched. |

Behaviour I'm explicitly **not** testing because we're not building it: tag-faceted search, RELATED_TO-graph expansion at query time, embedding similarity. Those don't exist and shouldn't have skeleton tests.

---

## Storage portability (Postgres-friendly by construction)

Worth being explicit because Marcus called this out: the file-per-atom layout is a local optimisation, not the abstract data model. Mapping to Postgres is mechanical:

| Local (file-per-atom) | Postgres |
|---|---|
| YAML frontmatter | scalar columns: `id`, `domain_id`, `source_experiment_id`, `confidence`, `created_at`, `updated_at` |
| `evidence_ids: [...]` | `jsonb` column (or junction table `atom_evidence(atom_id, experiment_id)`) |
| markdown body sections (`# Claim`, `# Context`, `# Action`) | `claim TEXT`, `context TEXT`, `action TEXT` |
| `.dojo/knowledge/{domain_id}/{atom_id}.md` directory grouping | purely a local read-optimisation; on Postgres → `WHERE domain_id = ?` (with index) |
| `links.json` | junction table `knowledge_links(atom_id, related_atom_id, link_type, ...)` — already shaped right |

The `MemoryStore` interface (`add`, `list`, `list_for_domain`, `search`, `get`, `delete`) doesn't expose anything filesystem-specific. A future `PostgresKnowledgeStore` is a sibling to `LocalMemoryStore` with the same surface — same dispatch pattern as `LocalKnowledgeLinkStore` would get a Postgres twin. No model lock-in.

What we are *not* doing now (and shouldn't paint ourselves into a corner against): adding fields whose semantics rely on filesystem behaviour, or query patterns that only the local impl can answer cheaply.

---

## Risks / open questions

These are the calls I want feedback on before implementing.

### A. Storage migration vs. breakage

**My pick:** no migration; pre-1.0 users delete `.dojo/memory/` (or rename to `.dojo/knowledge/` with a fresh empty store). Document in CHANGELOG.

**Alternative:** ~30-line one-shot importer that reads `atoms.json` if present, writes file-per-atom under `_global/` (since old atoms have no `domain_id`), renames the old file to `atoms.json.migrated`. Defensible — say the word and I'll add it.

### B. `MemoryStore` rename

`memory_store` was named for an in-memory dict. With files, `KnowledgeStore` is more honest. Renaming ripples through `LabEnvironment`, `tests/conftest.py`, prompts, the integration test fixture. **My pick:** leave the name in this PR, file a follow-up. The behavioural change is already big enough.

### C. `KnowledgeLink.CREATED_BY` redundancy

Atom now self-describes its `domain_id` / `source_experiment_id`, so the `CREATED_BY` row is duplicate info. **My pick:** keep emitting it in this PR (frontend reads `links` for the atom-detail page; removing it requires a coupled API + frontend change). Drop in a follow-up.

### D. LLMLinker write cost

Every `write_knowledge` makes one Haiku-tier completion when `memory.linker = "llm"`. ~6–14 calls per agent run. Sub-cent at Haiku pricing. Default stays `keyword`. **My pick:** opt-in only, per-atom (no batching). Batching the end-of-run flush is a follow-up if cost becomes real.

### E. Stub backend + LLMLinker

If `agent.backend = "stub"` and `memory.linker = "llm"`, the linker has no working `.complete()`. **My pick:** raise at `build_lab()` time with a clear error message. Matches the "fail loud" project convention. Tests use `linker=keyword` so this never trips.

---

## Out of scope

Per the issue's non-goals + the simplifications we agreed on:

- **`tags`** — not adding the field. Access patterns unvalidated; the claim text + domain scope already covers the common case.
- **`version`, `supersedes`** — removing entirely. If supersession comes back, it goes in the link table as `LinkType.SUPERSEDES`, not on the atom.
- **Vector / embedding search.** Defer until grep proves insufficient.
- **`RELATED_TO`-graph traversal at query time.** The graph is built (by either linker) and visible on the atom-detail page, but `search_knowledge` returns only direct text matches. Following the graph to expand search is a future change.
- **Multi-tenant or remote stores.** Local files only.
- **`atoms.json` migration** (Risk A).
- **`MemoryStore` rename** (Risk B).
- **Dropping `KnowledgeLink.CREATED_BY`** (Risk C).
- **LLMLinker batching** (Risk D).
- **`CompletionClient` abstraction** — explicitly rejected. Linker reuses `AgentBackend.complete()`.
- **Anthropic-specific code paths.** `LLMLinker` takes any `AgentBackend`; whichever provider the lab runs (Claude today, Copilot tomorrow) is what serves the linker's completions.

---

## Release notes (preview)

These will land under `[Unreleased]` in CHANGELOG.md during Phase 2; the version-bump step renames the section.

```markdown
### Agent prompts

(none in this release)

### Added

- **`LLMKnowledgeLinker`** ([src/dojo/runtime/llm_linker.py](src/dojo/runtime/llm_linker.py)) — alternative knowledge linker selectable via `memory.linker: "llm"` (default `"keyword"`). Uses one `AgentBackend.complete()` call per `write_knowledge` to pick `RELATED_TO` candidates from atoms in the same domain, with keyword-overlap fallback on any LLM error. Search semantics are unchanged: text-only over `claim`/`context`/`action`. (#5)
- **`MemorySettings.linker` and `MemorySettings.llm_linker_model`** ([src/dojo/config/settings.py](src/dojo/config/settings.py)) — new config knobs. `llm_linker_model` falls back to `agent.tool_generation_model` when unset. (#5)
- **`MemoryStore.list_for_domain(domain_id)`** ([src/dojo/interfaces/memory_store.py](src/dojo/interfaces/memory_store.py)) — first-class scoped listing, replacing "list everything and filter via the link store". (#5)

### Changed

- **Knowledge atom storage migrated to file-per-atom** ([src/dojo/storage/local/memory.py](src/dojo/storage/local/memory.py)) — atoms now live at `.dojo/knowledge/{domain_id}/{atom_id}.md` with YAML frontmatter + body, replacing the single-blob `.dojo/memory/atoms.json`. Grep-friendly, human-readable, scoped by domain on disk. **Existing pre-1.0 users:** the old `atoms.json` is no longer read; delete `.dojo/memory/` (or back it up) before upgrading.
- **`KnowledgeAtom` schema cleanup** ([src/dojo/core/knowledge.py](src/dojo/core/knowledge.py)) — added `domain_id` and `source_experiment_id` (each atom is now self-describing). Removed `version` and `supersedes` (vestigial — neither was read or written meaningfully). `evidence_ids` retained. The `/knowledge/*` HTTP responses and frontend types are updated to match. (#5)

### Removed

- **`KnowledgeAtom.version` and `KnowledgeAtom.supersedes`** — see Changed.
```
