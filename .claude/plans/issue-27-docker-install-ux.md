# Issue #27: Docker sandbox: tool verification fails on missing deps; auto-install prompt is unusable

**Issue:** https://github.com/Garsdal/Dojo/issues/27
**Branch (Phase 2):** `fix/issue-27-docker-install-ux`
**Status:** awaiting review

## Summary

When `dojo onboard` runs with `sandbox.backend = "docker"`, the auto-install retry loop in the verifier is shaped entirely around a host-executable workspace venv. If the docker-venv build silently fails (or `workspace.python_path` is unset for any other reason), we still ask the user "Install into the workspace venv? [y/n]", then refuse to act on `yes`. And even when `python_path` is set, `_pip_install_into_workspace` tries to run a Linux ELF binary on the macOS host. Fix: move install dispatch into `WorkspaceService` so it knows the sandbox backend; check workspace readiness *before* prompting; fail loud when the workspace isn't ready instead of letting verification proceed against the bare container python.

## Files to change

| File | Change |
|---|---|
| [src/dojo/runtime/workspace_service.py](src/dojo/runtime/workspace_service.py) | New `async install_packages(workspace, modules) -> InstallResult`. Dispatches docker vs host: docker uses `docker run --rm -v <ws>:<ws> -w <ws> <image> uv pip install --python <python_path> <mods>` (mirrors `_ensure_docker_venv` bind-mount). Host path uses today's `uv pip install --python <path>` / `python -m pip install` logic. Returns success bool + tail of stderr. |
| [src/dojo/cli/onboard.py](src/dojo/cli/onboard.py) | (a) Strip `_pip_install_into_workspace` and `_resolve_install_cmd` from the host-only path; reimplement as a thin async wrapper that constructs `WorkspaceService(...)` and calls the new method. (b) In `_generate_and_verify_with_retries`: refresh the domain *before* the `Confirm.ask` prompt; if `workspace.python_path` is missing or `workspace.ready is False`, print a clear actionable error (workspace setup didn't finish; rerun `dojo domain setup` and look for docker-venv build errors, or set `sandbox.backend = "local"`) and break out of the loop — do not prompt. (c) Pre-verification guard at the top of step 9: if `workspace.ready` is False, refuse to start tool generation and direct the user to fix the workspace first. |
| [src/dojo/runtime/setup_orchestrator.py](src/dojo/runtime/setup_orchestrator.py) | Re-save the partial workspace state when `WorkspaceService.setup()` raises — currently `domain.workspace` keeps its pre-setup shape (ws.path may already be resolved by `_resolve_path` since that succeeds before `_ensure_docker_venv`). Mark `workspace.ready = False` explicitly so downstream code has a single boolean to gate on. The `workspace_warning` string itself stays in the return tuple — no new schema field. |
| [tests/integration/test_onboard_flow.py](tests/integration/test_onboard_flow.py) | Replace the existing `_resolve_install_cmd_*` tests with equivalents that exercise `WorkspaceService.install_packages` (or drop them if subsumed by the new unit tests). |
| [tests/unit/test_workspace_service_docker_venv.py](tests/unit/test_workspace_service_docker_venv.py) | Extend with two tests covering `install_packages`: (1) host backend → `uv pip install --python <path>` runs on the host; (2) docker backend → `docker run -v <ws>:<ws> -w <ws> <image> uv pip install --python <path> <mods>` (verify argv shape via the same `_FakeProc` pattern already used). |
| New: `tests/unit/test_onboard_install_prompt.py` (or extend an existing onboard test) | Cover the check-before-prompt fix: when `workspace.python_path` is None, the auto-install branch must not call `Confirm.ask`. Use the `runner.invoke` pattern from `test_onboard_flow.py` and inject a domain with `python_path=None`. |
| [CHANGELOG.md](CHANGELOG.md) | New `## [v0.0.23] - 2026-05-14` section with `### Agent prompts` (none) + `### Fixed` (this bug). |
| [pyproject.toml](pyproject.toml) | Bump `version` `0.0.22` → `0.0.23`. |
| [CLAUDE.md](CLAUDE.md) | One-line note in "Known issues / nuances" about the docker-venv build being the load-bearing step — if it fails, `dojo domain setup` halts rather than silently downgrading. |

## Approach

1. **Add `WorkspaceService.install_packages(workspace, modules)`** in [workspace_service.py](src/dojo/runtime/workspace_service.py). Lives next to `_ensure_docker_venv` — same dispatch shape, same bind-mount idiom for the docker path. Returns a small dataclass or tuple `(ok: bool, message: str)` so the CLI can render success/failure consistently. The function refuses to run if `workspace.python_path` is None — that's a "workspace not ready" condition the caller should have caught.

2. **Rewire CLI install helpers** in [onboard.py](src/dojo/cli/onboard.py). `_pip_install_into_workspace` becomes a thin `async` helper that builds a `WorkspaceService(base_dir, settings.sandbox)` and awaits `install_packages`. The synchronous `_resolve_install_cmd` host-only logic is folded into the new method's host branch. Both call sites in onboard.py (preset install at line 319, retry-loop install at line 747) update to the new signature.

3. **Reorder check-before-prompt** in `_generate_and_verify_with_retries`. The refresh-from-disk step (currently lines 737–739, *after* the prompt) moves above the prompt. If the refreshed `workspace.python_path` is None or `workspace.ready` is False, print a clear actionable error block (referencing the prior `workspace_warning` if surfaced upstream) and break — no prompt, no retry. This is the headline UX fix.

4. **Pre-verification guard.** At the top of `_generate_and_verify_with_retries` (before the first `_do_generate` call), check `domain.workspace.ready`. If False, print a "workspace not ready" message and return False immediately. Aligned with the "no silent fallbacks" rule from CLAUDE.md.

5. **Persist `ready=False` on partial setup.** In [setup_orchestrator.py:107](src/dojo/runtime/setup_orchestrator.py#L107), after catching the exception, set `domain.workspace.ready = False` and call `lab.domain_store.save(domain)` so the on-disk state matches reality. Today the saved domain holds the pre-setup workspace (ready default), but a future call path might depend on this being explicit.

6. **Tests:** unit coverage for docker + host install dispatch using the existing `_FakeProc` pattern from `test_workspace_service_docker_venv.py`; CLI-level test that asserts no `Confirm.ask` is reached when `python_path=None`.

7. **Lint + manual smoke.** `just test && just lint`. Manual test (post-PR, by user): rerun `dojo onboard` in the gridcast workspace with docker backend; verify the workspace_warning is visible, no install prompt offered when `.venv-docker/` is missing, and that when `.venv-docker/` exists, answering yes to the install prompt actually installs sklearn inside the container.

8. **Version bump + changelog.** v0.0.23 patch release. CHANGELOG entry under `### Fixed`. No prompt or tool-description changes (Agent prompts: none in this release).

## Tests

New unit tests:
- `test_install_packages_docker_backend_uses_docker_run` — sandbox.backend = "docker"; verifies argv shape `docker run --rm -v <ws>:<ws> -w <ws> <image> uv pip install --python <python_path> <modules>` via `_FakeProc`.
- `test_install_packages_local_backend_runs_uv_on_host` — host path, asserts `uv pip install --python <path>` invocation.
- `test_install_packages_no_python_path_is_a_noop_with_error` — calls with `workspace.python_path = None`; expects no subprocess, returns failure result.

New / extended CLI test:
- `test_onboard_skips_install_prompt_when_python_path_missing` — drives the CLI through a state where verification fails *and* `python_path` is None; asserts the run ends without ever calling `Confirm.ask` for install.

Existing tests touched:
- `test_resolve_install_cmd_prefers_uv_when_on_path` / `test_resolve_install_cmd_falls_back_to_python_pip` — likely removed or rewritten against `WorkspaceService.install_packages` since `_resolve_install_cmd` is folded in. Don't lose the "uv-managed venvs don't ship pip" regression coverage — preserve it as a test on the new host branch.

Manual smoke (post-merge or pre-merge by user): rerun the failing onboarding in `~/Projects/electricitymaps/projects/gridcast` and confirm the new error path is clean.

## Risks / open questions

1. **Should `install_packages` *also* be exposed on the `Sandbox` interface?** Already in there as `Sandbox.install_packages` ([src/dojo/interfaces/sandbox.py:56](src/dojo/interfaces/sandbox.py#L56)) — but those implementations install into the *image*, not into `.venv-docker/`. They're for "smoke install during ad-hoc debugging", per the docstring. The two methods serve different use cases (image-level vs workspace-level); keeping them separate avoids overloading the sandbox abstraction. Worth confirming in review.

2. **Concurrent docker-venv mutations.** `dojo domain setup` can run while an agent run is reading from `.venv-docker/`. Today's `_ensure_docker_venv` is idempotent on existence; the new `install_packages` mutates the venv in place. Low risk in practice (single-tenant, one user) but worth a docstring note.

3. **Error-state visibility.** Should the workspace_warning string be persisted somewhere (e.g. a `workspace.last_setup_error: str | None`) so a later `dojo domain show` reveals it? Cleaner UX, but pulls in a schema change and a small migration. Plan ships *without* this — re-running `dojo domain setup` re-surfaces the error. Open to user feedback if we want the schema field too.

4. **Image pull cost on auto-install.** Each `docker run` for install pulls (if not cached) and starts a one-shot container — a few extra seconds per install. Acceptable; matches the existing `_ensure_docker_venv` UX.

## Out of scope

- Re-architecting `Sandbox.install_packages` or making install part of the sandbox port (explicit non-goal in the issue).
- Editing the workspace's `pyproject.toml`/`requirements.txt` (auto-install is venv-only).
- Persisting setup errors on the workspace schema (deferred — see Risks).
- A `dojo workspace doctor` / inspect command (would be nice; separate ticket).
- Non-Docker remote sandboxes.

## Release notes

CHANGELOG.md, under `## [v0.0.23] - 2026-05-14`:

```
### Agent prompts

(none in this release)

### Fixed

- **`dojo onboard` no longer prompts to install into a non-existent venv.** When the docker-venv build during workspace setup fails (or `workspace.python_path` is unset for any reason), tool verification now refuses to start instead of producing a confusing downstream `ModuleNotFoundError`, and the post-verification "Install into the workspace venv?" prompt is skipped entirely. (#27)
- **`dojo onboard` auto-install honours the docker sandbox.** When `sandbox.backend = "docker"`, missing modules detected by tool verification are installed *inside* the container against `.venv-docker/` (via `docker run -v <ws>:<ws>`), matching the venv the verifier itself runs against. Previously the install ran on the host with a Linux ELF interpreter and failed with `exec format error` on macOS. (#27)
```
