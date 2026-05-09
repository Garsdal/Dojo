# CLAUDE.md — Working in the Dojo.ml repo

> Reference for Claude Code (and me) when making changes here. Optimised for "what do I touch and how" rather than vision/strategy.

---

## How to read this file

1. **[The product in 3 commands](#the-product-in-3-commands)** — the user-visible UX. Start here. Internalise this before touching anything: `dojo init` → edit `PROGRAM.md` + `SETUP.md` → `dojo task setup` → `dojo run`. Everything else in this codebase exists to make those four steps work and to let us swap implementations underneath.
2. **[Core vs swappable adapters](#core-vs-swappable-adapters)** — what is the product (must not break) vs what is plumbing (designed to be replaced). Use this to judge "should this change live in the core, or behind an adapter?"
3. **[Quick commands](#quick-commands)** — tests, lint, run, **and release**. We work toward releases often: a typical session ends with a version bump, changelog entry, and tag push. The release flow is documented inline in [Releasing](#releasing).
4. **The rest of the file** is reference: architecture diagram, directory map, domain model, recipes, conventions. Skim by section heading; don't read top-to-bottom.

For vision/strategy, see [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md). For the long-form release runbook, see [docs/RELEASING.md](docs/RELEASING.md).

---

## The product in 3 commands

This is what a user does. Nothing else should leak into their experience.

```bash
dojo init --name my-domain --task-type regression   # 1. scaffold .dojo/ + PROGRAM.md + SETUP.md
$EDITOR PROGRAM.md                                   #    research goal / target / success
$EDITOR SETUP.md                                     #    dataset + evaluation spec
dojo task setup                                      # 2. AI generates load_data + evaluate, verifies, freezes
dojo run                                             # 3. agent runs experiments against the frozen contract
```

That's the whole package, from a user's perspective. The user **never needs to know** there's a `LabEnvironment`, a `TaskService`, a `ComputeBackend`, an MCP server, an `AgentBackend`, or storage adapters. Those exist for *us* — so we can swap the agent (Claude → another model), the storage layer (local JSON → Postgres), the tracking backend (file → MLflow), or the sandbox (subprocess → Docker) without touching the user-facing flow above.

**First principles** (push back if a change violates these):
- **Single-tenant.** One user, one machine, local JSON state in `.dojo/`. No tenant ids, no RBAC, no SaaS-shaped APIs.
- **Bring-your-own-pipeline.** A `Workspace` points at a local repo, a git URL, or an empty dir. We don't own the user's Python environment — we adapt to it.
- **Frozen evaluation, fair-game training.** The agent owns `train()`. The framework owns `load_data()` + `evaluate()`. That split is what makes metrics trustworthy run-over-run, and it is non-negotiable.
- **Open-core architecture.** This repo is the execution layer and is meant to be open. Sandbox cloud, hosted memory, and an agent reliability layer are not built and stay closed when they are.
- **MLflow is a bridge, not a platform.** `MlflowTracker` sits *on top of* whatever MLflow the user already has — never owns it.

If a change pulls in multi-tenant abstractions, speculative integrations (Kubeflow, Slack, etc.), distributed-storage generalisations, or cloud-execution code paths, **push back or ask first.**

---

## Core vs swappable adapters

When you're about to add code, ask: "is this the product, or is it a wrapper that lets the product run in a particular environment?"

### Core (the product — change carefully)

| Where | What it owns |
|---|---|
| [src/dojo/core/](src/dojo/core/) | Pure domain models: `Domain`, `Task`, `Workspace`, `Experiment`, `KnowledgeAtom`, state machines. No I/O. The conceptual model of Dojo. |
| [src/dojo/cli/](src/dojo/cli/) | The user-facing surface: `init`, `run`, `task`, `program`, `runs`, `experiments`, `stop`, `start`, `config`, `domain`. This is what the user sees. |
| [src/dojo/runtime/](src/dojo/runtime/) | Lifecycle services: `TaskService` (create/freeze/verify), `ExperimentService`, `WorkspaceService`, `runner.py` (the runner stub that wires `train()` ↔ `evaluate()`), `tool_verifier.py`. These enforce the frozen-contract guarantee. |
| [src/dojo/agents/](src/dojo/agents/) | `AgentOrchestrator`, `AgentRun`, system prompts, end-of-run knowledge summarizer. The orchestration logic *is* the product — agent backends underneath are swappable. |
| [src/dojo/tools/](src/dojo/tools/) | The MCP tool surface the agent sees: `run_experiment`, `write_knowledge`, `complete_experiment`, etc. Changing a tool's name or description changes user-visible agent behaviour. |
| [src/dojo/api/](src/dojo/api/) | FastAPI app + routers. Peer of the CLI; exposes the same lifecycle to non-CLI consumers. |

### Swappable adapters (wrappers — designed to be replaced)

These exist behind interfaces in [src/dojo/interfaces/](src/dojo/interfaces/). Adding a new backend = new file in the relevant adapter dir + dispatch in [api/deps.py](src/dojo/api/deps.py).

| Interface | Today's adapter(s) | Future possibilities |
|---|---|---|
| `AgentBackend` | `ClaudeAgentBackend`, `StubAgent` | Other LLM SDKs, hosted services |
| `ComputeBackend` | `LocalCompute` (in-process) | Remote/distributed |
| `Sandbox` | `LocalSandbox` (subprocess) | Docker, microVM, cloud sandbox |
| `TrackingConnector` | `FileTracker`, `MlflowTracker`, `NoopTracker` | W&B, Neptune |
| `DomainStore`/`ExperimentStore`/`MemoryStore`/`KnowledgeLinkStore`/`ArtifactStore`/`RunStore` | `Local*` (JSON files) | Postgres, S3 |
| `KnowledgeLinker` | `KeywordKnowledgeLinker` | Agentic / embedding-based |

**Heuristic:** if the change would still be needed when we swap the agent backend, it belongs in core. If it's specifically about *how* a particular agent / store / sandbox talks to the world, it belongs in an adapter.

---

## Quick commands

```bash
just dev              # Install backend (uv sync --all-extras) + frontend (npm install)
just test             # pytest -v (asyncio_mode=auto, real adapters in tmp dirs)
just lint             # Ruff check + format check
just format           # Auto-fix lint + format

just run-stub         # Server + stub agent (no API key, deterministic)
just run-claude       # Server + Claude agent (uses local `claude` CLI auth)
just run-stub-mlflow  # Same + MLflow on :8080
just run-claude-mlflow

just stop             # Kill backend (:8000), frontend (:5173), MLflow (:8080)

# In-process — no server needed
uv run dojo init --name foo --task-type regression
uv run dojo task setup
uv run dojo run
```

Always run `just test && just lint` before declaring a task done.

### Releasing

We cut releases often, frequently at the end of a work session. The release is **tag-driven** — pushing `vX.Y.Z` triggers `.github/workflows/release.yml` which builds, publishes to PyPI (Trusted Publishing, no tokens), and creates a GitHub Release. Locally you only bump the version, write the changelog entry, and push the tag.

**Quick path:**

```bash
just test && just lint                              # green local checks first
# 1. Inspect prompt + tool-description diffs since the last tag — these are the highest-stakes changes
git describe --tags --abbrev=0                      # last tag
git diff <last-tag>..HEAD -- 'src/dojo/agents/prompts.py' 'src/dojo/agents/summarizer.py' 'src/dojo/tools/'
# 2. Update CHANGELOG.md — insert a new section directly below ## [Unreleased]
#    `### Agent prompts` is ALWAYS first, even when empty. Then Added/Changed/Fixed/Removed.
# 3. Bump `version` in pyproject.toml (semver; 0.0.x can break freely)
# 4. Commit + push + tag + push tag
git commit -am "release: vX.Y.Z" && git push origin main
git tag vX.Y.Z && git push origin vX.Y.Z            # ← this is the irreversible step
# 5. Verify
uv tool install dojoml --force && dojo --version
```

**Why `### Agent prompts` is its own changelog section:** the agent's behaviour is steered almost entirely by [src/dojo/agents/prompts.py](src/dojo/agents/prompts.py), the tool descriptions in [src/dojo/tools/](src/dojo/tools/), and the end-of-run extractor in [src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py). A one-word change in any of these can shift behaviour across every domain — silently, without breaking a single test. Always populate the section (or write `(none in this release)`).

**Use the LLM-driven release flow** for full discipline (mandatory prompt-diff review, confirmation gate before the tag push): see the "Release prompt for LLMs" block in [docs/RELEASING.md](docs/RELEASING.md). Paste it into a fresh Claude Code session at the end of your work.

**Failure modes:** PyPI never accepts the same version twice. If publish fails, **always fix forward** — bump and retag. Never amend a published version.

---

## Architecture (hexagonal)

```
Settings (YAML + env)  →  build_lab(settings)  →  LabEnvironment (DI container)
                                                        │
CLI (Typer) → create_app(settings) → FastAPI ←──────────┘
                    │                          LabEnvironment {
              Router handlers                    compute, sandbox,
                    │                            experiment_store, artifact_store,
        AgentOrchestrator + Backend              memory_store, tracking,
        (Claude / Stub)                          domain_store, knowledge_link_store,
                    │                            knowledge_linker, run_store,
        TaskService / ExperimentService          settings
        / WorkspaceService                     }
                    │
        Adapters (storage / tracking / sandbox / compute / agent)
```

**Composition root:** [api/deps.py](src/dojo/api/deps.py) `build_lab()` constructs every adapter and injects them into a single `LabEnvironment` dataclass. The CLI uses [cli/_lab.py](src/dojo/cli/_lab.py) `build_cli_lab()` for the same purpose without spinning up the HTTP app.

**Single-domain model:** every experiment is scoped to a domain. Every knowledge atom links back to the experiment + domain that produced it via `KnowledgeLink`.

---

## Directory map

| Path | Purpose |
|---|---|
| [src/dojo/core/](src/dojo/core/) | Pure domain models. `Domain`, `DomainTool`, `Workspace`, `Experiment`, `Hypothesis`, `KnowledgeAtom`, `Task`, `TaskType`, `ToolContract`, state-machine transitions. No I/O. |
| [src/dojo/interfaces/](src/dojo/interfaces/) | ABCs (ports). One file per backend type. |
| [src/dojo/storage/local/](src/dojo/storage/local/) | Local JSON adapters: domain, experiment, memory, knowledge_link, artifact, run. |
| [src/dojo/tracking/](src/dojo/tracking/) | `FileTracker`, `MlflowTracker` (≥3.0), `NoopTracker`. |
| [src/dojo/sandbox/](src/dojo/sandbox/) | `LocalSandbox` (subprocess) — only adapter today. |
| [src/dojo/compute/](src/dojo/compute/) | `LocalCompute` (in-process). |
| [src/dojo/runtime/](src/dojo/runtime/) | `LabEnvironment` + lifecycle services: `TaskService`, `ExperimentService`, `DomainService`, `WorkspaceService`, `KeywordKnowledgeLinker`, `runner.py`, `tool_verifier.py`, `program_loader.py`, `setup_loader.py`. |
| [src/dojo/agents/](src/dojo/agents/) | Orchestration. `AgentBackend` ABC + `backends/claude.py` & `backends/stub.py`. `AgentOrchestrator`, `prompts.py`, `summarizer.py` (end-of-run knowledge flush). |
| [src/dojo/tools/](src/dojo/tools/) | MCP tool definitions. `experiments.py`, `knowledge.py`, `tracking.py`, `tool_generation.py`. `adapters/claude.py` converts `ToolDef` → MCP server. |
| [src/dojo/api/](src/dojo/api/) | FastAPI app. `app.py`, `deps.py`, `routers/` (one per resource). |
| [src/dojo/cli/](src/dojo/cli/) | Typer CLI: `init`, `run`, `stop`, `start`, `task`, `program`, `runs`, `experiments`, `domain`, `config`. |
| [src/dojo/config/](src/dojo/config/) | `Settings` (pydantic-settings), defaults, YAML loading. |
| [src/dojo/utils/](src/dojo/utils/) | `generate_id()` (ULID), JSON serialization, `structlog` setup. |
| [frontend/](frontend/) | React 19 + Vite 7 + shadcn/ui. **Not bundled in PyPI release** — solidify backend first. |
| [tests/](tests/) | `unit/`, `integration/`, `e2e/`. `conftest.py` builds a real `LabEnvironment` against a tmp dir — no mocking. |

---

## Core domain model

### Domain → Task → Experiments → Knowledge

```
Domain (you define)
  ├── Task            — the contract: load_data + evaluate (frozen, AI-generated at setup)
  │                     Today: TaskType.REGRESSION only. Other types are a registry-only addition.
  ├── Workspace       — local path / git url / empty dir; auto-detects venv & deps
  └── Experiments     — agent-created, many per domain
        ├── Hypothesis
        ├── CodeRuns (each `run_experiment` call)
        └── ExperimentResult (metrics, artifacts, logs, error)
              └── produces KnowledgeAtoms via KnowledgeLinker
                    └── linked via KnowledgeLink (CREATED_BY, RELATED_TO)
```

### State machines

- `ExperimentState`: `PENDING → RUNNING → COMPLETED | FAILED → ARCHIVED`
- `DomainStatus`: `DRAFT → ACTIVE → PAUSED → COMPLETED → ARCHIVED`
- `RunStatus` (agent): `PENDING → RUNNING → COMPLETED | FAILED | STOPPED`

Invalid transitions raise `InvalidTransitionError` from [core/state_machine.py](src/dojo/core/state_machine.py).

### Task contract (the anti-cheating gate)

A Task is the frozen contract for a domain's research loop. The user describes the data + evaluation in `SETUP.md`; `dojo task setup` uses an LLM to generate `load_data.py` and `evaluate.py`, runs them through [runtime/tool_verifier.py](src/dojo/runtime/tool_verifier.py) against the task's `ToolContract`s, and freezes the task. The orchestrator calls `assert_ready` before configuring the backend — agent runs against a non-frozen task are rejected with exit code 3.

`complete_experiment` rejects metric keys outside `task.config["expected_metrics"]` (auto-seeded from the registry's evaluator contract).

**Adding a new task type** = registry-only change in [core/task.py](src/dojo/core/task.py): add to `TaskType`, add a `TaskTypeSpec` to `TASK_TYPE_REGISTRY` with `runner_callsite`, `runner_prelude`, `verifier_fixture_keys`, `contract_version`, etc. Both [runtime/runner.py](src/dojo/runtime/runner.py) and [runtime/tool_verifier.py](src/dojo/runtime/tool_verifier.py) are task-type-agnostic.

**Regression contracts (current — version 4):**
- `def train(X_train, y_train, X_test, *, artifacts_dir) -> y_pred`
- `def evaluate(y_pred, *, X_train, X_test, y_train, y_test, artifacts_dir) -> dict`

Both share the same per-experiment `artifacts_dir`; anything written there is archived and forwarded to the tracking backend. Train artifacts are opportunistic (model checkpoints, training plots — agent's discretion); evaluate's are durable per-run by design (residuals, calibration). Bump `contract_version` whenever any `tool_contracts` shape changes; existing frozen tasks auto-reject on `assert_ready` and the user re-runs `dojo task setup`.

### Knowledge linking

Every `write_knowledge` call goes through a `KnowledgeLinker` ([interfaces/knowledge_linker.py](src/dojo/interfaces/knowledge_linker.py)). Two implementations ship today:

- **`KeywordKnowledgeLinker`** ([runtime/keyword_linker.py](src/dojo/runtime/keyword_linker.py)) — default. Picks `RELATED_TO` candidates via keyword overlap (≥40% of smaller word set, ≥3 overlapping words).
- **`LLMKnowledgeLinker`** ([runtime/llm_linker.py](src/dojo/runtime/llm_linker.py)) — opt-in via `memory.linker = "llm"`. Picks `RELATED_TO` candidates via one `AgentBackend.complete()` call per write, with keyword fallback on any LLM error. Reuses the lab's configured `agent.backend`; no separate completion-client abstraction.

Both linkers do the same four things: create a new immutable atom (no merging), pick similar existing atoms in the same domain, record a `CREATED_BY` link to the experiment + domain, record `RELATED_TO` links to the similar atoms.

**Search stays text-only over `claim` / `context` / `action`, regardless of which linker created the atoms.** The linkers differ only in *which* `RELATED_TO` edges land on disk — the atom shape and the search path are identical. Following `RELATED_TO` to expand search results, embedding similarity, and tag/faceted queries are explicit non-goals (see [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) §13).

Atoms are persisted file-per-atom under `.dojo/knowledge/{domain_id}/{atom_id}.md` (YAML frontmatter + body) by [storage/local/memory.py](src/dojo/storage/local/memory.py). Atoms with no `domain_id` go to `_global/`. The `links.json` blob in [storage/local/knowledge_link.py](src/dojo/storage/local/knowledge_link.py) tracks `CREATED_BY` + `RELATED_TO`. The abstract `MemoryStore` / `KnowledgeLinkStore` interfaces don't expose anything filesystem-specific, so a future Postgres adapter is a sibling drop-in (one row per atom, scalar columns + jsonb for `evidence_ids`, junction table for links).

End of every run, [agents/summarizer.py](src/dojo/agents/summarizer.py) extracts durable findings from the transcript via a one-shot LLM call and writes them as atoms — fires for COMPLETED, FAILED, and STOPPED. Idempotent; silently skips when the backend can't `complete()` (e.g. the stub).

---

## Agent system

### Backends

- **`ClaudeAgentBackend`** — uses `ClaudeSDKClient` from `claude-agent-sdk`. Tools served via MCP. Inherits the user's local `claude` CLI auth (no API key needed for runs; an `ANTHROPIC_API_KEY` is needed only for the tool-generation `complete()` call during `dojo task setup`).
- **`StubAgent`** — deterministic mock for offline / CI runs.

`create_agent_backend(settings.agent.backend)` in [agents/factory.py](src/dojo/agents/factory.py) dispatches on `"claude"` | `"stub"`.

### Run lifecycle

[agents/orchestrator.py](src/dojo/agents/orchestrator.py):

```
orchestrator.start(prompt, domain_id) →
  load Domain + accumulated knowledge →
  TaskService.assert_ready(domain) →                # frozen + verified gate
  build_system_prompt(run, domain, accumulated_knowledge) →
  collect_all_tools(lab, domain) →
  backend.configure(tools, config) →
  return AgentRun

orchestrator.execute(run) → async iterate backend.execute() → append events to run.events
                          → on terminate: flush_run_knowledge() (LLM extractor → atoms)
                          → emit `run_finalized` sentinel event
orchestrator.stop()       → backend.stop() → STOPPED → still flushes knowledge
```

Events stream to consumers via SSE at `/agent/runs/{id}/events`. The CLI reads the same in-memory `run.events` list directly. Run state is held in `_runs` ([api/routers/agent.py](src/dojo/api/routers/agent.py)) as a write-through cache over `LabEnvironment.run_store` (`LocalRunStore` writes to `.dojo/runs/{id}.json`); `GET /agent/runs/{id}` and the SSE stream fall back to disk on cache miss, so two processes (CLI + server) see each other's runs.

### Tools the agent has

| Tool | Purpose | File |
|---|---|---|
| `run_experiment` | Write `train()` code, framework executes runner that calls frozen `load_data` → `train` → `evaluate`. Records `CodeRun`, ingests artifacts. | [tools/experiments.py](src/dojo/tools/experiments.py) |
| `complete_experiment` / `fail_experiment` | Transition state, log metrics. Rejects metrics outside `expected_metrics`. | [tools/experiments.py](src/dojo/tools/experiments.py) |
| `get_experiment` / `list_experiments` / `compare_experiments` | Read-side. | [tools/experiments.py](src/dojo/tools/experiments.py) |
| `write_knowledge` | Routes through `KnowledgeLinker.produce_knowledge`. Cannot bypass linker. | [tools/knowledge.py](src/dojo/tools/knowledge.py) |
| `search_knowledge` / `list_knowledge` | Read knowledge with optional `domain_id` filter. | [tools/knowledge.py](src/dojo/tools/knowledge.py) |
| `log_metrics` / `log_params` | Write to active `TrackingConnector`. | [tools/tracking.py](src/dojo/tools/tracking.py) |

Built-in Claude tools also allowed: `Bash`, `Read`, `Write`, `Edit`, `WebFetch`. Bash is permitted but the system prompt steers the agent toward `run_experiment` for experiment scripts so artifacts get traced.

### Per-run artifacts

Agent code writes into `DOJO_ARTIFACTS_DIR` (per-experiment, at `.dojo/domains/{id}/runs/{eid}/artifacts/`). After the subprocess exits, [tools/experiments.py](src/dojo/tools/experiments.py) `_ingest_artifacts` walks the dir, saves each file via `lab.artifact_store.save()` under key `experiments/{eid}/artifacts/{relative_path}`, forwards to `lab.tracking.log_artifact()` (no-op for `FileTracker`/`NoopTracker`, real upload for `MlflowTracker`), and records the keys on `CodeRun.artifact_paths`. Storage / tracking failures log a warning and do not fail the run.

---

## Workspaces (BYO pipeline)

A `Workspace` ([core/domain.py](src/dojo/core/domain.py)) is a per-domain pre-configured execution environment. One-time setup happens via `WorkspaceService.setup(domain)` ([runtime/workspace_service.py](src/dojo/runtime/workspace_service.py)), then every agent run reuses it.

Sources: `local` (path on disk), `git` (clone into `.dojo/workspaces/{domain_id}`, optional ref), `empty` (fresh dir).

Setup auto-detects: existing `.venv`/`venv` → reuse; `pyproject.toml` → `uv sync` (preferred) or `pip install -e .`; `requirements.txt` → venv + `pip install -r`; else system Python.

The agent's `cwd` and `python_path` are pinned to the workspace at run-start. The system prompt explicitly tells the agent **not** to install packages or set up environments — they're already there.

**Prefer modifying the workspace abstraction over building parallel integration mechanisms.**

---

## Config

YAML at `.dojo/config.yaml`, overridable via env vars. See [config/settings.py](src/dojo/config/settings.py).

| Group | Key fields | Defaults |
|---|---|---|
| `api` | `host`, `port` | `127.0.0.1:8000` |
| `storage` | `base_dir` | `.dojo` |
| `tracking` | `backend`, `enabled`, `mlflow_tracking_uri`, `mlflow_experiment_name`, `mlflow_artifact_location` | `file`, `true` |
| `memory` | `backend`, `search_limit` | `local`, `10` |
| `frontend` | `enabled`, `port` | `true`, `5173` |
| `sandbox` | `timeout`, `verification_timeout` | — |
| `agent` | `backend`, `max_turns`, `max_budget_usd`, `permission_mode`, `cwd`, `tool_generation_model` | `claude`, `50`, `None`, `acceptEdits`, `None` |

### Pydantic-settings env-var gotcha

Prefix is `DOJO_` (single trailing underscore). Nested fields use `__` (double underscore):

```
✅ DOJO_AGENT__BACKEND=stub
✅ DOJO_TRACKING__BACKEND=mlflow
❌ DOJO__AGENT__BACKEND=stub      ← silently ignored
```

Pydantic-settings **silently ignores misspelled env vars** — defaults kick in with no warning. Always double-check the underscore count if overrides aren't sticking.

---

## Testing

```bash
just test                         # all
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
uv run pytest tests/e2e/ -v       # E2E (HTTP lifecycle)
```

`asyncio_mode = "auto"` in [pyproject.toml](pyproject.toml) — all `async def test_*` are auto-detected. `pythonpath = ["src"]`.

**Fixtures** ([tests/conftest.py](tests/conftest.py)): `settings(tmp_dir)` builds a `Settings` pointing at a temp dir; `lab(settings)` builds a real `LabEnvironment` with real adapters; `client(settings)` returns an httpx `AsyncClient` on the ASGI app. **No mocking** — everything runs against real adapters in tmp dirs. Match this pattern when adding tests.

---

## Recipes

### Adding a new agent backend

1. Implement `AgentBackend` in `src/dojo/agents/backends/<name>.py` (`configure`, `execute`, `stop`, `complete`, `name`).
2. Add it to dispatch in [agents/factory.py](src/dojo/agents/factory.py).
3. If it needs a different tool format, write an adapter in `tools/adapters/` (mirroring `claude.py`).
4. Tests: stub-style mocks of the SDK, plus an E2E that runs `/agent/run` end-to-end.

### Adding a new agent tool

1. Add a function in `src/dojo/tools/<resource>.py` that returns a `ToolDef`.
2. Wire it into [tools/server.py](src/dojo/tools/server.py) `collect_all_tools`.
3. Update the system prompt in [agents/prompts.py](src/dojo/agents/prompts.py) — **bump the `### Agent prompts` changelog entry on the next release.**

### Adding a new task type

Registry-only change in [core/task.py](src/dojo/core/task.py): new `TaskType` enum value, new `TaskTypeSpec` in `TASK_TYPE_REGISTRY` with `required_tools`, `runner_callsite`, `runner_prelude`, `verifier_fixture_keys`, `generation_prompt_template`, `contract_version`. Runner and verifier are already task-type-agnostic.

### Adding a new storage backend (e.g. Postgres)

1. Create `src/dojo/storage/postgres/` mirroring `local/`.
2. Each adapter implements its ABC from [src/dojo/interfaces/](src/dojo/interfaces/).
3. Add dispatch in [api/deps.py](src/dojo/api/deps.py) — pick which adapter set to instantiate based on `settings.storage.backend`.
4. Extend `StorageSettings` in [config/settings.py](src/dojo/config/settings.py) with connection fields.
5. Unit tests for adapter round-trips + integration test wiring through `LabEnvironment`.

### Adding a tracking backend

Mirror the existing dispatch in `_build_tracking()` in [api/deps.py](src/dojo/api/deps.py). The `TrackingConnector` interface is small (see [interfaces/tracking.py](src/dojo/interfaces/tracking.py)).

### Adding a new API route

1. Create `src/dojo/api/routers/<name>.py` with `APIRouter(prefix=..., tags=...)`.
2. Access lab via `request.app.state.lab: LabEnvironment`.
3. Register in [api/app.py](src/dojo/api/app.py).
4. Add an E2E test in `tests/e2e/`.
5. Frontend hook in `frontend/src/hooks/` if needed.

---

## Conventions

- **IDs:** ULIDs via `dojo.utils.ids.generate_id()`. Never `uuid4`.
- **Async everywhere:** all interface methods, all service methods, all router handlers.
- **Domain models:** `@dataclass`. **API request/response:** `pydantic.BaseModel`.
- **No global state:** everything flows through `LabEnvironment` injected at app startup.
- **Logging:** `structlog` via `from dojo.utils.logging import get_logger`. Structured kwargs (`logger.info("event_name", key=value)`), not f-strings.
- **Linting:** Ruff (`py313`, line-length 100, rules `E,F,W,I,UP,B,SIM,RUF`). Run `just format` before committing.
- **Errors:** raise specific exceptions (`InvalidTransitionError`, `TaskNotReadyError`, `ValueError`) at boundaries; let them bubble to the router which translates to HTTP.
- **No silent fallbacks:** if a config is wrong, fail loud at `build_lab()` time. Don't paper over with try/except.
- **Single-tenant assumption:** writing code that requires a tenant or user id is a smell — push back.

---

## Known issues / nuances

- **`Domain.tools` still exists alongside `domain.task.tools`** — `domain.task.tools` is the source of truth (`collect_all_tools` reads from there when a task is set, with `domain.tools` as a legacy fallback). `Domain.tools` is mirrored on writes for the existing frontend response; the field will be removed in the frontend audit.
- **Frontend not bundled in the PyPI release** — `dojo start` runs the API; UI users still clone the repo and `npm install` separately. Bundling built assets is planned for a later release.
- **`docs/`** — only `MASTER_PLAN.md`, `RELEASING.md`, `NEXT_STEPS.md`, and the `archive/` directory remain. Don't trust archived docs without cross-checking the code.
- **Tool-generation model split** — `dojo task setup` calls `backend.complete()` with `settings.agent.tool_generation_model` (which can require an `ANTHROPIC_API_KEY`); agent runs use the local `claude` CLI auth.
