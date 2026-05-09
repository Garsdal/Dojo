---
name: solve-issue
description: Drive a GitHub issue end-to-end: research the codebase, write a plan.md, pause for user review, then implement on a feature branch and open a PR (with version bump per docs/RELEASING.md if present). Use whenever the user says "solve issue #N", "work on issue #N", "implement issue #N", "let's tackle that ticket", or names a GitHub issue URL and wants progress on it. The skill runs in two phases — plan (stops for review) and implement — and detects which phase to run by checking for an existing plan.md for that issue.
---

# Solve Issue

Take a GitHub issue from "filed" to "PR open and version bumped, ready for human review". Two-phase, single skill: research + plan first, stop for the user to review the plan, then implement.

## Phase detection

This skill is invoked once per phase. On entry, **always** check whether a plan already exists for this issue.

```bash
ls .claude/plans/issue-<N>-*.md 2>/dev/null
```

- **No plan file found** → Phase 1: research + write plan, then stop.
- **Plan file exists** → Phase 2: read the plan (and any user edits), implement, open PR.

This means the user just runs the skill twice with the same issue number. The pause between phases is the gate where they review and edit the plan.

If the user explicitly says "redo the plan" or "rewrite the plan", treat as Phase 1 even if a file exists (overwrite after confirming).

## Inputs

The user gives you an issue identifier — could be `#5`, a full URL, or just a description like "the knowledge atom one". Resolve it:

```bash
gh issue list --state open --limit 30   # if you need to find it
gh issue view <N> --json number,title,body,url,labels
```

If multiple plausible matches, ask which one.

---

## Phase 1: Research and plan

### 1. Read the issue fully
`gh issue view <N>` — read every section. Note linked files, acceptance criteria, non-goals.

### 2. Explore the code
This is where you go *deeper* than create-issue. Goals:
- Read every file the issue references, plus their important callers/callees.
- Run `grep` / `Glob` for any symbols, configs, or patterns the issue mentions.
- Skim related tests so the plan can describe how the implementation will be tested.
- For Dojo: re-read the relevant section of [CLAUDE.md](../../../CLAUDE.md). If the change involves a new adapter, agent, tool, or route, the "Recipes" section already prescribes the steps — your plan should follow that shape.

If the codebase is large, spawn an `Explore` subagent for breadth searches and read targeted files yourself.

### 3. Write the plan

Write to `.claude/plans/issue-<N>-<slug>.md`. Slug = a kebab-case 2–4 word summary of the issue title. Example: `.claude/plans/issue-5-knowledge-atom-store.md`.

Plan template:

```markdown
# Issue #<N>: <issue title>

**Issue:** <issue URL>
**Branch (will be created in Phase 2):** `<type>/issue-<N>-<slug>`
**Status:** awaiting review

## Summary
<2–3 sentences: what we're building and why, in your own words. This is your understanding check — if you can't summarise it, you don't understand it yet.>

## Files to change
| File | Change |
|---|---|
| [path](src/foo/bar.py) | What changes here, briefly |
| [path](tests/...) | What tests get added/modified |

## Approach
<Numbered steps in implementation order. Each step should be small enough to commit independently. Mention abstractions you'll introduce, interfaces you'll touch, dispatching changes (e.g. wiring in api/deps.py for Dojo).>

1. ...
2. ...

## Tests
<What new tests will be added, what existing tests cover the change, how you'll verify the acceptance criteria from the issue.>

## Risks / open questions
<What could go wrong, alternatives considered, anything you want the user to weigh in on before implementing. If there are real forks in the road, surface them here as questions for the user.>

## Out of scope
<Mirror the issue's non-goals plus anything else you noticed but won't tackle.>

## Release notes
<For Dojo (or any repo with docs/RELEASING.md): one bullet that will go into CHANGELOG.md under the appropriate section. Also note if this changes agent prompts / tool descriptions — that section in CHANGELOG is mandatory for Dojo.>
```

### 4. Stop and report

