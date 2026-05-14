"""Docker sandbox — executes code inside an ephemeral `docker run` container.

Opt-in alternative to ``LocalSandbox``. The point is *containment, not capacity*:
agent code that OOMs kills the container, not the host, and ``--cpus`` keeps
runaway loops from saturating every core. Select via
``DOJO_SANDBOX__BACKEND=docker`` or ``sandbox.backend = "docker"`` in
``.dojo/config.yaml``.

Mirrors ``LocalSandbox``'s shape so the diff is reviewable — same arguments,
same ``ExecutionResult``, same script-write/cleanup dance — but shells out to
``docker run`` with the workspace bind-mounted at the same absolute path.

The workspace's ``.venv/bin/python`` from the host won't run inside a Linux
container on macOS (exec-format-error), so when ``auto_rebuild_venv`` is on we
build a sibling ``.venv-docker/`` once per workspace + image and rewrite
``python_path`` to point at it. Delete ``.venv-docker/`` to force a rebuild
(e.g. after dep changes).
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

# Suffix used for the in-container venv built next to the host's `.venv/`.
_DOCKER_VENV_DIRNAME = ".venv-docker"

# Marker prepended to stderr when the container is OOMKilled. Exit code 137 is
# SIGKILL (128 + 9), which docker uses for the cgroup OOM killer.
_OOM_EXIT_CODE = 137
_EXEC_FORMAT_EXIT_CODE = 126


class DockerSandbox(Sandbox):
    """Sandbox that executes code inside an ephemeral docker container."""

    def __init__(
        self,
        *,
        image: str = "python:3.13-slim",
        timeout: float = 300.0,
        memory_limit: str | None = None,
        cpu_limit: str | None = None,
        network: str = "bridge",
        auto_rebuild_venv: bool = True,
        docker_bin: str = "docker",
    ) -> None:
        self.image = image
        self.timeout = timeout
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network = network
        self.auto_rebuild_venv = auto_rebuild_venv
        self.docker_bin = docker_bin
        # Track in-flight container names so cleanup() can `docker kill` them.
        self._active_containers: set[str] = set()
        # Cache resolved `.venv-docker/bin/python` paths per cwd so back-to-back
        # experiments in the same run don't re-shell-out to docker. The on-disk
        # check inside `_ensure_docker_venv` is the cross-process source of
        # truth; this is a fast-path for the common single-process case.
        self._venv_cache: dict[str, str] = {}

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

        # Pick the python executable to run inside the container. The
        # auto-rebuild path swaps a host-built `.venv/bin/python` for a
        # Linux-compatible `.venv-docker/bin/python`; otherwise we pass the
        # path verbatim (Linux host, or user-managed docker venv).
        effective_python = await self._resolve_python_path(python_path, work_dir)

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
                # Best-effort kill. If `docker kill` fails (container already
                # gone), swallow — the --rm flag and finally block will clear
                # state either way.
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
                # The user disabled auto_rebuild_venv (or pointed at a non-venv
                # binary) and the host-built python won't run in the Linux
                # container. Surface a clear fix.
                stderr_str = (
                    "[dojo] python binary inside the container failed with "
                    "'exec format error'. Likely cause: a host-built `.venv/` "
                    "is being run inside a Linux container. Enable "
                    "`sandbox.auto_rebuild_venv = true` or use a `python_path` "
                    "that exists inside the image.\n" + stderr_str
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
        ``image`` or rely on the ``auto_rebuild_venv`` flow. This method exists
        to satisfy the interface and to give a usable smoke install during
        ad-hoc debugging.
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
        # --user there breaks the venv-rebuild step (the host UID has no
        # passwd entry inside the container).
        if sys.platform == "linux":
            argv.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

        argv.append(self.image)
        argv.extend([python_exec, script_path])
        return argv

    async def _resolve_python_path(self, python_path: str | None, cwd: str) -> str:
        """Pick the python executable to invoke inside the container.

        - None → container's system "python".
        - Host-built `.venv/bin/python` + auto_rebuild_venv on → swap for
          `.venv-docker/bin/python`, building it on first call.
        - Anything else → pass through verbatim. Caller knows what they're doing.
        """
        if python_path is None:
            return "python"

        if self.auto_rebuild_venv and _looks_like_host_venv_python(python_path, cwd):
            try:
                return await self._ensure_docker_venv(cwd)
            except DockerVenvBuildError as e:
                # Re-raise as the same error type — caller (execute) lets it
                # bubble up to the runner, where it surfaces in the experiment
                # result. Silent fallback to `python_path` would re-introduce
                # the exec-format-error UX we're trying to fix.
                raise e

        return python_path

    async def _ensure_docker_venv(self, cwd: str) -> str:
        """Lazily build `<cwd>/.venv-docker/` inside the configured image.

        Returns the path to `.venv-docker/bin/python`. Idempotent: subsequent
        calls reuse the on-disk venv (and the in-memory cache).
        """
        cached = self._venv_cache.get(cwd)
        if cached and Path(cached).exists():
            return cached

        venv_root = Path(cwd) / _DOCKER_VENV_DIRNAME
        venv_python = venv_root / "bin" / "python"
        if venv_python.exists():
            self._venv_cache[cwd] = str(venv_python)
            return str(venv_python)

        setup_cmd = _venv_setup_cmd(cwd)
        logger.info(
            "docker_venv_build_start",
            cwd=cwd,
            image=self.image,
            target=str(venv_root),
        )

        argv = [
            self.docker_bin,
            "run",
            "--rm",
            "-v",
            f"{cwd}:{cwd}",
            "-w",
            cwd,
            self.image,
            "bash",
            "-lc",
            setup_cmd,
        ]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        stdout = stdout_b.decode()
        stderr = stderr_b.decode()

        if proc.returncode != 0:
            logger.warning(
                "docker_venv_build_failed",
                cwd=cwd,
                image=self.image,
                exit_code=proc.returncode,
                stderr_tail=stderr[-500:],
            )
            raise DockerVenvBuildError(
                f"Failed to build {venv_root} inside {self.image} "
                f"(exit code {proc.returncode}). stderr tail:\n{stderr[-500:]}"
            )

        if not venv_python.exists():
            raise DockerVenvBuildError(
                f"Venv build reported success but {venv_python} is missing. "
                f"stdout tail:\n{stdout[-500:]}"
            )

        logger.info("docker_venv_build_done", cwd=cwd, python=str(venv_python))
        self._venv_cache[cwd] = str(venv_python)
        return str(venv_python)

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


class DockerVenvBuildError(RuntimeError):
    """Raised when building `.venv-docker/` inside the container fails."""


def _is_subpath(child: str, parent: str) -> bool:
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def _looks_like_host_venv_python(python_path: str, cwd: str) -> bool:
    """True iff `python_path` points at `<cwd>/.venv/bin/python` (or the cwd
    we're given via the workspace dispatch).

    The check is narrow on purpose: we only want to rewrite paths we know we
    created via the host's WorkspaceService. Anything else passes through.
    """
    p = Path(python_path)
    # Match `<cwd>/.venv/bin/python` (and the rare Windows-y variants) only
    # when the path lives inside `cwd`.
    try:
        rel = p.resolve().relative_to(Path(cwd).resolve())
    except ValueError:
        return False
    parts = rel.parts
    return len(parts) >= 3 and parts[0] == ".venv" and parts[-1] in {"python", "python3"}


def _venv_setup_cmd(cwd: str) -> str:
    """Pick the right install flow for the workspace's dep manifest."""
    cwd_path = Path(cwd)
    if (cwd_path / "pyproject.toml").exists():
        # uv flow. --no-install-project skips building the workspace's own
        # package (may need native deps the slim image doesn't ship). --no-dev
        # skips dev extras. Failures here surface to the user; we don't
        # silently fall back.
        return (
            "set -euo pipefail; "
            "pip install --quiet uv && "
            f"uv venv {_DOCKER_VENV_DIRNAME} && "
            f'VIRTUAL_ENV="$PWD/{_DOCKER_VENV_DIRNAME}" '
            "uv sync --active --no-install-project --no-dev"
        )
    if (cwd_path / "requirements.txt").exists():
        return (
            "set -euo pipefail; "
            f"python -m venv {_DOCKER_VENV_DIRNAME} && "
            f"{_DOCKER_VENV_DIRNAME}/bin/pip install --quiet -r requirements.txt"
        )
    # Bare venv. The user has no manifest — we still build an empty venv so
    # the resulting python is Linux-compatible.
    return f"set -euo pipefail; python -m venv {_DOCKER_VENV_DIRNAME}"


__all__ = ["DockerSandbox", "DockerVenvBuildError"]
