"""Docker sandbox — executes code inside an ephemeral `docker run` container.

Opt-in alternative to ``LocalSandbox``. The point is *containment, not capacity*:
agent code that OOMs kills the container, not the host, and ``--cpus`` keeps
runaway loops from saturating every core. Select via
``DOJO_SANDBOX__BACKEND=docker`` or ``sandbox.backend = "docker"`` in
``.dojo/config.yaml``.

Mirrors ``LocalSandbox``'s shape — same arguments, same ``ExecutionResult``,
same script-write/cleanup dance — but shells out to ``docker run`` with the
workspace bind-mounted at the same absolute path.

Producing a Linux-compatible interpreter is a *workspace* concern, not a
sandbox concern. ``WorkspaceService`` builds ``.venv-docker/`` when the docker
backend is selected and sets ``workspace.python_path`` accordingly; this
sandbox just runs whatever python it's handed.
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

from dojo.interfaces.sandbox import ExecutionResult, Sandbox
from dojo.sandbox.local import _safe_script_filename
from dojo.utils.ids import generate_id
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

# Exit code 137 is SIGKILL (128 + 9), which docker uses for the cgroup OOM
# killer; 126 is "command found but not executable" — most commonly the
# host-built venv hitting `exec format error` inside the Linux container.
_OOM_EXIT_CODE = 137
_EXEC_FORMAT_EXIT_CODE = 126


class DockerSandbox(Sandbox):
    """Sandbox that executes code inside an ephemeral docker container."""

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        timeout: float = 300.0,
        memory_limit: str | None = None,
        cpu_limit: str | None = None,
        network: str = "bridge",
        docker_bin: str = "docker",
    ) -> None:
        self.image = image
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network = network
        self.docker_bin = docker_bin
        # Track in-flight container names so cleanup() can `docker kill` them.
        self._active_containers: set[str] = set()

    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        cwd: str | None = None,
        python_path: str | None = None,
        env_vars: dict[str, str] | None = None,
        timeout: float | None = None,
        name: str | None = None,
        script_dir: str | None = None,
    ) -> ExecutionResult:
        if language != "python":
            return ExecutionResult(stderr=f"Unsupported language: {language}", exit_code=1)

        effective_timeout = timeout if timeout is not None else self.timeout
        work_dir = cwd or tempfile.mkdtemp()
        effective_script_dir = script_dir or work_dir
        effective_python = python_path or "python"

        script_path = Path(effective_script_dir) / _safe_script_filename(name, code)
        script_path.write_text(code)

        container_name = f"dojo-sandbox-{generate_id()}"
        self._active_containers.add(container_name)

        argv = self._build_run_argv(
            container_name=container_name,
            work_dir=work_dir,
            script_dir=effective_script_dir,
            env_vars=env_vars or {},
            python_exec=effective_python,
            script_path=str(script_path),
        )

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=effective_timeout
                )
            except TimeoutError:
                # Best-effort kill. --rm + the finally block clear state
                # either way.
                await self._docker_kill(container_name)
                duration_ms = (time.monotonic() - start) * 1000
                return ExecutionResult(
                    stderr="Execution timed out",
                    exit_code=-1,
                    duration_ms=duration_ms,
                )
            duration_ms = (time.monotonic() - start) * 1000

            stdout_str = stdout.decode()
            stderr_str = stderr.decode()
            exit_code = proc.returncode or 0

            if exit_code == _OOM_EXIT_CODE:
                limit_str = self.memory_limit or "unset"
                stderr_str = (
                    f"[dojo] Container OOMKilled (exit code 137). "
                    f"Memory limit was {limit_str}.\n" + stderr_str
                )
            elif exit_code == _EXEC_FORMAT_EXIT_CODE and "exec format error" in stderr_str:
                # The configured python_path won't run inside the Linux
                # container (typically a host-built `.venv/` from macOS).
                # WorkspaceService should have built `.venv-docker/` when the
                # docker backend was selected — flag the gap so users see it.
                stderr_str = (
                    "[dojo] python binary inside the container failed with "
                    "'exec format error'. The configured python_path is not "
                    "runnable in the container image. Re-run `dojo domain "
                    'setup` with `sandbox.backend = "docker"` so '
                    "WorkspaceService builds a Linux-compatible "
                    "`.venv-docker/` for this workspace.\n" + stderr_str
                )

            return ExecutionResult(
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )
        finally:
            self._active_containers.discard(container_name)
            script_path.unlink(missing_ok=True)

    async def install_packages(self, packages: list[str]) -> ExecutionResult:
        """Install packages in a one-shot container against the configured image.

        Not on the hot path — workspaces own their own venvs at run time. The
        recommended path for docker users is to bake deps into a custom
        ``image`` or let ``WorkspaceService`` build ``.venv-docker/``. This
        method exists to satisfy the interface and to give a usable smoke
        install during ad-hoc debugging.
        """
        argv = [
            self.docker_bin,
            "run",
            "--rm",
            self.image,
            "pip",
            "install",
            *packages,
        ]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return ExecutionResult(
            stdout=stdout.decode(),
            stderr=stderr.decode(),
            exit_code=proc.returncode or 0,
        )

    async def cleanup(self) -> None:
        """Best-effort `docker kill` of any container names we're still tracking."""
        for name in list(self._active_containers):
            await self._docker_kill(name)
        self._active_containers.clear()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _build_run_argv(
        self,
        *,
        container_name: str,
        work_dir: str,
        script_dir: str,
        env_vars: dict[str, str],
        python_exec: str,
        script_path: str,
    ) -> list[str]:
        argv: list[str] = [
            self.docker_bin,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            self.network,
        ]
        if self.memory_limit:
            # `--memory-swap=<limit>` (equal to --memory) disables swap so the
            # OOM killer fires at the configured limit instead of silently
            # swapping. Without this, OOM behaviour is host-dependent.
            argv.extend(["--memory", self.memory_limit, "--memory-swap", self.memory_limit])
        if self.cpu_limit:
            argv.extend(["--cpus", self.cpu_limit])

        # Bind-mount the workspace at the same absolute path so cwd, script
        # paths, DOJO_ARTIFACTS_DIR, and python_path all resolve transparently
        # inside the container.
        argv.extend(["-v", f"{work_dir}:{work_dir}"])
        if script_dir and script_dir != work_dir and not _is_subpath(script_dir, work_dir):
            argv.extend(["-v", f"{script_dir}:{script_dir}"])
        argv.extend(["-w", work_dir])

        # Forward only explicit env_vars — never the whole host env (too noisy,
        # leaks secrets). PYTHONUNBUFFERED=1 so stdout streams promptly.
        argv.extend(["-e", "PYTHONUNBUFFERED=1"])
        for key, value in env_vars.items():
            argv.extend(["-e", f"{key}={value}"])

        # On Linux the bind-mount preserves UID/GID, so we pass --user to keep
        # files written into the workspace owned by the host user. On macOS
        # Docker Desktop's VM handles this remapping automatically, so passing
        # --user there breaks the venv build (the host UID has no passwd
        # entry inside the container).
        if sys.platform == "linux":
            argv.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

        argv.append(self.image)
        argv.extend([python_exec, script_path])
        return argv

    async def _docker_kill(self, container_name: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.docker_bin,
                "kill",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except (FileNotFoundError, OSError):
            # docker binary missing or container already gone — nothing to do.
            return


def _is_subpath(child: str, parent: str) -> bool:
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


__all__ = ["DockerSandbox"]
