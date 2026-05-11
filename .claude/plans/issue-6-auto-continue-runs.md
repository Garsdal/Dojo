# Issue #6: Auto-continue agent runs so overnight sessions don't terminate early

**Issue:** https://github.com/Garsdal/Dojo/issues/6
**Branch (will be created in Phase 2):** `feat/issue-6-auto-continue-runs`
**Status:** awaiting review

## Summary

`dojo run` currently runs `backend.execute()` once. When the agent decides "my work is done" the SDK stream ends, we mark the run COMPLETED, and flush knowledge — even if `max_turns` / `max_budget_usd` are nowhere near exhausted. Make the orchestrator drive a **continuation loop**: when an iteration ends naturally and budget remains, reconfigure the backend and run another iteration. Track turn / cost budgets cumulatively on the `AgentRun`, add a wall-clock budget, and **flush knowledge only once at final termination** (over the full multi-iteration transcript) so we don't multiply the atom/link cost by N iterations.

## Files to change

| File | Change |
|---|---|
| [src/dojo/agents/types.py](src/dojo/agents/types.py) | Add `cumulative_turns`, `cumulative_cost_usd`, `iteration_count` to `AgentRun`. Add `max_wall_clock_s` to `AgentRunConfig`. |
| [src/dojo/config/settings.py](src/dojo/config/settings.py) | Add `max_wall_clock_s: float \| None = None` and `auto_continue: bool = True` to `AgentSettings`. Bump `max_turns` default from 50 → 500 (overnight-shaped default; short runs still bounded by `dojo stop`). |
| [src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py) | Refactor `execute()` into an outer continuation loop wrapping a `_run_iteration()` method. Track cumulative budgets, decide whether to continue after each iteration, reconfigure the backend with `remaining_turns` / `remaining_budget` between iterations. Knowledge flush stays in the outer `finally`. Add `mark_stop_requested` check + `_should_continue()` predicate. |
| [src/dojo/agents/summarizer.py](src/dojo/agents/summarizer.py) | Change `transcript[:8000]` → keep the **tail** (last 8000 chars). For a 10-iteration overnight run the findings live near the end; head-truncating throws the durable lessons away. |
| [src/dojo/agents/prompts.py](src/dojo/agents/prompts.py) | One small dose of option (2) from the issue: add a short paragraph clarifying that **the framework decides when the run ends**, not the agent — keep queuing the next hypothesis until tools refuse. No prompt should ever say "you're done"; the only termination signal the agent gets is budget exhaustion or `dojo stop`. |
| [src/dojo/cli/run.py](src/dojo/cli/run.py) | Render new `continuation_started` event in `_print_event` ("[dim]continuing — N turns / $X.YY of budget remaining[/dim]"). Also accept a new `--max-wall-clock-s` CLI option (mirrors settings). |
| [tests/unit/test_orchestrator.py](tests/unit/test_orchestrator.py) | Add `TestContinuationLoop` class covering: continues when budget remains; terminates on each axis (turns / cost / wall-clock); stops on `dojo stop` signal mid-loop; **knowledge flushed exactly once** across iterations; `is_error=True` result halts the loop; backend `error` event halts the loop. |
| [tests/unit/test_summarizer.py](tests/unit/test_summarizer.py) | Add a test that very long transcripts keep the tail content, not the head. |
| [CHANGELOG.md](CHANGELOG.md) | New `## [v0.0.19]` section. `### Agent prompts` populated (small no-self-terminate paragraph). `### Added` for continuation loop + wall-clock budget. `### Changed` for default `max_turns` bump and summarizer tail-truncation. |
| [pyproject.toml](pyproject.toml) | Bump `version` to `0.0.19`. |

## Approach

### 1. State plumbing (small, isolated)

Add to `AgentRun`:

```python
@dataclass
class AgentRun:
    ...
    cumulative_turns: int = 0
    cumulative_cost_usd: float = 0.0
    iteration_count: int = 0
```

Add to `AgentRunConfig`:

```python
max_wall_clock_s: float | None = None
```

Add to `AgentSettings`:

```python
max_turns: int = 500              # was 50
max_budget_usd: float | None = None
max_wall_clock_s: float | None = None  # new
auto_continue: bool = True             # new — explicit kill switch
```

