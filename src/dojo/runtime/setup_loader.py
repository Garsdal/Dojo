"""SETUP.md loader — task-setup spec for `dojo domain setup`.

Read once at task-generation time to drive `load_data` + `evaluate` creation.
The agent does NOT read this file — it is strictly for the human's data and
evaluation contract.

Resolution order for a domain's setup path:
1. `domain.setup_path` if set (explicit override)
2. `<base_dir>/domains/{id}/SETUP.md` (default)
"""

from __future__ import annotations

from pathlib import Path

from dojo.core.domain import Domain


def resolve_setup_path(domain: Domain, *, base_dir: Path | None = None) -> Path:
    """Return the canonical SETUP.md path for a domain."""
    if domain.setup_path:
        return Path(domain.setup_path).expanduser()
    base = Path(base_dir) if base_dir is not None else Path(".dojo")
    return base / "domains" / domain.id / "SETUP.md"


def load_setup(domain: Domain, *, base_dir: Path | None = None) -> str:
    """Read the domain's SETUP.md. Returns empty string if missing/blank."""
    path = resolve_setup_path(domain, base_dir=base_dir)
    if path.exists():
        content = path.read_text().strip()
        if content:
            return content
    return ""


def write_setup(domain: Domain, content: str, *, base_dir: Path | None = None) -> Path:
    """Write content to the domain's SETUP.md path. Creates parent dirs."""
    path = resolve_setup_path(domain, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


_DEFAULT_TEMPLATE = """\
# {name} — task setup

> Used once by `dojo domain setup` to generate `load_data` + `evaluate`.
> Edit, then run `dojo domain setup` to (re)generate and freeze.
> The agent does NOT read this file at run-time — it sees `PROGRAM.md`.

## Dataset
<!--
Describes where the data lives and how to load it. The AI uses this to write
`load_data`. Examples:

- sklearn loader:
    Use `sklearn.datasets.fetch_california_housing(return_X_y=True)`.

- Local CSV:
    `./data/housing.csv` — features are every column except `MedHouseVal`,
    target is `MedHouseVal`.

- URL:
    Download `https://example.com/data.csv` on first call (cache to `./data/`).
-->
TODO — describe the dataset.

## Evaluate
<!--
Describes what `evaluate(y_pred, *, X_train, X_test, y_train, y_test, artifacts_dir)`
should compute. The AI uses this to write `evaluate`. Signature is fixed —
returns `{{"rmse", "r2", "mae"}}` for regression — but the body is yours to
shape.

ARTIFACTS POLICY: anything `evaluate` writes to `artifacts_dir` is archived
on every experiment run. Use it for residual plots, calibration curves, or
any diagnostic you want consistently archived. (The agent's `train()` also
receives `artifacts_dir` and may write opportunistically — but `evaluate`'s
output is the durable per-run record.)

Examples:
- "Use sklearn's mean_squared_error / r2_score / mean_absolute_error against
  y_test. Save a residuals scatter to artifacts_dir/residuals.png."
- "Wrap our existing evaluator: `from mypkg.eval import evaluate as _impl`."
-->
TODO — describe how evaluation should work, or leave blank for the default.
"""


def default_setup_template(domain: Domain) -> str:
    """Return a default SETUP.md template for a fresh domain."""
    return _DEFAULT_TEMPLATE.format(name=domain.name or "Untitled domain")
