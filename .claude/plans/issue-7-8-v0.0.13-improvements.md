# Plan — v0.0.13 (issues #7 + #8)

Two improvements shipping together on `mlg/v0.0.13-improvements`:

- **#7** — `dojo init` should show a spinner during long startup steps (workspace setup hangs silently).
- **#8** — Agent system prompt: stronger baseline-first, more verbose findings, less hyperparameter focus, follow user code, allow SETUP.md peek.

Branch already exists with one prep commit (`1d2b452 feat(dojo): improve claude.md + add skills`). This plan adds two more commits then opens a single PR closing both issues.

---

## Issue #7 — init spinners

### Where

[src/dojo/cli/init.py](src/dojo/cli/init.py) `_init_async()` (line 116). The pattern to copy is already in [src/dojo/cli/task.py:238-241,275-279](src/dojo/cli/task.py#L238): `console.status("...", spinner="dots")` wraps the long-running async block.

### What's wrong

Today the file uses `console.print()` for every step. Fast steps print a green check, but the **workspace setup** step (line 159-176) calls `ws_service.setup()` which spawns subprocesses (`uv sync`, `pip install -r`, `git clone`) with stdout/stderr piped — to the user this looks like a hang for minutes.

Other steps (config bootstrap, domain save, task create, scaffold writes) are fast (sub-second) but are scattered visually — wrapping them in a consistent "→ … ✓" style makes the whole flow legible.

### What I'll change

Wrap each step in `console.status()`:

```python
with console.status("[cyan]bootstrapping config...[/cyan]", spinner="dots"):
    config_dir.mkdir(...)
    if not config_path.exists():
        config_init()
console.print("[green]✓[/green] config ready")
```

Specifically:

1. **Config bootstrap** (lines 131-140) — wrap in status, then green-check line.
2. **Domain save** (lines 156-157) — wrap.
3. **Workspace setup** (lines 159-176) — wrap with a label that updates per-phase. `WorkspaceService.setup()` already returns the resolved Workspace; we don't need finer granularity inside, but we *should* surface what kind of install it ran. Two options:
   - **(a)** Just spin with `"setting up workspace (venv + deps, can take a few minutes)..."` — minimal change.
   - **(b)** Add lightweight per-step logging inside `WorkspaceService.setup()` that yields events the CLI can consume.
   
   **Going with (a).** The workspace service already logs via structlog; piping its events into the spinner is more code than this fix warrants. The extra "(can take a few minutes)" line + spinner is enough to communicate "I'm not hung."
4. **Task creation** (lines 178-195) — wrap.
5. **PROGRAM.md / SETUP.md scaffold** (lines 201-219) — these are sub-millisecond file writes, no spinner; just green-check lines. Already done.

### Acceptance

- `uv run dojo init --name foo --task-type regression --workspace .` shows a moving spinner during dependency install.
- All existing init tests still pass.
- No new tests needed — this is presentation only.

### Risk

Very low. `console.status` is a context manager that no-ops in non-TTY environments (CI logs stay clean). All current `console.print` lines remain.

---

## Issue #8 — system prompt improvements

### Where

- [src/dojo/agents/prompts.py](src/dojo/agents/prompts.py) — `build_system_prompt()` (line 23-140); the workflow section (line 69-89) and "don't waste turns" section (line 91-112) are the levers.
- [src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py) — `INCLUDE`/`REJECT` rules (line 51-76); already rejects single-experiment hyperparameter values — keep that.
- [src/dojo/runtime/setup_loader.py](src/dojo/runtime/setup_loader.py) — SETUP.md path is `<base_dir>/domains/{domain_id}/SETUP.md`; we surface this in the prompt.

### What I'll change

#### 1. Reframe workflow around a baseline-first rhythm

Replace the current 6-step "Workflow" + "Don't waste turns" content with:

```
## Workflow

### Step 1 — Baseline (always first)
Your first run_experiment is a baseline. The simplest plausible end-to-end
model that satisfies the contract — no tuning, no feature engineering, no
ensembles. The point is to (a) prove the contract works in this workspace
and (b) anchor every later experiment to a real number.

For regression, that's typically `LinearRegression` or `Ridge()` with default
params on the raw features. If PROGRAM.md names a model class, use that
instead — but still run it with defaults.

### Step 2 — Read what's already known
search_knowledge to see what prior runs found. The "Accumulated knowledge"
section above is the curated summary; only fall back to list_experiments
if a specific claim needs to be re-verified.

### Step 3 — One change at a time
After the baseline, propose one hypothesis worth testing — preferably
something that changes the *modelling approach* (different model family,
different feature representation, different target transform). Hyperparameter
tuning is a late move, not an early one: a +0.5% from tuning is rarely
informative and burns the turn budget. Reach for it only after you have
2-3 model/feature variants on the board.

### Step 4 — Write findings as you go
After every experiment, ask: would a future run benefit from knowing this?
If yes, write_knowledge — and write it with enough context that someone
reading it cold can act on it. Two sentences beats one. Include:
  - the claim ("HistGradientBoosting beat LinearRegression by ~12% on RMSE")
  - the why or the supporting evidence ("non-linear feature/target relationship
    visible in residual plot from exp_01")
  - confidence calibrated to the strength of the evidence

In-loop captures are higher fidelity than the end-of-run extractor — when
in doubt, write. The extractor is a safety net, not the primary channel.
```

#### 2. Allow the agent to read user code (and SETUP.md)

Replace the "Don't waste turns on exploration" / "Tools like Bash/Glob/Read are last resorts" framing with a softer rule:

```
## Reading the workspace

Bash / Read / Glob are available — use them, but with intent.

- **Always-OK**: read PROGRAM.md (already shown above) and SETUP.md (at
  `<setup_path>`). SETUP.md is the human's plain-language description of
  the data + evaluation, written before tools were generated. It is safe
  to read and often clarifies what `evaluate()` is actually measuring.
- **Encouraged**: scan the workspace for existing scripts/notebooks that
  solve a related problem. If the user already has a `models/` or
  `notebooks/` directory, prefer mirroring their conventions (column
  selection, preprocessing, model class) over inventing your own.
- **Skip**: load_data.py and evaluate.py. These are frozen black boxes and
  the contract above is the source of truth. Reading them is rarely useful
  and the contract is already complete.

Reading is not a substitute for running. Your first run_experiment should
fire within the first 1-3 turns. A baseline that fails is more valuable
than a perfect mental model that hasn't been tested.
```

The SETUP.md path is rendered into the prompt by `_build_task_section()` (or a new section). To do this:

- Add a `setup_path` field surfaced via the existing `Domain.setup_path` (already saved in `init.py:217`). Render in `_build_domain_section()`:
  ```
  ### SETUP.md (data + eval spec, plain language)
  Path: {domain.setup_path}
  Read it if you need to understand what evaluate() is measuring.
  ```

#### 3. De-emphasize hyperparameters

- In the workflow text above, hyperparameter tuning is now framed as "a late move, not an early one" rather than just one of several legitimate first steps.
- In [summarizer.py:51-76](src/dojo/agents/summarizer.py#L51), keep the existing rejection of single-experiment hyperparameter values; **add** an explicit INCLUDE bullet for "modelling approach lessons" so the extractor isn't biased toward terseness.

#### 4. More verbose findings (atom rendering + summarizer)

- **Atom rendering** ([orchestrator.py:120-140](src/dojo/agents/orchestrator.py#L120) and `prompts.py:_build_knowledge_section`): today renders `[confidence] claim`. Knowledge atoms have a `context` field today (or close — verify in `core/atom.py`); if present, render claim + a single `context` line indented under it.
- **Summarizer prompt**: ask for "1-2 sentence claims that include the *why*", and bump max atoms from 5 → 7 (still small enough to stay high-signal).

### Acceptance

- A stub agent run still works (the stub doesn't read prompts, so no behaviour change there — only validates the build still wires up).
- Existing prompt-building tests still pass; if they assert exact prompt strings, update them. Likely files: `tests/unit/test_prompts.py` (check first).
- A manual smoke run with the Claude backend on a regression domain shows: (a) first experiment is a vanilla baseline, (b) at least one knowledge atom is written with context-style 1-2 sentence content.
- Changelog `### Agent prompts` entry mandatory.

### Risk

Medium. Prompt changes are by definition behaviour-changing across every domain. The rewrite is largely re-emphasis, not new directives, and the safety nets (frozen contract, summarizer, knowledge linker) all stay intact. We mitigate by:
- Running the existing prompt unit tests.
- A short stub run to confirm orchestrator still builds.
- Calling out the change loudly in the changelog so users can revert by pinning v0.0.12 if it backfires.

---

## Release flow

Once both fixes land:

1. `just test && just lint` — green.
2. **Diff prompts since v0.0.12** — already done as research above; the changes are in `prompts.py` + `summarizer.py`.
3. Update `CHANGELOG.md`:
   ```
   ## [0.0.13] — YYYY-MM-DD

   ### Agent prompts
   - Reframed the workflow around a baseline-first rhythm; hyperparameter
     tuning explicitly demoted to a late move.
   - Permitted (and encouraged) reading SETUP.md and the user's existing
     workspace code; previously discouraged as "last resort".
   - Knowledge atoms now ask for 1-2 sentence findings with rationale;
     accumulated knowledge renders the `context` line under each claim.
   - End-of-run summarizer max atoms: 5 → 7.

   ### Changed
   - `dojo init` wraps each startup step in a spinner; long workspace
     setup no longer looks like a hang. (#7)

   ### Fixed
   - (none)
   ```
4. Bump `version` in `pyproject.toml` from `0.0.12` → `0.0.13`.
5. Commit, push branch, open PR with `Closes #7` and `Closes #8`.
6. **Don't tag** — that's a separate manual step per `docs/RELEASING.md`.

---

## Out of scope

- Restructuring `KnowledgeAtom` to add fields (issue #5 covers the bigger atom-store rework).
- Auto-continue runs (issue #6 — separate release).
- Bundling the frontend in PyPI release.
- Adding tracing / per-step events to `WorkspaceService.setup()`.
- Replacing the keyword linker with an embedding/agentic linker.