`max_turns=500` is a default for the overnight shape the issue is solving. Short interactive runs are *not* hurt — the agent never reaches 500 turns in a 10-minute session anyway, and the user can interrupt with `dojo stop` / Ctrl-C at any time.

### 2. Orchestrator refactor

Split `execute()` into:

- `execute(run)` — the outer entry point. Drives the loop, holds the cumulative state, runs the flush in `finally`.
- `_run_one_iteration(run)` — the body of today's `execute()` minus the flush. Consumes the backend stream, transitions terminal status, returns whether the iteration ended *naturally* (clean stream end, no stop/error).

Loop sketch:

```python
async def execute(self, run):
    started_at = time.monotonic()
    stop_watcher = asyncio.create_task(self._watch_for_stop_signal(run.id))
    try:
        while True:
            run.iteration_count += 1
            ended_naturally = await self._run_one_iteration(run)
            self._absorb_iteration_budget(run)   # roll result.turns / cost_usd into cumulative_*

            if not ended_naturally:
                break                            # error / stop / is_error already set run.status
            if not self._should_continue(run, started_at):
                break                            # budget exhausted — keep COMPLETED status

            await self._prepare_continuation(run, started_at)  # rebuild prompt, reconfigure backend
            run.events.append(AgentEvent(
                event_type="continuation_started",
                data={
                    "iteration": run.iteration_count + 1,
                    "remaining_turns": self._remaining_turns(run),
                    "remaining_budget_usd": self._remaining_budget(run),
                    "elapsed_s": time.monotonic() - started_at,
                },
            ))
    finally:
        # (existing) stop_watcher cleanup
        # (existing) flush_knowledge — runs once over the entire run.events
        # (existing) run_finalized sentinel
```

