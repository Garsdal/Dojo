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


# ---------------------------------------------------------------------------
# install_packages — the auto-install path used by `dojo onboard` after a
# verifier ModuleNotFoundError. Has to dispatch on `sandbox.backend` because
# the host can't execute `.venv-docker/bin/python` (Linux ELF on macOS).
# ---------------------------------------------------------------------------


def _ready_workspace(tmp_path: Path, python_path: str) -> Workspace:
    return Workspace(
        source=WorkspaceSource.LOCAL,
        path=str(tmp_path),
        python_path=python_path,
        ready=True,
    )


async def test_install_packages_docker_backend_runs_inside_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With docker backend, install must `docker run` against the configured
    image with the workspace bind-mounted at the same absolute path."""
    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    svc = WorkspaceService(
        tmp_path / ".dojo",
        sandbox_settings=SandboxSettings(backend="docker", image="python:3.11-slim"),
    )
    ws = _ready_workspace(tmp_path, str(tmp_path / ".venv-docker" / "bin" / "python"))
    result = await svc.install_packages(ws, ["scikit-learn", "polars"])

    assert result.ok, result.message
    assert len(invocations) == 1
    call = invocations[0]
    assert call[0] == "docker"
    assert call[1] == "run"
    assert "--rm" in call
    assert f"{tmp_path}:{tmp_path}" in call
    assert "python:3.11-slim" in call
    # The inner command must `uv pip install --python <path>` against the
    # docker venv, not the host venv. `scikit-learn` and `polars` should be in
    # the inner shell command somewhere.
    inner = call[-1]
    assert "uv pip install" in inner
    assert "--python " + str(tmp_path / ".venv-docker" / "bin" / "python") in inner
    assert "scikit-learn" in inner
    assert "polars" in inner


async def test_install_packages_local_backend_runs_uv_on_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default `local` backend installs on the host with
    `uv pip install --python <path>`. Regression: uv-managed venvs don't ship
    pip, so `python -m pip install` would crash with `No module named pip`."""
    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        "dojo.runtime.workspace_service.shutil.which",
        lambda name: "/fake/uv" if name == "uv" else None,
    )

    svc = WorkspaceService(tmp_path / ".dojo")  # default backend = local
    ws = _ready_workspace(tmp_path, str(tmp_path / ".venv" / "bin" / "python"))
    result = await svc.install_packages(ws, ["matplotlib"])

    assert result.ok, result.message
    assert len(invocations) == 1
    assert invocations[0] == [
        "/fake/uv",
        "pip",
        "install",
        "--python",
        str(tmp_path / ".venv" / "bin" / "python"),
        "matplotlib",
    ]


async def test_install_packages_local_backend_falls_back_to_python_pip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When uv isn't on PATH (rare), fall back to `python -m pip install`."""
    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr("dojo.runtime.workspace_service.shutil.which", lambda _: None)

    svc = WorkspaceService(tmp_path / ".dojo")
    ws = _ready_workspace(tmp_path, "/path/to/python")
    result = await svc.install_packages(ws, ["matplotlib"])

    assert result.ok
    assert invocations[0] == ["/path/to/python", "-m", "pip", "install", "matplotlib"]


async def test_install_packages_refuses_when_python_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No python_path = workspace not ready; return failure without invoking
    any subprocess. The caller should have caught this — install_packages is
    just a defence in depth."""
    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    svc = WorkspaceService(
        tmp_path / ".dojo",
        sandbox_settings=SandboxSettings(backend="docker"),
    )
    ws = Workspace(source=WorkspaceSource.LOCAL, path=str(tmp_path), python_path=None)
    result = await svc.install_packages(ws, ["scikit-learn"])

    assert not result.ok
    assert "python_path" in result.message
    assert invocations == []


async def test_install_packages_empty_modules_is_noop(tmp_path: Path) -> None:
    svc = WorkspaceService(tmp_path / ".dojo")
    ws = _ready_workspace(tmp_path, "/path/to/python")
    result = await svc.install_packages(ws, [])
    assert result.ok
