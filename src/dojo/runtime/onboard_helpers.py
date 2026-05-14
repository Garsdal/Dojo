"""Pure-logic helpers for `dojo onboard`.

Kept separate from `cli/onboard.py` so they have no Typer / console
dependency and can be unit-tested without a CliRunner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SklearnPreset:
    """A canned starter PROGRAM.md + SETUP.md for a sklearn dataset.

    `pip_deps` are pre-installed into the workspace venv before tool
    generation runs — the user opted into the preset, so by definition
    they don't have an existing project that already provides them.
    """

    key: str
    label: str
    program_md: str
    setup_md: str
    pip_deps: tuple[str, ...]


_CALIFORNIA_HOUSING_PROGRAM = """\
# California housing

> Steering prompt for the Dojo.ml agent. Edit freely between runs — the
> agent reads this file at the start of each run.
>
> Data and evaluation specifics live in `SETUP.md` (read once by
> `dojo domain setup` to generate `load_data` + `evaluate`).

## Goal
Predict California median house value (regression). Minimise RMSE on a 20% held-out test split.

## Target
Median house value (in $100,000s) for census blocks in California.

## Success
Beat a linear baseline. Try at least one tree-based model. Avoid overfitting.

## Notes
"""


_CALIFORNIA_HOUSING_SETUP = """\
# California housing — task setup

> Used once by `dojo domain setup` to generate `load_data` + `evaluate`.
> Edit, then run `dojo domain setup` to (re)generate and freeze.
> The agent does NOT read this file at run-time — it sees `PROGRAM.md`.

## Dataset
Use `sklearn.datasets.fetch_california_housing(return_X_y=True)`.
Features and target both come back as numpy arrays — no column names needed.
https://scikit-learn.org/stable/modules/generated/sklearn.datasets.fetch_california_housing.html

## Evaluate
Use sklearn's mean_squared_error / r2_score / mean_absolute_error against y_test.
Save a residuals scatter plot to artifacts_dir/residuals.png.
"""


PRESETS: dict[str, SklearnPreset] = {
    "california_housing": SklearnPreset(
        key="california_housing",
        label="California housing (sklearn regression)",
        program_md=_CALIFORNIA_HOUSING_PROGRAM,
        setup_md=_CALIFORNIA_HOUSING_SETUP,
        pip_deps=("scikit-learn", "pandas", "numpy", "matplotlib"),
    ),
    # To add more presets (diabetes, breast_cancer, wine, etc.):
    #   - copy the structure above with a fresh PROGRAM.md / SETUP.md
    #   - declare the pip deps the verifier will need on a fresh venv
    #   - add a key to PRESETS
}


_MODULE_NOT_FOUND_RE = re.compile(r"No module named ['\"]([A-Za-z0-9_]+)(?:\.[A-Za-z0-9_.]+)?['\"]")


def parse_module_not_found(error_text: str) -> str | None:
    """Extract the top-level module name from a `ModuleNotFoundError` message.

    Handles:
        - "No module named 'matplotlib'" -> "matplotlib"
        - "No module named 'sklearn.datasets'" -> "sklearn"
        - The wrapped form from the verifier:
              "evaluate raised at evaluate.py:2: No module named 'matplotlib'"
        - Returns None for anything that doesn't match.
    """
    if not error_text:
        return None
    match = _MODULE_NOT_FOUND_RE.search(error_text)
    if match is None:
        return None
    return match.group(1)


def is_path_inside_dojo_repo(workspace: Path, *, dojo_repo: Path | None = None) -> bool:
    """True iff `workspace` resolves to inside the cloned Dojo repo itself.

    Used to warn before writing `.dojo/` somewhere the user almost certainly
    didn't mean — the documented mis-invocation is
    `uv --directory /path/to/Dojo run dojo onboard` which makes the CLI cd into
    the Dojo source tree and create `.dojo/` there.

    `dojo_repo` defaults to the package's resolved location's parent twice
    over (`<repo>/src/dojo/__init__.py` -> `<repo>`). When the package is
    installed via `uv tool install dojoml` it lives under
    `~/.local/share/uv/tools/dojoml/...`, which is also a valid place to
    refuse. The check is only meaningful when running from a checkout, but
    a stricter check would need to also detect installed-tool paths — keep
    it simple for now: any cwd path that has the resolved dojo source dir
    as a prefix triggers the warning.
    """
    try:
        ws = workspace.expanduser().resolve()
    except (OSError, RuntimeError):
        return False

    repo = _resolve_dojo_repo(dojo_repo)
    if repo is None:
        return False

    try:
        ws.relative_to(repo)
        return True
    except ValueError:
        return False


def _resolve_dojo_repo(override: Path | None) -> Path | None:
    """Return the resolved root of the dojo package's repo, or None.

    Walks up from `dojo/__init__.py` to the parent that contains either
    `pyproject.toml` (a checkout) or stops at a sensible boundary.
    """
    if override is not None:
        try:
            return override.expanduser().resolve()
        except (OSError, RuntimeError):
            return None

    try:
        import dojo

        package_dir = Path(dojo.__file__).resolve().parent  # .../src/dojo
    except (ImportError, AttributeError, TypeError):
        return None

    # Walk up until pyproject.toml found, or 4 parents up — whichever first.
    candidate = package_dir.parent  # .../src
    for _ in range(4):
        if (candidate / "pyproject.toml").is_file():
            return candidate
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent
    return None


def fill_program_template(
    base_template: str,
    *,
    target: str,
    success: str,
) -> str:
    """Replace the `TODO` placeholders in `default_program_template`'s output.

    The default template has two TODO lines under `## Target` and `## Success`.
    We replace them with the user's free-text answers without changing the
    surrounding section headers / HTML comments.
    """
    out = base_template
    out = out.replace(
        "TODO — describe the target.", target.strip() or "TODO — describe the target."
    )
    out = out.replace(
        "TODO — describe what success looks like.",
        success.strip() or "TODO — describe what success looks like.",
    )
    return out


def fill_setup_template(
    base_template: str,
    *,
    dataset: str,
    evaluate: str,
) -> str:
    """Replace the `TODO` placeholders in `default_setup_template`'s output."""
    out = base_template
    out = out.replace(
        "TODO — describe the dataset.",
        dataset.strip() or "TODO — describe the dataset.",
    )
    out = out.replace(
        "TODO — describe how evaluation should work, or leave blank for the default.",
        evaluate.strip()
        or "TODO — describe how evaluation should work, or leave blank for the default.",
    )
    return out