`_should_continue` returns False when **any** of:
- `self._stop_requested`
- `run.status != RUNNING` after the iteration (defensive; covers FAILED/STOPPED that slipped through `ended_naturally`)
- `auto_continue` is False (kill switch)
- `cumulative_turns >= max_turns` (or within a small floor, e.g. 5 — no point continuing if we can't even do a baseline)
- `max_budget_usd is not None and cumulative_cost_usd >= max_budget_usd`
- `max_wall_clock_s is not None and elapsed >= max_wall_clock_s`

`_prepare_continuation`:
- Reload domain (knowledge atoms may have changed mid-run via `write_knowledge`).
- Rebuild `system_prompt` via `build_system_prompt(run, domain=..., accumulated_knowledge=...)` — the agent gets the latest atoms it wrote.
- Build a fresh `AgentRunConfig` with `max_turns=remaining_turns`, `max_budget_usd=remaining_budget` so the SDK enforces the cumulative cap mid-iteration as well as between iterations.
- Call `backend.configure(tool_defs, config)` again. (Claude backend constructs a new `ClaudeSDKClient` in `configure` — exactly what we want; the prior client is discarded and a fresh session starts.)
- Tool defs don't change, so we cache them on the orchestrator at first `start()`.

The **continuation prompt** for the next `execute(prompt)` call: reuse `run.prompt` (the original PROGRAM.md goal). The agent doesn't need a special "you were continuing" message — accumulated knowledge in the system prompt is the seam. Keeps the design simple.

### 3. Knowledge flush — the scalability fix

Current state: `flush_run_knowledge` runs once at the end of `execute()`, extracts up to 7 atoms, and each atom write triggers `produce_knowledge` → CREATED_BY + RELATED_TO link creation. With `LLMKnowledgeLinker` that's 7 LLM calls. Doing this every iteration in a 20-hour overnight loop = 100+ atoms and 100+ extra LLM calls — exactly what the user flagged.

**Fix:** keep the flush in the outer `finally` (i.e. **once per run, not per iteration**). Because `run.events` accumulates across iterations (we never reset it), the final flush sees the full multi-iteration transcript and produces one summary covering the whole overnight session. Total cost stays at ≤7 atoms + ≤7 linker calls regardless of iteration count.

The agent still writes atoms in-loop via the `write_knowledge` tool — that's the high-fidelity primary channel. The end-of-run flush is the safety net for findings the agent didn't capture.

Companion fix in [summarizer.py](src/dojo/agents/summarizer.py): switch `transcript[:8000]` to a tail-take (`transcript[-8000:]`). On a long run the first 8000 chars are early baseline scaffolding; the findings live at the end. Optional refinement (mentioned in Risks): keep the first ~500 chars as a "run goal" header plus the last ~7500 chars. I'll start with a pure tail-take; the head-context value is small and the prompt already includes the PROGRAM.md goal indirectly.

### 4. Wall-clock enforcement

Checked between iterations only (cheap, no separate task). If a single iteration runs longer than `max_wall_clock_s`, we'll overshoot until it ends — fine, since the SDK already terminates the iteration on `max_turns`/`max_budget_usd` and overnight wall-clock budgets are coarse anyway. No need for a separate cancel task.

If we ever need hard mid-iteration enforcement, extend the existing `_watch_for_stop_signal` task to also watch the clock. Out of scope here.

### 5. Stop signal across iterations

`_watch_for_stop_signal` already polls `run_store.is_stop_requested`. It calls `backend.stop()` and sets `self._stop_requested`. After interrupt, the current iteration ends (error or natural). The loop's `_should_continue` short-circuits on `self._stop_requested` → exits. Knowledge flush in `finally` still runs.

SIGINT path (Ctrl-C) sets `_stop_requested` via the CLI's signal handler → same flow.

### 6. Prompt nudge (small dose of option 2)

In [prompts.py](src/dojo/agents/prompts.py), add a short paragraph near the workflow section:

> ### Termination
> The framework owns when the run ends — not you. There is a turn / dollar / wall-clock budget enforced by the runtime; until those are hit (or the user runs `dojo stop`), keep proposing the next hypothesis. Never end the loop with a "done" message — there is always a next experiment worth queuing.

This is the issue's recommended "small dose of (2)" alongside the structural fix (1). Cheap; complements the loop rather than replacing it.

### 7. CLI surface

Render `continuation_started` in [cli/run.py](src/dojo/cli/run.py) `_print_event`:

```python
elif et == "continuation_started":
    rem_turns = data.get("remaining_turns")
    rem_budget = data.get("remaining_budget_usd")
    budget_str = f", ${rem_budget:.2f}" if rem_budget is not None else ""
    console.print(
        f"[dim]↻ continuing iteration {data.get('iteration', '?')} "
        f"(remaining: {rem_turns} turns{budget_str})[/dim]"
    )
```

Add `--max-wall-clock-s` CLI option mirroring settings.

## Tests

New `TestContinuationLoop` in [tests/unit/test_orchestrator.py](tests/unit/test_orchestrator.py):

1. **`test_continues_when_budget_remains`** — Stub backend yields a natural-end result with `turns=5, cost_usd=0.1` and is configured for a second iteration. After execute(), `iteration_count >= 2` and a `continuation_started` event is in `run.events`.
2. **`test_terminates_on_max_turns`** — `max_turns=10`; iteration reports 10 turns. Loop exits. Run status COMPLETED.
3. **`test_terminates_on_max_budget`** — `max_budget_usd=0.5`; iteration reports cost 0.5. Loop exits.
4. **`test_terminates_on_wall_clock`** — Patch `time.monotonic` or pass a near-zero `max_wall_clock_s`. After one iteration, loop exits.
5. **`test_stop_signal_breaks_loop`** — Mid-loop `dojo stop` sentinel triggers; orchestrator does not start a new iteration. Status STOPPED. (Reuses the `_SlowBackend` pattern already in the file.)
6. **`test_error_event_halts_loop`** — Iteration yields error event; loop doesn't continue. Status FAILED.
7. **`test_is_error_result_halts_loop`** — Result event with `is_error=True` halts the loop.
8. **`test_knowledge_flushed_exactly_once`** — Use `_CompletingStubBackend` that counts `complete()` calls. Run a 3-iteration loop. Assert `complete_calls == 1` (one flush at end), not 3.
9. **`test_auto_continue_false_runs_once`** — `auto_continue=False` skips the loop entirely. Backwards-compatible kill switch.
10. **`test_cumulative_budgets_passed_to_backend`** — Verify the backend's second `configure()` receives `max_turns=remaining` not the original full amount.

New test in [tests/unit/test_summarizer.py](tests/unit/test_summarizer.py):

11. **`test_long_transcript_keeps_tail`** — Build an `events` list whose `collect_transcript()` produces ≫8000 chars where the durable finding is in the last event. Assert the prompt the backend sees contains the tail content (and not just the head scaffolding).

Existing tests: I'll verify all of [test_orchestrator.py](tests/unit/test_orchestrator.py)'s `TestEndOfRunKnowledgeFlush` cases still pass — the flush moves from "after the single execute" to "after the loop", which is the same semantics for single-iteration runs.

Acceptance criteria from the issue mapped to tests:

| Issue checkbox | Test |
|---|---|
| Keeps iterating after agent says "done" until budget | (1) |
| Continuations seeded with prior knowledge | covered indirectly by (1) — domain reload + system-prompt rebuild |
| Defaults tuned for overnight without breaking short runs | default change + (9) covers kill-switch path |
| `dojo stop` + `run_finalized` still correct across boundary | (5), plus the existing `run_finalized` sentinel test continues to pass |
| Tests on each budget axis | (2), (3), (4) |
| `### Agent prompts` changelog entry | yes — prompts.py changes |

## Risks / open questions

- **`max_turns=500` default.** A jump from 50 to 500. The agent never *reaches* 500 in a normal interactive session, so this only matters for budget-exhausted termination. Want to check: are you good with 500, or want a different number (200? 1000?)?
  - *Alternative:* leave `max_turns=50` and rely on continuations (each iteration is bounded by 50, total is unbounded). Cleaner — the loop *is* the way to extend. I lean toward this actually. **Will default to leaving `max_turns=50` and document the loop as the answer**, unless you want the bigger number.

- **Wall-clock granularity.** Checked between iterations only. If one iteration runs 6 hours and `max_wall_clock_s=4h`, you'll get ~6h. For overnight runs this is fine; tell me if you want hard mid-iteration enforcement.

- **Transcript head-vs-tail truncation.** Pure tail-take is the simplest fix. If you'd prefer "head 500 + tail 7500" to preserve early baseline context, I can do that — but the system prompt already has the run's PROGRAM.md goal, so I don't think the head adds much.

- **`backend.configure()` reuse.** Calling `configure()` again creates a new `ClaudeSDKClient`. The old one is GC'd. The Claude SDK should be fine with this (the existing `stop()` already implies the client can be discarded). One thing to validate: that interrupting a *new* client mid-loop works. I'll add an integration-style test using the StubAgent if Claude SDK testing is out of reach.

- **`iteration_count` persistence.** Lives on `AgentRun`. Will surface naturally in `runs show` once the field is in the JSON.

- **MLflow / tracking.** `result` events feed cost/turn data into the existing tracking flow. With continuations we get multiple `result` events — each iteration logs its own cost. That's actually nice (per-iteration cost breakdown) but I should confirm `MlflowTracker` doesn't barf on a "second result for the same run". I'll check during implementation; if it does, accumulate locally and only emit a synthetic final result.

## Out of scope

(Mirroring the issue's non-goals + a few I noticed.)

- Distributed / cloud orchestration.
- A scheduler or queue.
- Forcing users to write "do not stop" into PROGRAM.md.
- Changing what counts as a successful experiment.
- Reworking the `KnowledgeLinker` interface or the atom schema.
- Persisting session state between separate `dojo run` invocations (each `dojo run` is still one logical run; continuation happens within it).
- Hard mid-iteration wall-clock cancellation.

## Release notes

`## [v0.0.19] - <date>`:

**### Agent prompts** — added a "Termination" paragraph in [src/dojo/agents/prompts.py](src/dojo/agents/prompts.py) clarifying that the framework owns when the run ends; the agent should keep queuing hypotheses until the runtime stops it. Complements the new continuation loop.

**### Added** — continuation loop in [src/dojo/agents/orchestrator.py](src/dojo/agents/orchestrator.py): `dojo run` now auto-continues after a natural stream end until `max_turns`, `max_budget_usd`, `max_wall_clock_s`, or `dojo stop` is hit. New `max_wall_clock_s` setting + `--max-wall-clock-s` CLI flag. Continuation events render in the CLI stream. `AgentRun` tracks `cumulative_turns`, `cumulative_cost_usd`, `iteration_count` (visible in `dojo runs show`).

**### Changed** — knowledge flush now runs once at the *end of the loop* over the full multi-iteration transcript instead of after every iteration, keeping atom + linker cost flat regardless of how long the agent runs. The summarizer's transcript truncation switched from head-take to tail-take so durable findings near the end of long runs survive.

**### Fixed** — N/A.

(`Removed` — N/A.)
