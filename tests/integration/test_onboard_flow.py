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


def test_select_is_sync_no_nested_event_loop() -> None:
    """Regression: an earlier version used `questionary` whose sync `.ask()`
    started a nested asyncio loop (crash) and whose async `.ask_async()`
    forced `_select` to be a coroutine. Switching to `simple-term-menu`
    (POSIX termios, no event loop) lets `_select` go back to sync — and
    keeping it sync prevents anyone reintroducing the nested-loop hazard.
    """
    import inspect

    from dojo.cli.onboard import _select

    assert not inspect.iscoroutinefunction(_select), (
        "_select must stay sync — async signatures here historically meant a "
        "library that started its own event loop, which crashes inside "
        "asyncio.run(_onboard_async(...))."
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


def test_onboard_custom_path_skip_stops_before_tool_gen(onboard_dir: Path):
    """Custom + 'skip' writes default templates and stops cleanly before tool
    generation — no freeze, no verifier call. User can edit PROGRAM.md + SETUP.md
    and run `dojo task setup` later without needing `dojo task unfreeze` first."""
    runner = CliRunner()

    inputs = "\n".join(
        [
            "claude",  # agent backend
            "file",  # tracking
            "keyword",  # linker
            "my-research",  # domain name
            "",  # description
            "custom",  # decline preset side-prompt
            "skip",  # fill-mode: write defaults, finish manually
            "",  # buffer
        ]
    )

    result = runner.invoke(
        app,
        ["onboard", "--workspace", str(onboard_dir)],
        input=inputs,
    )

    assert result.exit_code == 0, result.output
    # Skip path explicitly does NOT freeze.
    assert "onboarding paused" in result.output
    assert "task frozen" not in result.output

    domain_files = list((onboard_dir / ".dojo" / "domains").glob("*.json"))
    assert len(domain_files) == 1
    data = json.loads(domain_files[0].read_text())
    assert data["task"]["frozen"] is False
    # Tools should not have been generated (skip path).
    assert data["task"]["tools"] == []

    # Default templates exist on disk for the user to edit.
    domain_dir = onboard_dir / ".dojo" / "domains" / domain_files[0].stem
    assert (domain_dir / "PROGRAM.md").exists()
    assert (domain_dir / "SETUP.md").exists()


def test_onboard_custom_path_editor_writes_edited_content(
    onboard_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Custom + 'editor' opens $EDITOR (monkeypatched), captures the edited
    content into PROGRAM.md and SETUP.md, and proceeds through verify + freeze."""
    import dojo.cli.onboard as onboard_mod

    edited_payloads = iter(
        [
            "# PROGRAM.md\nedited program content from $EDITOR\n",
            "# SETUP.md\nedited setup content from $EDITOR\n",
        ]
    )
    monkeypatch.setattr(
        onboard_mod.typer, "edit", lambda text=None, extension=None: next(edited_payloads)
    )

    runner = CliRunner()
    inputs = "\n".join(
        [
            "claude",  # agent backend
            "file",  # tracking
            "keyword",  # linker
            "my-research",  # domain name
            "",  # description
            "custom",  # decline preset side-prompt
            "editor",  # fill-mode: open in $EDITOR
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
    assert "edited program content from $EDITOR" in (domain_dir / "PROGRAM.md").read_text()
    assert "edited setup content from $EDITOR" in (domain_dir / "SETUP.md").read_text()


def test_onboard_custom_path_editor_falls_back_when_edit_returns_none(
    onboard_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """If `typer.edit` returns None (user closed without saving), fall back to
    the default template and warn — don't crash the flow."""
    import dojo.cli.onboard as onboard_mod

    monkeypatch.setattr(onboard_mod.typer, "edit", lambda text=None, extension=None: None)

    runner = CliRunner()
    inputs = "\n".join(
        [
            "claude",
            "file",
            "keyword",
            "my-research",
            "",
            "custom",
            "editor",
            "",
        ]
    )

    result = runner.invoke(
        app,
        ["onboard", "--workspace", str(onboard_dir)],
        input=inputs,
    )

    assert result.exit_code == 0, result.output
    assert "no changes saved" in result.output
    # Flow still proceeds to freeze (with the unedited defaults).
    assert "task frozen" in result.output
