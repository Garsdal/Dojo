"""Tests for the auto-install retry loop in `dojo onboard`.

These cover the issue-#27 regressions:

1. If the workspace isn't ready (no `python_path` / `ready=False`), the loop
   refuses to start — we don't run tool generation against the sandbox's
   default interpreter and we never prompt the user to install into a venv
   that doesn't exist.
2. If the workspace becomes un-ready mid-loop, we bail out before the
   `Confirm.ask` so we never ask a question we can't honour.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from dojo.cli import onboard as onboard_mod
from dojo.cli._lab import build_cli_lab
from dojo.cli.onboard import _generate_and_verify_with_retries, _workspace_is_ready
from dojo.core.domain import Domain, DomainStatus, Workspace, WorkspaceSource


def _make_unready_domain(tmp_path: Path) -> Domain:
    return Domain(
        name="t",
        description="",
        status=DomainStatus.ACTIVE,
        workspace=Workspace(
            source=WorkspaceSource.LOCAL,
            path=str(tmp_path),
            python_path=None,
            ready=False,
        ),
    )


def _make_ready_domain(tmp_path: Path) -> Domain:
    return Domain(
        name="t",
        description="",
        status=DomainStatus.ACTIVE,
        workspace=Workspace(
            source=WorkspaceSource.LOCAL,
            path=str(tmp_path),
            python_path=str(tmp_path / ".venv" / "bin" / "python"),
            ready=True,
        ),
    )


def test_workspace_is_ready_requires_python_path_and_ready_flag(tmp_path: Path) -> None:
    assert _workspace_is_ready(_make_ready_domain(tmp_path))
    assert not _workspace_is_ready(_make_unready_domain(tmp_path))
    # Ready=True but no python_path also counts as not-ready.
    d = _make_ready_domain(tmp_path)
    assert d.workspace is not None
    d.workspace.python_path = None
    assert not _workspace_is_ready(d)


async def test_retry_loop_refuses_to_start_when_workspace_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pre-flight guard: if the workspace isn't ready, the retry loop must
    return False *without* calling `_do_generate` or prompting the user.
    Previously we'd let tool gen + verification proceed against the docker
    image's default python and surface a misleading ModuleNotFoundError."""
    monkeypatch.setenv("DOJO_STORAGE__BASE_DIR", str(tmp_path / ".dojo"))
    monkeypatch.setenv("DOJO_AGENT__BACKEND", "stub")
    lab, _settings = build_cli_lab()
    domain = _make_unready_domain(tmp_path)
    await lab.domain_store.save(domain)

    generate_calls: list[Any] = []

    async def fake_do_generate(*args: Any, **kwargs: Any) -> list[Any]:
        generate_calls.append((args, kwargs))
        return []

    confirm_calls: list[Any] = []

    def fake_confirm(*args: Any, **kwargs: Any) -> bool:
        confirm_calls.append((args, kwargs))
        return True

    monkeypatch.setattr(onboard_mod, "_do_generate", fake_do_generate)
    monkeypatch.setattr(onboard_mod.Confirm, "ask", fake_confirm)

    success = await _generate_and_verify_with_retries(lab=lab, domain=domain)

    assert success is False
    assert generate_calls == [], "must not run tool generation when workspace isn't ready"
    assert confirm_calls == [], "must not prompt the user when we can't honour their yes"


async def test_retry_loop_skips_install_prompt_when_workspace_becomes_unready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If `_do_generate` reports a missing module but the on-disk workspace
    state has `python_path=None`, the loop must skip the install prompt and
    print the workspace-not-ready help instead. Defends against a workspace
    being un-set between attempts (e.g. user edits config.yaml mid-run)."""
    monkeypatch.setenv("DOJO_STORAGE__BASE_DIR", str(tmp_path / ".dojo"))
    monkeypatch.setenv("DOJO_AGENT__BACKEND", "stub")
    lab, _settings = build_cli_lab()

    # Seed an in-memory ready domain so the pre-flight guard passes…
    domain = _make_ready_domain(tmp_path)
    # …but persist an UN-ready version, so when the loop refreshes from disk
    # before the install prompt it discovers the workspace can't be touched.
    persisted = _make_unready_domain(tmp_path)
    persisted.id = domain.id
    await lab.domain_store.save(persisted)

    # `_do_generate` returns one tool that failed verification with a missing
    # module — exactly the path that previously triggered the broken prompt.
    class _FakeVerification:
        verified = False
        errors: ClassVar[list[str]] = [
            "load_data raised at load_data.py:1: No module named 'sklearn'"
        ]

    class _FakeTool:
        verification = _FakeVerification()

    async def fake_do_generate(*args: Any, **kwargs: Any) -> list[Any]:
        return [_FakeTool()]

    confirm_calls: list[Any] = []

    def fake_confirm(*args: Any, **kwargs: Any) -> bool:
        confirm_calls.append((args, kwargs))
        return True

    monkeypatch.setattr(onboard_mod, "_do_generate", fake_do_generate)
    monkeypatch.setattr(onboard_mod.Confirm, "ask", fake_confirm)

    success = await _generate_and_verify_with_retries(lab=lab, domain=domain)

    assert success is False
    assert confirm_calls == [], "must not prompt when refreshed workspace has no python_path"
