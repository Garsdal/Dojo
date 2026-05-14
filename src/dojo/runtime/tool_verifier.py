"""verify_required_tools — runs all required tools for a task in a single subprocess.

Design:
- One combined subprocess per task-type verification (not one per tool).
  ``TaskTypeSpec.verifier_script`` is a self-contained Python script that imports
  all required tool modules, calls them end-to-end in the right order, and emits
  per-tool result / error markers on stdout.
- Data flows in-process within the subprocess — no serialisation to/from the
  parent. load_data's output is passed directly to evaluate inside the same
  Python process; only a small JSON summary crosses the subprocess boundary.
- Subprocess for isolation (untrusted AI-generated code must not pollute the
  server's imports, call sys.exit, or OOM-crash the server process).

Returns a ``VerificationResult`` populated on each ``DomainTool``.
"""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dojo.core.domain import DomainTool, VerificationResult, Workspace
from dojo.core.task import TASK_TYPE_REGISTRY, Task, ToolContract
from dojo.interfaces.sandbox import Sandbox
from dojo.utils.logging import get_logger

logger = get_logger(__name__)

_TOOL_RESULT_MARKER = "__DOJO_TOOL_RESULT__:"
_TOOL_ERROR_MARKER = "__DOJO_TOOL_ERROR__:"


