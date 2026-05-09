# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
with the caveat that 0.0.x releases may break the API freely.

`### Agent prompts` is always the first section in a release entry, even when
empty, because prompt and tool-description changes are the highest-stakes
behavioural changes in this codebase. See [docs/RELEASING.md](docs/RELEASING.md)
for the release workflow.

## [Unreleased]

## [v0.0.16] - 2026-05-09

### Agent prompts

(none in this release)

### Added

- **`dojo onboard`** ([src/dojo/cli/onboard.py](src/dojo/cli/onboard.py)) — guided, all-in-one setup that gets a user from zero to runnable in one command. Designed for the canonical "I'm already in my Python project" workflow: `cd path/to/your/python/project && dojo onboard`. The flow walks through config knobs (agent / tracking / linker backends with sensible defaults), domain creation, line-by-line PROGRAM.md / SETUP.md filling, then inline AI tool generation + verification + freeze — leaving the user one command away from `dojo run`. Multi-choice prompts use arrow-key selectors via [questionary](https://github.com/tmbo/questionary) with descriptive labels (e.g. "Use existing" / "Overwrite" / "Abort" instead of `[u/o/a]`); a Rich text-input fallback covers non-TTY contexts so CI / scripted callers still work. Auto-installs missing modules into the workspace venv on `ModuleNotFoundError` (with confirmation), retries verification up to 3 times, and shows a softened heads-up when run from inside the cloned Dojo source tree (proceed-by-default for Dojo developers smoke-testing locally). (#13)
- **`--preset california_housing` flag for `dojo onboard`** — for users without an existing project who want to see Dojo work end-to-end on a canned sklearn dataset. Writes a ready-to-run PROGRAM.md / SETUP.md and pre-installs preset deps (`scikit-learn`, `pandas`, `numpy`, `matplotlib`) into a fresh venv. Preset registry lives in [src/dojo/runtime/onboard_helpers.py](src/dojo/runtime/onboard_helpers.py); adding more presets (diabetes, breast_cancer, wine, etc.) is a single dict entry. (#13)
- **`dojo.runtime.setup_orchestrator`** ([src/dojo/runtime/setup_orchestrator.py](src/dojo/runtime/setup_orchestrator.py)) — shared async helpers (`build_workspace_from_arg`, `build_task_config`, `create_domain_with_workspace`, `create_regression_task`) used by both `dojo init` and `dojo onboard` so the two CLI entry points can't drift on domain / workspace / task creation. (#13)

### Changed

- **README restructured around `dojo onboard`** ([README.md](README.md)) — quickstart now leads with `cd <existing project> && dojo onboard && dojo run` (the dominant workflow). The `--preset` path moves to a "Don't have a project yet?" subsection, and `dojo init` is demoted to "scripted setup for CI". Starter PROGRAM.md / SETUP.md examples that used to live in the README are now the source of the `california_housing` preset — single source of truth, no drift. (#13)
- **CLAUDE.md "The product in 2 commands"** — top-level snippet updated to show `dojo onboard` → `dojo run` as the primary path; the four-step `init + edit + task setup + run` flow is preserved as the scripted alternative. (#13)
- **`dojo init`** ([src/dojo/cli/init.py](src/dojo/cli/init.py)) — domain / workspace / task creation extracted into the shared `setup_orchestrator` helpers; behaviour unchanged. The "next steps" footer now points new users at `dojo onboard` for friendlier first-time setup. (#13)

### Removed

- **`LLMSettings` and `Settings.llm`** ([src/dojo/config/settings.py](src/dojo/config/settings.py)) — dead config block (`provider` / `model` / `api_key`) that no code consumed except the `/config` endpoint that echoed it back to the frontend. Provider selection lives on `agent.backend`; the model used for one-shot completions lives on `agent.tool_generation_model` (and `memory.llm_linker_model` for the LLM linker added in v0.0.15). The `/config` response no longer includes `llm`, and newly-written `.dojo/config.yaml` files no longer contain the `llm:` block. The `Settings` model now uses `extra="ignore"` so users with a stale `llm:` block from a pre-v0.0.16 config don't hit a hard `ValidationError` on first run after upgrading — the block is silently dropped. (#14)

## [v0.0.15] - 2026-05-09

### Agent prompts

(none in this release)

### Added

- **`LLMKnowledgeLinker`** ([src/dojo/runtime/llm_linker.py](src/dojo/runtime/llm_linker.py)) — alternative knowledge linker selectable via `memory.linker = "llm"` (default `"keyword"`). One `AgentBackend.complete()` call per `write_knowledge` picks `RELATED_TO` candidates from up to 30 atoms in the same domain selected by **text relevance** (the new atom's `claim` / `context` / `action` is run through the same keyword search the agent's `search_knowledge` tool uses), not by recency — so a relevant atom from atom #47 of 500 is just as findable as yesterday's. Keyword-overlap fallback on any LLM error or malformed JSON. Search semantics are unchanged: text-only over `claim` / `context` / `action`. Reuses the lab's configured `agent.backend` — no separate completion-client abstraction. Fail-loud at `build_lab()` time if the configured backend doesn't override `complete()`. (#5)
- **`MemorySettings.linker` and `MemorySettings.llm_linker_model`** ([src/dojo/config/settings.py](src/dojo/config/settings.py)) — new config knobs. `llm_linker_model` falls back to `agent.tool_generation_model` when unset; only consulted when `linker == "llm"`. (#5)
- **`MemoryStore.list_for_domain(domain_id)`** ([src/dojo/interfaces/memory_store.py](src/dojo/interfaces/memory_store.py)) — first-class scoped listing. `MemoryStore.search(...)` now accepts an optional `domain_id`, replacing the "fetch all in domain, then filter in Python" branch in both the `search_knowledge` MCP tool and the `/knowledge/relevant` HTTP route. (#5)

### Changed

- **Knowledge atom storage migrated to file-per-atom** ([src/dojo/storage/local/memory.py](src/dojo/storage/local/memory.py)) — atoms now live at `.dojo/knowledge/{domain_id}/{atom_id}.md` with YAML frontmatter + body, replacing the single-blob `.dojo/memory/atoms.json`. Atoms with no `domain_id` go to `_global/`. Grep-friendly on disk; the in-process search is a pure-Python keyword scan over the same files. The abstract data model maps cleanly to a future Postgres adapter (one row per atom, jsonb for `evidence_ids`, junction table for links). **Existing pre-1.0 users:** the old `atoms.json` is no longer read; delete `.dojo/memory/` (or back it up) before upgrading. (#5)
- **`KnowledgeAtom` schema cleanup** ([src/dojo/core/knowledge.py](src/dojo/core/knowledge.py)) — added `domain_id` and `source_experiment_id` so each atom is self-describing. Removed `version` and `supersedes` (vestigial — never read or written meaningfully). `evidence_ids` retained. The `/knowledge/*` HTTP responses, MCP tool result shapes, and frontend types are updated to match; the atom card UI no longer displays a `v1` badge or "Updated N times" line, and `useKnowledgeEvolution` becomes a simple cumulative count (atoms are immutable-append). (#5)
- **`docs/MASTER_PLAN.md` §3.5 rewritten + new §13 non-goals** — describes the new direction (file-per-atom, selectable linker) and anchors the constraint that **search remains text-only over `claim`/`context`/`action`** regardless of which linker created the atoms. `RELATED_TO`-graph traversal at query time and tag/faceted retrieval are explicit non-goals until the simple path proves insufficient. (#5)
- **`CLAUDE.md` "Knowledge linking" section** updated to match the new design; same text-search-only constraint anchored as the project-memory reference. (#5)

### Removed

- **`KnowledgeAtom.version` and `KnowledgeAtom.supersedes`** — see *Changed*. (#5)

## [v0.0.14] - 2026-05-09

### Agent prompts

(none in this release)

### Changed

- **README restructured around `uv tool install dojoml`** ([README.md](README.md)) — PyPI install + the 3-command quickstart now lead the page, with all contributor / development content consolidated into a single "Development" section near the bottom that points at [CLAUDE.md](CLAUDE.md). `just`, `npm`, and the cloned-repo path are no longer in the user-facing flow. Adds an explicit note that the React frontend isn't bundled in the PyPI release yet — UI users still need the dev path. (#10)

## [v0.0.13] - 2026-05-09

### Agent prompts

- **Workflow reframed around a baseline-first rhythm** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py)) — the system prompt's workflow section now leads with an explicit "Step 1 — Baseline (always first)" directive: the first `run_experiment` is the simplest plausible end-to-end model with default parameters, no tuning, no feature engineering. Hyperparameter tuning is explicitly demoted to a late move ("a +0.5% from tuning is rarely informative and burns turn budget") rather than being one of several legitimate first steps. The "Don't waste turns on exploration" section is replaced by a softer "Reading the workspace" section that **encourages** reading user code (mirroring conventions in `models/`, `src/`, `notebooks/`) instead of treating Bash/Read/Glob as last resorts. (#8)
- **SETUP.md surfaced to the agent** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py) `_build_domain_section`) — when a domain has `setup_path` set, the prompt now lists it under the Domain section with explicit permission to read it ("safe and frozen — reading it does not change the contract"). This gives the agent the human-language description of the data + evaluation, not just the frozen tools. (#8)
- **Findings ask for verbosity** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py), [src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py)) — the `write_knowledge` guidance now asks for 1-2 sentence claims with the *why*, not one-word headlines. The end-of-run summarizer prompt mirrors this: examples include rationale ("tree models beat linear by ~12% RMSE — the residual plot from exp_01 shows the relationship is non-linear"), and the cap moves from 5 → 7 atoms to give the verbose form room. Single-experiment hyperparameter values are still rejected unless the value itself generalises. (#8)
- **Accumulated knowledge renders context** ([src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py)) — the per-run knowledge index now renders the atom's `context` line indented under each claim, so the agent inherits the situation in which a finding held, not just the headline. (#8)

### Changed

- **`dojo init` startup steps now show spinners** ([src/dojo/cli/init.py](src/dojo/cli/init.py)) — every step (config bootstrap, domain creation, workspace setup, task creation, PROGRAM.md / SETUP.md scaffolds) is wrapped in `console.status(..., spinner="dots")`. The workspace setup step (which can run `uv sync` / `pip install -r` / `git clone` for minutes with stdout piped) is labelled "(can take a few minutes)" and now visibly spins instead of appearing to hang. (#7)

## [v0.0.12] - 2026-05-06

### Agent prompts

(none in this release)

### Added

- **`dojo experiments ls --sort {metric,created}`** ([src/dojo/cli/experiments.py](src/dojo/cli/experiments.py)) — new flag toggles between the existing primary-metric ranking (default, completed experiments only) and a creation-time view (`--sort created`, all experiments, newest first). The created view adds a per-row timestamp column and prints "sorted by created_at (newest first)" instead of the metric/direction header. Empty-state messaging branches on the sort: `created` says "no experiments yet"; `metric` keeps the existing "no completed experiments yet (N failed)" line. The rank header column is renamed `rank` → `#` to make sense in either view.

## [v0.0.11] - 2026-05-06

### Agent prompts

- **System prompt — train signature is `def train(X_train, y_train, X_test, *, artifacts_dir) -> y_pred`** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py)) — every signature reference (role description, `run_experiment` summary, workflow step 3, example `train_code`, the "Contract — exact signatures" code block) and the framework call site (`y_pred = train(...)`, `metrics = evaluate(...)`) now thread `artifacts_dir=artifacts_dir` to both. The agent will write train code that accepts `artifacts_dir` as a keyword-only kwarg, and the documented framework call shape matches the actual runner.
- **System prompt — new `### Artifacts` policy block** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py)) — three explicit bullets: train artifacts are *opportunistic* (model checkpoints, learning curves, feature importances — agent's discretion), evaluate artifacts are *durable* (residuals / calibration produced every run by design), do NOT read prior experiments' artifacts from inside `train()` (each run gets a fresh dir). The example `train_code` shows a commented `joblib.dump(model, artifacts_dir / "model.pkl")` as a copy-pattern. The agent will save model checkpoints when worth comparing across experiments and will not look up prior runs' artifacts.
- **System prompt — "Don't read `load_data`/`evaluate`" rewritten** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py)) — old text said behaviour is "steered by the `## Dataset` / `## Evaluate` sections of PROGRAM.md"; new text says behaviour was "fixed at task-setup time from the user's data + evaluation spec (a separate file you don't see)". The agent will no longer hunt for `## Dataset` / `## Evaluate` headings in PROGRAM.md — those headings have moved to `SETUP.md`, which the agent does not read.
- **`run_experiment` MCP tool description** ([src/dojo/tools/experiments.py](src/dojo/tools/experiments.py)) — train signature in both the tool `description` and the `train_code` parameter description updated to `def train(X_train, y_train, X_test, *, artifacts_dir) -> y_pred`. Evaluate call shape in the description now shows `artifacts_dir=...`. New sentence: "Both train and evaluate share the same `artifacts_dir` — anything written there is archived for the experiment." The schema the agent autonomously reads now matches the runner's actual call.
- **AI tool-generation prompt — SETUP.md is the sole source of truth** ([src/dojo/tools/tool_generation.py](src/dojo/tools/tool_generation.py), [src/dojo/core/task.py](src/dojo/core/task.py)) — `build_task_generation_prompt` parameter renamed `program_md` → `setup_md`; helper renamed `_format_program_md` → `_format_setup_md`. Every `PROGRAM.md` mention inside `_REGRESSION_PROMPT` is now `SETUP.md`. The AI generator that writes `load_data.py` / `evaluate.py` during `dojo task setup` no longer sees PROGRAM.md (now agent-steering only).
- **Regression tool-generation prompt — `evaluate` must save a default diagnostic** ([src/dojo/core/task.py](src/dojo/core/task.py)) — Module 2 evaluate's previously-optional artifacts language replaced: "Should write a default diagnostic into `artifacts_dir` for every run — e.g. a residual scatter plot via matplotlib (3 lines: figure, scatter, savefig). This is the durable per-run record consumers will look at. Skip only if SETUP.md explicitly says nothing should be saved." Effect: AI-generated `evaluate.py` will now save a residual plot every run by default rather than ignoring `artifacts_dir`.

### Added

- **`SETUP.md` — separate task-setup spec file** ([src/dojo/runtime/setup_loader.py](src/dojo/runtime/setup_loader.py)) — new module mirroring `program_loader.py`. `dojo init` now scaffolds both `PROGRAM.md` (agent steering — Goal / Target / Success / Notes) and `SETUP.md` (data + evaluation spec — Dataset / Evaluate). The agent reads PROGRAM.md only; `dojo task setup` reads SETUP.md only. Strict separation keeps tool-generation content out of the agent's runtime context.
- **`train()` receives `artifacts_dir`** ([src/dojo/core/task.py](src/dojo/core/task.py)) — `runner_callsite` now passes `artifacts_dir=Path(os.environ["DOJO_ARTIFACTS_DIR"])` to BOTH `train()` and `evaluate()`. Train artifacts are agent-opportunistic (model checkpoints, training plots); evaluate artifacts are durable per-run (residuals, calibration). Both are picked up by `_ingest_artifacts` and forwarded to `ArtifactStore.save` + `TrackingConnector.log_artifact` (uploads to MLflow when configured). Regression contract version bumped 3 → 4.
- **Phased startup spinner** ([src/dojo/cli/run.py](src/dojo/cli/run.py), [src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py)) — `orchestrator.start()` accepts an optional `progress: Callable[[str], None] | None = None` callback that fires for each of "loading domain context", "checking task readiness", "indexing prior knowledge", "configuring agent backend". The CLI wraps the call in a Rich `console.status` spinner that ticks through these labels, replacing the previous silent ~tens-of-seconds startup pause. The API/SSE path is unchanged (default `progress=None`).
- **`Domain.setup_path` field** ([src/dojo/core/domain.py](src/dojo/core/domain.py), [src/dojo/storage/local/domain.py](src/dojo/storage/local/domain.py)) — persisted across `LocalDomainStore` save/load round-trips so the server and CLI see the SETUP.md location consistently.
- **README §Artifacts section + Migrating from v0.0.10** ([README.md](README.md)) — documents the train-opportunistic / evaluate-durable policy and where artifacts land (`.dojo/artifacts/...` archive plus MLflow when enabled). Migration steps for splitting an existing PROGRAM.md into PROGRAM.md + SETUP.md.

### Changed

- **`PROGRAM.md` template is now steering-only** ([src/dojo/runtime/program_loader.py](src/dojo/runtime/program_loader.py)) — `default_program_template` produces `## Goal / ## Target / ## Success / ## Notes` only; `## Dataset`, `## Evaluate`, `## Contract`, `## Task type` move to `SETUP.md`. The function signature drops the now-unused `task_type` keyword.
- **`dojo task setup` and `POST /domains/{id}/tools/generate` read `SETUP.md`** ([src/dojo/cli/task.py](src/dojo/cli/task.py), [src/dojo/api/routers/domains.py](src/dojo/api/routers/domains.py), [src/dojo/runtime/tool_verifier.py](src/dojo/runtime/tool_verifier.py)) — error hints previously pointing users at "fix PROGRAM.md" for dataset/eval issues now point at SETUP.md.
- **Regression contract bumped to version 4** ([src/dojo/core/task.py](src/dojo/core/task.py)) — frozen v0.0.10 tasks (`contract_version=3`) auto-reject on `assert_ready` with the existing re-verify message. **Action required:** run `dojo task setup` to regenerate any pre-existing frozen task.

### Notes

- 16 commits + 1 follow-up fix; ~2,700 lines added across src/tests/docs; 386 tests passing, ruff clean.
- The PROGRAM.md/SETUP.md split is the headline architectural change — the agent's runtime context is now focused purely on research steering. The `train(..., artifacts_dir)` change is the headline UX improvement — agent-written artifacts (e.g. `model.pkl`) are now archived alongside evaluate's diagnostics.

## [v0.0.10] - 2026-05-05

### Agent prompts

- **End-of-run knowledge flush prompt rewritten** ([src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py)) — the extractor now demands TRANSFERABLE findings only and is given an explicit REJECT list (dataset shape descriptions, single-experiment hyperparameter values, running totals, single-experiment numeric results without comparison context). Capped at 3-5 atoms with calibrated-confidence anchors (≥0.7 = bet on it, ≤0.3 = weak signal). Effect: stopped runs produce few, high-signal atoms instead of dataset-shape recaps.

### Added

- **`knowledge_atom_created` and `knowledge_link_created` log events** ([src/dojo/runtime/keyword_linker.py](src/dojo/runtime/keyword_linker.py)) — replace the single `knowledge_linked` line. Now you can tell at a glance how many atoms were written vs. how many links per atom (CREATED_BY plus zero or more RELATED_TO).
- **`knowledge_flush_started` / `knowledge_flush_completed` events on `run.events`** ([src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py)) — surface the end-of-run flush in the same event stream the CLI and SSE consumers already read. The CLI renders a "saving durable knowledge…" indicator and a final saved/skipped line whether you stopped via Ctrl-C or `dojo stop` from another terminal — no more silent 30-second wait.
- **`run_finalized` sentinel event** ([src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py)) — emitted as the very last event on every termination path so SSE consumers can wait for it before sending `done`. The SSE generator now uses the sentinel as its primary terminator with a belt-and-braces fallback for orchestrator hard crashes.

### Changed

- **Confidence floor + cap on flush output** ([src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py)) — `extract_knowledge_atoms` drops atoms with `confidence < 0.5` and truncates to at most 5. Non-numeric / null `confidence` values normalise to 0.5 instead of raising and silently killing the batch. The normalised value is written back onto the atom dict so downstream casts don't re-raise.
- **`_graceful_stop` no longer prints inline** ([src/dojo/cli/run.py](src/dojo/cli/run.py)) — flush indicators come from the events now, removing the duplicate-print risk on dual-flush paths. `_stream_events` returns its rendered count so the post-stop block can drain remaining events without double-printing.

### Removed

- **Orphaned `src/dojo/runtime/knowledge_linker.py` duplicate** — a stale near-copy of `keyword_linker.py` that didn't implement the `KnowledgeLinker` interface and had no imports anywhere.

## [v0.0.9] - 2026-05-05

### Agent prompts

(none in this release)

### Changed

- **`evaluate` contract — `artifacts_dir` parameter** ([src/dojo/core/task.py](src/dojo/core/task.py)) — `evaluate(y_pred, *, X_train, X_test, y_train, y_test)` is now `evaluate(y_pred, *, X_train, X_test, y_train, y_test, artifacts_dir)`. The framework passes a real, per-run writable directory; `evaluate` may write plots or diagnostics there, or ignore the parameter. Replaces the `DOJO_ARTIFACTS_DIR` env-var convention that was leaking into AI-generated tool code and crashing `dojo task setup` verification. Contract version bumped 2 → 3 — existing frozen tasks must be re-generated with `dojo task setup`.

### Fixed

- **`dojo task setup` — evaluate verification crash** ([src/dojo/runtime/tool_verifier.py](src/dojo/runtime/tool_verifier.py)) — the verifier subprocess now provides `artifacts_dir` to `evaluate` via a temporary directory rather than relying on `DOJO_ARTIFACTS_DIR` being set. Previously any AI-generated `evaluate.py` that wrote artifacts (e.g. evaluation summary plots) would raise `KeyError: 'DOJO_ARTIFACTS_DIR'` during verification and prevent the task from being frozen.

## [v0.0.8] - 2026-05-05

### Agent prompts

- **`write_knowledge` tool description** ([src/dojo/tools/knowledge.py](src/dojo/tools/knowledge.py)) — removed the line "Always do this after experiments", which directly contradicted the prompt's "be selective" guidance. New description gives concrete triggers (rule-out, dead hyperparameter range, feature/preprocessing verdict) and explicitly says "skip routine incremental tuning". Effect: the agent should now have a coherent posture instead of resolving the contradiction by writing nothing.
- **System prompt — `write_knowledge` guidance** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py)) — replaced "if and only if... skip routine incremental tuning" with "would a future run of this domain benefit from knowing this? When in doubt, write it" plus a one-line note that an end-of-run extractor exists as a safety net. The double-hedged framing was pushing the model to default to silence; the new framing gives the agent permission to write durable findings without fearing bloat.
- **System prompt — secondary mention** ([src/dojo/agents/prompts.py](src/dojo/agents/prompts.py)) — tightened "Be selective with `write_knowledge` — record only durable findings... don't bloat the store" to "Use `write_knowledge` for durable findings, not per-experiment recaps: one atom per real learning, not one per turn." Same intent, less anxious framing.

### Added

- **End-of-run knowledge flush** ([src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py), [src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py)) — `AgentOrchestrator.execute()` now runs a one-shot LLM extractor on the run transcript and writes durable findings as knowledge atoms via `lab.knowledge_linker`. Fires for COMPLETED, FAILED, and STOPPED runs. Idempotent via a `_knowledge_flushed` flag so the CLI graceful-stop path doesn't double-write. Silently skips when the backend doesn't support `complete()` (e.g. the stub) or when there's no transcript content. Closes the gap where API-driven runs (`POST /agent/run`) had no knowledge-capture safety net.
- **`flush_run_knowledge` shared helper** ([src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py)) — extract + write in one call. Used by both the orchestrator's automatic flush and the CLI's Ctrl-C cleanup path.

### Changed

- **CLI graceful-stop delegates to the orchestrator** ([src/dojo/cli/run.py](src/dojo/cli/run.py)) — `_graceful_stop` now calls `orchestrator.flush_knowledge(run)` instead of inlining transcript extraction. Same UX (the "Ctrl-C again to skip" affordance is preserved); the underlying logic now lives in one place.

### Notes

- 7 new unit tests in [tests/unit/test_orchestrator.py](tests/unit/test_orchestrator.py) cover the flush hook across all terminal statuses, idempotency, fence-stripping, and silent failure on `complete()` exceptions.
