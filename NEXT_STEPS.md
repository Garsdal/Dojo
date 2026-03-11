# NEXT_STEPS.md — Code Improvement Plan

> Follow-up improvements after the MASTER_PLAN implementation.
> Six focused changes to clean up legacy code, simplify abstractions, and prepare for future backends.

---

## Phase 1: Remove Legacy Task Code

**Goal:** Fully commit to the Domain model — remove all backward-compatible task logic.

### Why
The `Task` model was the original unit of work before domains were introduced. Currently both co-exist: the task router wraps domains under the hood, the orchestrator accepts both `task_id` and `domain_id`, and the frontend still ships task types/hooks. This dual path adds dead code and confusion.

### Files to Delete
| File | Reason |
|---|---|
| `src/agentml/core/task.py` | `Task`, `TaskPlan`, `TaskResult`, `TaskStatus` — unused by domains |
| `src/agentml/api/routers/tasks.py` | Full task router with in-memory `_tasks` dict |
| `frontend/src/hooks/use-tasks.ts` | SWR hooks for `/tasks` endpoints |
| `frontend/src/pages/tasks.tsx` | Legacy tasks page (already unrouted) |
| `frontend/src/pages/dashboard.tsx` | Old dashboard (already unrouted) |
| `frontend/src/pages/experiments.tsx` | Old standalone experiments page (unrouted) |
| `frontend/src/pages/knowledge.tsx` | Old standalone knowledge page (unrouted) |

### Files to Modify

**`src/agentml/api/app.py`**
- Remove `from agentml.api.routers import tasks` and `app.include_router(tasks.router)`.

**`src/agentml/agents/orchestrator.py`**
- Remove `task_id` parameter from `start()`. Signature becomes:
  ```python
  async def start(self, prompt: str, *, domain_id: str) -> AgentRun:
  ```
- Remove the `resolved_domain_id = domain_id or task_id or generate_id()` fallback.

**`frontend/src/types.ts`**
- Delete the `Task` interface and `ExperimentSummary` (if unused elsewhere).

### Tests to Update
- `tests/e2e/test_full_lifecycle.py` — remove any `/tasks` endpoint tests.
- `tests/e2e/test_agent_run.py` — update `start()` calls to pass `domain_id=` only.
- `tests/unit/test_orchestrator.py` — remove `task_id` test cases, add `domain_id`-required tests.

### Validation
- `just test` — all tests pass with no task references.
- `just lint` — no unused imports.
- Frontend builds with `npm run build` in `frontend/`.

---

## Phase 2: Make `domain_id` Non-Nullable

**Goal:** `domain_id` should be a required `str` everywhere except in rare entry-point contexts where the API creates a domain on the fly.

### Current State (problems)

| Location | Current Signature | Problem |
|---|---|---|
| `agents/types.py` — `AgentRunConfig` | `domain_id: str = ""` | Empty string is a sentinel |
| `agents/types.py` — `AgentRun` | `domain_id: str = ""` | Same |
| `api/routers/agent.py` — `StartRunRequest` | `domain_id: str \| None = None` | Nullable |
| `orchestrator.py` — `start()` | `domain_id: str \| None = None` | Falls back to `generate_id()` |
| `runtime/lab.py` — `LabEnvironment` | `domain_store: DomainStore \| None` | Nullable container field |
| `runtime/lab.py` — `LabEnvironment` | `knowledge_link_store: KnowledgeLinkStore \| None` | Nullable container field |

### Target State

| Location | New Signature | Notes |
|---|---|---|
| `AgentRunConfig` | `domain_id: str` (required) | No default |
| `AgentRun` | `domain_id: str` (required) | No default |
| `StartRunRequest` | `domain_id: str` (required) | API enforces it |
| `orchestrator.start()` | `domain_id: str` (required keyword arg) | Caller must supply |
| `LabEnvironment` | `domain_store: DomainStore` | Non-optional |
| `LabEnvironment` | `knowledge_link_store: KnowledgeLinkStore` | Non-optional |

