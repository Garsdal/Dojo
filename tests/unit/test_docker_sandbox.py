"""Unit tests for DockerSandbox — argv construction, OOM marker, cleanup, venv path.

These tests stub out `asyncio.create_subprocess_exec` so they run without a
real Docker daemon. Live integration coverage lives in
[tests/integration/test_docker_sandbox_integration.py].
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dojo.sandbox.docker import DockerSandbox, DockerVenvBuildError


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
    """Capture every `docker` argv passed through `asyncio.create_subprocess_exec`.

    Defaults to a `(stdout=b"", stderr=b"", returncode=0)` fake. Tests can swap
    the proc factory via `argv_capture.set_factory(...)`.
    """
    cap = _Capture()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", cap)
    return cap


async def test_argv_contains_resource_limits_and_mount(
    argv_capture: _Capture, tmp_path: Path
) -> None:
    sandbox = DockerSandbox(
        image="python:3.13-slim",
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
    assert "python:3.13-slim" in argv


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


async def test_argv_uses_explicit_python_path_when_not_a_host_venv(
    argv_capture: _Capture, tmp_path: Path
) -> None:
    sandbox = DockerSandbox()
    await sandbox.execute(
        "print('x')",
        cwd=str(tmp_path),
        python_path="/usr/local/bin/python3.11",
    )
    argv = argv_capture.calls[0]
    # Image is at a known index — the python path immediately follows.
    img_idx = argv.index("python:3.13-slim")
    assert argv[img_idx + 1] == "/usr/local/bin/python3.11"


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
    argv_capture.set_factory(
        lambda argv: _FakeProc(
            stderr=b"exec /work/.venv/bin/python: exec format error\n",
            returncode=126,
        )
    )
    sandbox = DockerSandbox(auto_rebuild_venv=False)
    result = await sandbox.execute(
        "print('x')",
        cwd=str(tmp_path),
        python_path="/usr/local/bin/python",
    )
    assert "auto_rebuild_venv" in result.stderr


async def test_timeout_kills_container_and_returns_minus_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        # The first call is `docker run` and hangs; the second is the kill.
        if argv[:2] == ("docker", "run"):
            return _FakeProc(hang=True)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    sandbox = DockerSandbox(timeout=0.05)
    result = await sandbox.execute("import time; time.sleep(60)", cwd=str(tmp_path))
    assert result.exit_code == -1
    assert result.stderr == "Execution timed out"
    # Sanity check: a `docker kill` was issued on timeout.
    kill_calls = [argv for argv in invocations if argv[:2] == ["docker", "kill"]]
    assert len(kill_calls) == 1
    # The kill target is the same container name that the run had.
    run_call = next(argv for argv in invocations if argv[:2] == ["docker", "run"])
    container_name = run_call[run_call.index("--name") + 1]
    assert container_name == kill_calls[0][2]


async def test_cleanup_kills_active_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


async def test_venv_rebuild_used_when_host_venv_python_passed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Pretend the user has a host `.venv/bin/python` and pyproject.toml.
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")

    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        # The venv-rebuild call uses `bash -lc <setup>`. Simulate success by
        # materialising the `.venv-docker/bin/python` it claims to produce.
        if "bash" in argv:
            (tmp_path / ".venv-docker" / "bin").mkdir(parents=True, exist_ok=True)
            (tmp_path / ".venv-docker" / "bin" / "python").write_text("#!/bin/sh\n")
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    sandbox = DockerSandbox()
    await sandbox.execute(
        "print('x')",
        cwd=str(tmp_path),
        python_path=str(tmp_path / ".venv" / "bin" / "python"),
    )

    # First call: venv build via `bash -lc`. Second call: the actual run,
    # with python path rewritten to `.venv-docker/bin/python`.
    bash_calls = [a for a in invocations if "bash" in a]
    assert len(bash_calls) == 1
    run_call = next(a for a in invocations if a[:2] == ["docker", "run"] and "bash" not in a)
    assert str(tmp_path / ".venv-docker" / "bin" / "python") in run_call


async def test_venv_rebuild_failure_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        return _FakeProc(stderr=b"uv: command not found\n", returncode=127)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    sandbox = DockerSandbox()
    with pytest.raises(DockerVenvBuildError, match="Failed to build"):
        await sandbox.execute(
            "print('x')",
            cwd=str(tmp_path),
            python_path=str(tmp_path / ".venv" / "bin" / "python"),
        )


async def test_venv_rebuild_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\nversion="0"\n')
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    # Pre-existing .venv-docker — the rebuild should not fire.
    (tmp_path / ".venv-docker" / "bin").mkdir(parents=True)
    (tmp_path / ".venv-docker" / "bin" / "python").write_text("#!/bin/sh\n")

    invocations: list[list[str]] = []

    async def fake_exec(*argv: str, **_: Any) -> _FakeProc:
        invocations.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    sandbox = DockerSandbox()
    await sandbox.execute(
        "print('x')",
        cwd=str(tmp_path),
        python_path=str(tmp_path / ".venv" / "bin" / "python"),
    )
    # No bash setup invocation — we reused the existing `.venv-docker/`.
    assert not any("bash" in a for a in invocations)


async def test_unsupported_language_returns_clear_error(tmp_path: Path) -> None:
    sandbox = DockerSandbox()
    result = await sandbox.execute("oops", language="ruby", cwd=str(tmp_path))
    assert result.exit_code == 1
    assert "Unsupported language" in result.stderr
