# Issue #20: Add dojo-onboard Claude Code skill as the conversational entry point

**Issue:** https://github.com/Garsdal/Dojo/issues/20
**Branch (will be created in Phase 2):** `feat/issue-20-onboard-skill`
**Status:** awaiting review

## Summary

`dojo onboard` is a 649-line line-by-line Typer prompt — wrong tool for long-form PROGRAM.md / SETUP.md text. The user skips through the prompts (because pasting paragraphs into a `Prompt.ask` is miserable), then gets stuck in a `dojo task unfreeze` → edit → `dojo task setup` dance because onboard already drove the task all the way through tool generation + freeze with garbage placeholder content.

Two cleanly independent fixes solve this:

1. **Fix the prompt UX at the root.** Replace the four line-by-line `Prompt.ask` calls for PROGRAM.md/SETUP.md content with a 2-way choice: **open in `$EDITOR` now** or **skip and finish manually**. When the user picks "skip", onboard stops *before* tool generation — no premature freeze, so no unfreeze needed later. No more pasting paragraphs into a CLI prompt.
2. **Ship the conversational entry point as a Claude Code skill.** Skill lives at `.claude/skills/dojo-onboard/SKILL.md` in the repo (single source of truth — *not* bundled in the wheel). A new `dojo skill install <name>` command fetches it from GitHub at the installed version's tag. Skill primarily targets the "drop Dojo into my existing codebase" case, where the AI reads the user's code, asks a few clarifying questions, and writes the `load_data` + `evaluate` connectors.

## Files to change

| File | Change |
|---|---|
| [src/dojo/cli/onboard.py](src/dojo/cli/onboard.py) | Replace `_resolve_program_and_setup`'s line-by-line `Prompt.ask` calls (lines ~500–520) with a 2-way `_select`: **edit in `$EDITOR`** (via `click.edit(filename=…)` on the default template) or **skip — finish manually**. Return a new tristate from the function — `(program_md, setup_md, preset_or_None, finish_mode)` where `finish_mode ∈ {"continue", "stop"}`. In `_onboard_async`, when `finish_mode == "stop"`, write the files, print clear next steps (`"Edit PROGRAM.md + SETUP.md, then run dojo task setup"`), and return *before* the tool-generation / verify / freeze phases. |
| [.claude/skills/dojo-onboard/SKILL.md](.claude/skills/dojo-onboard/SKILL.md) | NEW. The skill itself. Conversational onboarding targeting the "drop Dojo into my existing codebase" case. YAML frontmatter matches `ship-it`/`solve-issue` convention. Single source of truth — not duplicated anywhere else. |
| [src/dojo/cli/skill.py](src/dojo/cli/skill.py) | NEW. `dojo skill list` (enumerates known skills hardcoded today; `dojo-onboard` only) and `dojo skill install <name> [--scope user\|project] [--ref vX.Y.Z\|main] [--force]`. Fetches `https://raw.githubusercontent.com/Garsdal/Dojo/<ref>/.claude/skills/<name>/SKILL.md` via `urllib.request`. Default `--ref` = `v{dojo.__version__}` with fallback to `main` on 404. Writes to `~/.claude/skills/<name>/SKILL.md` (user, default) or `./.claude/skills/<name>/SKILL.md` (project). |
| [src/dojo/cli/main.py](src/dojo/cli/main.py) | Register the new `skill` Typer sub-app. |
| [README.md](README.md) | New section `## Conversational setup — dojo-onboard skill` placed after `## Quickstart — dojo onboard` and before `### Don't have a project yet? Try a preset`. Positions the skill explicitly: *use this if you're dropping Dojo into an existing Python project — the skill reads your code, asks a few questions, and writes the `load_data` + `evaluate` connectors for you*. Documents `dojo skill install dojo-onboard`. Names the three paths clearly: skill (existing codebase) / `dojo onboard --preset` (fresh sklearn tire-kick) / `dojo init` (scripted/CI). |
| [tests/integration/test_onboard_skip_flow.py](tests/integration/test_onboard_skip_flow.py) | NEW. Drive `dojo onboard` via `CliRunner`, choose "skip" at the PROGRAM/SETUP step, assert exit 0, assert PROGRAM.md + SETUP.md exist with default-template content, assert the domain's task is **not frozen** and tools were **not generated**. |
| [tests/integration/test_onboard_editor_flow.py](tests/integration/test_onboard_editor_flow.py) | NEW. Drive `dojo onboard` via `CliRunner`, choose "edit in editor", monkeypatch `click.edit` to write canned content back, assert the canned content lands in PROGRAM.md/SETUP.md, and (with stub backend) assert the flow proceeds to verify + freeze. |
| [tests/integration/test_skill_install.py](tests/integration/test_skill_install.py) | NEW. Monkeypatch the HTTP fetch in `src/dojo/cli/skill.py`, run `dojo skill install dojo-onboard --scope project`, assert `./.claude/skills/dojo-onboard/SKILL.md` exists with the fetched content. Second call without `--force` exits non-zero; with `--force` succeeds. Test the `v{version}` → `main` fallback by returning 404 on the first URL. |
| [CHANGELOG.md](CHANGELOG.md) | New section under `## [Unreleased]` with version bump (see Release notes below). |
| [pyproject.toml](pyproject.toml) | Version bump `0.0.x → 0.0.(x+1)`. No build-config changes — the skill isn't bundled in the wheel. |

