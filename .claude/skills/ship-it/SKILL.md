---
name: ship-it
description: End-to-end workflow that turns a one-line user prompt about a desired change into a merged PR — chains create-issue, solve-issue (plan), pause for human plan review, then solve-issue (implement) + open PR with version bump. Use whenever the user describes something they want shipped and gestures at the whole flow — phrases like "ship this", "/ship-it", "drive this end to end", "open an issue and work it", "let's just do the full loop", or anything that implies create-issue → plan → review → PR rather than just one step. Single trigger for the full create-issue → plan → review → PR loop.
---

# Ship It

The orchestrator for the full "prompt → merged PR" loop. Composes `create-issue` and `solve-issue` (both phases) with a single human gate — plan review.

## When to use

The user wants the whole flow from a short prompt, not just one step. They might say:
- "ship it: <description of change>"
- "open an issue for <thing> and work it"
- "drive this end to end"
- "/ship-it ..."

If they only want an issue filed (and will pick it up later), use `create-issue` directly. If they already have an issue and just want it solved, use `solve-issue`. Use `ship-it` when they want minimum-friction handoff from "I have an idea" to "PR is open".

## The flow

```
user prompt
    │
    ▼
[1] create-issue       — fast, brief search → GitHub issue #N opens
    │
    ▼
[2] solve-issue (Phase 1) — deep research → .claude/plans/issue-N-<slug>.md
    │
    ▼
*** STOP — human reviews/edits plan.md ***
    │
    ▼
[3] solve-issue (Phase 2) — implement → branch → version bump → PR opens
    │
    ▼
*** human reviews PR; on merge, issue auto-closes via "Closes #N" ***
    │
    ▼
(optional) run docs/RELEASING.md flow to tag and publish
```

## How to run it

This skill is a thin orchestrator. **Don't reimplement** what `create-issue` and `solve-issue` do — invoke them.

### Step 1: Run create-issue

Apply the `create-issue` skill to the user's prompt. When it finishes, you have an issue number `#N`.

Tell the user the issue URL in one line.

### Step 2: Run solve-issue (Phase 1)

Immediately apply the `solve-issue` skill against `#N`. Because no plan file exists yet, it runs Phase 1 — research + write `.claude/plans/issue-<N>-<slug>.md`.

When it finishes, **stop**. Tell the user:
- Issue URL (from step 1).
- Plan path.
- The 1–2 key judgment calls in the plan they should sanity-check.
- Explicit prompt: "Review and edit the plan, then say 'continue' (or just re-run /ship-it) and I'll implement."

### Plan-review gate

This is the only human gate in the loop. Reasons it matters:
- The plan is cheap to change; the implementation isn't.
- The user often spots scope or approach issues here that the agent missed.
- It anchors the implementation phase to a written contract — drift becomes obvious.

Do not skip this gate even if the plan looks obviously correct.

### Step 3: Run solve-issue (Phase 2)

When the user comes back ("continue", "go ahead", or re-runs the skill), apply `solve-issue` again. This time the plan file exists, so it runs Phase 2 — implement, version-bump (if `docs/RELEASING.md` exists), open PR.

When it finishes, report:
- PR URL.
- Branch name.
- What's in the changelog entry (if applicable).
- Confirmation that the PR body has `Closes #<N>` so merge auto-closes the issue.

## Resuming a partial run

If the user invokes `ship-it` and there's already a plan file or a PR for the issue, don't restart from the beginning. Detect state:

```bash
gh issue list --state open --search "<keywords from user prompt>"
ls .claude/plans/issue-*.md 2>/dev/null
gh pr list --search "<issue number>" --state all
```

- Issue exists, no plan → jump to step 2 (Phase 1).
- Issue exists, plan exists, no PR → jump to step 3 (Phase 2).
- PR exists → tell the user; don't open a duplicate.

If genuinely ambiguous (multiple matching issues, etc.), ask one clarifying question.

## What this skill explicitly does NOT do

- **Doesn't merge the PR.** Human review stays a human responsibility.
- **Doesn't tag/release.** The post-merge release step (`git tag`, `git push --tags`, PyPI publish) is driven by `docs/RELEASING.md`, separately, when the user is ready to ship.
- **Doesn't auto-fix CI failures on the PR.** If CI fails, the user can ask you to fix in a follow-up — the skill's job ends at "PR open with green-ish local tests".
- **Doesn't rerun create-issue if an issue already exists** for the user's intent. Look first.

## Why two skills + an orchestrator instead of one mega-skill

- `create-issue` is sometimes useful on its own (queue something for later).
- `solve-issue` is sometimes useful on its own (you already filed the issue manually).
- Splitting keeps each skill's instructions tight and lets the same skills serve a richer tree of workflows. `ship-it` is just the most common path through them.
- The plan-review gate is a natural mid-run pause; building it into one monolithic skill makes the "stop and wait" semantics fuzzier.

## Speed expectations

- Step 1 (create-issue): a few minutes, intentionally light.
- Step 2 (plan): a few–to-many minutes depending on issue size. Spawn an `Explore` subagent for breadth.
- Step 3 (implement + PR): scales with the change. Run tests/lint before pushing.

If any step is taking dramatically longer than expected, surface it to the user rather than silently grinding.