async def verify_required_tools(
    tools: list[DomainTool],
    task: Task,
    *,
    sandbox: Sandbox,
    workspace: Workspace | None,
    timeout: float = 60.0,
    module_dir: Path | None = None,
) -> list[DomainTool]:
    """Run the task's combined verifier script in a single subprocess.

    Writes all tool modules to a shared directory (so they can import each
    other), executes ``TaskTypeSpec.verifier_script``, then parses per-tool
    result/error markers from stdout and populates ``DomainTool.verification``.

    When ``module_dir`` is given it persists across calls — useful so
    load_data can cache expensive dataset fetches next to the module files and
    subsequent calls reuse that cache.  When omitted a fresh tempdir is created
    and torn down after verification.
    """
    spec = TASK_TYPE_REGISTRY.get(task.type)
    if spec is None:
        return tools

    by_name = {t.name: t for t in tools}
    owns_dir = module_dir is None
    dir_path = Path(tempfile.mkdtemp(prefix="dojo_verify_")) if owns_dir else module_dir
    assert dir_path is not None

    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        dir_path = dir_path.resolve()

        for contract in spec.required_tools:
            tool = by_name.get(contract.name)
            if tool and tool.code:
                filename = tool.module_filename or contract.module_filename or f"{tool.name}.py"
                (dir_path / filename).write_text(tool.code)

        _cwd, python_path, env_vars = _workspace_args(workspace)

        start = time.monotonic()
        result = await sandbox.execute(
            spec.verifier_script,
            cwd=str(dir_path),
            python_path=python_path,
            env_vars=env_vars or None,
            timeout=timeout,
            name="dojo_verify",
        )
        duration_ms = (time.monotonic() - start) * 1000.0
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        tool_results, tool_errors = _parse_tool_markers(stdout)

        for contract in spec.required_tools:
            tool = by_name.get(contract.name)
            if tool is None:
                continue
            tool.verification = _build_verification_result(
                contract=contract,
                tool_results=tool_results,
                tool_errors=tool_errors,
                duration_ms=duration_ms,
                stdout=stdout,
                stderr=stderr,
                exit_code=result.exit_code,
            )

    finally:
        if owns_dir:
            _rmtree_quiet(dir_path)

    return tools


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_tool_markers(
    stdout: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan stdout for per-tool result and error markers.

    Returns (tool_results, tool_errors) where keys are tool names.
    Later lines win (so re-runs within one script can overwrite earlier ones).
    """
    tool_results: dict[str, Any] = {}
    tool_errors: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.rstrip()
        if line.startswith(_TOOL_RESULT_MARKER):
            try:
                payload = json.loads(line[len(_TOOL_RESULT_MARKER) :])
                tool_results[payload["tool"]] = payload.get("sample", {})
            except (json.JSONDecodeError, KeyError):
                pass
        elif line.startswith(_TOOL_ERROR_MARKER):
            try:
                payload = json.loads(line[len(_TOOL_ERROR_MARKER) :])
                tool_errors[payload["tool"]] = payload
            except (json.JSONDecodeError, KeyError):
                pass
    return tool_results, tool_errors


def _build_verification_result(
    *,
    contract: ToolContract,
    tool_results: dict[str, Any],
    tool_errors: dict[str, Any],
    duration_ms: float,
    stdout: str,
    stderr: str,
    exit_code: int,
) -> VerificationResult:
    now = datetime.now(UTC)

    if contract.name in tool_errors:
        err = tool_errors[contract.name]
        msg = err.get("message") or err.get("type") or "verification failed"
        tb = err.get("traceback") or ""
        origin = _last_user_frame(tb, contract.module_filename)
        where = f" at {origin}" if origin else ""
        return VerificationResult(
            verified=False,
            errors=[f"{contract.name} raised{where}: {msg}"],
            duration_ms=duration_ms,
            verified_at=now,
        )

    if contract.name in tool_results:
        sample = tool_results[contract.name]
        errors: list[str] = []
        if contract.return_kind == "dict" and isinstance(sample, dict):
            _validate_returns(sample, contract, errors)
        return VerificationResult(
            verified=not errors,
            errors=errors,
            sample_output=_summarise_output(sample) if not errors else {},
            duration_ms=duration_ms,
            verified_at=now,
        )

    # Tool marker missing — the script may have crashed before reaching it.
    if exit_code != 0:
        detail = _format_exit_error(contract.name, exit_code, stderr, stdout)
        return VerificationResult(
            verified=False,
            errors=[detail],
            duration_ms=duration_ms,
            verified_at=now,
        )

    return VerificationResult(
        verified=False,
        errors=[
            f"{contract.name}: no result marker found — "
            f"a previous tool in the verifier script likely failed"
        ],
        duration_ms=duration_ms,
        verified_at=now,
    )


def _validate_returns(sample: dict[str, Any], contract: ToolContract, errors: list[str]) -> None:
    for key, spec in contract.returns_schema.items():
        if key not in sample:
            errors.append(f"missing required key {key!r} in output")
            continue
        problem = _check_type(sample[key], spec)
        if problem:
            errors.append(f"key {key!r}: {problem}")


def _last_user_frame(traceback_text: str, module_filename: str) -> str | None:
    """Extract the last frame from a Python traceback that points at the
    generated tool module (e.g. ``evaluate.py:12``).

    Frames inside dojo's own runner stub or stdlib / third-party packages are
    skipped — we only want to point at the file the user (or AI) authored,
    so the error message can clearly say "fix this line in evaluate.py".
    """
    if not traceback_text:
        return None
    target = module_filename
    last: tuple[str, str] | None = None
    for line in traceback_text.splitlines():
        line = line.strip()
        if not line.startswith("File "):
            continue
        try:
            head, rest = line.split(",", 1)
            path = head[len('File "') : -1]
            line_no = rest.strip().split(",")[0].removeprefix("line ").strip()
        except (ValueError, IndexError):
            continue
        if path.endswith("/" + target) or path.endswith("\\" + target) or path == target:
            last = (target, line_no)
    if last is None:
        return None
    return f"{last[0]}:{last[1]}"


def _format_exit_error(tool_name: str, exit_code: int, stderr: str, stdout: str) -> str:
    """Build a human-readable error from a non-zero exit, with hints for
    well-known signal codes so users don't have to look up POSIX numbers."""
    detail = stderr.strip()[:500] or stdout.strip()[:500]
    hint = ""
    if exit_code in (-9, 137):
        hint = (
            " — likely the OS killed it for using too much memory (SIGKILL). "
            "Try shrinking the dataset window in SETUP.md, or pre-build any "
            "expensive cache outside `dojo domain setup` (run the file once with "
            "`uv run python <sources_dir>/load_data.py`)."
        )
    elif exit_code in (-15, 143):
        hint = " — process was terminated (SIGTERM)."
    elif stderr and "Execution timed out" in stderr:
        hint = (
            " — verification timed out. Bump the cap with "
            "`dojo domain setup --timeout <seconds>` or pre-build the cache."
        )
    suffix = f": {detail}" if detail else ""
    return f"{tool_name} exited with code {exit_code}{hint}{suffix}"


def _workspace_args(
    workspace: Workspace | None,
) -> tuple[str | None, str | None, dict[str, str] | None]:
    if workspace is None or not workspace.ready:
        return None, None, None
    return (
        workspace.path or None,
        workspace.python_path,
        workspace.env_vars or None,
    )


def _check_type(value: Any, spec: str) -> str | None:
    """Best-effort type check — returns an error string or None.

    The schema is a free-form description like "list of float" or "float".
    We do loose, forgiving checks: presence + obvious mismatches.
    """
    s = spec.lower()
    if "list" in s:
        if not isinstance(value, list):
            return f"expected list, got {type(value).__name__}"
        if not value:
            return (
                "expected a non-empty list, got []. "
                "Your data loader returned 0 rows — likely the dataset window "
                "in SETUP.md produced no matching rows."
            )
        if "list of list" in s and not isinstance(value[0], list):
            return "expected list of lists"
        return None
    if "float" in s or "number" in s:
        if not isinstance(value, (int, float)):
            return f"expected number, got {type(value).__name__}"
        return None
    if "int" in s:
        if not isinstance(value, int) or isinstance(value, bool):
            return f"expected int, got {type(value).__name__}"
        return None
    if "str" in s:
        if not isinstance(value, str):
            return f"expected str, got {type(value).__name__}"
        return None
    return None


def _summarise_output(sample: dict[str, Any], *, max_list_items: int = 3) -> dict[str, Any]:
    """Return a small, persistable summary of the tool output.

    The sample may already be pre-summarised by the verifier script's ``_brief()``
    helper (e.g. ``{"type": "array", "len": 1000, "head": [...]}``) or it may be
    plain JSON-safe values (e.g. ``{"rmse": 0.1, "r2": 0.8, "mae": 0.05}``).
    Handle both shapes.
    """
    out: dict[str, Any] = {}
    for k, v in sample.items():
        if isinstance(v, dict) and "len" in v and "head" in v:
            # Already a brief summary from the verifier script's _brief() helper
            out[k] = v
        elif isinstance(v, list):
            out[k] = {"type": "list", "length": len(v), "head": v[:max_list_items]}
        elif isinstance(v, dict):
            out[k] = {"type": "dict", "keys": list(v.keys())[:10]}
        else:
            out[k] = v
    return out


def _rmtree_quiet(path: Path) -> None:
    """Best-effort recursive delete; swallow errors so cleanup never breaks
    a passing verification."""
    import contextlib
    import shutil

    with contextlib.suppress(OSError):
        shutil.rmtree(path, ignore_errors=True)
