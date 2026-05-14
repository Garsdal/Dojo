"""`dojo onboard --non-interactive` scaffolds both PROGRAM.md and SETUP.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from dojo.cli.onboard import _onboard_async


@pytest.mark.asyncio
async def test_onboard_non_interactive_writes_program_and_setup(tmp_path: Path, monkeypatch):
    """Non-interactive onboarding writes default templates and stops cleanly."""
    monkeypatch.chdir(tmp_path)

    await _onboard_async(
        workspace_arg="empty",
        preset_key=None,
        name="cal_housing",
        non_interactive=True,
        config_dir=tmp_path / ".dojo",
    )

    domains_dir = tmp_path / ".dojo" / "domains"
    domain_ids = [p for p in domains_dir.iterdir() if p.is_dir()]
    assert len(domain_ids) == 1
    d_dir = domain_ids[0]
    program = d_dir / "PROGRAM.md"
    setup = d_dir / "SETUP.md"
    assert program.exists() and setup.exists()
    # Strict separation of contents — the agent's steering doc must not
    # contain dataset/eval boilerplate, and vice versa.
    assert "## Dataset" not in program.read_text()
    assert "## Goal" not in setup.read_text()
    assert "## Dataset" in setup.read_text()
