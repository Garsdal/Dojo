"""Dojo.ml CLI — main entry point."""

import typer

from dojo._version import __version__

app = typer.Typer(
    name="dojo",
    help="Dojo.ml — AI-powered experiment orchestration",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Dojo.ml v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Dojo.ml CLI."""


@app.command()
def start(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to listen on"),
    no_frontend: bool = typer.Option(
        False, "--no-frontend", help="Skip launching the frontend dev server"
    ),
) -> None:
    """Start the Dojo.ml server."""
    from dojo.cli.start import start as _start

    _start(host=host, port=port, no_frontend=no_frontend)


# --- Top-level commands ---

from dojo.cli.onboard import onboard as _onboard  # noqa: E402
from dojo.cli.run import run as _run  # noqa: E402
from dojo.cli.stop import stop as _stop  # noqa: E402

app.command("onboard")(_onboard)
app.command("run")(_run)
app.command("stop")(_stop)


# --- Subcommand groups ---

from dojo.cli.config import config_app  # noqa: E402
from dojo.cli.domain import app as domain_app  # noqa: E402
from dojo.cli.experiments import app as experiments_app  # noqa: E402
from dojo.cli.program import app as program_app  # noqa: E402
from dojo.cli.runs import app as runs_app  # noqa: E402
from dojo.cli.skill import app as skill_app  # noqa: E402

app.add_typer(config_app, name="config")
app.add_typer(domain_app, name="domain")
app.add_typer(runs_app, name="runs")
app.add_typer(experiments_app, name="experiments")
app.add_typer(program_app, name="program")
app.add_typer(skill_app, name="skill")
