---
name: ship-it
description: End-to-end workflow that turns a one-line user prompt about a desired change into a released version — chains create-issue, solve-issue (plan), pause for plan review, solve-issue (implement) + PR, pause for PR merge, then drives the post-merge release (verify issue closure, tag, publish). Use whenever the user describes something they want shipped and gestures at the whole flow — phrases like "ship this", "/ship-it", "drive this end to end", "open an issue and work it", "let's just do the full loop", or anything that implies create-issue → plan → review → PR → release rather than just one step.
---

# Ship It

The orchestrator for the full "prompt → released" loop. Composes `create-issue` and `solve-issue` (both phases), then drives the post-merge release. Two human gates: plan review, and PR-merge review.

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
*** STOP — prompt user to review + merge PR; offer release-now ***
    │
    ▼
[4] post-merge — verify linked issues closed; if user opted in, tag + publish
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

The PR body MUST include `Closes #<N>` for every linked issue, **on its own line, outside any code block**. Step 4 verifies issues actually closed regardless, but a well-formed `Closes` line is the cheapest path.

When it finishes, **stop and prompt the user explicitly** (this is the second human gate — don't skip it):

> PR open: <URL>. Branch: `<branch>`. Tests + lint green locally; CI is running.
>
> Please review and merge the PR when you're happy with it. Once it's merged, tell me **"merged"** (or **"release now"**) and I'll handle the post-merge release: verify issues closed, tag, and trigger publish. If you'd rather pause here, just say so.

The point of this prompt is to make the next step a one-word user reply rather than the user having to remember to come back and ask for the release. It removes the friction that exists when the skill silently ends at "PR open".

### Plan-review vs. PR-merge gates

Both gates are necessary; both are short.

| Gate | What's reviewed | Why it matters |
|---|---|---|
| Plan review (between 2 and 3) | A markdown plan | Cheap to redirect; expensive to redirect later |
| PR-merge review (between 3 and 4) | The actual diff + CI + the user's own instinct on whether to ship | This is where the user takes ownership of the change |

Don't auto-merge the PR. The user merges it, then signals to ship-it that step 4 should run.

### Step 4: Post-merge follow-through

Triggered when the user says "merged", "release now", "go ahead with the release", or re-invokes ship-it after the PR is merged.

#### 4a. Confirm the PR is actually merged

```bash
gh pr view <N> --json state,mergedAt,mergeCommit
```

- `state == "MERGED"` → continue.
- `state == "OPEN"` → tell the user and stop. Do not auto-merge.
- `state == "CLOSED"` (without merge) → tell the user; ask whether to abandon the release.

#### 4b. Verify linked issues actually closed (defensive)

`Closes #N` usually auto-closes the linked issue at merge time, but it can silently fail — squash-merge can drop the keyword from the merge commit, the keyword can land inside a code block, the issue number can be wrong, or the user could have manually edited the PR body. So **do not trust auto-close — verify**.

```bash
# Get the list of issues the PR was supposed to close. Pull from the PR
# body's "Closes #N" / "Fixes #N" / "Resolves #N" lines.
gh pr view <PR> --json body -q .body | grep -iEo '(close[sd]?|fix(e[sd])?|resolve[sd]?) #[0-9]+' | grep -oE '[0-9]+'
```

For each issue number found, check its state:

```bash
gh issue view <N> --json state,number,title
```

- `state == "CLOSED"` → great, no-op.
- `state == "OPEN"` → close it manually with a clear comment linking to the PR:
  ```bash
  gh issue close <N> --comment "Closed by #<PR> (auto-close keyword didn't fire)."
  ```

Report what you did: "Verified #7 and #8 closed at merge; #N had to be closed manually." If everything was already closed, just say so in one line.

#### 4c. Run the release flow (only if `docs/RELEASING.md` exists and a version bump landed)

If the PR included a version bump per `docs/RELEASING.md`:

1. **Switch to main and pull**:
   ```bash
   git checkout main && git pull --ff-only
   ```
2. **Sanity-check the bump**: read `pyproject.toml` (or wherever the version lives — RELEASING.md should say) and confirm the version on main matches what the PR planned. Confirm the last tag is `vN-1` so we're not double-tagging.
3. **Re-read RELEASING.md**. If it includes a confirmation step or prompt-diff review, honour it. For Dojo specifically: prompt and tool-description changes since the last tag must be summarised in the changelog's `### Agent prompts` section — confirm that's populated for this version.
4. **Tag and push** — this is the irreversible step:
   ```bash
   git tag v<X.Y.Z> && git push origin v<X.Y.Z>
   ```
   Don't run this without one final mental check: matching version on main, last tag is the previous version, changelog entry exists. If anything is off, stop and tell the user.
5. **Watch the release workflow** if there is one (`gh run watch <id>`); report success or surface the failure.
6. **Verify the package is live** on whatever index the project publishes to (e.g. `curl -s https://pypi.org/pypi/<package>/json | python3 -c '...'` for PyPI).
7. Report: PyPI URL, GitHub release URL, time taken.

If `docs/RELEASING.md` doesn't exist, **skip this sub-step entirely** — don't invent a release flow. Stop at 4b and tell the user the PR is merged + issues closed.

#### 4d. Failure-mode notes

- **PyPI never accepts the same version twice.** If publish fails, the fix is to bump and retag — never amend or force-push the tag. Surface this loudly to the user and stop; don't silently retry.
- **Tag was already pushed** (e.g. user did it manually): `git push origin <tag>` will succeed as a no-op or fail with "already exists". Either way, jump to step 5 (watch the workflow that's presumably already running).

## Resuming a partial run

If the user invokes `ship-it` and prior state exists, don't restart from the beginning. Detect state:

```bash
gh issue list --state open --search "<keywords from user prompt>"
ls .claude/plans/issue-*.md 2>/dev/null
gh pr list --search "<issue number>" --state all
```

- Issue exists, no plan → jump to step 2 (Phase 1).
- Issue exists, plan exists, no PR → jump to step 3 (Phase 2).
- PR exists, OPEN → tell the user; don't open a duplicate. Repeat the step-3 prompt for review/merge.
- PR exists, MERGED, but issues still open or release not done → jump to step 4.
- PR merged, issues closed, tag pushed → tell the user, no-op.

If genuinely ambiguous (multiple matching issues, etc.), ask one clarifying question.

## What this skill explicitly does NOT do

- **Doesn't merge the PR.** Human review + merge stays a human responsibility — that's the second gate.
- **Doesn't tag/release without explicit consent.** Step 4 only runs when the user signals "merged" / "release now". If they say "I'll release later", stop after step 3.
- **Doesn't auto-fix CI failures on the PR.** If CI fails, the user can ask you to fix in a follow-up.
- **Doesn't rerun create-issue if an issue already exists** for the user's intent. Look first.
- **Doesn't trust `Closes #N` blindly.** Step 4b verifies.

## Why two skills + an orchestrator instead of one mega-skill

- `create-issue` is sometimes useful on its own (queue something for later).
- `solve-issue` is sometimes useful on its own (you already filed the issue manually).
- Splitting keeps each skill's instructions tight and lets the same skills serve a richer tree of workflows. `ship-it` is just the most common path through them.
- The plan-review and PR-merge gates are natural mid-run pauses; building them into one monolithic skill makes the "stop and wait" semantics fuzzier.
- Step 4 is intentionally inside `ship-it` rather than its own skill — most users want "PR → release" to feel like one click, and the release flow is small enough to embed without bloating the orchestrator.

## Speed expectations

- Step 1 (create-issue): a few minutes, intentionally light.
- Step 2 (plan): a few–to-many minutes depending on issue size. Spawn an `Explore` subagent for breadth.
- Step 3 (implement + PR): scales with the change. Run tests/lint before pushing.
- Step 4 (post-merge): seconds for the issue-close verification; a minute or two for the release pipeline (tag push → CI build → publish).

If any step is taking dramatically longer than expected, surface it to the user rather than silently grinding.
