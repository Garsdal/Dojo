"""Unit tests for `dojo.runtime.onboard_helpers`."""

from pathlib import Path

import pytest

from dojo.runtime.onboard_helpers import (
    PRESETS,
    fill_program_template,
    fill_setup_template,
    is_path_inside_dojo_repo,
    parse_module_not_found,
)


# --- parse_module_not_found ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No module named 'matplotlib'", "matplotlib"),
        ("No module named 'sklearn.datasets'", "sklearn"),
        ('No module named "matplotlib"', "matplotlib"),
        # The wrapped form the tool_verifier actually emits.
        (
            "evaluate raised at evaluate.py:2: No module named 'matplotlib'",
            "matplotlib",
        ),
        ("load_data raised at load_data.py:5: No module named 'sklearn.datasets'", "sklearn"),
        # Garbage / unrelated errors -> None
        ("", None),
        ("ValueError: bad input", None),
        ("ImportError: cannot import name 'foo' from 'bar'", None),
        ("No module named", None),  # missing the quoted name
    ],
)
def test_parse_module_not_found(text: str, expected: str | None) -> None:
    assert parse_module_not_found(text) == expected


# --- is_path_inside_dojo_repo ---------------------------------------------


def test_is_path_inside_dojo_repo_false_for_tmp(tmp_path: Path) -> None:
    assert is_path_inside_dojo_repo(tmp_path) is False


def test_is_path_inside_dojo_repo_true_for_dojo_source() -> None:
    """The Dojo source tree itself should trigger the footgun warning."""
    import dojo

    package_dir = Path(dojo.__file__).resolve().parent
    assert is_path_inside_dojo_repo(package_dir) is True


def test_is_path_inside_dojo_repo_with_override(tmp_path: Path) -> None:
    """Explicit override pins which dir counts as 'the repo'."""
    fake_repo = tmp_path / "fake_dojo_repo"
    fake_repo.mkdir()
    (fake_repo / "pyproject.toml").write_text("")

    inside = fake_repo / "subdir"
    inside.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    assert is_path_inside_dojo_repo(inside, dojo_repo=fake_repo) is True
    assert is_path_inside_dojo_repo(outside, dojo_repo=fake_repo) is False


def test_is_path_inside_dojo_repo_handles_relative_paths(tmp_path: Path) -> None:
    """Relative paths must be resolved before comparison."""
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "pyproject.toml").write_text("")
    inside = fake_repo / "sub"
    inside.mkdir()

    # Relative path that resolves into fake_repo
    assert is_path_inside_dojo_repo(Path(str(inside)), dojo_repo=fake_repo) is True


# --- PRESETS registry ------------------------------------------------------


def test_california_housing_preset_present() -> None:
    assert "california_housing" in PRESETS
    p = PRESETS["california_housing"]
    assert p.key == "california_housing"
    assert p.label
    assert p.program_md.strip()
    assert p.setup_md.strip()
    # The preset must declare deps a fresh venv would need.
    assert "scikit-learn" in p.pip_deps
    assert "matplotlib" in p.pip_deps


def test_preset_setup_md_mentions_sklearn_loader() -> None:
    """Smoke-check that the SETUP.md is actually preset-shaped, not a TODO stub."""
    setup = PRESETS["california_housing"].setup_md
    assert "fetch_california_housing" in setup
    assert "TODO" not in setup


def test_preset_program_md_mentions_target_and_success() -> None:
    """The PROGRAM.md must have the user's three steering bullets filled in."""
    program = PRESETS["california_housing"].program_md
    assert "## Goal" in program
    assert "## Target" in program
    assert "## Success" in program
    assert "TODO" not in program


# --- template fillers ------------------------------------------------------


def test_fill_program_template_replaces_todos() -> None:
    base = (
        "# X\n## Target\nTODO — describe the target.\n"
        "## Success\nTODO — describe what success looks like.\n"
    )
    out = fill_program_template(base, target="predict X", success="beat baseline")
    assert "predict X" in out
    assert "beat baseline" in out
    assert "TODO — describe the target." not in out
    assert "TODO — describe what success looks like." not in out


def test_fill_program_template_keeps_todo_when_blank() -> None:
    """Blank input shouldn't blow away the TODO marker (user can fix later)."""
    base = "## Target\nTODO — describe the target.\n## Success\nTODO — describe what success looks like.\n"
    out = fill_program_template(base, target="", success="   ")
    assert "TODO — describe the target." in out
    assert "TODO — describe what success looks like." in out


def test_fill_setup_template_replaces_todos() -> None:
    base = (
        "## Dataset\nTODO — describe the dataset.\n"
        "## Evaluate\nTODO — describe how evaluation should work, or leave blank for the default.\n"
    )
    out = fill_setup_template(
        base,
        dataset="Use a CSV at data/x.csv",
        evaluate="RMSE / R2",
    )
    assert "Use a CSV at data/x.csv" in out
    assert "RMSE / R2" in out
    assert "TODO — describe the dataset." not in out