### Cascade Changes
- **`LabEnvironment`** becomes:
  ```python
  @dataclass
  class LabEnvironment:
      compute: ComputeBackend
      sandbox: Sandbox
      experiment_store: ExperimentStore
      artifact_store: ArtifactStore
      memory_store: MemoryStore
      tracking: TrackingConnector
      domain_store: DomainStore          # no longer Optional
      knowledge_link_store: KnowledgeLinkStore  # no longer Optional
  ```
- **All `if lab.domain_store is not None` / `if lab.knowledge_link_store is not None` guards** can be removed from `domains.py`, `knowledge.py` routers, and tools.
- **`_get_linker()` helpers** in routers become straightforward (no `None` return).
- **`build_lab()` in `deps.py`** already always builds both stores — just need to update type hints.
- **`conftest.py`** fixtures must always supply both stores.
- **Agent router** (`/agent/run`): If `domain_id` is required, the frontend must always pick/create a domain before starting a run.

### Validation
- `just test` — all tests pass.
- `mypy` or Pyright — no type errors from removed `Optional`.

---

## Phase 3: Simplify Knowledge Linking

**Goal:** Stop merging atoms. Save every raw atom. Link them to experiments and group similar ones at read time.

### Current Behavior (problems)
`KnowledgeLinker.produce_knowledge()` currently:
1. Searches for a matching atom by keyword overlap (≥40%).
2. If match found: **merges** — averages confidence, picks the longer claim, increments version, stores a snapshot, creates an `UPDATED_BY` link.
3. If no match: creates new atom, stores snapshot, creates `CREATED_BY` link.

Problems:
- Merging loses the original raw claim text.
- Average confidence is arbitrary.
- "Pick longer claim" is a fragile heuristic.
- Hard to audit what each experiment actually produced.

### New Design

**Principle:** Every experiment produces immutable raw atoms. Linking is purely relational — it records "experiment X also found something related to atom Y." Grouping is a read-time concern.

**`produce_knowledge()` becomes:**
```python
async def produce_knowledge(self, *, context, claim, action, confidence,
                            evidence_ids, experiment_id, domain_id) -> LinkingResult:
    # 1. Always create a new atom
    atom = KnowledgeAtom(context=context, claim=claim, action=action,
                         confidence=confidence, evidence_ids=evidence_ids)
    await self.memory_store.add(atom)

    # 2. Find similar existing atoms (for grouping, not merging)
    similar = self._find_similar(atom)

    # 3. Create a CREATED_BY link from this atom to the experiment
    await self._create_link(atom.id, experiment_id, domain_id, LinkType.CREATED_BY)

    # 4. For each similar atom, create a RELATED_TO link (new link type)
    for existing_atom in similar:
        await self._create_link(atom.id, experiment_id, domain_id,
                                LinkType.RELATED_TO, related_atom_id=existing_atom.id)

    return LinkingResult(atom_id=atom.id, action="created",
                         version=1, confidence=confidence)
```

**Key changes:**
- No more merging. No more `UPDATED_BY` link type.
- Add `RELATED_TO` link type to `LinkType` enum.
- `KnowledgeLink` gets an optional `related_atom_id: str | None` field to record atom-to-atom relationships.
- Remove `KnowledgeSnapshot` model entirely — versioning/snapshots were artifacts of the merge approach.
- `get_domain_knowledge()` returns raw atoms with their links; grouping of related atoms is done by the API/frontend.

**Simplified `LinkType` enum:**
```python
class LinkType(str, Enum):
    CREATED_BY = "created_by"       # atom was produced by this experiment
    RELATED_TO = "related_to"       # atom is similar to another atom
```

