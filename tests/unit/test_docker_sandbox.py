"""Unit tests for DockerSandbox — argv construction, OOM marker, cleanup.

These tests stub out `asyncio.create_subprocess_exec` so they run without a
real Docker daemon. Live integration coverage lives in
[tests/integration/test_docker_sandbox_integration.py].

The venv-rebuild flow is a *workspace* concern and is tested in
[tests/unit/test_workspace_service_docker_venv.py]; the sandbox itself just
runs whatever `python_path` it's handed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dojo.sandbox.docker import DockerSandbox


class _FakeProc:
    """Minimal stand-in for `asyncio.subprocess.Process`."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        hang: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(60)
        return self._stdout, self._stderr


class _Capture:
    """Records argv and yields configurable fake procs."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._factory: Any = lambda argv: _FakeProc()

    def set_factory(self, factory: Any) -> None:
        self._factory = factory

    async def __call__(self, *argv: str, **_: Any) -> _FakeProc:
        self.calls.append(list(argv))
        return self._factory(list(argv))


@pytest.fixture
def argv_capture(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", cap)
    return cap


async def test_argv_contains_resource_limits_and_mount(
    argv_capture: _Capture, tmp_path: Path
) -> None:
    sandbox = DockerSandbox(
        image="python:3.11-slim",
        memory_limit="8g",
        cpu_limit="4",
        network="bridge",
    )
    await sandbox.execute("print('x')", cwd=str(tmp_path), name="probe")

    argv = argv_capture.calls[0]
    assert argv[0] == "docker"
    assert "--rm" in argv
    assert "--memory" in argv and argv[argv.index("--memory") + 1] == "8g"
    # `--memory-swap` mirrors `--memory` so swap is disabled — OOM kicks in at
    # the configured limit instead of silently spilling to swap.
    assert "--memory-swap" in argv and argv[argv.index("--memory-swap") + 1] == "8g"
    assert "--cpus" in argv and argv[argv.index("--cpus") + 1] == "4"
    assert "--network" in argv and argv[argv.index("--network") + 1] == "bridge"
    assert "-v" in argv and f"{tmp_path}:{tmp_path}" in argv
    assert "-w" in argv and argv[argv.index("-w") + 1] == str(tmp_path)
    assert "-e" in argv and "PYTHONUNBUFFERED=1" in argv
    assert "python:3.11-slim" in argv


async def test_default_image_is_311_slim(argv_capture: _Capture, tmp_path: Path) -> None:
    """`python:3.11-slim` matches the project's minimum supported Python; a
    workspace that targets 3.11+ never sees a newer-than-promised container
    Python."""
    sandbox = DockerSandbox()
    await sandbox.execute("print('x')", cwd=str(tmp_path))
    assert "python:3.11-slim" in argv_capture.calls[0]


async def test_argv_omits_memory_swap_when_no_memory_limit(
    argv_capture: _Capture, tmp_path: Path
) -> None:
    sandbox = DockerSandbox()
    await sandbox.execute("print('x')", cwd=str(tmp_path))
    argv = argv_capture.calls[0]
    assert "--memory" not in argv
    assert "--memory-swap" not in argv


async def test_argv_network_none_overrides_bridge(argv_capture: _Capture, tmp_path: Path) -> None:
    sandbox = DockerSandbox(network="none")
    await sandbox.execute("print('x')", cwd=str(tmp_path))
    argv = argv_capture.calls[0]
    assert argv[argv.index("--network") + 1] == "none"


async def test_argv_forwards_env_vars(argv_capture: _Capture, tmp_path: Path) -> None:
    sandbox = DockerSandbox()
    await sandbox.execute(
        "print('x')",
        cwd=str(tmp_path),
        env_vars={"DOJO_ARTIFACTS_DIR": "/work/artifacts", "FOO": "bar"},
    )
    argv = argv_capture.calls[0]
    assert "DOJO_ARTIFACTS_DIR=/work/artifacts" in argv
    assert "FOO=bar" in argv


async def test_argv_passes_python_path_verbatim(argv_capture: _Capture, tmp_path: Path) -> None:
    """Sandbox no longer rewrites python_path — venv concerns live in
    WorkspaceService."""
    sandbox = DockerSandbox()
    venv_python = str(tmp_path / ".venv-docker" / "bin" / "python")
    await sandbox.execute("print('x')", cwd=str(tmp_path), python_path=venv_python)
    argv = argv_capture.calls[0]
    img_idx = argv.index("python:3.11-slim")
    assert argv[img_idx + 1] == venv_python


async def test_argv_default_python_when_none(argv_capture: _Capture, tmp_path: Path) -> None:
    sandbox = DockerSandbox()
    await sandbox.execute("print('x')", cwd=str(tmp_path))
    argv = argv_capture.calls[0]
    img_idx = argv.index("python:3.11-slim")
    assert argv[img_idx + 1] == "python"


async def test_oom_exit_code_prepends_marker(argv_capture: _Capture, tmp_path: Path) -> None:
    argv_capture.set_factory(lambda argv: _FakeProc(stderr=b"MemoryError\n", returncode=137))
    sandbox = DockerSandbox(memory_limit="32m")
    result = await sandbox.execute("x = bytearray(1<<30)", cwd=str(tmp_path))
    assert result.exit_code == 137
    assert "OOMKilled" in result.stderr
    assert "32m" in result.stderr


async def test_exec_format_error_surfaces_clear_message(
    argv_capture: _Capture, tmp_path: Path
) -> None:
    """A host-built venv leaking into the container should surface a clear
    fix-it message pointing at `dojo domain setup`."""
    argv_capture.set_factory(
        lambda argv: _FakeProc(
            stderr=b"exec /work/.venv/bin/python: exec format error\n",
            returncode=126,
        )
    )
    sandbox = DockerSandbox()
    result = await sandbox.execute(
        "print('x')",
        cwd=str(tmp_path),
        python_path="/work/.venv/bin/python",
    )
    assert "dojo domain setup" in result.stderr
    assert ".venv-docker" in result.stderr


async def test_timeout_kills_container_and_returns_minus_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        if argv[:2] == ("docker", "run"):
            return _FakeProc(hang=True)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    sandbox = DockerSandbox(timeout=0.05)
    result = await sandbox.execute("import time; time.sleep(60)", cwd=str(tmp_path))
    assert result.exit_code == -1
    assert result.stderr == "Execution timed out"
    kill_calls = [argv for argv in invocations if argv[:2] == ["docker", "kill"]]
    assert len(kill_calls) == 1
    run_call = next(argv for argv in invocations if argv[:2] == ["docker", "run"])
    container_name = run_call[run_call.index("--name") + 1]
    assert container_name == kill_calls[0][2]


async def test_cleanup_kills_active_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    sandbox = DockerSandbox()
    sandbox._active_containers.update({"dojo-sandbox-aaa", "dojo-sandbox-bbb"})
    await sandbox.cleanup()
    kill_targets = {argv[2] for argv in invocations if argv[:2] == ["docker", "kill"]}
    assert kill_targets == {"dojo-sandbox-aaa", "dojo-sandbox-bbb"}
    assert sandbox._active_containers == set()


async def test_script_cleaned_up_after_run(argv_capture: _Capture, tmp_path: Path) -> None:
    sandbox = DockerSandbox()
    await sandbox.execute("print('x')", cwd=str(tmp_path), name="probe")
    assert not (tmp_path / "probe.py").exists()


async def test_unsupported_language_returns_clear_error(tmp_path: Path) -> None:
    sandbox = DockerSandbox()
    result = await sandbox.execute("oops", language="ruby", cwd=str(tmp_path))
    assert result.exit_code == 1
    assert "Unsupported language" in result.stderr
