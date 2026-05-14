"""Integration tests for DockerSandbox — only run when Docker is available.

Gated by `_docker_available()` (shells out `docker info`). Locally `just test`
will pick these up when the Docker daemon is up; on CI without Docker they
auto-skip.

These are deliberately small — the unit tests in
[test_docker_sandbox.py](../unit/test_docker_sandbox.py) already cover argv
construction and edge cases against a stubbed `docker` binary. What we
actually want from integration coverage is proof that:

1. The host doesn't die when the container OOMs (this is the headline reason
   for the whole sandbox).
2. Artifacts written through the bind-mount actually land on the host.
3. The default `--network=bridge` lets experiments reach the internet.
4. The venv-rebuild flow produces a Linux-compatible interpreter.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dojo.sandbox.docker import DockerSandbox


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        )
    except (subprocess.TimeoutExpired, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="docker daemon not reachable",
)


async def test_smoke_hello(tmp_path: Path) -> None:
    sandbox = DockerSandbox()
    result = await sandbox.execute("print('hello')", cwd=str(tmp_path))
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


async def test_oom_kills_container_not_host(tmp_path: Path) -> None:
    """Allocating 256 MiB inside a 32 MiB container should OOM the container
    and leave the host (this test process) alive."""
    sandbox = DockerSandbox(memory_limit="32m")
    result = await sandbox.execute(
        "x = bytearray(256 * 1024 * 1024)",
        cwd=str(tmp_path),
    )
    assert result.exit_code == 137
    assert "OOMKilled" in result.stderr
    # The fact that the next line runs is the test: we're still alive.
    assert 1 + 1 == 2


async def test_artifacts_via_bind_mount(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    code = (
        "import os, pathlib;"
        "pathlib.Path(os.environ['DOJO_ARTIFACTS_DIR'], 'hello.txt')"
        ".write_text('hi from container')"
    )
    sandbox = DockerSandbox()
    result = await sandbox.execute(
        code,
        cwd=str(tmp_path),
        env_vars={"DOJO_ARTIFACTS_DIR": str(artifacts_dir)},
    )
    assert result.exit_code == 0, result.stderr
    assert (artifacts_dir / "hello.txt").read_text() == "hi from container"


async def test_default_network_reaches_the_internet(tmp_path: Path) -> None:
    """`network='bridge'` is the default — confirm experiments can resolve DNS."""
    sandbox = DockerSandbox()
    result = await sandbox.execute(
        "import socket; print(socket.gethostbyname('pypi.org'))",
        cwd=str(tmp_path),
    )
    assert result.exit_code == 0, result.stderr


async def test_venv_rebuild_with_pip_flow(tmp_path: Path) -> None:
    """An empty `.venv-docker` should materialise for a workspace with only
    `requirements.txt`; the resulting python is Linux-compatible."""
    (tmp_path / "requirements.txt").write_text("")  # no deps
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")

    sandbox = DockerSandbox()
    result = await sandbox.execute(
        "import sys; print(sys.executable)",
        cwd=str(tmp_path),
        python_path=str(tmp_path / ".venv" / "bin" / "python"),
    )
    assert result.exit_code == 0, result.stderr
    # The interpreter that ran is the docker venv's, not the host's.
    assert ".venv-docker" in result.stdout
    assert (tmp_path / ".venv-docker" / "bin" / "python").exists()