## Approach

Two cleanly separable changes; either could ship without the other and still be a win.

**Part A — Onboard prompt UX (no auto-unfreeze).** The only behaviour change inside the existing CLI is in `_resolve_program_and_setup` ([src/dojo/cli/onboard.py:464](src/dojo/cli/onboard.py)). Today it does:

```
Target — what is the model predicting? <line input>
Success — how will you know it worked? <line input>
Dataset — where does the data live? <line input>
Evaluate — how should the metrics be computed? <line input>
```

Four single-line prompts, then onward to tool generation → verify → freeze. The new flow:

```
PROGRAM.md + SETUP.md — these describe your dataset, objective, and evaluation.
How would you like to fill them in?
  > Open in $EDITOR now (recommended)
    Skip — write defaults and finish manually
```

- **"Open in $EDITOR now"**: write the default template to disk, call `click.edit(filename=program_path)` (then again for setup), re-read the file. Proceeds to tool generation + verify + freeze as today. If `$EDITOR` is unset, `click.edit` falls back to `vi`/`notepad`; if that fails for any reason, surface the error and offer "skip" as a fallback.
- **"Skip — write defaults and finish manually"**: write default template to disk, **stop the onboard flow** before tool generation. Print:
    ```
    ✓ wrote PROGRAM.md and SETUP.md (defaults). Edit them and then run:
        dojo task setup    # generates load_data.py + evaluate.py, verifies, freezes
        dojo run           # start the agent
    ```
  The task stays unfrozen — `dojo task setup` works on a non-frozen task today (line 219), so no `unfreeze` is needed. The pain point dissolves.

`_resolve_program_and_setup` returns a new field `finish_mode: Literal["continue", "stop"]`. `_onboard_async` branches on it — `stop` short-circuits past `_pip_install_into_workspace`, `_generate_and_verify_with_retries`, and `_do_freeze`.

Presets are unchanged — preset path always `finish_mode = "continue"` because preset content is real, not placeholder.

**Part B — Skill in the repo, installable via CLI.**

