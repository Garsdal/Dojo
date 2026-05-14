# Issue #24: Streamline onboarding — trim README, fold task CLI into domain, clarify domain scope

**Issue:** https://github.com/Garsdal/Dojo/issues/24
**Branch (will be created in Phase 2):** `refactor/issue-24-streamline-onboarding`
**Status:** awaiting review

## Summary

Cut the user-facing CLI surface to its minimum (`dojo onboard` + `dojo domain {setup, unfreeze, show, use}`), delete `dojo task`, `dojo init`, and `dojo domain create` outright, trim [README.md](README.md) to a ~120-line quickstart that puts the `dojo-onboard` Claude Code skill front and center, and add explicit "what's a domain?" copy so users stop creating a new domain per experiment. Bump to `v0.0.21`.

The `dojo-onboard` skill currently depends on `dojo init --non-interactive` for non-interactive scaffolding. To kill `dojo init` without breaking the skill, I'll fold its scaffold-and-stop behaviour into `dojo onboard --non-interactive` — same flow, no new command, just a flag on an existing one.

## Files to change

### CLI surface

| File | Change |
|---|---|
| [src/dojo/cli/task.py](src/dojo/cli/task.py) | **Delete.** Move `_do_generate` + `_do_freeze` helpers into `cli/domain.py`. Drop the `generate` / `freeze` commands entirely (no public callers besides `dojo task setup`). |
| [src/dojo/cli/init.py](src/dojo/cli/init.py) | **Delete.** Behaviour subsumed by `dojo onboard --non-interactive`. Move `_patch_config` into [src/dojo/runtime/setup_orchestrator.py](src/dojo/runtime/setup_orchestrator.py) since both `init` and `onboard` use it today. |
| [src/dojo/cli/domain.py](src/dojo/cli/domain.py) | Heavy rewrite. **Delete** `create`, `current`, `scan` commands. **Add** `setup` (one-shot generate+verify+freeze), `unfreeze`, `show` (prints domain metadata + task state — replaces `dojo task show` *and* `dojo domain current`). **Keep** `use`. Help text gains the "what's a domain?" paragraph. |
| [src/dojo/cli/main.py](src/dojo/cli/main.py) | Remove `app.command("init")(_init)` and `app.add_typer(task_app, name="task")`. Drop the corresponding imports. |
| [src/dojo/cli/onboard.py](src/dojo/cli/onboard.py) | Add `--non-interactive` flag. When set, require `--name`; skip all prompts; write defaults; **stop** before tool generation (same as today's `finish_mode == "stop"` branch). Update imports (`_do_freeze` now lives in `cli/domain.py`, `_patch_config` now in `setup_orchestrator.py`). Update the stdin-not-TTY error message to drop the `dojo init --non-interactive` recommendation. Update the "next steps" final message to use `dojo domain setup` instead of `dojo task setup`. |
| [src/dojo/cli/run.py](src/dojo/cli/run.py#L128-L131) | Update error hint: `dojo task generate ... dojo task freeze ... dojo task setup` → `dojo domain setup`. |
| [src/dojo/cli/state.py](src/dojo/cli/state.py#L109) | Update help text from `dojo init` to `dojo onboard`. |

### Runtime + framework error messages

| File | Change |
|---|---|
| [src/dojo/runtime/task_service.py](src/dojo/runtime/task_service.py) | Replace `dojo task freeze` / `dojo task setup` in error messages with `dojo domain setup`. |
| [src/dojo/runtime/tool_verifier.py](src/dojo/runtime/tool_verifier.py) | Update help string referencing `dojo task setup --timeout`. |
| [src/dojo/runtime/setup_orchestrator.py](src/dojo/runtime/setup_orchestrator.py) | Update module docstring (drop `dojo init` reference). Absorb `_patch_config` from `cli/init.py`. |
| [src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py#L125) | Replace `Create one with \`dojo init\`` → `Create one with \`dojo onboard\``. |
| [src/dojo/tools/experiments.py](src/dojo/tools/experiments.py#L69) | Replace `dojo task freeze` → `dojo domain setup`. |

### Tests

| File | Change |
|---|---|
| [tests/integration/test_cli_phase2.py](tests/integration/test_cli_phase2.py) | Rename CLI invocations (`dojo task show / freeze / unfreeze` → `dojo domain show / freeze / unfreeze` — though `freeze` no longer exists as a command, so adjust to call `TaskService` directly or via `dojo domain setup`). |
| [tests/integration/test_init_writes_setup.py](tests/integration/test_init_writes_setup.py) | **Delete or rename to `test_onboard_writes_setup.py`.** Currently imports `_init_async` from `cli.init` which is gone; replace with the equivalent `dojo onboard --non-interactive` invocation. |
| [tests/integration/test_task_setup.py](tests/integration/test_task_setup.py) | Rename to `test_domain_setup.py` and update invocation strings. |
| [tests/integration/test_onboard_flow.py](tests/integration/test_onboard_flow.py) | Update imports (no longer import from `cli.init` / `cli.task`); add a test for `dojo onboard --non-interactive`. |

### Documentation

| File | Change |
|---|---|
| [README.md](README.md) | **Major trim to ≤120 lines.** Skill path is primary; `dojo onboard` is documented fallback. Delete: artifacts section, v0.0.10 migration, scripted `dojo init` path, Opus 4.7 callout, HTTP API table, full dev section (keep 3-line pointer). Add: "What's a domain?" callout near the top. |
| `docs/ARTIFACTS.md` | **New file.** Move the content from README's Artifacts section here. (Already covered partly in CLAUDE.md — link rather than duplicate where possible.) |
| `docs/HTTP_API.md` | **New file.** Move the API endpoints table here with a one-line preamble pointing at `/docs` for the live OpenAPI. |
| [CLAUDE.md](CLAUDE.md) | Update "in 2 commands" section: replace `dojo init` + `dojo task setup` with `dojo onboard` + `dojo domain setup` (interactive) / `dojo onboard --non-interactive ... && dojo domain setup` (scripted). Update the recipes section. |
| [docs/RELEASING.md](docs/RELEASING.md) | Replace `dojo task setup` references with `dojo domain setup`. |
| [.claude/skills/dojo-onboard/SKILL.md](.claude/skills/dojo-onboard/SKILL.md) | Replace `dojo init --non-interactive` → `dojo onboard --non-interactive`; replace all `dojo task setup` → `dojo domain setup`; replace `dojo task unfreeze` → `dojo domain unfreeze`; replace `dojo task show` → `dojo domain show`; update the bail-out message ("dojo init --non-interactive" → "dojo onboard --non-interactive"). |
| [CHANGELOG.md](CHANGELOG.md) | Add `## [v0.0.21] - <today>` section with `### Agent prompts (none)`, `### Removed` listing the deleted commands, `### Changed` listing the renames + README trim. |
| [pyproject.toml](pyproject.toml) | Bump `version = "0.0.20"` → `"0.0.21"`. |

## Approach

Implementation in this order — each step is independently committable.

### 1. Move shared helpers into a stable home (no behaviour change)

- Move `_patch_config` from [src/dojo/cli/init.py](src/dojo/cli/init.py) into [src/dojo/runtime/setup_orchestrator.py](src/dojo/runtime/setup_orchestrator.py). Update `cli/onboard.py` import.
- Move `_do_generate` + `_do_freeze` (and the small helpers `_write_modules_to_sources`, `_verify_marker`) from [src/dojo/cli/task.py](src/dojo/cli/task.py) into [src/dojo/cli/domain.py](src/dojo/cli/domain.py) as module-private functions. Update `cli/onboard.py` import.
- Run tests — should still pass (nothing wired into Typer changed yet).

### 2. Add `dojo domain {setup, unfreeze, show}` commands

In [src/dojo/cli/domain.py](src/dojo/cli/domain.py):

- `setup`: literal port of `dojo task setup` from `cli/task.py`. Same flags (`--domain`, `--hint`, `--unsafe-skip-verify`, `--timeout`).
- `unfreeze`: literal port of `dojo task unfreeze`.
- `show`: combines `dojo task show` (task state) with new domain metadata (name, id, status, workspace source/path). Replaces the deleted `dojo domain current` since `show` with no args defaults to the current domain.

The help text on the Typer `app` itself gets the "What's a domain?" paragraph so it shows in `dojo domain --help`.

### 3. Delete `dojo task` and `dojo init`

- Delete [src/dojo/cli/task.py](src/dojo/cli/task.py).
- Delete [src/dojo/cli/init.py](src/dojo/cli/init.py).
- In [src/dojo/cli/main.py](src/dojo/cli/main.py), remove the `from dojo.cli.init import init as _init`, `from dojo.cli.task import app as task_app`, `app.command("init")(_init)`, and `app.add_typer(task_app, name="task")` lines.

### 4. Delete `dojo domain create`, `current`, `scan`

In [src/dojo/cli/domain.py](src/dojo/cli/domain.py), remove the `@app.command()` decorators (and bodies) for `create`, `current`, `scan`. The `_create_domain` helper goes too — it's only called by `create`. (Onboard uses `create_domain_with_workspace` from `setup_orchestrator.py`, which stays.)

### 5. Add `--non-interactive` to `dojo onboard`

In [src/dojo/cli/onboard.py](src/dojo/cli/onboard.py):

- New flag: `--non-interactive` (bool, default False). Requires `--name`. Skips every `Prompt.ask` / `_select` / `Confirm.ask`. Always uses default config (claude / file / keyword) unless explicit flags override (not adding new flags this round — defaults are fine).
- When set: skip the "what's in PROGRAM.md/SETUP.md" picker entirely and use `finish_mode = "stop"` (write default templates, exit cleanly). This matches `dojo init --non-interactive`'s exact behaviour.
- Update the stdin-not-TTY guard to no longer mention `dojo init --non-interactive`; instead recommend `dojo onboard --non-interactive --name X`.
- Update the final "next steps" message to use `dojo domain setup` instead of `dojo task setup`.

### 6. Update all error messages and help text

Sweep through [src/dojo/cli/run.py](src/dojo/cli/run.py), [src/dojo/cli/state.py](src/dojo/cli/state.py), [src/dojo/runtime/task_service.py](src/dojo/runtime/task_service.py), [src/dojo/runtime/tool_verifier.py](src/dojo/runtime/tool_verifier.py), [src/dojo/runtime/setup_orchestrator.py](src/dojo/runtime/setup_orchestrator.py), [src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py), and [src/dojo/tools/experiments.py](src/dojo/tools/experiments.py). Use `rg "dojo (task|init|domain create)"` to find any I missed.

### 7. Update the dojo-onboard skill

Replace every `dojo init --non-interactive` with `dojo onboard --non-interactive`, every `dojo task setup` with `dojo domain setup`, and similarly for `unfreeze` / `show`. Re-read the skill end-to-end to make sure the narrative still flows after the renames.

### 8. Update tests

- Delete or rewrite [tests/integration/test_init_writes_setup.py](tests/integration/test_init_writes_setup.py) to call `dojo onboard --non-interactive` instead.
- Rename [tests/integration/test_task_setup.py](tests/integration/test_task_setup.py) → `test_domain_setup.py` and update the CLI invocation strings inside.
- Update [tests/integration/test_cli_phase2.py](tests/integration/test_cli_phase2.py) — the `dojo task freeze` invocation needs to either call `TaskService` directly (cleanest since `freeze` is no longer a CLI command) or be replaced by a flow that uses `dojo domain setup`.
- Update [tests/integration/test_onboard_flow.py](tests/integration/test_onboard_flow.py) imports.
- Add one test: `dojo onboard --non-interactive --name X --workspace .` creates the domain, scaffolds PROGRAM.md + SETUP.md, and exits cleanly without generating tools (mirrors what `test_init_writes_setup.py` was asserting).

### 9. Trim the README

Target: ≤120 lines. Order:

1. Title + logo + one-line tagline.
2. **What is Dojo?** (kept, ~10 lines)
3. **What's a domain?** (new, ~5 lines — the callout from the issue)
4. **Quickstart with the `dojo-onboard` Claude Code skill** (primary path, ~15 lines)
5. **No Claude Code? Use `dojo onboard` directly** (fallback, ~8 lines)
6. **Try a preset** (tire-kicker, ~8 lines)
7. **Configuration** (5 lines)
8. **Pointers** (CLAUDE.md, ARTIFACTS.md, HTTP_API.md, RELEASING.md)

Move artifacts content → `docs/ARTIFACTS.md`. Move API table → `docs/HTTP_API.md`. Delete: v0.0.10 migration, Opus 4.7 callout, scripted-init section, full dev section (replace with a 3-line pointer to CLAUDE.md).

### 10. Update CLAUDE.md

- "In 2 commands" section: replace `dojo onboard` (primary) + `dojo init`/`dojo task setup` (scripted) with `dojo onboard` (primary) + `dojo onboard --non-interactive ... && dojo domain setup` (scripted).
- Recipes section: any reference to `dojo task setup` becomes `dojo domain setup`.
- "Known issues / nuances": drop the `Domain.tools` legacy fallback note if it's no longer relevant (out of scope to verify deeply — leave as-is if unsure).

### 11. Version bump + changelog

- [pyproject.toml](pyproject.toml): `0.0.20` → `0.0.21`.
- [CHANGELOG.md](CHANGELOG.md): new section, today's date.

```markdown
## [v0.0.21] - <date>

### Agent prompts

(none in this release)

### Removed

- **`dojo task` namespace** — `dojo task {setup, generate, freeze, unfreeze, show}` are all deleted. Use `dojo domain setup` (one-shot generate+verify+freeze), `dojo domain unfreeze`, and `dojo domain show` instead. The `TaskService` Python API is unchanged.
- **`dojo init`** — deleted. Use `dojo onboard` (interactive) or `dojo onboard --non-interactive --name X` (scripted). The latter replicates the old init flow: write config, create domain, scaffold PROGRAM.md + SETUP.md, exit without generating tools.
- **`dojo domain {create, current, scan}`** — deleted. `dojo onboard` is the only way to create a domain. `dojo domain show` (no args) replaces `current`.

### Changed

- **README trimmed to a quickstart** ([README.md](README.md)). Long-form content moved to `docs/ARTIFACTS.md` and `docs/HTTP_API.md`.
- **`dojo onboard` gains `--non-interactive`** ([src/dojo/cli/onboard.py](src/dojo/cli/onboard.py)) — absorbs the scripted/CI path that used to live in `dojo init`.
- **README adds "What's a domain?" callout** clarifying that a domain corresponds to a frozen `load_data` + `evaluate` contract; multiple experiments live inside one domain.
```

### 12. Run `just test && just lint`

Fix anything that breaks. Verify `dojo --help`, `dojo domain --help`, `dojo onboard --help` print the expected surface.

## Tests

- **Unit/integration tests covering CLI invocations**: all updated to use the new command names. The CLI tests via `typer.testing.CliRunner` should continue to assert the same behaviour against the new entry points.
- **New test**: `dojo onboard --non-interactive --name X --workspace .` exits 0, creates `.dojo/`, writes default `PROGRAM.md` + `SETUP.md`, sets `current_domain_id`, and does **not** invoke tool generation (the task should be un-frozen with no tools generated yet). This is the contract the skill depends on.
- **Manual smoke test before pushing**: run `dojo onboard --preset california_housing` in a tmp dir and confirm the end-to-end flow still completes (the preset path exercises tool generation + freeze + `dojo run` readiness).
- **Smoke test for the skill**: re-read the updated [.claude/skills/dojo-onboard/SKILL.md](.claude/skills/dojo-onboard/SKILL.md) end-to-end and confirm every CLI invocation it contains references a command that exists post-rename.

Acceptance criteria from the issue are mapped one-to-one in step 12.

## Risks / open questions

- **`dojo domain show` vs `dojo domain current`.** I'm collapsing both into `show` — with no args, it shows the current domain. Confirm this is the desired UX. Alternative: keep `current` as a short alias since it's a frequent lookup.
- **The `dojo onboard --non-interactive` flag.** Strictly speaking the issue says "Don't add new commands", and adding a flag to an existing command isn't a new command — but it *is* new surface area. The alternative is asking the skill to use the HTTP API for domain creation, which is more code in the skill and a worse failure mode. I think the flag is the right call but flagging for confirmation.
- **`dojo init` test file**: [tests/integration/test_init_writes_setup.py](tests/integration/test_init_writes_setup.py) imports `_init_async` directly — i.e. it tests a Python function, not the CLI invocation. I'll rewrite it to call `_onboard_async` (or its non-interactive equivalent) directly. If that's too invasive, the simpler path is to delete the file and rely on `test_onboard_flow.py` for coverage.
- **`docs/ARTIFACTS.md` vs CLAUDE.md duplication.** Artifacts are already partly covered in CLAUDE.md under the "Per-run artifacts" subsection. I'll keep `docs/ARTIFACTS.md` short and user-facing (what files end up where, how tracking forwards them) and link to CLAUDE.md for the architectural detail.
- **Other CLI namespaces (`runs`, `experiments`, `program`)** — not touched. Out of scope per the issue. Their help text may still reference `dojo task setup`; I'll catch those during the error-message sweep but won't restructure them.
- **HTTP API stays.** The corresponding endpoints (`POST /domains/{id}/task/freeze`, `POST /domains/{id}/tools/generate`, etc.) are untouched — they're the source of truth for the frontend.

## Out of scope

- Changing the `Task` Python abstraction or the `TaskService` API.
- Bundling the frontend in the PyPI release.
- Redesigning the `dojo-onboard` skill itself (only updating its command references).
- Multi-domain workflow features.
- Adding new subcommands beyond the agreed set.
- Touching archived design docs under `docs/archive/`.

## Release notes

CHANGELOG entry above. The `### Agent prompts` section is empty — this release doesn't touch any prompt or tool description. The `### Removed` section is the headline.

This is a breaking CLI change. Users on `v0.0.20` who upgrade need to switch `dojo task setup` → `dojo domain setup`, `dojo init --non-interactive` → `dojo onboard --non-interactive`. No migration script — small user base, single-tenant, the changelog tells them.
