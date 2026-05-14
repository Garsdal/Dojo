# MASTER_PLAN.md — Dojo.ml Vision & Architecture

> **Dojo.ml** — An autonomous ML research framework. Define a research domain with a frozen data + evaluation contract, and an agent runs experiments against it overnight, accumulating compressed knowledge of what actually works.

---

## 1. Vision

### What we're building

Dojo runs **controlled, reproducible ML experiments on your existing pipelines and builds a memory of what actually works.** A human defines a *domain* — a research area pointing at real data with a fixed evaluation contract — and an autonomous agent iterates on training code inside that contract, learning across many experiments.

The structural insight: the framework, not the agent, owns evaluation. Agents are creative but unreliable; their reports of their own performance are not. So we draw a hard line:

```
load_data.py      → frozen Python module, function `load_data()`     (framework calls it)
evaluate.py       → frozen Python module, function `evaluate(y_pred)` (framework calls it)
train.py          → run_experiment_code per experiment               (mutable — agent writes)
predictions.json  → train.py's only output: a list of y_pred         (agent → framework hand-off)
PROGRAM.md        → Domain.prompt (steering prompt)                  (human edits between runs)
```

This is the [Karpathy autoresearch](https://github.com/karpathy/autoresearch) split — `prepare.py` is fixed, `train.py` is fair game, `program.md` is what the human iterates on. We're generalising that pattern beyond LLM training so it works for any well-defined ML problem class — starting with regression.

`load_data.py` and `evaluate.py` are AI-generated at setup time, then human-reviewed, then frozen by copying them into `.dojo/domains/{id}/tools/`. At experiment time the agent writes a `train.py` that imports `load_data`, trains a model, and saves `y_pred` to `predictions.json`. The framework — never the agent — calls `evaluate(y_pred)` to compute the recorded metric. The agent's `train.py` is a normal Python script: no wrapping, no auto-prologue, no fixture injection.

### Why a framework, not a script

Anyone can wire Claude up to a Jupyter notebook for an evening. What we're building has to:

1. **Make cheating structurally impossible.** Agent metrics must be trustworthy without auditing every code block.
2. **Compose across runs.** Knowledge from past experiments shapes future ones, on the same problem and across problems.
3. **Stay reproducible.** Every experiment is a tracked, replayable artifact: code, config, data version, metric.
4. **Be portable.** Point at any local repo or git URL via the `Workspace` abstraction; don't make users rewrite their pipeline to use Dojo.

### Three-level hierarchy

```
Domain (human-defined)
  ├── Workspace                   — pre-configured execution env (local repo / git url / empty)
  ├── Task (typed, currently only RegressionTask)
  │     ├── load_data.py module   — frozen function `load_data()`, copied to canonical path at freeze
  │     └── evaluate.py module    — frozen function `evaluate(y_pred)`, copied to canonical path at freeze
  └── Experiments                 — agent-created, many per domain
        └── Knowledge atoms       — produced, linked across experiments via KnowledgeLinker
```

The Task pins the contract; the agent operates inside it. The frozen modules live in `<workspace>/` (visible, editable until freeze) and `.dojo/domains/{id}/tools/` (canonical, read-first via `PYTHONPATH`). Knowledge is the framework's long-term output.

---

## 2. Positioning & strategic stance

This stance is **load-bearing** for everything that follows. Read before proposing new features.

### Open-core, already open

Dojo is open source. This repo is the **execution layer** and stays open. The hard parts that we'll close once they exist:

| Layer | Status | Plan |
|---|---|---|
| Domain abstraction, experiment loop, knowledge atoms, agent orchestration core | Open (this repo) | Stays open |
| Local adapters (storage, sandbox, compute, MLflow tracker) | Open (this repo) | Stays open |
| Sandboxed cloud execution (Modal-style) | Not built | Closed when built |
| Hosted memory layer (managed knowledge atom store, cross-domain retrieval) | Not built | Closed when built |
| Agent reliability layer (retries, guardrails, eval correctness, anti-cheating enforcement) | Partially built (anti-cheating) | The product/managed pieces stay closed |

### Single-tenant, local-first

There is one user, one machine, one `.dojo/` directory of JSON state. That's the assumption baked into the storage adapters and it's a feature, not a limitation:

- No multi-tenant MLflow operations problem
- No tenant isolation testing matrix
- No compliance surface area
- Data stays on the user's machine

The first time we genuinely need multi-tenancy (e.g., a hosted offering after enough validation), we add a Postgres adapter behind the existing `ExperimentStore` / `DomainStore` interfaces. Until then, **don't add tenant ids, RBAC, or SaaS-shaped APIs**.

### Bring your own Python pipeline

The integration surface is the [`Workspace`](src/dojo/core/domain.py) abstraction. Point Dojo at:

- A local path on disk, OR
- A git URL (cloned to `.dojo/workspaces/{domain_id}`), OR
- An empty dir Dojo creates fresh

Workspace setup auto-detects `pyproject.toml` (uses `uv sync`), `requirements.txt` (creates venv + pip install), or an existing `.venv`. The agent's `cwd` and `python_path` are pinned to the workspace at run-start. **Do not** build parallel adapters for Kubeflow, Airflow, Prefect, etc. — make the workspace abstraction work harder.

### MLflow as a bridge, not a platform

`MlflowTracker` sits **on top of** whatever MLflow the user already has. We never own or operate MLflow infrastructure. Single-user-per-MLflow-instance keeps it simple. If a user prefers no tracking, `FileTracker` writes JSON to `.dojo/tracking/`.

### CLI-first; HTTP and frontend are peers

The canonical surface is the terminal. A user gets from "empty directory" to "agent running" with two commands:

```bash
dojo init     # interactive (or fully flag-driven): config + workspace + task + AI tool gen + verify + freeze
dojo run      # agent runs against the current domain; events stream to terminal
```

In between, the human edits `PROGRAM.md` — Karpathy-style: a Markdown file containing the steering prompt. Iteration on `PROGRAM.md` between runs is the primary dial the user has.

CLI commands call `LabEnvironment` services directly (the same ones the FastAPI routers call) — no HTTP round-trip from the CLI. A running **Dojo** server is required *only* for the web frontend or external HTTP clients, never for the CLI itself. This means:

- The framework is fully usable in CI, scripts, headless boxes, and SSH sessions.
- The frontend (and any future SaaS) is built **on top of** the same runtime layer the CLI uses, not the other way round.
- No path is privileged — a feature must work via the CLI before we expose it to the API or UI.

**External infrastructure the user still provides** (none of which is "the Dojo server"):

| Dependency | When | Notes |
|---|---|---|
| `claude` CLI | Always (for non-stub agent runs) | Installed once by the user; inherits their auth. `ClaudeSDKClient` shells out to it. |
| MLflow tracking server | Only if `tracking.backend = mlflow` | The user's MLflow, never ours. `tracking.backend = file` removes this dependency. |
| `uv` / `python -m venv` | Once per workspace | Used by `WorkspaceService.setup()` to install the workspace's deps. |

**Honest practical caveats** of the in-process model:

- `dojo run` blocks the terminal until the run finishes. For long runs, fall back to standard Unix tooling (`nohup`, `tmux`) — we deliberately don't build a Dojo daemon.
- Persisted state (`.dojo/`) is the single source of truth. Any second process — another CLI invocation, the optional HTTP server, a `dojo runs show` from a different terminal — must read run state from disk, not from in-memory caches. This is a hard rule (see §8 cleanup notes and Phase 1 of [NEXT_STEPS.md](NEXT_STEPS.md)).
- Concurrent writes to `.dojo/` JSON files are not protected by file locks. Single-user, one-active-run-per-machine is fine; many-concurrent-agents-per-machine is out of scope until we have a shared backend.

### Out of scope (for now)

These are not "bad ideas" — they are deliberately not on the roadmap until prior steps validate the framework:

- Multi-tenancy / SaaS hosting
- Cloud sandbox / Modal / Supabase / hosted compute
- Enterprise integrations beyond MLflow (Kubeflow, Airflow, Slack, JIRA, etc.)
- Multiple task types beyond `RegressionTask` (classification, forecasting, generative)
- Multiple Tasks per Domain
- Frontend feature work beyond keeping the existing pages alive

---

## 3. Core abstractions

### 3.1 Domain

A research area, human-defined. Holds the steering prompt, accumulated knowledge, exactly one Task, and one Workspace.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` (ULID) | |
| `name`, `description`, `prompt` | `str` | Steering prompt is the equivalent of `program.md` — human iterates on it |
| `status` | `DomainStatus` | `DRAFT → ACTIVE → PAUSED → COMPLETED → ARCHIVED` |
| `task` | `Task | None` | Exactly one (None during DRAFT before task is created) |
| `workspace` | `Workspace | None` | The execution env |
| `experiment_ids` | `list[str]` | Denormalized for fast queries |
| `metadata`, `config` | `dict` | Extensible |
| `created_at`, `updated_at` | `datetime` | |

**Change from current code:** the `tools: list[DomainTool]` field on `Domain` moves onto `Task.tools`. A Domain itself holds no tools — only its Task does.

### 3.2 Task (the contract)

The Task is the framework's anti-cheating mechanism. It defines what the agent is allowed to change and what is frozen.

```python
class TaskType(StrEnum):
    REGRESSION = "regression"
    # CLASSIFICATION, FORECASTING, GENERATIVE, CUSTOM are future — do not implement preemptively

class Direction(StrEnum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"

@dataclass
class Task:
    id: str = field(default_factory=generate_id)
    type: TaskType = TaskType.REGRESSION
    name: str = ""
    description: str = ""
    primary_metric: str = "rmse"        # filled from registry default; user can override
    direction: Direction = Direction.MINIMIZE
    tools: list[DomainTool] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)  # task-specific (data path, target column, test split, etc.)
    frozen: bool = False                # once True, tools cannot be modified for any subsequent run
    created_at: datetime = ...
    updated_at: datetime = ...
```

#### Per-type registry

```python
@dataclass
class ToolContract:
    """Describes a frozen tool — a Python module + function the framework calls.

    The verifier imports the module and calls the function with synthetic inputs;
    `params_schema` and `returns_schema` describe the function signature, not a
    stdout-JSON shape.
    """
    name: str                         # logical tool name, e.g. "load_data"
    module_filename: str              # file on disk, e.g. "load_data.py"
    entrypoint: str                   # function to call, e.g. "load_data"
    description: str
    params_schema: dict[str, str]     # function parameters
    returns_schema: dict[str, str]    # function return value

@dataclass
class TaskTypeSpec:
    default_metric: str
    default_direction: Direction
    required_tools: list[ToolContract]    # modules that must exist + verify before freeze
    generation_prompt_template: str       # input to AI tool generation
    config_schema: dict                   # JSON schema for Task.config (e.g., target_column, test_split)

TASK_TYPE_REGISTRY: dict[TaskType, TaskTypeSpec] = {
    TaskType.REGRESSION: TaskTypeSpec(
        default_metric="rmse",
        default_direction=Direction.MINIMIZE,
        required_tools=[
            ToolContract(
                name="load_data",
                module_filename="load_data.py",
                entrypoint="load_data",
                description="Load and split the dataset",
                params_schema={},
                returns_schema={"X_train": "array", "X_test": "array",
                                "y_train": "array", "y_test": "array"},
            ),
            ToolContract(
                name="evaluate",
                module_filename="evaluate.py",
                entrypoint="evaluate",
                description="Evaluate predictions against y_test",
                params_schema={"y_pred": "array"},
                returns_schema={"rmse": "float", "r2": "float", "mae": "float"},
            ),
        ],
        generation_prompt_template=...,
        config_schema={"target_column": "str", "test_split_ratio": "float", "data_path": "str"},
    ),
}
```

#### What "frozen" means concretely

- `Task.frozen = False`: tool files live in the workspace, the user (or AI regeneration) can edit them. Agent runs are blocked.
- User runs `dojo task freeze` (or `POST /domains/{id}/task/freeze`) → framework copies each `module_filename` from the workspace into `.dojo/domains/{id}/tools/`, computes SHA-256 hashes, stores them on `task.config["tool_hashes"]`, sets `frozen = True`.
- Once frozen, every subsequent agent run resolves `from load_data import load_data` and `from evaluate import evaluate` from the canonical dir (it sits first on `PYTHONPATH`). The agent overwriting `<workspace>/evaluate.py` is a no-op for recorded metrics. Editing a frozen task requires explicitly unfreezing (which invalidates prior experiment comparisons — surface this in UI later).

### 3.3 Workspace (existing, no changes)

[`src/dojo/core/domain.py:38`](src/dojo/core/domain.py#L38). Already supports `local` / `git` / `empty` source and auto-detects `.venv` / `pyproject.toml` / `requirements.txt`. Setup happens once via `WorkspaceService.setup(domain)`; the agent reuses the prepared env on every run.

### 3.4 Experiment (minor changes)

[`src/dojo/core/experiment.py`](src/dojo/core/experiment.py). Stays scoped to a Domain (and therefore implicitly to its Task). `CodeRun` already records each `run_experiment_code` call. The state machine is unchanged: `PENDING → RUNNING → COMPLETED | FAILED → ARCHIVED`.

The training code the agent passes to `run_experiment_code` is what mirrors Karpathy's `train.py`. Per-run, that code is allowed to be anything; per-domain, what it can *do* is constrained by the Task tools available to it.

### 3.5 Knowledge atoms + linking

Atoms are immutable; links are `CREATED_BY` and `RELATED_TO`. The first-pass `KeywordKnowledgeLinker` was deliberately minimal; with the task contract + experiment lifecycle now producing atoms at a useful rate, the storage layer is being made more durable (issue #5):

- **File-per-atom storage.** Atoms live at `.dojo/knowledge/{domain_id}/{atom_id}.md` (YAML frontmatter + body), not in a single `atoms.json`. Grep-friendly and human-readable on disk; the abstract data model maps cleanly to a Postgres row + jsonb when we add a remote store, so the local layout doesn't lock us in.
- **`LLMKnowledgeLinker`** is a selectable alternative behind the same `KnowledgeLinker` interface. It only changes how `RELATED_TO` links are picked (LLM call vs. keyword overlap); `KeywordKnowledgeLinker` stays the default.

**Search stays text-only over `claim` / `context` / `action`, regardless of which linker created the atoms.** The two linkers produce identical atoms, searched identically — they only differ in which `RELATED_TO` edges exist on disk. Following `RELATED_TO` to expand search results, embedding/vector retrieval, and faceted/tag-based queries are explicit non-goals until the simple path proves insufficient (see §13).

---

## 4. The anti-cheating boundary, in practice

This is the section that justifies the whole design. If this is wrong, nothing else matters.

### The four-tool-call experiment loop

The agent runs every experiment as a four-call sequence. Each call does one thing:

| # | Tool | Owner | Side effects |
|---|---|---|---|
| 1 | `create_experiment(domain_id, hypothesis)` | Agent | Returns `experiment_id`. State PENDING → RUNNING. |
| 2 | `run_experiment_code(experiment_id, train_code)` | Agent → framework | Saves `train_code` as `.dojo/artifacts/experiments/{id}/_dojo_train_<N>.py`. Runs it as a normal Python script in the workspace with canonical-tools-first `PYTHONPATH`. Returns `{stdout, stderr, exit_code}`. **No metric handling.** |
| 3 | `evaluate_experiment(experiment_id)` | Framework | Reads `<workspace>/predictions.json`. Imports `evaluate` from the canonical path. Calls `evaluate(y_pred)`. Records metrics. State RUNNING → COMPLETED. Returns the metric dict. |
| 4 | `write_knowledge(experiment_id, claim, ...)` | Agent | Records the learning. |

The agent never:
- handles the `y_pred` array as a tool-call parameter;
- imports `evaluate` directly;
- decides what value gets recorded as the metric.

The framework owns evaluation — completely. The agent's only contribution to the metric is `y_pred` (a list it writes to `predictions.json`). If the agent's `y_pred` is good, the metric is good. If `y_pred` is bad, the metric reflects bad predictions evaluated honestly.

### What the agent can do during a run

- Write training code and submit it via `run_experiment_code` — the only mutable surface.
- Call `log_metrics(metrics)` for hyperparameter tracking and aux measurements (NOT the primary metric — that comes from `evaluate_experiment`).
- Call `write_knowledge(...)` to record findings.

### What the agent cannot do

- Modify `load_data.py` or `evaluate.py` in a way that affects recorded metrics. Workspace edits to the modules are shadowed by canonical at import time.
- Pass a metric dict to the framework. There is no `complete_experiment(metrics=...)` exposed to the agent — `evaluate_experiment` is the only path metrics enter the system.
- Skip `load_data`. If the agent's train.py recomputes the split inline, its `y_pred` is ordered against a different test set than the canonical `evaluate` will compare against, so the metric will be obviously bad — self-correcting.
- Register new tools at runtime. The agent's MCP surface is fixed at run-start.

### Enforcement points

1. **Canonical tool path.** `freeze` copies `<workspace>/load_data.py` and `<workspace>/evaluate.py` to `.dojo/domains/{id}/tools/`. SHA-256 hashes recorded on `task.config["tool_hashes"]`. `assert_ready` verifies hashes match before allowing a run — defence-in-depth against tampering with `.dojo/`.
2. **`PYTHONPATH` ordering.** Every sandbox subprocess sets `PYTHONPATH = <canonical>:<workspace>`. `from evaluate import evaluate` always resolves canonical first.
3. **Framework-only call site.** `evaluate` is only ever called from inside the `evaluate_experiment` MCP handler, in a subprocess the framework controls. The agent has no MCP tool for `evaluate`.
4. **Restricted MCP surface.** `collect_all_tools(lab, domain)` returns only platform tools — `create_experiment`, `run_experiment_code`, `evaluate_experiment`, `fail_experiment`, `get_experiment`, `list_experiments`, `compare_experiments`, `log_metrics`, `log_params`, `write_knowledge`, `search_knowledge`, `list_knowledge`. No per-domain tool registration.
5. **`predictions.json` is the only hand-off.** The agent's train.py communicates with the framework solely by writing this file. No stdout markers, no env var protocols, no shared state.

### Soft enforcement (good-faith, not airtight)

The `Bash`, `Read`, and `Write` Claude built-in tools are still allowed for productivity — the agent can read files, install packages, do quick checks. A truly adversarial agent could in principle bypass the contract by:
- writing a fake `predictions.json` directly without training a model (yields whatever metric that fake represents — auditable in `_dojo_train_<N>.py` artifact);
- spawning a subprocess that ignores the canonical `PYTHONPATH` and uses its own evaluator (would still need to write `predictions.json`, and the recorded metric still comes from canonical evaluate).

We accept these because:

- Our agents are not adversarial; they're constrained-but-cooperative LLM agents.
- The structural separation (`evaluate` is framework-called, `predictions.json` is the only hand-off, canonical `PYTHONPATH` shadows the workspace) means the recorded metric is always `canonical_evaluate(predictions.json)`. The agent cannot directly write to that variable.
- Every saved train script is auditable. A reviewer reading `.dojo/artifacts/experiments/{id}/_dojo_train_*.py` can spot fake-predictions cheating immediately.
- Hard enforcement (sandboxed file ACLs, network isolation, signed artifacts) belongs in the sandboxed cloud execution layer, which is the **closed** part of the open-core split.

So: **structural anti-cheating now, hardened anti-cheating in the closed cloud layer later.**

---

## 5. AI-generated tool flow (and why it's load-bearing)

The magic of Dojo is that a user describes their data and evaluation in natural language, and the framework generates working tools. Without this, every domain requires hand-written Python — and we're back to "wire Claude to a Jupyter notebook."

### Generation flow

```
1. User creates Domain + Task (type=REGRESSION, points at workspace)
   └── User edits PROGRAM.md to describe the dataset, target, and success criteria

2. Framework calls AI tool generation (`dojo task generate`)
   └── Build a single prompt that includes:
         - the registry's regression generation_prompt_template
         - PROGRAM.md content (the user's natural-language spec, source of truth)
         - any structured hints the user passed (data_path, target_column — optional)
         - the workspace tree summary (built by WorkspaceScanner)
   └── Call the LLM with `--model claude-sonnet-4-6`
   └── Parse output: a JSON array of `{name, filename, entrypoint, code}` per tool

3. Framework writes generated modules to the workspace
   └── <workspace>/load_data.py
   └── <workspace>/evaluate.py
   └── User can read these in their editor before approving

4. Framework verifies each generated module
   └── For each ToolContract: importlib-import the module, call entrypoint with synthetic inputs
   └── For regression: load_data() returns 4-tuple → use y_test as y_pred fixture for evaluate()
   └── Validate function returns against ToolContract.returns_schema
   └── Record VerificationResult on the DomainTool

5. User reviews and approves
   └── Reads <workspace>/load_data.py, <workspace>/evaluate.py
   └── Sees verification status from `dojo task show` (✓ / ✗ per tool)
   └── Approves → `dojo task freeze`

6. `freeze` makes it canonical
   └── Copies <workspace>/load_data.py to .dojo/domains/{id}/tools/load_data.py
   └── Copies <workspace>/evaluate.py to .dojo/domains/{id}/tools/evaluate.py
   └── Records SHA-256 hashes on Task.config["tool_hashes"]
   └── Sets task.frozen = True

7. Task is now frozen — agent runs are unblocked
```

### Verification step

The verifier ([`runtime/tool_verifier.py`](src/dojo/runtime/tool_verifier.py)) imports the generated module via `importlib` (in a subprocess for isolation, so verifier failures don't pollute the dojo process). It:

- Imports the module from its file path.
- Looks up the function named by `ToolContract.entrypoint`.
- Calls it with fixtures derived from `ToolContract.params_schema`. For regression's `evaluate`, the fixture for `y_pred` is `y_test` from a successful `load_data()` call (perfect predictions; should yield rmse≈0, r2≈1).
- Validates the return value against `ToolContract.returns_schema`.
- Records `{"verified": True/False, "errors": [...], "sample_output": {...}}` on the `DomainTool`.

`TaskService.freeze` rejects when any required tool's verification is missing or failed.

### Cleanup: Claude CLI auth

Both `dojo run` (agent runs) and `dojo task generate` (one-shot tool generation) use `backend.complete()` which shells out to `claude -p --model <id> <prompt>`. Same auth path as agent runs — no `ANTHROPIC_API_KEY` needed, the `claude` CLI inherits the user's local Claude Code login. The default model for tool generation is configurable via `agent.tool_generation_model` (defaults to `claude-sonnet-4-6`).

---

## 6. Architecture (hexagonal, preserved)

The ports & adapters layout stays. The new pieces fit cleanly into existing layers.

```
┌──────────────────────────────────────────────────────────────┐
│ Frontend (de-prioritized)                                     │
│ Domain overview · Domain detail · Agent chat                  │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP / SSE
┌──────────────────────────────▼───────────────────────────────┐
│ API (FastAPI)                                                 │
│ /domains  /tasks  /experiments  /knowledge  /agent  /tracking│
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ Runtime services                                              │
│ DomainService · TaskService (NEW) · ExperimentService         │
│ WorkspaceService · KnowledgeLinker · ToolGenerator (existing) │
│ ToolVerifier (NEW) · AgentOrchestrator                        │
│                LabEnvironment (DI dataclass)                  │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ Interfaces (ABCs)                                             │
│ DomainStore · ExperimentStore · MemoryStore · TrackingConnector│
│ KnowledgeLinkStore · KnowledgeLinker · Sandbox · AgentBackend │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ Adapters                                                      │
│ Local (JSON) · MLflow · File tracker · Local + Docker sandbox │
│ · Claude / Stub agent backends                                │
└──────────────────────────────────────────────────────────────┘
```

### What changes

| Layer | Component | Change |
|---|---|---|
| `core/` | `Task`, `TaskType`, `Direction`, `ToolContract`, `TaskTypeSpec`, `TASK_TYPE_REGISTRY` | DONE — `core/task.py`. Phase 4 expands `ToolContract` with `module_filename` + `entrypoint`. |
| `core/` | `Domain` | DONE — `task: Task | None` added; `program_path: str | None` added. Phase 4 drops `Domain.tools` field once frontend response migrated. |
| `core/` | `DomainTool` | Phase 4 adds `module_filename: str` and `entrypoint: str`. Drops `executable: bool` and `parameters: dict` (stdout-JSON-era fields). |
| `runtime/` | `TaskService` | DONE — Phase 4 adds canonical-path copy in `freeze` (copy `<workspace>/<filename>` to `.dojo/domains/{id}/tools/<filename>` + SHA-256 hash). |
| `runtime/` | `ToolVerifier` | Phase 4 rewrites — drops script execution, uses `importlib` in a subprocess to import + call the module's function. |
| `runtime/` | `DomainService` | DONE — no longer manages tools directly. |
| `runtime/` | `program_loader.py` | DONE — PROGRAM.md resolution + load + write. |
| `tools/` | `tool_generation.py` | Phase 4 updates output format: AI emits `{name, filename, entrypoint, code}` per tool; `dicts_to_domain_tools` populates the new `DomainTool` fields. |
| `tools/` | `domain_tools.py` | Phase 4 removes — tools are no longer agent-callable as MCP tools. |
| `tools/` | `experiments.py` | Phase 4 adds `evaluate_experiment` MCP tool (the only path metrics enter the system). `run_experiment_code` stops extracting metrics — just runs train.py and returns `{stdout, stderr, exit_code}`. `complete_experiment` becomes internal. |
| `tools/` | `server.py` `collect_all_tools` | Phase 4 drops the per-domain `create_domain_tools(...)` call — agent's MCP surface is platform tools only. |
| `agents/` | `prompts.py` | DONE (3b) and Phase 4 rewrites `_build_task_section` around the four-tool-call sequence. Drops references to agent calling `evaluate` or `complete_experiment`. |
| `agents/` | `orchestrator.py` | DONE — blocks run start if `domain.task is None`, `frozen is False`, or any required tool unverified. |
| `api/` | `routers/domains.py` | DONE — tool generation produces verified-but-unfrozen tools; freeze gate enforces verification. |
| `api/` | `routers/agent.py` | DONE — explicit 422 with `{kind: "task_not_ready"}` if domain has no frozen task. |
| `storage/` | `local/domain.py` | DONE — Domain JSON serialisation includes nested Task with verification round-trip. |

### What stays the same

`Workspace`, `WorkspaceService`, `WorkspaceScanner`, `ExperimentService`, `KnowledgeLinker` (keyword-overlap), `KnowledgeLink`, all `TrackingConnector` adapters, all `Sandbox` adapters, all `MemoryStore` adapters, the SSE event mechanism, the entire ULID + structlog + ruff convention layer.

---

## 7. End-to-end lifecycle

The mental model for what a Dojo session looks like.

```
1. Human creates a Domain
   ├── `dojo init --name <X> --task-type regression`
   ├── Names it, configures workspace (local / git / empty) → WorkspaceService.setup()
   └── Framework scaffolds <workspace>/PROGRAM.md from a template

2. Human edits PROGRAM.md
   ├── Describes the dataset (sklearn loader / local CSV / URL — natural language)
   ├── Describes the target and what success looks like
   └── This is the source of truth for tool generation

3. Framework generates tools (`dojo task setup` = generate + verify + freeze)
   ├── AI reads PROGRAM.md, emits load_data.py + evaluate.py to <workspace>/
   ├── ToolVerifier importlib-imports each module, calls the entrypoint, validates returns
   ├── Human reviews <workspace>/load_data.py and <workspace>/evaluate.py in their editor
   └── `dojo task freeze` copies modules to .dojo/domains/{id}/tools/, hashes them,
                          sets task.frozen = True

4. Human starts an agent run (`dojo run`)
   ├── Domain has a frozen task — orchestrator allows the run
   ├── System prompt frames the contract: agent owns train.py, framework owns load_data + evaluate
   └── Agent enters research loop:

   5. Agent plans an experiment
      ├── Searches accumulated knowledge for the domain
      ├── Forms a hypothesis ("baseline linear regression")
      └── create_experiment(domain_id, hypothesis) → returns experiment_id, state RUNNING

   6. Agent executes (4 MCP calls per experiment)
      ├── run_experiment_code(experiment_id, train_code)
      │     train_code is a normal Python script:
      │       from load_data import load_data
      │       X_train, X_test, y_train, y_test = load_data()
      │       model = LinearRegression().fit(X_train, y_train)
      │       y_pred = model.predict(X_test).tolist()
      │       json.dump(y_pred, open("predictions.json", "w"))
      │     Framework saves it as _dojo_train_<N>.py, runs it, returns stdout/stderr.
      │     PYTHONPATH = canonical_tools_dir : workspace, so `from load_data import ...`
      │     resolves the canonical version (workspace overwrites are shadowed).
      ├── evaluate_experiment(experiment_id)
      │     Framework reads <workspace>/predictions.json, imports canonical evaluate,
      │     calls evaluate(y_pred), gets {"rmse": 0.72, "r2": 0.61, "mae": 0.53},
      │     records on experiment.result.metrics, transitions to COMPLETED.
      │     Returns the metric dict to the agent.
      └── (optional) log_metrics for hyperparameters / aux measurements

   7. Agent records knowledge
      └── write_knowledge(context, claim, action, confidence, evidence_ids=[experiment_id])
            → KnowledgeLinker creates new atom + RELATED_TO links to similar prior atoms

   8. Agent loops back to step 5 — uses the new knowledge to plan the next experiment
      └── Stops when max_turns reached, max_budget_usd reached, or human stops

9. Human reviews
   ├── `dojo runs show <id>` for events, metrics, cost
   ├── Metric evolution across experiments in the domain (frontend or HTTP)
   ├── Knowledge atoms — what was learned
   ├── Iterates on PROGRAM.md
   └── Starts another run; the new PROGRAM.md takes effect at run start
```

---

## 8. State the codebase needs to be in to ship this

### Cleanup before / during the rewrite

These are pre-existing cruft items that this rewrite touches anyway. Most are small.

1. **In-memory agent runs** ([api/routers/agent.py:19](src/dojo/api/routers/agent.py#L19)) — the `_runs` dict still holds run state. Recent commit `95faee5` started persisting runs but the in-memory store hasn't been reconciled. **Disk must be the single source of truth** — without that, a CLI-started run is invisible to a separately-running HTTP server, and vice versa, breaking the "CLI and server are peers" invariant. The fix is a Phase 1 prerequisite, not Phase 0 cleanup.
2. **Stale `AGENTS.md`** — predates Domains, Workspaces, Claude backend. Either rewrite to point at [CLAUDE.md](CLAUDE.md) or delete.
3. **Legacy `task_id` references in frontend** ([frontend/src/hooks/use-tasks.ts](frontend/src/hooks/use-tasks.ts), old pages) — drop them; the backend `Task` model is gone.
4. **Stale plan docs in `docs/`** — many are superseded by this MASTER_PLAN. Audit and delete or archive.
5. **Claude CLI vs Anthropic API split** (covered in §5) — unify auth paths.

### What this plan explicitly does *not* change

- The hexagonal architecture
- Knowledge linking implementation (`KeywordKnowledgeLinker` stays)
- The `Workspace` design and `WorkspaceService.setup()` flow
- Tracking adapters
- The agent backend interface (Claude / Stub)
- The MCP-based tool surface
- The frontend (de-prioritized; it'll continue to work, but isn't part of this plan)

---

## 9. Implementation phases (high level)

The detailed sequenced punch-list lives in [NEXT_STEPS.md](NEXT_STEPS.md). High level:

| Phase | Theme | Outcome |
|---|---|---|
| **0** ✅ | Cleanup | Stale docs / legacy code gone; one Claude auth path; broken legacy `dojo run` reclaimed; lint clean |
| **1** ✅ | Task abstraction + disk-as-source-of-truth | `core/task.py` exists; `Domain` holds a `Task` and a `program_path`; storage round-trips; `RunStore` + `LocalRunStore` persist runs; orchestrator writes through on every status change and every 10 events; agent router reads through on cache miss |
| **2** ✅ | CLI happy path + PROGRAM.md | `dojo init` / `dojo run` flow works in-process; current-domain state file; PROGRAM.md convention; `dojo task` / `dojo runs` / `dojo program` subcommands |
| **3** ✅ | Tool verification + anti-cheating gating (stdout-JSON contract) | `ToolVerifier` runs each generated tool in sandbox; freeze gate enforces verification; orchestrator blocks unfrozen / unverified runs; system prompt frames the contract. *Some mechanics superseded by Phase 4.* |
| **3.5** ✅ | Natural-language happy path (PROGRAM.md as spec) | `dojo init` doesn't demand structured fields; PROGRAM.md is threaded into the generation prompt; `dojo task setup` is a single command |
| **4** | Function-based contract + framework-owned evaluation | Tools become Python modules with named functions; `dojo task freeze` copies them to canonical `.dojo/domains/{id}/tools/`; new `evaluate_experiment` MCP tool is the only path metrics enter the system; agent's MCP surface restricted to platform tools; California housing E2E green |
| **5** | Reconnaissance for what's next | Knowledge linker upgrade decision; wall-clock budget decision; first external user |

Frontend work resumes only after Phase 4 — once the backend contract is solid and the CLI proves the loop, the UI changes are mechanical.

---

## 10. Karpathy autoresearch — explicit mapping

Because this is the design north star, mapping it out keeps decisions consistent.

| Karpathy autoresearch | Dojo equivalent |
|---|---|
| One repo per problem | One Domain |
| `prepare.py` (frozen) — data prep, dataloader, evaluation | Two frozen Python modules at canonical path: `load_data.py` (function `load_data() -> tuple`) and `evaluate.py` (function `evaluate(y_pred) -> dict`). Imports resolve via `PYTHONPATH` rooted at `.dojo/domains/{id}/tools/`. |
| `from prepare import make_dataloader, evaluate_bpb` in `train.py` | `from load_data import load_data` in agent's `_dojo_train_<N>.py`. The framework calls `evaluate` itself — agent never imports it. |
| `train.py` (agent edits) | Code passed to `run_experiment_code` per experiment. Saved as `.dojo/artifacts/experiments/{id}/_dojo_train_<N>.py`. Runs as a normal Python script, no wrapping. |
| `program.md` (human edits) | `PROGRAM.md` file at `<workspace>/PROGRAM.md` (or domain-local fallback), loaded into `Domain.prompt` at run start |
| Fixed 5-min wall-clock budget | `max_turns` / `max_budget_usd` / future wall-clock budget on agent run |
| `val_bpb` metric, lower is better | `Task.primary_metric` + `Task.direction` (per `TaskTypeSpec`) |
| Single GPU, single host | Single-tenant, local sandbox |
| Agent edits one file (`train.py`) | Agent calls one mutable tool (`run_experiment_code`); the script it submits is a normal `train.py` |
| Human iterates on `program.md` between sessions | Human iterates on `PROGRAM.md` between sessions |
| Result: a single metric printed by the script | Result: `evaluate_experiment` reads `predictions.json`, calls canonical `evaluate`, records the metric — agent never handles the metric directly |

A "Karpathy mode" Dojo Domain — once we add `GenerativeTask` later — is just `Domain(workspace=local repo) + Task(type=GENERATIVE, primary_metric="val_bpb", direction=MINIMIZE)`. Same shape, different Task type.

---

## 11. Success criteria

We'll know this design is working when:

1. **One frozen RegressionTask runs end-to-end on a real dataset.** Agent only writes training code; metrics come from the frozen evaluator; results are reproducible run-over-run.
2. **The agent cannot game the score** under good-faith use. If an agent rewrites a metric in its training code, it doesn't show up in `complete_experiment` — only what the frozen `evaluate` returned does.
3. **Knowledge accumulates across runs.** A second run on the same Domain visibly uses findings from the first.
4. **A new user can set up a domain in under 30 minutes.** Workspace + Task + AI-generated tools + freeze + first run.
5. **3 real users (outside Marcus) have run a domain to completion** on their own data — the validation gate before considering the closed cloud layer.

---

## 12. Decisions log

Pinning the calls so they don't get re-litigated. If you disagree with one of these, raise it explicitly — don't drift.

| # | Decision | Why | Date |
|---|---|---|---|
| 1 | One Task per Domain | Avoid bloat; Karpathy's pattern is one repo per task | 2026-05-03 |
| 2 | Only `RegressionTask` for now | Make one work end-to-end before adding more | 2026-05-03 |
| 3 | Typed via enum + registry, not class hierarchy | Fits the rest of the codebase (dataclasses + dispatch tables); JSON round-trips cleanly | 2026-05-03 |
| 4 | Evaluation runs as a frozen tool, not built-in framework code | Regression evaluation is too use-case-specific to hard-code; tool path is consistent and extensible | 2026-05-03 |
| 5 | Open-core, single-tenant, local-first | Validate before SaaS; keep the cheating-prevention story structural-only until cloud sandbox is built | 2026-05-03 |
| 6 | No abstraction names containing "Dojo" | Project may be renamed | 2026-05-03 |
| 7 | Frontend de-prioritized | Solidify the core contract first; UI is mechanical once the backend is right | 2026-05-03 |
| 8 | CLI is the canonical surface; HTTP and frontend are peers | A user must be able to do everything from the terminal alone, in-process, without a running server. Frontend/SaaS sit on top of the same runtime layer the CLI uses. | 2026-05-03 |
| 9 | `PROGRAM.md` is the editable steering prompt | Karpathy-style. Lives in the workspace by default. File content wins over `Domain.prompt` at run start so editing between runs takes effect without DB writes. | 2026-05-03 |
| 10 | Tools are Python modules with named functions, not stdout-JSON scripts | The agent imports them as normal Python; the framework calls them via `importlib`. Drops literal-injection wrapping and stdout markers. Aligns with Karpathy's `from prepare import ...` pattern. | 2026-05-03 |
| 11 | Frozen tools live at `.dojo/domains/{id}/tools/`; sandbox `PYTHONPATH` puts canonical first | Workspace edits to `evaluate.py` are shadowed at import time. SHA-256 hashes recorded on freeze for tamper detection. | 2026-05-03 |
| 12 | Framework owns the experiment loop end-to-end via `evaluate_experiment` | Agent's contribution is `predictions.json`. Framework calls `evaluate(y_pred)` itself; the recorded metric is the canonical evaluator's return. Removes the agent's ability to pass a metric dict to the system. | 2026-05-03 |
| 13 | Four-tool-call experiment loop | `create_experiment` → `run_experiment_code` → `evaluate_experiment` → `write_knowledge`. No `complete_experiment(metrics=...)` exposed to the agent — the state transition is internal to `evaluate_experiment`. | 2026-05-03 |
| 14 | `predictions.json` (workspace-relative) is the only train→framework hand-off | One convention, no env var protocols, no shared state, no stdout markers, no auto-prologue/epilogue wrapping. The agent's train.py runs the same way `python train.py` would on the user's terminal. | 2026-05-03 |

---

## 13. What's *not* in this plan

Deliberately out of scope for this rewrite. We can revisit any of these later, but they should not influence current decisions.

- **Recursive self-improvement / meta-agent.** A meta-agent that proposes hypotheses *for* the agent — interesting, but it sits *above* this layer and doesn't change anything below it.
- **Embedding-based knowledge retrieval.** Keyword overlap is fine for now. `LLMKnowledgeLinker` (issue #5) is an agentic *linker*, not an agentic *retriever* — it picks `RELATED_TO` edges at write time but doesn't change the search path.
- **`RELATED_TO`-graph traversal at query time.** The graph is built and visible on the atom-detail page, but `search_knowledge` returns only direct text matches. Following the graph to expand results is a future change.
- **Tag / faceted retrieval on knowledge atoms.** No `tags` field on atoms today. Add only when we have evidence the simple text path is the bottleneck.
- **Multi-host / distributed compute.** All compute is local until the closed cloud layer.
- **Notebook-style interactive runs.** The unit is an autonomous run, not a REPL session.
- **Generic "task type plugin system".** Tasks are typed via the registry; we add new entries when we need them, not via a plugin mechanism.
