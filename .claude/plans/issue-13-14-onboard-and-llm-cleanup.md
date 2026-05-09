# Plan — Issues #13 + #14 (combined release)

**Issues**
- [#13](https://github.com/Garsdal/Dojo/issues/13) — `dojo onboard`: guided, all-in-one setup that gets a user from zero to runnable. **Primary.**
- [#14](https://github.com/Garsdal/Dojo/issues/14) — Remove dead `llm` settings group. **Cleanup, ride-along.**

**Scope of this PR**: combined release. Single branch, single PR, single version bump (one `vX.Y.Z` tag covers both). README is rewritten to lead with `dojo onboard` per the user's instruction.

---

## Why these two go together

Both touch the user's first 60 seconds with Dojo:
- #13 reshapes the **flow** (one command instead of four).
- #14 removes the **noise** (`llm:` block that confuses users staring at `.dojo/config.yaml`).

If we ship onboarding without the cleanup, every new user's generated config still has the dead block. If we ship the cleanup without the new flow, we still have the four-step ceremony. They reinforce each other.

The README rewrite the user asked for is anchored on `onboard` — natural to do in the same PR.

---

## Part 1 — Issue #14 first (10 min, clears the field)

Cheap to land first because it has zero interactions with #13's surface.

### Changes

1. **[src/dojo/config/settings.py](src/dojo/config/settings.py)** — delete `LLMSettings` (lines 16–21) and the `llm: LLMSettings` field on `Settings` (line 106).
2. **[src/dojo/api/routers/config.py:15](src/dojo/api/routers/config.py#L15)** — remove the `"llm": {...}` key from the response dict. Don't replace with a stub; the comment in #14 says "drop the consumer in the same PR" and a grep already confirmed no frontend consumer.
3. **[src/dojo/config/defaults.py:14-17](src/dojo/config/defaults.py#L14-L17)** — delete the `"llm": {"provider": "stub", "model": "stub"}` block.
4. **[src/dojo/cli/config.py:29-31](src/dojo/cli/config.py#L29-L31)** — remove the `llm:` block from the YAML template `config_init` writes. New `.dojo/config.yaml` files will not contain it.
5. **Frontend grep**: I already confirmed no `.ts(x)` references to `config.llm`. Confirm during implementation by re-running `grep -rn "config\.llm\|\.llm\." frontend/src/` — if anything turns up, drop it. If nothing, no frontend change.
6. **CLAUDE.md**: the §Config table doesn't currently list `llm` — leave alone. (The acceptance criterion in #14 says "should-stay-absent"; it's already absent.)
7. **Existing tests**: `tests/unit/test_settings.py` may reference `LLMSettings` or `settings.llm`. If so, delete those assertions. Will check during implementation.

### Tests added

Nothing new. The change is a pure deletion; existing settings/config tests already cover the surviving fields.

### Risk

Negligible. Pre-1.0 break is fine per the issue. Old `.dojo/config.yaml` files with a stray `llm:` block are tolerated by pydantic-settings (extras ignored under default config) — no migration needed.

---

## Part 2 — Issue #13: `dojo onboard`

This is the bulk of the work. The design below tries to honour the issue body's spec while keeping the surface area tight.

### Architectural posture

- **`dojo onboard` is a new top-level CLI command.** New file [src/dojo/cli/onboard.py](src/dojo/cli/onboard.py). Wired into [src/dojo/cli/main.py](src/dojo/cli/main.py) next to `init` / `run` / `stop`.
- **`dojo init` stays.** It is now the **non-interactive scriptable variant** for power users / CI. Its existing `--non-interactive` flag is unchanged. The README will demote it to a "for scripts / CI" subsection per the acceptance criterion.
- **Onboard does not duplicate logic.** It composes the existing services (`DomainService`, `WorkspaceService`, `TaskService`, `_do_generate`, `_do_freeze` from [src/dojo/cli/task.py](src/dojo/cli/task.py)) and the existing helpers (`default_program_template`, `default_setup_template`). The new code is entirely about **prompting + presets + footgun detection + missing-import remediation**.
- **Helpers live in their own module.** New file [src/dojo/runtime/onboard_helpers.py](src/dojo/runtime/onboard_helpers.py) contains the pure-logic pieces (preset registry, `parse_module_not_found`, `is_path_inside_dojo_repo`). This is deliberate so unit tests don't need a `CliRunner`.

### Two natural usage modes — the default is "drop into my project"

The dominant Dojo workflow is **`cd my-existing-python-project && dojo onboard`** — the user already has code, an environment, and a `pyproject.toml`/`requirements.txt`. `.dojo/` is added next to their existing source, the workspace is `.`, and `WorkspaceService` reuses whatever venv + deps are already there. The user brings their own dataset + evaluation; **presets are not part of this path**.

The secondary mode is **"try the framework on a canned example"** — `mkdir housing && cd housing && dojo onboard --preset california_housing`. Presets are explicitly opt-in via the `--preset` flag.

Concretely:
- **Default workspace is `.`** — same default as `init` today, but onboard surfaces it as the assumption rather than a question. "I'll set up Dojo in `<cwd>` (uses your existing `pyproject.toml` if present)." The user only sees a workspace question if they pass an explicit flag or if the cwd looks wrong (the footgun check below).
- **No "preset vs custom" prompt by default.** Onboard's main path is custom (the user's data, the user's evaluation). The preset path is reachable via `--preset <key>` and via a single explicit prompt: "Want to use a preset instead? [N/preset_name]". Default: no.
- **Existing `pyproject.toml`/`requirements.txt` is the dep source of truth.** `WorkspaceService.setup` already detects and uses them ([runtime/workspace_service.py](src/dojo/runtime/workspace_service.py)). Onboard does **not** install anything proactively in the custom path — only the on-failure `ModuleNotFoundError` retry loop runs. Preset path additionally pre-installs the preset's `pip_deps` because the user, by definition, doesn't have a project yet.
- **Footgun warning narrows in scope.** Only warn if the cwd looks like the cloned Dojo repo itself (the documented mis-invocation from the issue body) — not a generic "are you sure about this path?" prompt. In any normal existing project, onboard just proceeds silently.

### File-by-file plan

#### New: `src/dojo/runtime/onboard_helpers.py`

Pure-logic helpers — no I/O, no Typer, no `console`. Each is small enough to unit-test independently.

```python
@dataclass(frozen=True)
class SklearnPreset:
    key: str                    # "california_housing"
    label: str                  # "California housing (regression)"
    program_md: str             # full PROGRAM.md content
    setup_md: str               # full SETUP.md content
    pip_deps: tuple[str, ...]   # ("scikit-learn", "pandas", "numpy", "matplotlib")

PRESETS: dict[str, SklearnPreset] = {...}

def parse_module_not_found(error_text: str) -> str | None:
    """Extract the module name from `ModuleNotFoundError: No module named 'foo'`.
    Returns None if the error doesn't match. Robust to nested 'foo.bar' (returns 'foo')."""

def is_path_inside_dojo_repo(workspace: Path, *, dojo_repo: Path | None = None) -> bool:
    """True iff `workspace` is inside the cloned Dojo repo itself.
    `dojo_repo` defaults to the package's resolved location (`Path(dojo.__file__).parent.parent.parent`).
    Used to warn before writing `.dojo/` somewhere the user almost certainly didn't mean."""
```

**Preset starting set**: `california_housing` only (the issue says "start with"). Each preset's PROGRAM.md and SETUP.md are the exact templates the README already shows for housing — copy them verbatim so the README and the preset don't drift.

#### New: `src/dojo/cli/onboard.py`

Orchestrates the prompt flow. Structure:

```python
def onboard(
    workspace: str = typer.Option(".", "--workspace"),
    preset: str | None = typer.Option(None, "--preset",
        help="Sklearn preset key (e.g. california_housing). Skip prompts if given."),
    name: str | None = typer.Option(None, "--name"),
    config_dir: Path = typer.Option(Path(".dojo"), "--config-dir"),
) -> None:
    asyncio.run(_onboard_async(...))
```

`_onboard_async` runs these steps. Each step prints a numbered banner so the user can see where they are. The flow is biased for the **"I'm already in my Python project"** path — questions are skipped or have one-keystroke defaults whenever the cwd looks normal.

1. **Cwd footgun check (silent unless triggered)**. If `is_path_inside_dojo_repo(cwd)`, print a yellow warning: "this looks like the cloned Dojo repo itself — you probably want to `cd` into a fresh project dir or your own ML repo". Prompt to continue or abort. **Otherwise, no question.** This is the only place the workspace path is interrogated; in the normal case the user never sees it.
2. **Existing `.dojo/` check**. If `config_dir` exists and is non-empty, prompt: `[U]se existing / [O]verwrite / [A]bort`. (Default Use; Abort exits 0.)
3. **Surface the assumption (one line, no prompt)**. Print: `Setting up Dojo in <cwd>. Detected: pyproject.toml / requirements.txt / no Python project — using <existing venv | will create venv | system Python>`. The detection comes from `WorkspaceService` logic (which is the source of truth for env detection); we just preview its decision. No question — if the user wanted a different workspace they'd pass `--workspace`.
4. **Config decisions, prompted with sensible defaults**:
   - agent backend (`claude` / `stub`) — default `claude`
   - tracking backend (`file` / `mlflow`) — default `file`; if `mlflow`: `mlflow_tracking_uri`, `mlflow_experiment_name`
   - knowledge linker (`keyword` / `llm`) — default `keyword`
   - sandbox `verification_timeout` — default 600.0, accept-as-default offered
   
   Write `.dojo/config.yaml` directly via the same template `config_init` uses, plus the chosen overrides. **Do not re-implement `_patch_config`** — call it. (Currently it lives in [src/dojo/cli/init.py:298](src/dojo/cli/init.py#L298); promote it to a small helper accessible from both `init` and `onboard`. Easiest move: keep it where it is and import it from `onboard.py`.)
5. **Domain name + description** — prompt; default name = cwd basename.
6. **Preset vs. custom branch**:
   - If `--preset` was given: use that preset's `program_md` / `setup_md` directly. Skip the next prompt.
   - Otherwise: **default is "custom"** — prompt the user line-by-line for the PROGRAM.md (goal / target / success) and SETUP.md (dataset description / evaluation spec) fields, filling in the TODOs in `default_program_template` / `default_setup_template`. The user can opt into a preset with a single side prompt: "Use a preset instead of describing your own dataset? [n/california_housing]" — default `n`. Don't make presets the headline; they're for tire-kickers.
7. **Create domain + workspace + task**. Reuse exactly what `init.py` does today (create `Domain`, `WorkspaceService.setup`, `TaskService.create`). Move that block out of `init.py` into a small `_init_domain_task(...)` helper in either `onboard_helpers.py` or a new `runtime/setup_orchestrator.py`. Both `init` and `onboard` call it. Keeps the domain-creation logic in one place — important because we don't want them to drift.
8. **Preset-only: pre-install preset deps**. Skipped in the custom path — the user's existing `pyproject.toml` is the dep source of truth there. Only when `--preset` was used: resolve the workspace's venv + python via `WorkspaceService`, then `subprocess.run([python, "-m", "pip", "install", *preset.pip_deps], ...)`. On failure, warn and continue (the verifier will fail loudly later if a dep is genuinely missing).
9. **Inline tool generation + verification with retry-on-missing-import**:
   - Call the existing `_do_generate(lab, d, hint="", verify=True, save=True, timeout=None)` from [src/dojo/cli/task.py:198](src/dojo/cli/task.py#L198). This already does the AI generation + verification + save; reuse it as-is.
   - **The remediation hook**: `_do_generate` raises `typer.Exit(EXIT_GATE)` on verification failure today. We **don't** want that exit path during onboard. Two options:
     - **(A)** Refactor `_do_generate` so it returns a result object instead of exiting; have `task setup` translate the result into the existing exit-3 behaviour. **Recommended.** Cleaner long-term, makes onboard's retry loop trivial.
     - **(B)** Wrap the call in `try/except typer.Exit` and inspect `d.task.tools[*].verification.errors` directly. Hacky but smaller diff.
   - Going with **(A)**. New shape:
     ```python
     # task.py
     async def _do_generate(...) -> list[DomainTool]: ...   # unchanged returns
     async def _do_freeze(...) -> None: ...
     # In `setup` command, _do_generate now never raises Exit; the surrounding command checks each tool's verification and decides whether to exit. Same for the API path.
     ```
     `_do_freeze` already raises `TaskVerificationError` cleanly — that's the right boundary for onboard to catch. So actually the smaller change is: leave `_do_generate` alone (it doesn't `Exit` on verification — it just records errors on each tool), and the retry loop in onboard inspects `tool.verification.errors` and re-runs `_do_generate` after `pip install`.
   - **Re-checking the code**: `_do_generate` in [task.py:198](src/dojo/cli/task.py#L198) does NOT call `typer.Exit` on verification failure — it only writes errors to `tool.verification`. The `Exit` happens in `_do_freeze` via `TaskVerificationError`. So onboard can call `_do_generate` directly, inspect `tool.verification.errors` for `ModuleNotFoundError`, run pip, retry. Then call `_do_freeze` only when all tools verified.
   - Retry loop:
     ```
     for attempt in range(MAX_INSTALL_RETRIES = 3):
         tools = await _do_generate(...)  # writes verification on each tool
         missing = []
         for t in tools:
             if t.verification and not t.verification.verified:
                 for err in t.verification.errors:
                     mod = parse_module_not_found(err)
                     if mod: missing.append(mod)
         if not missing: break
         deduped = sorted(set(missing))
         if not typer.confirm(f"Verification failed: missing module(s) {deduped}. Install into the workspace venv?"):
             break
         _pip_install_into_workspace(domain.workspace, deduped)
     ```
     If after the retries any tool is still unverified, surface the errors the same way `dojo task setup` does today (re-use the help block from [task.py:340-353](src/dojo/cli/task.py#L340-L353)) and exit 3. Don't try to auto-fix non-import errors.
10. **Freeze**. Call `_do_freeze(lab, d, unsafe_skip_verify=False)`. If it succeeds, set `current_domain_id` and print the final "ready — run `dojo run`" line.

#### Modified: `src/dojo/cli/main.py`

```python
from dojo.cli.onboard import onboard as _onboard
app.command("onboard")(_onboard)
```

One line, between `init` and `run`.

#### Modified: `src/dojo/cli/init.py`

Two small changes:
1. Extract the domain-creation block (lines 144–214 — domain + workspace + task) into a shared async helper. Both `init` and `onboard` call it. **No behaviour change** for `init`.
2. Update the final "next steps" message to mention `dojo onboard` as the friendlier alternative for new users.

#### Modified: `src/dojo/cli/task.py`

No required changes for onboard (per the analysis above). The only candidate refactor — moving `Exit(EXIT_GATE)` decisions out of helpers and into command callbacks — is **deferred**. It would be cleaner but it's not blocking.

### README rewrite

Replace [README.md](README.md) §Quickstart (lines 64–84) with a structure that leads with **"drop into your existing Python project"** as the canonical path. Presets and scripted use are subsections.

```markdown
## Quickstart — `dojo onboard`

`dojo onboard` is the recommended entry point. Run it inside an existing
Python project — it adds `.dojo/` next to your code, reuses your
`pyproject.toml` / `requirements.txt` for dependencies, and walks you
through everything else:

    cd path/to/your/python/project
    uv tool install dojoml          # one-time
    dojo onboard                    # answers a few questions, generates load_data + evaluate, freezes the task
    dojo run                        # the agent starts running experiments

That's it. Your research lives at `.dojo/` in the project — knowledge,
runs, frozen tools — and your code stays where it always was.

### Don't have an existing project? Try a preset

If you just want to see Dojo work end-to-end on a canned dataset:

    mkdir housing && cd housing
    dojo onboard --preset california_housing   # writes a ready-to-run PROGRAM.md + SETUP.md
    dojo run --max-turns 30

The `california_housing` preset uses sklearn's `fetch_california_housing`
and installs the few packages it needs (`scikit-learn`, `pandas`,
`numpy`, `matplotlib`) into a fresh venv. More presets coming.

### Scripted setup (`dojo init`)

For CI or non-interactive use where prompts aren't acceptable, the older
four-step path is still there:

    dojo init --name housing --task-type regression --non-interactive
    $EDITOR PROGRAM.md SETUP.md
    dojo task setup
    dojo run
```

The "what happens under the hood" / "useful neighbours" / "stopping a run" / etc. sections stay; just the lead block changes. **The starter PROGRAM.md / SETUP.md examples currently in the README move into the `california_housing` preset's source** — single source of truth, no drift between docs and code.

### CLAUDE.md update

[CLAUDE.md §"The product in 3 commands"](CLAUDE.md) (lines ~22–28): re-shoot the snippet so it shows `dojo onboard` → `dojo run` first, with `dojo init + edit + dojo task setup + dojo run` as the scripted alternative below.

### Tests

Match the existing layout (real adapters, no mocking, tmp dirs).

**Unit (pure logic)** — `tests/unit/test_onboard_helpers.py`:
- `parse_module_not_found` covers: `"No module named 'matplotlib'"`, `"No module named 'sklearn.datasets'"` (returns `sklearn`), garbage strings (returns None), the wrapped form `"evaluate raised at evaluate.py:2: No module named 'matplotlib'"` from the verifier's actual error format ([tool_verifier.py:166](src/dojo/runtime/tool_verifier.py#L166)).
- `is_path_inside_dojo_repo` covers: a tmp_path returns False; the package's own dir returns True; relative-vs-absolute normalisation.
- `SklearnPreset` registry: `california_housing` is present, has non-empty `program_md`/`setup_md`/`pip_deps`.

**Integration** — `tests/integration/test_onboard_flow.py`:
- Run the full onboard flow with `--preset california_housing` against a tmp dir, using `agent.backend = stub`. Assert: `.dojo/config.yaml` written, `PROGRAM.md` + `SETUP.md` populated from preset, domain saved, task created. (Stub backend won't generate real tools — so we stop short of `_do_generate` for this test, or we stub `complete()` to return a canned tool dict. Match `tests/integration/test_task_setup.py` style.)
- Smoke-test the prompted (non-preset) flow via `CliRunner` with scripted input.

**Settings test housekeeping** — drop any `LLMSettings` / `settings.llm` references in `tests/unit/test_settings.py`.

---

## Judgment calls the user should sanity-check

1. **Composition vs. duplication of `init` logic.** I'm proposing to extract the domain/workspace/task-creation block from `init.py` into a shared helper (`_init_domain_task`) so `onboard` and `init` share it. Alternative: leave `init` alone and have `onboard` call its `_init_async` directly with a flag. **My pick: extract.** Less coupling, two clear callers. Push back if you'd rather keep `init.py` self-contained.

2. **One-preset start vs. four.** The issue body suggests starting with `california_housing`, `diabetes`, `breast_cancer`, `wine`. I'm proposing **just `california_housing`** for v0.0.16, with a comment in `onboard_helpers.py` showing how to add the others. Reason: each preset needs its own carefully-crafted SETUP.md to actually verify-and-run; landing four at once means four ways for the release to be embarrassing. Push back if you'd rather do all four.

3. **Auto-install scope.** I'm scoping auto-install to "verifier failed with `ModuleNotFoundError`, ask once, install if confirmed". The issue says "preflight covers the obvious cases listed in the preset; on-failure covers anything the AI-generated `evaluate.py` reaches for". I'm doing **both** (preset deps installed before tool generation + on-failure remediation). Push back if you'd rather do only one.

4. **`_do_generate` refactor.** As noted above, on closer reading `_do_generate` doesn't actually `Exit` on verification failure — only `_do_freeze` does. So **no refactor needed** to `task.py`. Onboard can sit cleanly on top of the existing helpers.

5. **CLAUDE.md `### Agent prompts` changelog entry.** Neither #13 nor #14 changes prompts. Section will say `(none in this release)`.

6. **Version bump.** Last release was `v0.0.15`. This is a **feature release** (new `onboard` command + dead-code removal). I propose `v0.0.16` per [docs/RELEASING.md](docs/RELEASING.md) — minor bump within `0.0.x`. (No semver implication; `0.0.x` may break freely.)

---

## Acceptance criteria mapping

### Issue #13

- [x] `dojo onboard` exists, runs to completion (against an existing project or a fresh dir), produces a frozen task. (Steps 1–10 above.)
- [x] `california_housing` preset takes user from `dojo onboard` to `dojo run` with no manual edits. (Step 6 + step 8 + step 9.)
- [x] Missing-dep auto-install on `ModuleNotFoundError`. (Step 9 retry loop.)
- [x] Footgun warning when workspace inside Dojo repo. (Step 1.)
- [x] `dojo init` continues to work unchanged for non-interactive use. (No behaviour change to `init.py` other than helper extraction; existing tests verify.)
- [x] Unit tests for preset registry, missing-import parser, footgun detector. (`tests/unit/test_onboard_helpers.py`.)
- [x] Smoke test for prompted flow. (`tests/integration/test_onboard_flow.py`.)
- [x] README updated to lead with `dojo onboard`. (Above §README rewrite.)
- [x] CLAUDE.md "The product in 3 commands" updated. (Above §CLAUDE.md update.)

### Issue #14

- [x] `LLMSettings` and `Settings.llm` gone. (Part 1, step 1.)
- [x] `/config` response no longer includes `llm`. (Part 1, step 2.)
- [x] New `.dojo/config.yaml` files don't include `llm:`. (Part 1, steps 3–4.)
- [x] `just test && just lint` clean. (Verified before push.)
- [x] CHANGELOG one-liner under `### Removed`.

---

## Order of work

1. Branch off `main`: `feat/onboard-and-llm-cleanup`.
2. **Part 1** (#14) — delete the dead block. Run `just test`. Tiny commit.
3. **Part 2** (#13) skeleton — new files, presets, helpers, tests for helpers. Commit.
4. **Part 2** wire — `onboard.py`, register in `main.py`. Manual smoke run (`dojo onboard --preset california_housing` against `/tmp/xx`) with `agent.backend = stub` to validate the path end-to-end without burning Claude tokens.
5. **Part 2** integration test. Commit.
6. README + CLAUDE.md updates. Commit.
7. Version bump to `0.0.16` in [pyproject.toml](pyproject.toml). CHANGELOG entry covering both issues, with `### Agent prompts: (none in this release)` first, then sections for `### Added` (onboard command + presets), `### Changed` (README + CLAUDE.md), `### Removed` (`LLMSettings`).
8. `just test && just lint`.
9. Push branch, open PR titled e.g. `feat(cli): dojo onboard + drop dead llm settings (closes #13, #14)`. PR body includes `Closes #13` and `Closes #14` on their own lines.

---

## Risks + how I'm mitigating

- **Auto-install hits the wrong venv.** `WorkspaceService` already pins `python_path` per workspace; I'll use it directly rather than relying on `sys.executable`. Smoke-test path verifies `pip install` lands in `.venv`, not the global env.
- **Interactive prompts break in non-TTY contexts.** `dojo onboard` is interactive by design — if `sys.stdin.isatty()` is false and no `--preset` is given, fail fast with a message pointing at `dojo init` for scripted use.
- **Preset deps drift from the AI's actual generated code.** Preset deps are a best guess; the on-failure remediation backstops them. If the AI generates code that needs `seaborn` and the preset only listed `matplotlib`, the verifier will fail, the user will be prompted to install `seaborn`, and we move on. So drift is self-healing.
- **Verifier subprocess uses a different python than `pip install` targets.** The `tool_verifier` calls `sandbox.execute` with `python_path=workspace.python_path` ([tool_verifier.py:76-86](src/dojo/runtime/tool_verifier.py#L76-L86)) — same source as the install target. Verified consistent.