### Files to Modify
| File | Change |
|---|---|
| `core/knowledge_link.py` | Remove `KnowledgeSnapshot`, simplify `LinkType`, add `related_atom_id` to `KnowledgeLink` |
| `runtime/knowledge_linker.py` | Remove merge logic, remove snapshot creation, simplify `produce_knowledge()` |
| `interfaces/knowledge_link_store.py` | Remove snapshot-related methods if baked in |
| `storage/local_knowledge_link.py` | Remove snapshot storage, add `related_atom_id` support |
| `api/routers/knowledge.py` | Remove `KnowledgeSnapshotResponse`, update endpoints, add grouped-knowledge response |
| `api/routers/domains.py` | Remove evolution endpoint or repurpose for raw atom timeline |
| `tools/knowledge.py` | Remove merged-atom logic |
| `frontend/src/types.ts` | Remove `KnowledgeSnapshot`, `LinkingResult.merged_with`, update `KnowledgeLink` |
| `frontend/src/hooks/use-knowledge-evolution.ts` | Remove or repurpose |
| `frontend/src/components/knowledge/knowledge-evolution-chart.tsx` | Remove or repurpose |

### New API Responses

```json
// GET /domains/{id}/knowledge — returns raw atoms with group info
[
  {
    "id": "atom_abc",
    "context": "...",
    "claim": "...",
    "confidence": 0.85,
    "experiment_id": "exp_123",
    "related_atoms": ["atom_xyz", "atom_def"]
  }
]
```

### Validation
- Unit tests for `KnowledgeLinker` — assert no merging occurs, assert `RELATED_TO` links created.
- E2E tests — two similar atoms from different experiments → both stored, linked.
- Frontend builds and displays grouped atoms.

---

## Phase 4: KnowledgeLinker Interface

**Goal:** Create an ABC so linker implementations can be swapped. Ship a keyword-overlap default; plan for agentic linking.

### New Interface

```python
# src/agentml/interfaces/knowledge_linker.py

from abc import ABC, abstractmethod
from agentml.core.knowledge import KnowledgeAtom
from agentml.core.knowledge_link import KnowledgeLink

class KnowledgeLinker(ABC):
    """Port for knowledge-linking strategies."""

    @abstractmethod
    async def produce_knowledge(self, *, context: str, claim: str, action: str,
                                confidence: float, evidence_ids: list[str],
                                experiment_id: str, domain_id: str) -> LinkingResult:
        """Store a new atom and link it to related knowledge."""

    @abstractmethod
    async def find_similar(self, atom: KnowledgeAtom) -> list[KnowledgeAtom]:
        """Find atoms semantically similar to the given one."""

    @abstractmethod
    async def get_domain_knowledge(self, domain_id: str) -> list[KnowledgeAtom]:
        """All atoms linked to a domain."""

    @abstractmethod
    async def get_atom_links(self, atom_id: str) -> list[KnowledgeLink]:
        """All links for an atom."""
```

### Implementations

| Implementation | Location | Strategy |
|---|---|---|
| `KeywordKnowledgeLinker` | `src/agentml/runtime/keyword_linker.py` | Current 40% word overlap (default) |
| `AgenticKnowledgeLinker` | `src/agentml/runtime/agentic_linker.py` (future) | Uses LLM to judge semantic similarity |

### Wiring

**`LabEnvironment`** gets a new field:
```python
knowledge_linker: KnowledgeLinker
```

**`build_lab()` in `deps.py`** constructs the linker once:
```python
from agentml.runtime.keyword_linker import KeywordKnowledgeLinker

knowledge_linker=KeywordKnowledgeLinker(memory_store, knowledge_link_store)
```

**Config extension** (future — not needed now):
```yaml
knowledge:
  linker: keyword   # or "agentic"
```

### Cascade
- Routers use `lab.knowledge_linker` directly — no more `_get_linker()` helper that constructs on every request.
- Tools use `lab.knowledge_linker` instead of importing the concrete class.
- Remove direct imports of the concrete linker from routers/tools.

### Validation
- `just test` — all existing linker tests pass against `KeywordKnowledgeLinker`.
- New unit test: mock linker interface → verify router behavior is implementation-agnostic.

