"""Integration tests for `dojo skill install` / `dojo skill list`.

Skills are fetched from the Dojo GitHub repo over HTTP; tests monkeypatch
the fetch so they're offline-safe and deterministic.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dojo.cli.main import app

CANNED_SKILL_MD = "---\nname: dojo-onboard\ndescription: test fixture\n---\n\n# fake skill\n"


@pytest.fixture
def skill_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Run inside tmp dir so project-scope installs land under tmp."""
    monkeypatch.chdir(tmp_path)
    # Redirect user scope so the test doesn't write to the real ~/.claude/.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    yield tmp_path


def test_skill_list_includes_dojo_onboard(skill_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "list"])
    assert result.exit_code == 0
    assert "dojo-onboard" in result.output


def test_install_project_scope_writes_skill_md(
    skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dojo.cli.skill as skill_mod

    captured: dict[str, str] = {}

    def fake_fetch(*, name: str, ref: str) -> str:
        captured["name"] = name
        captured["ref"] = ref
        return CANNED_SKILL_MD

    monkeypatch.setattr(skill_mod, "_fetch_skill_md", fake_fetch)

    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "dojo-onboard", "--scope", "project"])
    assert result.exit_code == 0, result.output
    assert captured["name"] == "dojo-onboard"

    target = skill_dir / ".claude" / "skills" / "dojo-onboard" / "SKILL.md"
    assert target.read_text() == CANNED_SKILL_MD


def test_install_user_scope_writes_to_home_claude(
    skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dojo.cli.skill as skill_mod

    monkeypatch.setattr(skill_mod, "_fetch_skill_md", lambda *, name, ref: CANNED_SKILL_MD)

    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "dojo-onboard"])
    assert result.exit_code == 0, result.output

    home = Path(skill_dir / "home")
    target = home / ".claude" / "skills" / "dojo-onboard" / "SKILL.md"
    assert target.exists()
    assert target.read_text() == CANNED_SKILL_MD


def test_install_unknown_skill_errors_fast(skill_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "no-such-skill"])
    assert result.exit_code == 1
    assert "unknown skill" in result.output


def test_install_refuses_overwrite_without_force(
    skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dojo.cli.skill as skill_mod

    monkeypatch.setattr(skill_mod, "_fetch_skill_md", lambda *, name, ref: CANNED_SKILL_MD)

    runner = CliRunner()
    # First install — succeeds.
    r1 = runner.invoke(app, ["skill", "install", "dojo-onboard", "--scope", "project"])
    assert r1.exit_code == 0, r1.output

    # Second install without --force — refuses.
    r2 = runner.invoke(app, ["skill", "install", "dojo-onboard", "--scope", "project"])
    assert r2.exit_code == 1
    assert "already exists" in r2.output

    # With --force — succeeds.
    r3 = runner.invoke(app, ["skill", "install", "dojo-onboard", "--scope", "project", "--force"])
    assert r3.exit_code == 0, r3.output


def test_install_falls_back_to_main_on_version_tag_404(
    skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the version-pinned tag doesn't have the skill yet (e.g. installing
    on `main` ahead of the next tag), fall through to `main`."""
    import dojo.cli.skill as skill_mod

    calls: list[str] = []

    def flaky_fetch(*, name: str, ref: str) -> str:
        calls.append(ref)
        if ref.startswith("v"):
            raise urllib.error.HTTPError(
                url="http://example", code=404, msg="Not Found", hdrs=None, fp=None
            )
        return CANNED_SKILL_MD

    monkeypatch.setattr(skill_mod, "_fetch_skill_md", flaky_fetch)

    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "dojo-onboard", "--scope", "project"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert calls[0].startswith("v")
    assert calls[1] == "main"


def test_install_surfaces_network_error(skill_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import dojo.cli.skill as skill_mod

    def broken_fetch(*, name: str, ref: str) -> str:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(skill_mod, "_fetch_skill_md", broken_fetch)

    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "dojo-onboard"])
    assert result.exit_code == 2
    assert "could not fetch" in result.output


def test_install_explicit_ref_skips_fallback(
    skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing --ref should use that ref and only that ref (no main fallback)."""
    import dojo.cli.skill as skill_mod

    calls: list[str] = []

    def fetch(*, name: str, ref: str) -> str:
        calls.append(ref)
        raise urllib.error.HTTPError(
            url="http://example", code=404, msg="Not Found", hdrs=None, fp=None
        )

    monkeypatch.setattr(skill_mod, "_fetch_skill_md", fetch)

    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "dojo-onboard", "--ref", "v0.1.0"])
    assert result.exit_code == 2
    assert calls == ["v0.1.0"]
