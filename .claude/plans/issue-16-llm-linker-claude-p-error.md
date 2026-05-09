# Issue #16: LLM linker silently falls back to keyword when run inside Claude Code

**Issue:** https://github.com/Garsdal/Dojo/issues/16
**Branch (Phase 2):** `fix/issue-16-claude-complete-nested-session`
**Status:** awaiting review

## Summary

`ClaudeAgentBackend.complete()` shells out to `claude -p` but (a) only includes stderr in its `RuntimeError`, and (b) inherits `CLAUDECODE` from the parent shell. When `dojo run` is launched from a Claude Code terminal, `claude -p` hits its nested-session guard and writes the real error to **stdout** with empty stderr — so every LLM-linker call past the first silently falls back to the keyword heuristic with an unhelpful `error=''` log line. Fix: include stdout in the error, and unset `CLAUDECODE` for the subprocess.

## Files to change

| File | Change |
|---|---|
| [src/dojo/agents/backends/claude.py](src/dojo/agents/backends/claude.py) | In `complete()`: build subprocess env without `CLAUDECODE`; include both stdout and stderr in `RuntimeError`. |
| [tests/unit/test_claude_model_flag.py](tests/unit/test_claude_model_flag.py) | Add two tests: failing subprocess surfaces stdout in the exception; subprocess env strips `CLAUDECODE`. (Same file already exercises `complete()` via `monkeypatch` — keep tests grouped here rather than spawning a new file.) |
| [pyproject.toml](pyproject.toml) | Bump `0.0.16` → `0.0.17`. |
| [CHANGELOG.md](CHANGELOG.md) | New `## [v0.0.17]` section with `### Agent prompts (none in this release)` + `### Fixed`. |

## Approach

1. In `complete()`, derive a child env: `env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}` and pass it as `env=env` to `asyncio.create_subprocess_exec`. This is the smallest change that prevents the nested-session block — the `claude -p` invocation is genuinely a fresh, intentional shell-out, not a nested session.
2. In the same function, change the error to:
   ```python
   raise RuntimeError(
       f"claude -p failed (exit {proc.returncode}): "
       f"{(stderr.decode().strip() or stdout.decode().strip())!r}"
   )
   ```
   Stderr-first preserves existing behaviour for backends that do write to stderr; stdout fallback rescues the nested-session case (and any other claude-CLI errors that print to stdout).
3. Add unit tests next to the existing `test_complete_*` functions, using the same `monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)` pattern. Two new tests:
   - `test_complete_error_includes_stdout`: `_FakeProc` returns `returncode=1`, stdout=b"some error", stderr=b""; assert raised `RuntimeError` contains `"some error"`.
   - `test_complete_strips_claudecode_from_env`: monkeypatch `os.environ["CLAUDECODE"] = "1"`, capture the `env=` kwarg, assert `"CLAUDECODE"` is absent.
4. Bump version to `0.0.17` (patch bump — small bug fix). Add CHANGELOG entry under `### Fixed` — `### Agent prompts (none in this release)` first per the repo convention.
5. `just test && just lint` green; push branch; open PR with `Closes #16`.

## Tests

- New unit tests cover both behaviours in [tests/unit/test_claude_model_flag.py](tests/unit/test_claude_model_flag.py).
- Existing `test_complete_*` tests continue to pass (their `_FakeProc` returns `returncode=0`, so the new error path doesn't fire).
- Existing tests don't pass `env=` so we need to make sure passing `env=` doesn't break the model-flag tests — quick check: their `_fake_exec` accepts `**kwargs`, so it does.
- No integration test needed — the failure mode is environmental (parent shell env), not exercisable in tmp-dir integration tests.

## Risks / open questions

- **Are there cases where `CLAUDECODE` is genuinely needed by the child `claude -p`?** The CLI's check is "you're inside another Claude session, don't fork" — that's exactly what we want to bypass for one-shot completions. The agent run via `ClaudeSDKClient` (a separate path) is unaffected.
- **Should we also strip other inherited Claude vars?** No — limiting the change to `CLAUDECODE` keeps the diff narrow and matches the CLI's own bypass instruction (`To bypass this check, unset the CLAUDECODE environment variable`). If other vars cause trouble later, file a follow-up.
- **Stderr vs stdout precedence** — keeping `stderr or stdout` (rather than concatenating) avoids noisy duplicate output when both are written and matches the user's mental model of "one error message".

## Out of scope

- Retry/backoff for transient `claude` CLI failures.
- Switching `complete()` to a non-CLI implementation (Anthropic SDK, etc.).
- Broader subprocess env scrubbing.
- Surfacing LLM-linker fallback frequency in run summaries.

## Release notes

CHANGELOG `## [v0.0.17] - 2026-05-09`:

```
### Agent prompts

(none in this release)

### Fixed

- **`ClaudeAgentBackend.complete()`** ([src/dojo/agents/backends/claude.py](src/dojo/agents/backends/claude.py)) — when invoked from inside a Claude Code shell, `claude -p` rejects the call with its nested-session guard, writing the error to stdout and leaving stderr empty. The subprocess wrapper now (1) strips `CLAUDECODE` from the child env so the guard doesn't trip, and (2) includes stdout in the `RuntimeError` when stderr is empty so users see the actual error. Affects `LLMKnowledgeLinker`, the end-of-run summarizer, and `dojo task setup` tool generation. (#16)
```