---

## Phase 5: Restructure `storage/` for Multiple Backends

**Goal:** Organize storage adapters into sub-packages so adding a Supabase/Postgres backend is clean.

### Current Structure (flat)
```
storage/
  __init__.py
  local_artifact.py
  local_domain.py
  local_experiment.py
  local_knowledge_link.py
  local_memory.py
```

### Target Structure
```
storage/
  __init__.py               # Re-exports for convenience
  local/
    __init__.py             # Re-exports all local adapters
    artifact.py             # LocalArtifactStore
    domain.py               # LocalDomainStore
    experiment.py           # LocalExperimentStore
    knowledge_link.py       # LocalKnowledgeLinkStore
    memory.py               # LocalMemoryStore
  # Future:
  # supabase/
  #   __init__.py
  #   artifact.py           # SupabaseArtifactStore
  #   domain.py             # SupabaseDomainStore
  #   ...
```

### Migration Steps

1. **Create `storage/local/` package** with `__init__.py`.
2. **Move and rename** each `local_*.py` → `local/*.py` (drop the `local_` prefix since the package name conveys it):
   - `local_artifact.py` → `local/artifact.py`
   - `local_domain.py` → `local/domain.py`
   - `local_experiment.py` → `local/experiment.py`
   - `local_knowledge_link.py` → `local/knowledge_link.py`
   - `local_memory.py` → `local/memory.py`
3. **Update `storage/local/__init__.py`** to re-export:
   ```python
   from .artifact import LocalArtifactStore
   from .domain import LocalDomainStore
   from .experiment import LocalExperimentStore
   from .knowledge_link import LocalKnowledgeLinkStore
   from .memory import LocalMemoryStore

   __all__ = [
       "LocalArtifactStore",
       "LocalDomainStore",
       "LocalExperimentStore",
       "LocalKnowledgeLinkStore",
       "LocalMemoryStore",
   ]
   ```
4. **Update `storage/__init__.py`** to re-export from `local` subpackage so existing imports don't all break at once:
   ```python
   from .local import (
       LocalArtifactStore,
       LocalDomainStore,
       LocalExperimentStore,
       LocalKnowledgeLinkStore,
       LocalMemoryStore,
   )
   ```
5. **Update imports** throughout the codebase. Key files:
   - `api/deps.py` — `from agentml.storage.local import ...` (or `from agentml.storage.local.experiment import ...`)
   - All test files that import storage adapters directly.

### Future Backend Pattern
Adding Supabase/Postgres later:
```python
# storage/supabase/__init__.py
from .artifact import SupabaseArtifactStore
from .domain import SupabaseDomainStore
...
```

```python
# api/deps.py — build_lab dispatches on config
if settings.storage.backend == "local":
    from agentml.storage.local import LocalExperimentStore as ExperimentStoreImpl
elif settings.storage.backend == "supabase":
    from agentml.storage.supabase import SupabaseExperimentStore as ExperimentStoreImpl
```

This requires adding `backend: str = "local"` to `StorageSettings`.

### Validation
- `just test` — all tests pass after import updates.
- `just lint` — no import errors.
- Verify `from agentml.storage import LocalExperimentStore` still works (backward compat re-export).

---

## Phase 6: Simplify Domain Tools

**Goal:** Make `DomainTool` purely descriptive. The agent decides how to use tools — we don't need a subprocess execution layer.

### Current Problem
`tools/domain_tools.py` converts each `DomainTool` into an executable `ToolDef` that runs `DomainTool.code` via subprocess (tempfile + `subprocess.run()`). This is problematic:
- The agent is supposed to handle code execution (via sandbox/compute).
- Writing executable `code` for each tool is fragile and hard to generate correctly.
- Subprocess boilerplate duplicates the sandbox abstraction.
- It conflates "what a tool conceptually does" with "how to run it."

### New Design

