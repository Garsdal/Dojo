"""Phase 2 CLI happy-path integration tests.

Covers the user-facing surface:
  - dojo onboard --non-interactive
  - dojo domain show / unfreeze (freeze is internal — exercised via dojo domain setup)
  - dojo program show
  - dojo run (with stub agent, in-process, no server)
  - dojo runs ls / show
  - dojo domain use

Tests use Typer's CliRunner. Each test runs in a fresh tmp dir so the
generated `.dojo/` does not collide.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dojo.cli.main import app


@pytest.fixture
def cli_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Run each CLI test in an isolated working directory."""
    monkeypatch.chdir(tmp_path)
    # Force stub agent so onboard doesn't try to call claude
    monkeypatch.setenv("DOJO_AGENT__BACKEND", "stub")
    yield tmp_path


@pytest.fixture
def initialized_dir(cli_dir: Path) -> Path:
    """An isolated dir that has gone through `dojo onboard --non-interactive`.

    The user is expected to describe the dataset in SETUP.md, then run
    `dojo domain setup`.
    """
    runner = CliRunner()
    workspace = cli_dir / "ws"
    workspace.mkdir()

    result = runner.invoke(
        app,
        [
            "onboard",
            "--name",
            "housing",
            "--workspace",
            str(workspace),
            "--non-interactive",
        ],
    )
    assert result.exit_code == 0, result.output
    return cli_dir


def test_onboard_non_interactive_creates_domain_task_program(initialized_dir: Path):
    state = (initialized_dir / ".dojo" / "state.yaml").read_text()
    assert "current_domain_id:" in state
    # PROGRAM.md is scaffolded under .dojo/domains/{id}/ — keeps the user's
    # repo clean, regardless of whether a workspace is set.
    program = list(initialized_dir.glob(".dojo/domains/*/PROGRAM.md"))
    assert len(program) == 1
    assert not (initialized_dir / "ws" / "PROGRAM.md").exists()
    body = program[0].read_text()
    assert "housing" in body
    # Steering-only template: dataset/evaluate/contract/task-type live in SETUP.md
    assert "## Goal" in body
    assert "## Target" in body
    assert "## Success" in body
    assert "## Notes" in body
    assert "SETUP.md" in body
    assert "## Dataset" not in body
    assert "## Evaluate" not in body


def test_onboard_non_interactive_task_config_defaults(initialized_dir: Path):
    """Onboard's regression task is happy without dataset flags."""
    # task.config should not contain data_path / target_column
    domain_files = list((initialized_dir / ".dojo" / "domains").glob("*.json"))
    assert len(domain_files) == 1
    import json

    data = json.loads(domain_files[0].read_text())
    assert data["task"] is not None
    cfg = data["task"]["config"]
    assert "data_path" not in cfg
    assert "target_column" not in cfg
    assert cfg["test_split_ratio"] == 0.2
    assert cfg["expected_metrics"] == ["rmse", "r2", "mae"]


def test_onboard_non_interactive_requires_name(cli_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["onboard", "--non-interactive"])
    # Missing --name should exit with EXIT_USER_ERROR
    assert result.exit_code != 0
    assert "--name" in result.output


def test_domain_show_after_onboard(initialized_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["domain", "show"])
    assert result.exit_code == 0
    assert "housing" in result.output
    assert "regression" in result.output
    assert "not frozen" in result.output


def test_domain_unfreeze(initialized_dir: Path):
    """Unfreezing flips the task back to mutable — verified via show."""
    import asyncio

    from dojo.cli._lab import build_cli_lab
    from dojo.runtime.task_service import TaskService

    # Force-freeze via the service so we can test unfreeze.
    async def _force_freeze() -> None:
        lab, _ = build_cli_lab()
        domain = (await lab.domain_store.list())[0]
        await TaskService(lab).freeze(domain.id, skip_verification=True)

    asyncio.run(_force_freeze())

    runner = CliRunner()
    show = runner.invoke(app, ["domain", "show"])
    assert "frozen" in show.output and "not frozen" not in show.output

    unfreeze = runner.invoke(app, ["domain", "unfreeze"])
    assert unfreeze.exit_code == 0, unfreeze.output

    show_after = runner.invoke(app, ["domain", "show"])
    assert "not frozen" in show_after.output


