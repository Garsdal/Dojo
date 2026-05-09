---
name: create-issue
description: Create a GitHub issue from a short user prompt for the Dojo repo. Use whenever the user describes a bug, feature, refactor, or improvement they want tracked — phrases like "open an issue for…", "file a ticket for…", "we should fix…", "let's track…", "create an issue", or any change request that doesn't need to be implemented right now. The skill does a brief code search to enrich the issue with file/line references, drafts a clear title + body, and creates the issue via `gh`. Optimised for speed — deep research belongs in solve-issue, not here.
---

# Create Issue

Turn a one-line user request into a well-scoped GitHub issue with enough context that a future agent (or human) can pick it up cold.

## When to use

The user describes something they want fixed, added, or changed but is **not** asking you to implement it now. Typical phrasings:
- "open an issue for…"
- "file a ticket for…"
- "we should fix / improve / refactor…"
- "create an issue about…"
- "track this somewhere…"

If the user wants implementation **now**, don't use this — go straight to coding.

## What this skill does (and doesn't)

**Does:**
- Brief code search (≤5–10 minutes) to ground the issue in real files and current state.
- Drafts a concise issue title + body.
- Creates the issue via `gh issue create`.
- Returns the issue URL.

**Doesn't:**
- Deep research, design, or solution proposal — that's `solve-issue`'s job.
- Implement anything.
- Open PRs.

If the user's prompt is already substantial (architecture proposal, multi-step plan), still keep the search light. The point of the issue is to capture intent + just enough context, not to pre-solve it.

## Workflow

### 1. Understand the request
Read what the user said. Note the rough area of code involved. If genuinely ambiguous (could mean two very different things), ask one clarifying question — otherwise proceed.

### 2. Brief code search
Spend a small amount of effort orienting:
- `gh repo view --json nameWithOwner -q .nameWithOwner` to confirm the repo (don't assume).
- One or two targeted `grep`/`Glob` calls for the symbols, files, or concepts the user named.
- Read 1–2 of the most relevant files to confirm current state.
- For Dojo specifically: cross-check against [CLAUDE.md](../../../CLAUDE.md)'s directory map and "open questions" section — it often already has the context.

Stop searching once you have enough to write file/line references confidently. Resist going deeper.

### 3. Draft the issue

Write directly into the `gh issue create` body. Structure:

```markdown
## Context
<2–4 sentences: what's the situation today, what's the relevant prior art, what changed that motivates this issue. Link 1–3 files using markdown links like [path](src/foo/bar.py) or with line refs [path](src/foo/bar.py#L42).>

## Goals
<numbered list of concrete, scoped outcomes>

## Non-goals (for this issue)
<bullet list — explicit things this issue is NOT trying to solve, to prevent scope creep. Especially important in Dojo: call out anything that would violate the single-tenant / open-core / BYO-pipeline positioning.>

## Notes / open questions
<bullet list of anything the implementer should know but isn't decided yet — schema choices, alternatives considered, related code paths>

## Acceptance
<bulleted checklist of what "done" looks like, including tests where applicable>
```

Sections are guidance, not a rigid template — drop ones that don't apply. Don't pad. A 15-line issue that reads cleanly beats a 60-line one full of restated obvious context.

### 4. Title

Imperative, ≤70 chars, no trailing period. Match the style of recent issue titles in the repo if there's a clear convention.

Good: `Properly build the knowledge atom store + LLMLinker (grep-friendly structure)`
Bad: `Knowledge atoms` / `Fix the thing with knowledge` / `Build a complete redesign of the entire knowledge subsystem with vector search and multi-tenant support`

### 5. Create the issue

```bash
gh issue create --repo <owner>/<repo> --title "<title>" --body "$(cat <<'EOF'
<body>
EOF
)"
```

Always pass the body via heredoc so markdown formatting survives.

If the repo has labels that obviously fit (e.g. `bug`, `enhancement`), add `--label`. Don't invent labels — only use ones that exist (`gh label list` if unsure, but skip if you don't already know).

### 6. Report back

Return the issue URL and a one-line summary of what was filed. The user can click through if they want to verify.

## Speed budget

This whole skill should typically finish in **a few tool calls**. If you find yourself reading >5 files or doing exhaustive searches, stop — that's a signal the user wanted solve-issue, not create-issue. Either ship a lean issue and let solve-issue do the deep dive, or surface the question to the user.

## Why this matters

The whole workflow (issue → plan → PR) only works if the issue is good enough that the next phase can pick it up without you re-explaining. Aim for: a stranger reading the issue + the linked files could understand the problem and start work. No more, no less.
