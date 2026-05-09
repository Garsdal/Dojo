"""Tests that ClaudeAgentBackend forwards --model to the `claude` CLI."""

from __future__ import annotations

from typing import Any

import pytest

from dojo.agents.backends.claude import ClaudeAgentBackend
from dojo.agents.factory import create_agent_backend


def test_backend_default_no_model():
    b = create_agent_backend("claude")
    assert isinstance(b, ClaudeAgentBackend)
    assert b.model is None


def test_backend_carries_model_from_factory():
    b = create_agent_backend("claude", model="claude-sonnet-4-6")
    assert isinstance(b, ClaudeAgentBackend)
    assert b.model == "claude-sonnet-4-6"


async def test_complete_passes_model_flag_when_set(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b'{"ok": true}', b"")

    async def _fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        return _FakeProc()

    import asyncio

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    b = ClaudeAgentBackend(model="claude-sonnet-4-6")
    out = await b.complete("hello")
    assert out == '{"ok": true}'
    assert captured["argv"][0] == "claude"
    assert "--model" in captured["argv"]
    model_idx = captured["argv"].index("--model")
    assert captured["argv"][model_idx + 1] == "claude-sonnet-4-6"
    # Prompt must come after the model flag
    assert "hello" in captured["argv"]


async def test_complete_omits_model_flag_when_unset(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"ok", b"")

    async def _fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        return _FakeProc()

    import asyncio

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    b = ClaudeAgentBackend()
    await b.complete("p")
    assert "--model" not in captured["argv"]


async def test_complete_error_falls_back_to_stdout(monkeypatch: pytest.MonkeyPatch):
    """When `claude -p` writes the error to stdout (e.g. nested-session guard),
    the RuntimeError should still include it instead of an empty string."""

    class _FakeProc:
        returncode = 1

        async def communicate(self):
            return (b"Error: nested session not allowed", b"")

    async def _fake_exec(*argv, **kwargs):
        return _FakeProc()

    import asyncio

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    b = ClaudeAgentBackend()
    with pytest.raises(RuntimeError, match="nested session not allowed"):
        await b.complete("p")


async def test_complete_strips_claudecode_from_subprocess_env(monkeypatch: pytest.MonkeyPatch):
    """Even if the parent process has CLAUDECODE set (e.g. dojo invoked from a
    Claude Code shell), the `claude -p` subprocess must not inherit it — that
    would trip the CLI's nested-session guard."""
    captured: dict[str, Any] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"ok", b"")

    async def _fake_exec(*argv, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeProc()

    import asyncio

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    b = ClaudeAgentBackend()
    await b.complete("p")
    assert captured["env"] is not None, "subprocess must be invoked with an explicit env"
    assert "CLAUDECODE" not in captured["env"]