1. Write `.claude/skills/dojo-onboard/SKILL.md` — the skill itself. Frontmatter:
   ```yaml
   ---
   name: dojo-onboard
   description: Onboard the user's existing Python project into Dojo by reading their code, asking targeted questions about the data + evaluation, and driving `dojo init` + `dojo task setup` until the AI-generated `load_data.py` and `evaluate.py` verify cleanly. Use when the user wants to set up Dojo on a project that already has data loaders or an evaluation metric, rather than starting from a canned sklearn preset.
   ---
   ```
   Body teaches Claude to: detect existing `.dojo/` and offer to clean up; read `pyproject.toml` + nearby `*.py` to infer data loaders and metrics; ask 2–4 clarifying questions; run `dojo init --non-interactive --name <slug> --task-type regression`; write `PROGRAM.md` + `SETUP.md` via `Write` (not via CLI prompts); run `dojo task setup`; on `exit code 3`, parse `tool_verifier` errors from stderr, edit `SETUP.md`, re-run `dojo task setup` — looping until clean. Stop with `dojo run` instructions. Non-goals listed explicitly: no bypassing freeze, no hand-editing generated tool code, no inventing task types.

2. Build `dojo skill install`. Behaviour:
   ```
   dojo skill list
   # Available skills:
   #   dojo-onboard  Conversational onboarding for existing Python codebases.

   dojo skill install dojo-onboard
   # ✓ fetched .claude/skills/dojo-onboard/SKILL.md from Garsdal/Dojo@v0.0.X
   # ✓ wrote ~/.claude/skills/dojo-onboard/SKILL.md
   # Invoke it from Claude Code with /dojo-onboard.
   ```
   Implementation: `urllib.request.urlopen` against `https://raw.githubusercontent.com/Garsdal/Dojo/{ref}/.claude/skills/{name}/SKILL.md`. `ref` defaults to `v{dojo.__version__}`; on `HTTPError 404` it retries with `main` (the version-tag fallback covers the period before the first release that contains the skill, and any race where a user installs `main` ahead of the next tag). `--ref` lets the user pin explicitly. `--scope` chooses target dir; `--force` is required to overwrite. Refuse to install a skill not in the hardcoded `SKILLS = ["dojo-onboard"]` list to keep the surface small.

3. Wire the sub-app into `src/dojo/cli/main.py` next to the other sub-apps (`task`, `runs`, `experiments`, `domain`, `config`, `program`).

**Part C — README.** New section, ~20 lines. Three explicit paths:

- **Existing Python project, real data** → install the skill, invoke `/dojo-onboard`. AI writes the connectors.
- **Just want to try Dojo on a canned dataset** → `dojo onboard --preset california_housing`.
- **Scripted / CI** → `dojo init --non-interactive` and `dojo task setup`.

Plus a one-line note that the skill requires Claude Code installed locally — it's not invoked by `dojo` directly.

## Tests

| What | Where | Verifies |
|---|---|---|
| Onboard skip path | `tests/integration/test_onboard_skip_flow.py` | Choosing "skip" writes templates and stops cleanly before tool generation. Task is not frozen. Removes the unfreeze-after-edit pain. |
| Onboard editor path | `tests/integration/test_onboard_editor_flow.py` | Choosing "edit in editor" picks up the edited content and proceeds through verify + freeze (stub backend). |
| Skill install — happy path | `tests/integration/test_skill_install.py::test_install_to_project_scope` | `dojo skill install dojo-onboard --scope project` writes SKILL.md to `.claude/skills/dojo-onboard/SKILL.md`. |
| Skill install — version fallback | `tests/integration/test_skill_install.py::test_install_falls_back_to_main_on_404` | Versioned URL 404 → falls back to `main`. |
| Skill install — overwrite gate | `tests/integration/test_skill_install.py::test_install_refuses_overwrite_without_force` | Existing file → non-zero exit; `--force` → success. |
| Existing onboard preset flow | `tests/integration/test_onboard_flow.py` (unchanged) | Typer `dojo onboard --preset` path still works end-to-end. Honours the "don't break the existing flow" non-goal. |
| Existing init flow | `tests/integration/test_init_writes_setup.py` (unchanged) | `dojo init --non-interactive` still scaffolds correctly. |

