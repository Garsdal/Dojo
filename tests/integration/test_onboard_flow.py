"""Integration test for `dojo onboard` — preset path runs end-to-end.

Uses the same fake-backend pattern as `test_task_setup.py` so we can drive
the AI tool-generation step without hitting Claude.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dojo.cli.main import app

# Canned tools the verifier accepts — same shape as test_task_setup.py.
_CANNED_TOOLS_JSON = """[
  {
    "name": "load_data",
    "filename": "load_data.py",
    "entrypoint": "load_data",
    "description": "Load and split a fixture dataset",
    "type": "data_loader",
    "code": "def load_data():\\n    return [[1.0]], [[2.0]], [1.0], [2.0]\\n"
  },
  {
    "name": "evaluate",
    "filename": "evaluate.py",
    "entrypoint": "evaluate",
    "description": "Compute rmse / r2 / mae against y_test",
    "type": "evaluator",
    "code": "import math\\n\\ndef evaluate(y_pred, *, X_train, X_test, y_train, y_test, artifacts_dir=None):\\n    diffs = [a - b for a, b in zip(y_pred, y_test)]\\n    mse = sum(d*d for d in diffs)/len(diffs)\\n    mae = sum(abs(d) for d in diffs)/len(diffs)\\n    return {\\"rmse\\": math.sqrt(mse), \\"r2\\": 1.0, \\"mae\\": mae}\\n"
  }
]"""


class _FakeBackend:
    name = "fake"
    model = "fake-model"

    async def complete(self, prompt: str) -> str:
        return _CANNED_TOOLS_JSON


@pytest.fixture
def onboard_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Tmp dir + stub backend factory + chdir into the dir.

    CliRunner pipes input via the runner's `input=` kwarg but stdin still
    reports as non-TTY, which onboard's UX guard refuses. Pretend it's a
    TTY for tests so the interactive paths work.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOJO_AGENT__BACKEND", "stub")

    # Onboard imports `_do_generate` from cli/task — patch the factory there.
    import dojo.cli.task as task_cli

    monkeypatch.setattr(
        task_cli, "create_agent_backend", lambda _name, *, model=None: _FakeBackend()
    )

    import dojo.cli.onboard as onboard_mod

    monkeypatch.setattr(onboard_mod, "_stdin_is_tty", lambda: True)
    yield tmp_path


def test_onboard_preset_runs_end_to_end(onboard_dir: Path):
    """Full preset flow: produces a frozen task ready for `dojo run`."""
    runner = CliRunner()

    # CliRunner's input drives the interactive Prompt.ask calls. The flow is:
    #   1. (footgun check — silent in tmp_path)
    #   2. (existing .dojo check — silent because dir doesn't exist yet)
    #   3. (workspace preview — no prompt)
    #   4. config: agent backend / tracking / linker — all defaults
    #   5. domain name (default = tmp basename) + description
    # Each "\n" accepts the default for one prompt. Order matters.
    inputs = "\n".join(
        [
            "claude",  # agent backend (default)
            "file",  # tracking backend (default)
            "keyword",  # linker (default)
            "",  # domain name (use default — cwd basename)
            "",  # description
            "",  # extra newline buffer
        ]
    )

    result = runner.invoke(
        app,
        ["onboard", "--preset", "california_housing", "--workspace", str(onboard_dir)],
        input=inputs,
    )

    assert result.exit_code == 0, result.output
    assert "using preset" in result.output
    assert "california_housing" in result.output or "California housing" in result.output
    assert "task frozen" in result.output

    # Domain on disk: task is frozen with verified tools.
    domain_files = list((onboard_dir / ".dojo" / "domains").glob("*.json"))
    assert len(domain_files) == 1
    data = json.loads(domain_files[0].read_text())
    assert data["task"]["frozen"] is True
    by_name = {t["name"]: t for t in data["task"]["tools"]}
    for name in ("load_data", "evaluate"):
        v = by_name[name].get("verification")
        assert v is not None and v["verified"] is True

    # PROGRAM.md / SETUP.md were written from the preset.
    domain_dir = onboard_dir / ".dojo" / "domains" / domain_files[0].stem
    program = (domain_dir / "PROGRAM.md").read_text()
    setup = (domain_dir / "SETUP.md").read_text()
    assert "California housing" in program
    assert "fetch_california_housing" in setup


def test_select_is_coroutine_so_it_works_inside_asyncio_run() -> None:
    """Regression: questionary's sync `.ask()` starts a nested asyncio loop.

    Inside `_onboard_async` (driven by `asyncio.run`) that raises
    `RuntimeError: asyncio.run() cannot be called from a running event loop`.
    `_select` must be a coroutine using `.ask_async()` so it joins the
    surrounding loop instead of starting its own.
    """
    import inspect

    from dojo.cli.onboard import _select

    assert inspect.iscoroutinefunction(_select), (
        "_select must be async to avoid nested asyncio.run() inside questionary"
    )


def test_resolve_install_cmd_prefers_uv_when_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: uv-managed venvs don't ship pip, so `python -m pip install`
    crashes with `No module named pip`. Use `uv pip install --python <path>`
    when uv is available."""
    import shutil

    from dojo.cli.onboard import _resolve_install_cmd

    monkeypatch.setattr(shutil, "which", lambda name: "/fake/uv" if name == "uv" else None)
    cmd = _resolve_install_cmd("/path/to/python", ["matplotlib", "scikit-learn"])
    assert cmd == [
        "/fake/uv",
        "pip",
        "install",
        "--python",
        "/path/to/python",
        "matplotlib",
        "scikit-learn",
    ]


def test_resolve_install_cmd_falls_back_to_python_pip(monkeypatch: pytest.MonkeyPatch) -> None:
    """When uv isn't on PATH (rare), fall back to `python -m pip install`."""
    import shutil

    from dojo.cli.onboard import _resolve_install_cmd

    monkeypatch.setattr(shutil, "which", lambda name: None)
    cmd = _resolve_install_cmd("/path/to/python", ["matplotlib"])
    assert cmd == ["/path/to/python", "-m", "pip", "install", "matplotlib"]


def test_onboard_unknown_preset_errors_fast(onboard_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["onboard", "--preset", "not_a_real_preset"])
    assert result.exit_code == 1
    assert "unknown preset" in result.output


def test_onboard_custom_path_writes_user_text(onboard_dir: Path):
    """The non-preset path fills the default templates with line-by-line input."""
    runner = CliRunner()

    inputs = "\n".join(
        [
            "claude",  # agent backend
            "file",  # tracking
            "keyword",  # linker
            "my-research",  # domain name
            "",  # description
            "custom",  # decline preset side-prompt (use custom flow)
            "the median house value",  # target
            "RMSE under 0.5",  # success
            "use sklearn fetch_california_housing",  # dataset
            "rmse + r2 + mae",  # evaluate
            "",  # buffer
        ]
    )

    result = runner.invoke(
        app,
        ["onboard", "--workspace", str(onboard_dir)],
        input=inputs,
    )

    assert result.exit_code == 0, result.output
    assert "task frozen" in result.output

    domain_files = list((onboard_dir / ".dojo" / "domains").glob("*.json"))
    assert len(domain_files) == 1
    domain_dir = onboard_dir / ".dojo" / "domains" / domain_files[0].stem
    program = (domain_dir / "PROGRAM.md").read_text()
    setup = (domain_dir / "SETUP.md").read_text()
    # User answers landed in the templates.
    assert "the median house value" in program
    assert "RMSE under 0.5" in program
    assert "use sklearn fetch_california_housing" in setup
    assert "rmse + r2 + mae" in setup
