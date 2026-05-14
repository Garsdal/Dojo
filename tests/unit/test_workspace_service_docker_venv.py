"""Unit tests for the docker venv path in WorkspaceService.

When `sandbox.backend == "docker"`, WorkspaceService.setup() must build
`.venv-docker/` inside the configured image and publish that as the
workspace's interpreter. The build happens via a stubbed
`asyncio.create_subprocess_exec` so these tests don't require a Docker
daemon — live coverage is in
[tests/integration/test_docker_sandbox_integration.py].
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dojo.config.settings import SandboxSettings
from dojo.core.domain import Domain, DomainStatus, Workspace, WorkspaceSource
from dojo.runtime.workspace_service import WorkspaceService


class _FakeProc:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _make_domain(ws_path: Path) -> Domain:
    return Domain(
        name="t",
        description="",
        status=DomainStatus.ACTIVE,
        workspace=Workspace(source=WorkspaceSource.LOCAL, path=str(ws_path)),
    )


async def test_docker_backend_builds_venv_docker_and_publishes_python_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Workspace with a pyproject so the uv flow fires.
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
    # Pre-existing host venv so `_ensure_python_env` short-circuits — we want
    # to focus the test on the docker-venv step.
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")

    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        # The docker venv build call lands as `docker run ... bash -lc <cmd>`.
        # Simulate the resulting on-disk state so the post-check passes.
        if argv[0] == "docker" and "bash" in argv:
            (tmp_path / ".venv-docker" / "bin").mkdir(parents=True, exist_ok=True)
            (tmp_path / ".venv-docker" / "bin" / "python").write_text("#!/bin/sh\n")
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    svc = WorkspaceService(
        tmp_path / ".dojo",
        sandbox_settings=SandboxSettings(backend="docker", image="python:3.11-slim"),
    )
    ws = await svc.setup(_make_domain(tmp_path))

    assert ws.python_path == str(tmp_path / ".venv-docker" / "bin" / "python")
    assert ws.ready
    # The docker run was issued with the configured image and the right cwd
    # bind-mount.
    docker_calls = [a for a in invocations if a[0] == "docker" and "bash" in a]
    assert len(docker_calls) == 1
    call = docker_calls[0]
    assert "python:3.11-slim" in call
    assert f"{tmp_path}:{tmp_path}" in call


async def test_local_backend_does_not_invoke_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default `local` sandbox backend should never shell out to `docker`."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")

    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    svc = WorkspaceService(tmp_path / ".dojo")  # no sandbox_settings → local default
    ws = await svc.setup(_make_domain(tmp_path))

    assert ws.python_path == str(tmp_path / ".venv" / "bin" / "python")
    assert not any(call and call[0] == "docker" for call in invocations)


async def test_docker_venv_idempotent_when_already_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An existing `.venv-docker/bin/python` short-circuits the build."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    (tmp_path / ".venv-docker" / "bin").mkdir(parents=True)
    (tmp_path / ".venv-docker" / "bin" / "python").write_text("#!/bin/sh\n")

    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    svc = WorkspaceService(
        tmp_path / ".dojo",
        sandbox_settings=SandboxSettings(backend="docker"),
    )
    ws = await svc.setup(_make_domain(tmp_path))

    assert ws.python_path == str(tmp_path / ".venv-docker" / "bin" / "python")
    # No `docker run` invocation — the existing venv was reused.
    assert not any(a and a[0] == "docker" for a in invocations)


async def test_docker_venv_build_failure_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        # The docker venv build fails loud — no silent fallback to the host venv.
        if argv[0] == "docker" and "bash" in argv:
            return _FakeProc(stderr=b"uv: command not found\n", returncode=127)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    svc = WorkspaceService(
        tmp_path / ".dojo",
        sandbox_settings=SandboxSettings(backend="docker"),
    )
    with pytest.raises(RuntimeError, match="Failed to build"):
        await svc.setup(_make_domain(tmp_path))
