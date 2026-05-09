# Issue #10: Restructure README around uv tool install + getting started; move dev content to bottom

**Issue:** https://github.com/Garsdal/Dojo/issues/10
**Branch (will be created in Phase 2):** `docs/issue-10-readme-pypi-restructure`
**Status:** awaiting review

## Summary

Now that `dojoml` is on PyPI, the README should lead with `uv tool install dojoml` and the 3-command flow, not `just dev`. We restructure [README.md](README.md) so the first thing a new user sees is "install + run California housing"; everything contributor-only (`just`, frontend, project tree, API endpoints, architecture) moves into a single "Development" section near the bottom that mostly defers to [CLAUDE.md](CLAUDE.md).

This is a single-file edit. No code changes, no test changes.

## Files to change

| File | Change |
|---|---|
| [README.md](README.md) | Full restructure per the proposed outline below. |
| [CHANGELOG.md](CHANGELOG.md) | Add a new release section per [docs/RELEASING.md](docs/RELEASING.md). |
| [pyproject.toml](pyproject.toml) | Patch version bump (docs-only; harmless). |

## Proposed new README outline

In order, top to bottom:

1. **Title + tagline + logo + demo video** — unchanged.
2. **What is Dojo?** — unchanged (already concise, positioning is clear).
3. **Status** — keep the proof-of-concept callout, trim from 5 bullets to 3 (agent / storage / tasks). Drop compute + tracking detail here — they show up later.
4. **Install** *(new top-level section, replaces "Prerequisites")*:
   - One-liner: `uv tool install dojoml` (recommended).
   - Alternatives: `pipx install dojoml`, `pip install dojoml`.
   - Note that the package is `dojoml` and the CLI binary is `dojo`.
   - Prereqs trimmed to: Python 3.13+, the `claude` CLI logged in. Drop `just`, `uv` (folded into install), Node.js (moves to Dev section).
5. **Quickstart — California Housing in 3 commands** — keep the existing walkthrough verbatim from `mkdir housing && cd housing` through `dojo run --max-turns 30`, the Opus tip, the `PROGRAM.md` / `SETUP.md` examples, the "What happens under the hood" bullets, and `Useful neighbours`. Drop the "in-process, no server needed" line about CLI-vs-HTTP — that's an implementation detail users don't need on the front page.
6. **Stopping a run** — unchanged.
7. **Reviewing what happened** — unchanged.
8. **Artifacts** — unchanged.
9. **Migrating from v0.0.10** — keep, but demote to the bottom of the user-facing flow (it's reference material).
10. **Configuration** — keep the YAML + env-var examples; trim narrative.
11. **Web UI / server (optional)** — short user-facing note: `dojo start` runs the API on `http://localhost:8000`; the React frontend is **not bundled in the PyPI release yet** — see Development to run it from a checkout.
12. **Development** *(new consolidated section near the bottom)*:
    - "Most of the contributor reference lives in [CLAUDE.md](CLAUDE.md). This section is the minimum to clone and run tests."
    - Clone + `just dev` + `just test` / `just lint` / `just format`.
    - `just run-stub` / `just run-claude` for the full server-with-frontend dev loop. Mention Node 18+ here.
    - Pointer to [CLAUDE.md](CLAUDE.md) for architecture / directory map / recipes.
    - Pointer to [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) for vision.
    - Pointer to [docs/RELEASING.md](docs/RELEASING.md) for the release flow.
13. **API endpoints table + project structure** — move the existing tables here as a sub-section under Development, or drop entirely (CLAUDE.md already has the directory map). **Decision:** drop the project-structure tree (duplicates CLAUDE.md's directory map) and keep the API endpoints table — it's small and there's no equivalent in CLAUDE.md.
14. **Footer pointer line** to CLAUDE.md / MASTER_PLAN / RELEASING — unchanged.

## Approach

1. Rewrite [README.md](README.md) end-to-end per the outline above. Preserve every code block that's in the user-facing flow today verbatim — the California housing walkthrough has been validated against the live CLI, don't introduce drift.
2. Verify the install section's commands. `uv tool install dojoml` should be the recommended path; sanity-check the package metadata at https://pypi.org/project/dojoml/ exists (it does — that's the trigger for this issue).
3. Bump `version` in [pyproject.toml](pyproject.toml) from the current value (whatever it is; check before bumping) to the next patch — docs-only changes are still semver patches.
4. Add a new section to [CHANGELOG.md](CHANGELOG.md) directly below `## [Unreleased]` with `### Agent prompts (none in this release)` and a `### Changed` bullet for the README restructure.
5. Do **not** change CLAUDE.md, docs/MASTER_PLAN.md, or any code.

## Tests

- `just test && just lint` should still pass (no code changes, but run them — lint can flag README-adjacent things on rare occasions).
- Manually skim the rendered README on the branch to verify markdown still renders cleanly (no broken anchors/links).
- Spot-check the California housing block can be copy-pasted as-is from a fresh shell with only `uv tool install dojoml` run beforehand. Don't actually run a full agent loop — just confirm `dojo init`, `dojo task setup` (or at least `dojo --version` / `dojo --help`) work from a temp dir.

## Risks / open questions

- **Risk: drift between README quickstart and reality.** The current 5-step block (`mkdir housing` … `dojo run`) has been the canonical demo for several releases. I plan to keep it byte-for-byte except for the surrounding prose. Flag for review: anything you've changed in the CLI surface recently that should be reflected here.
- **Open question: keep the "What happens under the hood" prose?** It's three bullets that explain `dojo init` / `dojo task setup` / `dojo run`. I lean *keep* — it's the only place a user learns *why* `evaluate` is frozen. Easy to drop if you want a leaner page.
- **Open question: where does the demo video live in the new structure?** Current location (right after the title) is good; I plan to leave it.
- **Risk: the "API endpoints" table is mostly useful for people writing against the HTTP API directly, which is a contributor-ish use case. I lean *keep but in Development*.** Open to dropping entirely.

## Out of scope

- No content changes to CLAUDE.md, MASTER_PLAN, RELEASING, NEXT_STEPS.
- No new docs files. Single-file README restructure (plus CHANGELOG + pyproject for the release).
- No screenshots, no new diagrams.
- No change to product framing (single-tenant, BYO-pipeline, MLflow-as-bridge).

## Release notes

CHANGELOG entry under the new version section:

```
### Agent prompts
(none in this release)

### Changed
- README restructured around `uv tool install dojoml`: PyPI install + the 3-command quickstart now lead, with all contributor/development content consolidated into a single "Development" section near the bottom that points at CLAUDE.md.
```

Patch version bump only — no behaviour changes.