def test_program_show_prints_scaffolded_content(initialized_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["program", "show"])
    assert result.exit_code == 0
    assert "Steering prompt" in result.output


def test_run_then_runs_show_in_process(initialized_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end: prep a verified+frozen domain, run, observe."""
    import asyncio

    from dojo.cli._lab import build_cli_lab
    from dojo.core.domain import DomainTool, ToolType, VerificationResult
    from dojo.runtime.task_service import TaskService

    # Force the lab to pick up the .dojo/ inside the test dir
    monkeypatch.chdir(initialized_dir)
    lab, _settings = build_cli_lab()

    async def _seed_verified_tools() -> None:
        domains = await lab.domain_store.list()
        domain = domains[0]
        domain.task.tools = [
            DomainTool(
                name="load_data",
                type=ToolType.DATA_LOADER,
                code="print('{}')",
                verification=VerificationResult(verified=True),
            ),
            DomainTool(
                name="evaluate",
                type=ToolType.EVALUATOR,
                code="print('{}')",
                verification=VerificationResult(verified=True),
            ),
        ]
        await lab.domain_store.save(domain)
        await TaskService(lab).freeze(domain.id)

    asyncio.run(_seed_verified_tools())

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--max-turns", "5"])
    assert result.exit_code == 0, result.output
    assert "completed" in result.output

    show = runner.invoke(app, ["runs", "show"])  # uses current_run_id
    assert show.exit_code == 0
    assert "completed" in show.output

    ls = runner.invoke(app, ["runs", "ls"])
    assert ls.exit_code == 0
    assert "completed" in ls.output


def test_run_blocked_when_task_not_frozen(initialized_dir: Path):
    """`dojo run` exits 3 with an actionable message if task isn't ready."""
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--max-turns", "5"])
    assert result.exit_code == 3, result.output
    assert "task not ready" in result.output
    assert "dojo domain setup" in result.output


def test_runs_show_unknown_id(initialized_dir: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["runs", "show", "ghost-id"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_no_current_domain_actionable_error(cli_dir: Path):
    runner = CliRunner()
    # No onboard has happened yet
    result = runner.invoke(app, ["domain", "show"])
    assert result.exit_code == 1
    assert "dojo onboard" in result.output or "domain use" in result.output


def test_domain_use_switches_pointer(initialized_dir: Path):
    """`domain use` switches the current-domain pointer between two domains
    sharing one .dojo/ store. Onboard refuses to scaffold over an existing
    .dojo/, so the second domain is saved directly via the domain_store."""
    import asyncio

    from dojo.cli._lab import build_cli_lab
    from dojo.core.domain import Domain, DomainStatus

    async def _add_second_domain() -> None:
        lab, _ = build_cli_lab()
        await lab.domain_store.save(
            Domain(name="housing2", description="", status=DomainStatus.ACTIVE)
        )

    asyncio.run(_add_second_domain())

    runner = CliRunner()
    # Switch to the second
    use2 = runner.invoke(app, ["domain", "use", "housing2"])
    assert use2.exit_code == 0
    show2 = runner.invoke(app, ["domain", "show"])
    assert "housing2" in show2.output

    # Switch back to the first by name
    use1 = runner.invoke(app, ["domain", "use", "housing"])
    assert use1.exit_code == 0
    show1 = runner.invoke(app, ["domain", "show"])
    assert "housing" in show1.output and "housing2" not in show1.output.split("\n")[0]


# Suppress the env-var diff between subprocess invocations
@pytest.fixture(autouse=True)
def _no_anthropic_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


# Sanity: nothing leaks into the working directory of the test runner
def test_no_dot_dojo_outside_tmp(cli_dir: Path):
    # Before tests run, the fixture chdir'd into a fresh tmp dir.
    assert not (Path(os.getcwd()) / ".dojo").exists() or Path(os.getcwd()) == cli_dir
