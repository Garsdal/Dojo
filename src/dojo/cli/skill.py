"""`dojo skill` — fetch Claude Code skills bundled with the Dojo repo.

Skills aren't shipped inside the PyPI wheel; they live in the GitHub
repo at `.claude/skills/<name>/SKILL.md` and are fetched on demand via
this command. Default ref is the installed Dojo version's git tag with
a fallback to `main` (which covers the gap before the first tag that
includes a given skill, plus `--ref main` invocations explicitly).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import typer
from rich.console import Console

from dojo._version import __version__

app = typer.Typer(name="skill", help="Install Claude Code skills shipped with Dojo.")
console = Console()

# Hardcoded allowlist — keeps the surface small and tells the user up
# front what's available. Each entry is the directory name under
# `.claude/skills/` in the Dojo repo.
SKILLS: dict[str, str] = {
    "dojo-onboard": "Conversational onboarding for existing Python codebases.",
}

REPO_RAW_BASE = "https://raw.githubusercontent.com/Garsdal/Dojo"

EXIT_USER_ERROR = 1
EXIT_NETWORK = 2


def _user_scope_dir() -> Path:
    return Path.home() / ".claude" / "skills"


def _project_scope_dir() -> Path:
    return Path.cwd() / ".claude" / "skills"


def _fetch_skill_md(*, name: str, ref: str) -> str:
    """Fetch `SKILL.md` for `name` at `ref` from the Dojo repo.

    Raises `urllib.error.HTTPError` on non-200 responses so callers can
    distinguish 404 (fall back to `main`) from other failures.
    """
    url = f"{REPO_RAW_BASE}/{ref}/.claude/skills/{name}/SKILL.md"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read().decode("utf-8")


@app.command("list")
def list_skills() -> None:
    """List skills available to install."""
    console.print("[bold]Available skills:[/bold]")
    for slug, desc in SKILLS.items():
        console.print(f"  [cyan]{slug}[/cyan]  {desc}")
    console.print(
        "\n[dim]Install with [bold]dojo skill install <name>[/bold]. "
        "Default scope is user (~/.claude/skills/).[/dim]"
    )


@app.command("install")
def install(
    name: str = typer.Argument(..., help="Skill to install (see `dojo skill list`)."),
    scope: str = typer.Option(
        "user",
        "--scope",
        help="Install location: 'user' (~/.claude/skills/) or 'project' (./.claude/skills/).",
    ),
    ref: str | None = typer.Option(
        None,
        "--ref",
        help="Git ref to fetch from (default: v<dojo-version>, falling back to main).",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing skill of the same name."
    ),
) -> None:
    """Install a Claude Code skill into ~/.claude/skills/ (or ./.claude/skills/)."""
    if name not in SKILLS:
        console.print(
            f"[red]error:[/red] unknown skill {name!r}. Run [bold]dojo skill list[/bold]."
        )
        raise typer.Exit(code=EXIT_USER_ERROR)

    if scope not in ("user", "project"):
        console.print(f"[red]error:[/red] --scope must be 'user' or 'project', got {scope!r}.")
        raise typer.Exit(code=EXIT_USER_ERROR)

    target_root = _user_scope_dir() if scope == "user" else _project_scope_dir()
    target_dir = target_root / name
    target_file = target_dir / "SKILL.md"

    if target_file.exists() and not force:
        console.print(
            f"[red]error:[/red] {target_file} already exists. Re-run with [bold]--force[/bold] "
            "to overwrite."
        )
        raise typer.Exit(code=EXIT_USER_ERROR)

    # Pick the ref. Default: pinned version tag, fall back to `main` on 404
    # (covers pre-tag installs and the release-introducing-the-skill window).
    refs_to_try: list[str] = []
    if ref is not None:
        refs_to_try.append(ref)
    else:
        refs_to_try = [f"v{__version__}", "main"]

    content: str | None = None
    used_ref: str | None = None
    last_error: Exception | None = None
    for candidate in refs_to_try:
        try:
            content = _fetch_skill_md(name=name, ref=candidate)
            used_ref = candidate
            break
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 404 and ref is None and candidate != refs_to_try[-1]:
                console.print(f"[dim]not found at {candidate} — trying {refs_to_try[-1]}...[/dim]")
                continue
            break
        except urllib.error.URLError as e:
            last_error = e
            break

    if content is None or used_ref is None:
        console.print(
            f"[red]error:[/red] could not fetch {name} from GitHub ({last_error}). "
            "Check your network or try [bold]--ref main[/bold] explicitly."
        )
        raise typer.Exit(code=EXIT_NETWORK)

    target_dir.mkdir(parents=True, exist_ok=True)
    target_file.write_text(content)

    console.print(
        f"[green]✓[/green] fetched {name} from Garsdal/Dojo@{used_ref}\n"
        f"[green]✓[/green] wrote {target_file}\n"
        f"\nInvoke it from Claude Code with [bold]/{name}[/bold]."
    )
