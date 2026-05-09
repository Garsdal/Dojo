# Issue #18: Tell agent not to use TodoWrite — silences CLI narration

**Issue:** https://github.com/Garsdal/Dojo/issues/18
**Branch (will be created in Phase 2):** `fix/issue-18-disable-todowrite`
**Status:** awaiting review

## Summary

The agent system prompt currently says nothing about `TodoWrite`. When the
Claude backend uses it, the call shows up in the CLI's tool stream but its
content is hidden, and the agent stops narrating — the user sees a wall of
`→ TodoWrite` / `→ Bash` / `→ run_experiment` lines with no explanation.
Fix is prompt-only: add a short "Output discipline" rule that bans
`TodoWrite` and asks for brief inline narration instead.

## Files to change

| File | Change |
|---|---|
| [src/dojo/agents/prompts.py](src/dojo/agents/prompts.py) | Add an "Output discipline" subsection under "Important rules" telling the agent not to call `TodoWrite` and to narrate progress in plain text between tool calls. |
| [pyproject.toml](pyproject.toml) | Bump `version` 0.0.17 → 0.0.18. |
| [CHANGELOG.md](CHANGELOG.md) | New `## [v0.0.18] - <today>` section directly below `## [Unreleased]`, with a populated `### Agent prompts` entry describing the change. |

No test changes — there's no existing test that asserts on prompt text, and
adding a substring assertion would be brittle (and wouldn't actually
exercise agent behaviour). Existing tests should stay green; that's the
verification.

## Approach

1. **Add the guidance to [prompts.py](src/dojo/agents/prompts.py).** Drop a
   one-paragraph rule at the end of "Important rules" (around line 159–169)
   so it sits next to the other run-time rules the agent reads last. Wording
   target — concise, mirrors the tone of the existing Bash guidance in
   "Reading the workspace":

   > **Output discipline.** Do NOT use ``TodoWrite``. The dojo CLI doesn't
   > surface its content, so calling it makes you go silent from the user's
   > perspective. Between tool calls, write a short plain-text line —
   > what you're about to try, what a result told you, what you're picking
   > next. One sentence is usually enough. The user is watching this stream
   > to follow your reasoning; keep it visible.

2. **Bump the version** in [pyproject.toml](pyproject.toml) to `0.0.18`
   (patch — this is a steering tweak, not new functionality).

3. **Add the changelog entry** directly below `## [Unreleased]` in
   [CHANGELOG.md](CHANGELOG.md), following the existing template (Agent
   prompts always first, dated section header). Single bullet under
   `### Agent prompts` summarising the rule and the symptom it fixes,
   with `(#18)` at the end.

4. **Run `just test && just lint`** locally before pushing.

5. **Open PR** with `Closes #18` on its own line, referencing the plan file
   and listing the manual verification step (run the stub or claude agent
   locally and confirm `TodoWrite` doesn't appear in the event stream).

## Tests

- `just test` — full pytest suite. Prompt change is text-only and shouldn't
  shift any assertions; if anything breaks it's a brittle test we'd want to
  know about anyway.
- `just lint` — ruff check + format.
- **Manual** (recorded in the PR's Test plan): run `just run-claude` against
  a small domain, watch the agent transcript, confirm no `→ TodoWrite`
  events appear and that there's plain-text narration between tool calls.
  Stub agent doesn't exercise `TodoWrite` (it's a Claude built-in), so this
  is necessarily a Claude-backend manual check.

## Risks / open questions

- **Prompt-only steering isn't a hard guarantee.** A model can still ignore
  the instruction. The non-goals in the issue rule out belt-and-braces
  enforcement at the SDK / `allowed_tools` level for this PR — if the
  prompt doesn't hold up in practice we can add a hard block in a follow-up.
  Surfacing for the user: are you OK with the soft-block-only approach for
  v0.0.18, or want me to also strip `TodoWrite` from `allowed_tools` in
  [src/dojo/agents/backends/claude.py](src/dojo/agents/backends/claude.py)?
  My recommendation: ship the prompt-only fix first and see if it sticks.
- **Placement.** I'm putting the rule under "Important rules" rather than
  inventing a new top-level section. Rationale: it's a behavioural rule,
  same shape as the existing "Metrics come from the framework" / "Be
  systematic" bullets. Open to moving it into "Reading the workspace"
  alongside the Bash guidance if you'd rather keep all "tool steering" in
  one place.

## Out of scope

- Disabling `TodoWrite` at SDK level (`allowed_tools` filter in the Claude
  backend).
- Reworking the CLI's event renderer to display `TodoWrite` content.
- Any change to `agents/factory.py`, `agents/orchestrator.py`,
  `agents/backends/claude.py`.

## Release notes

CHANGELOG entry under `## [v0.0.18] - <today>` → `### Agent prompts`:

> - **Don't call `TodoWrite`.** [src/dojo/agents/prompts.py](src/dojo/agents/prompts.py)
>   now explicitly tells the agent not to use the `TodoWrite` built-in and to
>   narrate progress as plain text between tool calls instead. The dojo CLI
>   doesn't surface `TodoWrite` content, so when the agent reached for it the
>   user's view of the run went silent for long stretches. (#18)