Manual verification of the issue's acceptance criteria:
- [ ] Skill exists at `.claude/skills/dojo-onboard/SKILL.md` with a clear trigger description (frontmatter `description` field is the trigger for Claude Code).
- [ ] Running the skill against an empty / existing Python project produces a valid `.dojo/` with frozen task, no markdown editing required (manual — needs Claude Code to invoke).
- [ ] Verifier failures surface back into the conversation and the skill iterates (manual — needs to deliberately trigger a verification failure).
- [ ] Documented install path in README — `dojo skill install dojo-onboard`.
- [ ] `dojo onboard` Typer flow + scripted `dojo init` path still work, all existing tests pass.

## Risks / open questions

- **`click.edit` on headless CI / no `$EDITOR`.** Test environments don't have a real editor; `click.edit` returns `None` or raises. Tests monkeypatch it; production code surfaces the error and points to "skip" as a fallback. CI doesn't run `dojo onboard` interactively, so this isn't a CI risk — just a UX-failure path to handle gracefully.
- **GitHub raw-content fetch as a runtime dependency.** `dojo skill install` is a network call. Failure modes: no network, GitHub down, rate-limited. The command fails loudly with a clear message ("could not reach `raw.githubusercontent.com`; try again with `--ref main` or download manually") — no silent fallback to a stale bundled copy (we don't have one).
- **Version-pinned `--ref` default has a chicken-egg on the release that introduces this.** Until `v0.0.X` is tagged, `v{version}` 404s and the code falls back to `main`. Once tagged, the versioned path works for that release going forward. Acceptable.
- **Onboard flow now branches earlier.** Adding `finish_mode = "stop"` means tests that previously asserted "onboard always ends frozen" need updating (only the new "skip" test cares about unfrozen). I'll grep for any such assertions and adjust.
- **Skill primarily-existing-codebase positioning.** The issue body talks about both empty projects and existing projects; the README will lean explicitly toward existing codebases per the user's clarifying ask, because that's where the AI-writes-connectors value is highest. Empty-project users have `dojo onboard --preset`, which is simpler.
- **No `dojo skill update`.** v1 omits it. To update, re-run `dojo skill install <name> --force`. If we add more skills this becomes worth its own command.

## Out of scope

Mirroring the issue's non-goals plus a couple I noticed:

- Replacing the Typer `dojo onboard` flow (both coexist).
- Bypassing the frozen-contract gate.
- Non-Claude-Code agent SDKs (Cursor, etc.).
- New task-type presets (regression only).
- Restructuring `SETUP.md` schema or `tool_verifier` contract.
- Bundling the skill into the PyPI wheel (intentionally not done — repo is the single source of truth).
- Auto-unfreeze on `dojo task setup` (intentionally not done — the prompt-UX fix removes the need).
- `dojo skill update` / `dojo skill uninstall` (re-run `--force` for now).
- Embedding skill prompts in Dojo's knowledge store.

## Release notes

`CHANGELOG.md` entry under a new `## [v0.0.X] - YYYY-MM-DD` section:

```
### Agent prompts
- Added `dojo-onboard` Claude Code skill: conversational onboarding aimed at users dropping Dojo into an existing Python codebase. The skill reads the user's code, asks targeted questions, drives `dojo init` + `dojo task setup`, and iterates on verifier failures until the AI-generated `load_data.py` + `evaluate.py` pass.

### Added
- `dojo skill install <name> [--scope user|project] [--ref <git-ref>] [--force]` and `dojo skill list` for fetching bundled Claude Code skills from the Dojo repo. Default `--ref` is the installed version's tag with fallback to `main`.
- README section explaining when to use the skill vs. `dojo onboard --preset` vs. scripted `dojo init`.

### Changed
- `dojo onboard` no longer prompts line-by-line for PROGRAM.md / SETUP.md content. Users pick **"Open in $EDITOR"** (recommended) or **"Skip — finish manually"**. The skip path writes default templates and stops cleanly *before* tool generation, so `dojo task setup` can be run later without first having to `dojo task unfreeze`.
```
