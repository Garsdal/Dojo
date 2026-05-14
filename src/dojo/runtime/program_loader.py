"""PROGRAM.md loader — Karpathy-style human-editable steering prompt.

A `PROGRAM.md` file lives under the domain's local state and acts as the
agent's steering prompt. Editing the file between runs is the lightest
possible feedback loop — no API call, no UI.

Resolution order for a domain's program path:
1. `domain.program_path` if set (explicit override)
2. `<base_dir>/domains/{id}/PROGRAM.md` (default — keeps the user's repo clean)

At agent run start, the orchestrator reads the file (if present) and uses its
content as the steering prompt. Falls back to `domain.prompt` if the file is
missing or empty — preserves existing behaviour for callers that haven't
adopted PROGRAM.md yet.
"""

from __future__ import annotations

from pathlib import Path

from dojo.core.domain import Domain


def resolve_program_path(domain: Domain, *, base_dir: Path | None = None) -> Path:
    """Return the canonical PROGRAM.md path for a domain.

    Does not check existence — callers decide what to do when the file is missing.
    """
    if domain.program_path:
        return Path(domain.program_path).expanduser()
    base = Path(base_dir) if base_dir is not None else Path(".dojo")
    return base / "domains" / domain.id / "PROGRAM.md"


def load_program(domain: Domain, *, base_dir: Path | None = None) -> str:
    """Read the domain's PROGRAM.md, falling back to `domain.prompt`.

    Returns an empty string if neither source has content.
    """
    path = resolve_program_path(domain, base_dir=base_dir)
    if path.exists():
        content = path.read_text().strip()
        if content:
            return content
    return domain.prompt or ""


def write_program(domain: Domain, content: str, *, base_dir: Path | None = None) -> Path:
    """Write content to the domain's PROGRAM.md path. Creates parent dirs.

    Returns the path that was written.
    """
    path = resolve_program_path(domain, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


_DEFAULT_TEMPLATE = """\
# {name}

> Steering prompt for the Dojo.ml agent. Edit freely between runs — the
> agent reads this file at the start of each run.
>
> Data and evaluation specifics live in `SETUP.md` (read once by
> `dojo domain setup` to generate `load_data` + `evaluate`).

## Goal
{description}

## Target
<!--
What is the model predicting? A single sentence is enough.
For sklearn-style (X, y) datasets, just describe the target — there is no
column name.
-->
TODO — describe the target.

## Success
<!--
How do you know the agent did well? RMSE under some threshold, beating a
linear baseline, etc. The agent reads this and uses it to plan experiments.
-->
TODO — describe what success looks like.

## Notes
<!--
Bullet hypotheses you've ruled out, things you've tried, references to past
runs. The agent reads this section every run.
-->
"""


def default_program_template(domain: Domain) -> str:
    """Return a default PROGRAM.md template for a fresh domain."""
    return _DEFAULT_TEMPLATE.format(
        name=domain.name or "Untitled domain",
        description=domain.description or "(describe the research goal)",
    )