**`DomainTool` becomes a semantic descriptor** — it tells the agent what operations are available in this domain, not how to execute them. The agent uses this context to decide what code to write and run via existing sandbox/compute infrastructure.

**Updated `DomainTool` model:**
```python
@dataclass
class DomainTool:
    id: str = field(default_factory=generate_id)
    name: str = ""                    # e.g., "fetch_data", "evaluate_results"
    description: str = ""             # What this tool does conceptually
    type: str = "analysis"            # Category: "data", "analysis", "evaluation", etc.
    parameters: dict[str, Any] = field(default_factory=dict)  # Parameter schema
    example_usage: str = ""           # Example code/pseudocode the agent can reference
    created_by: str = "user"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

Key changes:
- **Remove `code: str`** field (executable code).
- **Add `example_usage: str`** field — optional pseudocode or snippet the agent can reference, but not something we execute directly.

**Delete `tools/domain_tools.py`** entirely. The `_build_script()`, `_run_tool()`, and `convert_domain_tools()` functions are no longer needed.

### How the Agent Uses Domain Tools

Domain tools are injected into the agent's system prompt (this already happens in `prompts.py`). The prompt tells the agent:

> *"This domain has the following tools available: `fetch_data` — Loads the training dataset from the configured source. `evaluate_results` — Run evaluation metrics on the model outputs."*

The agent then:
1. Reads the tool descriptions and `example_usage`.
2. Writes appropriate code using its own judgment.
3. Executes that code via the existing sandbox/compute infrastructure.
4. Reports results back.

No conversion to `ToolDef` is needed. Domain tools are context, not callable functions.

### Files to Modify
| File | Change |
|---|---|
| `core/domain.py` | Remove `code` field, add `example_usage` |
| `tools/domain_tools.py` | **Delete entirely** |
| `agents/orchestrator.py` | Remove `convert_domain_tools()` import and usage |
| `agents/prompts.py` | Update domain tools section to use `example_usage` instead of `code` |
| `agents/factory.py` | Remove domain tool injection if wired there |
| `api/routers/domains.py` | Update tool CRUD to handle `example_usage` instead of `code` |
| `tools/tool_generation.py` | Update prompt builder to generate `example_usage` instead of `code` |
| `frontend/src/types.ts` | Update `DomainTool` type: remove `code`, add `example_usage` |
| Frontend tool components | Display `example_usage` instead of `code` |

### Validation
- `just test` — verify no references to `domain_tools.py`.
- Agent runs still get domain tool context in prompt.
- Tool generation produces `example_usage` examples.

---

## Execution Order

The phases have some dependencies. Recommended order:

```
Phase 1 (Remove Tasks)
  └─→ Phase 2 (Non-nullable domain_id)  ← depends on Phase 1 removing task_id fallback

Phase 3 (Simplify Linking)
  └─→ Phase 4 (KnowledgeLinker Interface)  ← easier to design interface after simplification

Phase 5 (Storage Restructure)  ← independent, can run in parallel with 3-4
Phase 6 (Simplify Domain Tools)  ← independent, can run in parallel with 3-4
```

**Suggested sequence:** 1 → 2 → 3 → 4 → 5 → 6

Phases 5 and 6 are low-risk refactors that can be done in any order. Phases 1-2 should be done first because they remove dead code and tighten types, making subsequent changes cleaner. Phases 3-4 are the most intricate and benefit from the simplified codebase.

---

## Test Impact Summary

| Phase | Tests to Delete | Tests to Update | Tests to Add |
|---|---|---|---|
| 1 | Task-related e2e tests | orchestrator tests, lifecycle tests | — |
| 2 | — | Most test fixtures (add required `domain_id`) | Type validation tests |
| 3 | Snapshot/merge tests | Linker unit tests, knowledge e2e | Related-atom grouping tests |
| 4 | — | Linker tests (use interface) | Mock-linker router tests |
| 5 | — | Import paths in test files | — |
| 6 | `domain_tools` tests | Orchestrator tool injection tests | Prompt context tests |