Tell the user:
- Path to the plan file.
- The 1–2 most important judgment calls in it (e.g. "I picked `.dojo/knowledge/{domain}/{atom}.md` over a single JSON file — see Risks").
- That you're stopping for them to review.

**Do not start implementing.** Phase 2 only runs when the skill is invoked again.

---

## Phase 2: Implement and open PR

Triggered when a plan file already exists. Read the plan first — including any edits the user made.

### 1. Check the working tree
- Repo is the one the plan refers to. Confirm with `gh repo view --json nameWithOwner -q .nameWithOwner`.
- Working tree should be clean. If not, ask the user what to do (don't auto-stash).
- Up-to-date with `main`: `git fetch origin && git checkout main && git pull --ff-only`.

### 2. Create the branch

Branch name format: `<type>/issue-<N>-<slug>` where:
- `type` ∈ `feat`, `fix`, `refactor`, `docs`, `chore`, `test` — pick from the issue/plan.
- `<N>` is the issue number.
- `<slug>` matches the plan filename slug.

```bash
git checkout -b feat/issue-5-knowledge-atom-store
```

### 3. Implement

Follow the plan's "Approach" steps. Commit logically — multiple small commits are better than one big squashed one. Reference the issue in commit messages where natural (`refs #5` or `#5` in the subject), but don't force it into every commit.

Run the project's test/lint commands as you go. For Dojo: `just test && just lint` before declaring done. **Do not** mark the work complete with failing tests.

If you hit something the plan didn't anticipate:
- Small deviation → just do it, note it in the PR body.
- Significant deviation (different approach, scope change) → stop and tell the user. Update the plan rather than diverging silently.

### 4. Bump version (if RELEASING.md exists)

Check for `docs/RELEASING.md`. If present:
- Read it to understand the project's release flow.
- For Dojo: bump `project.version` in `pyproject.toml` per semver (0.0.x can break freely; bump patch by default, minor on substantial features). Add a `## [vX.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md` directly below `## [Unreleased]`. **Always include `### Agent prompts`**, even if `(none in this release)` — see Dojo's RELEASING.md for why.
- The release itself (tagging, PyPI publish) happens **after merge**, driven separately. The PR's job is to land the bump + changelog so the post-merge tag step can fire. Don't tag from the branch.

If no `docs/RELEASING.md`, skip this step entirely — don't invent a release flow.

### 5. Push and open PR

```bash
git push -u origin <branch>
gh pr create --base main --title "<type>: <subject> (#<N>)" --body "$(cat <<'EOF'
## Summary
<1–3 bullets describing the change>

Closes #<N>

## Plan
This PR implements [.claude/plans/issue-<N>-<slug>.md](.claude/plans/issue-<N>-<slug>.md).

## Test plan
- [ ] <how to verify, per acceptance criteria from the issue>
- [ ] <any manual checks>

## Release notes
<the CHANGELOG bullet(s) added in step 4. Or "(no release flow in this repo)" if step 4 was skipped.>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The `Closes #<N>` line is load-bearing: GitHub will auto-close the issue when the PR merges.

### 6. Report back

Return:
- PR URL.
- Branch name.
- Whether tests passed locally.
- Anything the user should look at first when reviewing (e.g. "the schema choice in [path] is the main judgment call here").

## Branch / commit hygiene

- One PR per issue. If the plan ballooned mid-implementation, surface it before opening the PR — better to split than to land a giant unfocused PR.
- Don't `--force` push unless asked.
- Don't skip hooks (`--no-verify`). If a hook fails, fix the underlying issue.

## After merge (informational, not part of this skill's runtime)

- The `Closes #<N>` line auto-closes the issue **most of the time**, but it can silently fail (squash-merge dropping the keyword, the keyword landing inside a code block, typos). Don't trust it blindly — verify after merge that linked issues are actually CLOSED.
- Tag/release happens after merge — for Dojo, see the release prompt in `docs/RELEASING.md`. The `ship-it` skill drives this automatically as Step 4 when invoked at the post-merge stage; standalone `solve-issue` runs stop at "PR open" and leave the release to the user.
