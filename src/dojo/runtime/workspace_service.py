"""WorkspaceService — one-time workspace setup and validation."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dojo.config.settings import SandboxSettings
from dojo.core.domain import Domain, Workspace, WorkspaceSource
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

# Sibling venv built inside the configured docker image. Lives next to the
# host's `.venv/` so users keep their existing workflow; the suffix is the
# only thing telling them apart.
_DOCKER_VENV_DIRNAME = ".venv-docker"


@dataclass(frozen=True)
class InstallResult:
    """Outcome of installing packages into a workspace venv."""

    ok: bool
    message: str


class WorkspaceService:
    """Sets up and validates domain workspaces.

    A workspace is a persistent execution environment for a domain.
    Setup happens once; all agent runs reuse the prepared workspace.

    When the docker sandbox backend is selected, this service also builds a
    sibling ``.venv-docker/`` inside the configured image so that
    ``workspace.python_path`` points at a Linux-compatible interpreter
    regardless of the host platform. The sandbox itself stays unaware of
    this — it just runs whatever python path the workspace publishes.
    """

    def __init__(
        self,
        base_dir: Path,
        sandbox_settings: SandboxSettings | None = None,
    ) -> None:
        self.base_dir = base_dir / "workspaces"
        # Default to a plain LocalSandbox-style config when no settings are
        # provided. Tests that don't care about the docker venv path can keep
        # the old `WorkspaceService(base_dir)` call.
        self.sandbox_settings = sandbox_settings or SandboxSettings()

    async def setup(self, domain: Domain) -> Workspace:
        """Prepare a workspace for a domain.

        Resolves the path, detects or creates a virtual environment,
        installs dependencies, and marks the workspace as ready.

        Args:
            domain: The domain whose workspace to set up.

        Returns:
            Updated Workspace with python_path and ready=True.

        Raises:
            ValueError: If workspace config is invalid.
            RuntimeError: If setup fails.
        """
        ws = domain.workspace
        if ws is None:
            raise ValueError(f"Domain {domain.id} has no workspace configured")

        ws_path = await self._resolve_path(domain.id, ws)
        ws.path = str(ws_path)

        if ws.setup_script:
            await self._run_setup_script(ws_path, ws.setup_script)

        python_path = await self._ensure_python_env(ws_path, ws)

        # When docker is the configured backend the host's `.venv/bin/python`
        # won't run inside a Linux container (most commonly: macOS host,
        # Linux image). Build `.venv-docker/` once per workspace and publish
        # that as the workspace's interpreter. The sandbox stays unaware —
        # it just runs whatever path it's handed.
        if self.sandbox_settings.backend == "docker":
            python_path = await self._ensure_docker_venv(ws_path)

        ws.python_path = python_path
        ws.ready = True

        logger.info("workspace_ready", domain_id=domain.id, path=ws.path, python=python_path)
        return ws

    async def validate(self, domain: Domain) -> dict[str, Any]:
        """Validate that a workspace is functional.

        Returns a dict with 'ok' bool and 'errors' list.
        """
        ws = domain.workspace
        if ws is None:
            return {"ok": False, "errors": ["No workspace configured"]}

        errors: list[str] = []

        # Check path exists
        ws_path = Path(ws.path)
        if not ws_path.exists():
            errors.append(f"Workspace path does not exist: {ws.path}")
            return {"ok": False, "errors": errors}

        # Check Python executable
        python = ws.python_path or "python"
        try:
            proc = await asyncio.create_subprocess_exec(
                python,
                "-c",
                "import sys; print(sys.version)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws_path),
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode != 0:
                errors.append(f"Python check failed: {stderr.decode()}")
        except (TimeoutError, FileNotFoundError) as e:
            errors.append(f"Python not found or timed out: {e}")

        return {"ok": len(errors) == 0, "errors": errors}

    async def install_packages(self, workspace: Workspace, modules: list[str]) -> InstallResult:
        """Install ``modules`` into the workspace's running venv.

        Dispatches on ``sandbox_settings.backend``:

        - ``"docker"`` — install **inside** the configured image with the
          workspace bind-mounted at the same absolute path. The python lives at
          ``<ws>/.venv-docker/bin/python`` and is a Linux ELF binary, so we
          can't run ``pip`` against it from a macOS host. Mirrors the
          bind-mount idiom used by :meth:`_ensure_docker_venv`.
        - any other backend — install on the host against the published
          ``workspace.python_path``. Prefers ``uv pip install --python <path>``
          when ``uv`` is on PATH (uv-built venvs don't ship pip, so
          ``python -m pip`` would crash with ``No module named pip``).

        Refuses to run with no ``python_path`` — that's a "workspace not
        ready" condition the caller should have caught.
        """
        if not modules:
            return InstallResult(ok=True, message="")
        if not workspace.python_path or not workspace.path:
            return InstallResult(
                ok=False,
                message="workspace has no python_path; setup did not complete",
            )

        if self.sandbox_settings.backend == "docker":
            return await self._install_in_docker(workspace, modules)
        return await self._install_on_host(workspace, modules)

    async def _install_on_host(self, workspace: Workspace, modules: list[str]) -> InstallResult:
        python_path = workspace.python_path
        assert python_path is not None  # checked by caller
        uv_bin = shutil.which("uv")
        if uv_bin:
            cmd = [uv_bin, "pip", "install", "--python", python_path, *modules]
        else:
            cmd = [python_path, "-m", "pip", "install", *modules]
        return await self._run_install(cmd, label="host", workspace_path=workspace.path)

    async def _install_in_docker(self, workspace: Workspace, modules: list[str]) -> InstallResult:
        python_path = workspace.python_path
        ws_path = workspace.path
        assert python_path is not None and ws_path is not None  # checked by caller
        image = self.sandbox_settings.image
        # Run uv inside the container so the install lands in .venv-docker/
        # on the host filesystem via the bind-mount. We don't trust the image
        # to ship uv, so pip-install it first (same pattern as _ensure_docker_venv).
        inner = (
            "set -euo pipefail; "
            "pip install --quiet uv && "
            f"uv pip install --python {python_path} " + " ".join(_shell_quote(m) for m in modules)
        )
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ws_path}:{ws_path}",
            "-w",
            ws_path,
            image,
            "bash",
            "-lc",
            inner,
        ]
        return await self._run_install(cmd, label=f"docker({image})", workspace_path=ws_path)

    async def _run_install(
        self, cmd: list[str], *, label: str, workspace_path: str
    ) -> InstallResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=600.0)
        except (TimeoutError, FileNotFoundError, OSError) as e:
            return InstallResult(ok=False, message=f"{label} install failed to start: {e}")
        if proc.returncode != 0:
            tail = (stderr_b.decode() or stdout_b.decode()).strip().splitlines()[-3:]
            return InstallResult(
                ok=False,
                message=f"{label} install exited {proc.returncode}: " + " | ".join(tail),
            )
        return InstallResult(ok=True, message=f"installed via {label}")

    def get_status(self, workspace: Workspace) -> dict[str, Any]:
        """Return setup status summary for a workspace."""
        if workspace is None:
            return {"configured": False}

        ws_path = Path(workspace.path) if workspace.path else None
        return {
            "configured": True,
            "ready": workspace.ready,
            "path": workspace.path,
            "source": workspace.source.value,
            "python_path": workspace.python_path,
            "path_exists": ws_path.exists() if ws_path else False,
        }

    # --- Private helpers ---

    async def _resolve_path(self, domain_id: str, ws: Workspace) -> Path:
        """Resolve or create the workspace directory."""
        if ws.source == WorkspaceSource.LOCAL:
            path = Path(ws.path).expanduser().resolve()
            if not path.exists():
                raise RuntimeError(f"Local workspace path does not exist: {path}")
            return path

        if ws.source == WorkspaceSource.GIT:
            path = self.base_dir / domain_id
            if not path.exists():
                await self._clone_repo(ws.git_url or "", ws.git_ref, path)
            return path

        # EMPTY
        path = self.base_dir / domain_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _clone_repo(self, url: str, ref: str | None, target: Path) -> None:
        """Clone a git repository to target directory."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", url, str(target)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {stderr.decode()}")

        if ref:
            checkout = await asyncio.create_subprocess_exec(
                "git",
                "checkout",
                ref,
                cwd=str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(checkout.communicate(), timeout=30.0)

    async def _ensure_python_env(self, ws_path: Path, ws: Workspace) -> str:
        """Detect or create a Python virtual environment.

        Priority:
        1. Existing .venv/venv in workspace
        2. pyproject.toml → uv sync or pip install -e .
        3. requirements.txt → venv + pip install -r
        4. Nothing → return system python
        """
        # Check for existing venv
        for venv_name in (".venv", "venv"):
            venv_path = ws_path / venv_name
            if venv_path.exists():
                python = self._venv_python(venv_path)
                if Path(python).exists():
                    return python

        # Check for pyproject.toml
        if (ws_path / "pyproject.toml").exists():
            return await self._setup_with_pyproject(ws_path)

        # Check for requirements.txt
        if (ws_path / "requirements.txt").exists():
            return await self._setup_with_requirements(ws_path)

        # Fallback: system python
        return sys.executable

    async def _setup_with_pyproject(self, ws_path: Path) -> str:
        """Set up environment from pyproject.toml using uv or pip."""
        venv_path = ws_path / ".venv"

        # Try uv first (much faster)
        if shutil.which("uv"):
            proc = await asyncio.create_subprocess_exec(
                "uv",
                "sync",
                cwd=str(ws_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
            if proc.returncode == 0:
                python = self._venv_python(venv_path)
                if Path(python).exists():
                    return python
            else:
                logger.warning("uv_sync_failed", error=stderr.decode()[:200])

        # Fallback: pip install -e .
        venv_path.mkdir(exist_ok=True)
        await self._create_venv(venv_path)
        python = self._venv_python(venv_path)
        proc = await asyncio.create_subprocess_exec(
            python,
            "-m",
            "pip",
            "install",
            "-e",
            ".",
            cwd=str(ws_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300.0)
        return python

    async def _setup_with_requirements(self, ws_path: Path) -> str:
        """Set up environment from requirements.txt."""
        venv_path = ws_path / ".venv"
        await self._create_venv(venv_path)
        python = self._venv_python(venv_path)
        proc = await asyncio.create_subprocess_exec(
            python,
            "-m",
            "pip",
            "install",
            "-r",
            "requirements.txt",
            cwd=str(ws_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300.0)
        return python

    async def _create_venv(self, venv_path: Path) -> None:
        """Create a virtual environment."""
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "venv",
            str(venv_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        if proc.returncode != 0:
            raise RuntimeError(f"venv creation failed: {stderr.decode()}")

    @staticmethod
    def _venv_python(venv_path: Path) -> str:
        """Return path to Python executable in a venv."""
        # Unix: .venv/bin/python
        unix_python = venv_path / "bin" / "python"
        if unix_python.exists():
            return str(unix_python)
        # Windows: .venv/Scripts/python.exe
        win_python = venv_path / "Scripts" / "python.exe"
        if win_python.exists():
            return str(win_python)
        return str(unix_python)  # Return expected path even if not yet created

    async def _run_setup_script(self, ws_path: Path, script: str) -> None:
        """Run a user-provided setup script in the workspace."""
        proc = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            script,
            cwd=str(ws_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode != 0:
            raise RuntimeError(f"Setup script failed: {stderr.decode()}")

    async def _ensure_docker_venv(self, ws_path: Path) -> str:
        """Build (or reuse) ``<ws_path>/.venv-docker/`` inside the configured
        docker image and return its python path.

        The build runs in a one-shot ``docker run`` with the workspace
        bind-mounted at the same absolute path, so files land on the host. We
        pick the install command from the workspace's manifest:

        - ``pyproject.toml`` → ``uv sync --no-install-project --no-dev`` (the
          workspace's own package often needs system build deps the slim
          image doesn't ship; experiments still import workspace code via the
          bind-mounted source tree).
        - ``requirements.txt`` → ``pip install -r``.
        - neither → empty venv (still gives a Linux-compatible interpreter).

        Idempotent: an existing ``.venv-docker/bin/python`` short-circuits
        the build. Delete the directory to force a rebuild after dep changes.
        """
        venv_root = ws_path / _DOCKER_VENV_DIRNAME
        venv_python = venv_root / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)

        image = self.sandbox_settings.image
        setup_cmd = _docker_venv_setup_cmd(ws_path)
        logger.info("docker_venv_build_start", cwd=str(ws_path), image=image)

        argv = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ws_path}:{ws_path}",
            "-w",
            str(ws_path),
            image,
            "bash",
            "-lc",
            setup_cmd,
        ]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=900.0)
        stdout = stdout_b.decode()
        stderr = stderr_b.decode()

        if proc.returncode != 0:
            logger.warning(
                "docker_venv_build_failed",
                cwd=str(ws_path),
                image=image,
                exit_code=proc.returncode,
                stderr_tail=stderr[-500:],
            )
            raise RuntimeError(
                f"Failed to build {venv_root} inside {image} "
                f"(exit code {proc.returncode}). stderr tail:\n{stderr[-500:]}"
            )

        if not venv_python.exists():
            raise RuntimeError(
                f"Docker venv build reported success but {venv_python} is missing. "
                f"stdout tail:\n{stdout[-500:]}"
            )

        logger.info("docker_venv_build_done", cwd=str(ws_path), python=str(venv_python))
        return str(venv_python)


def _shell_quote(s: str) -> str:
    """Minimal shell-safe quoting for module names passed to bash -lc."""
    import shlex

    return shlex.quote(s)


def _docker_venv_setup_cmd(ws_path: Path) -> str:
    """Pick the right install flow for the workspace's dep manifest."""
    if (ws_path / "pyproject.toml").exists():
        return (
            "set -euo pipefail; "
            "pip install --quiet uv && "
            f"uv venv {_DOCKER_VENV_DIRNAME} && "
            f'VIRTUAL_ENV="$PWD/{_DOCKER_VENV_DIRNAME}" '
            "uv sync --active --no-install-project --no-dev"
        )
    if (ws_path / "requirements.txt").exists():
        return (
            "set -euo pipefail; "
            f"python -m venv {_DOCKER_VENV_DIRNAME} && "
            f"{_DOCKER_VENV_DIRNAME}/bin/pip install --quiet -r requirements.txt"
        )
    return f"set -euo pipefail; python -m venv {_DOCKER_VENV_DIRNAME}"
