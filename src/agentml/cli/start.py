"""CLI start command — launches the uvicorn server and optional frontend."""

import signal
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agentml._version import __version__

console = Console()


def _print_startup_banner(settings, frontend_running: bool = False) -> None:
    """Print a colorful Rich startup banner."""
    lines = Text()
    lines.append("\n")
    lines.append("  AgentML", style="bold cyan")
    lines.append(f" v{__version__}\n\n", style="dim")

    host = settings.api.host
    port = settings.api.port

    entries = [
        ("Backend API ", f"http://{host}:{port}"),
        ("API Docs    ", f"http://{host}:{port}/docs"),
    ]

    if frontend_running:
        entries.append(("Frontend    ", f"http://localhost:{settings.frontend.port}"))

    if settings.tracking.enabled:
        if settings.tracking.backend == "mlflow":
            entries.append(("Tracking    ", f"mlflow ({settings.tracking.mlflow_tracking_uri})"))
        else:
            entries.append(("Tracking    ", settings.tracking.backend))

    entries.append(("Memory      ", settings.memory.backend))

    for label, url in entries:
        lines.append("  ● ", style="green")
        lines.append(label, style="white")
        lines.append(f" {url}\n", style="bold white underline")

    lines.append("\n")

    paths = [
        ("Storage     ", str(settings.storage.base_dir) + "/"),
        ("Experiments ", str(settings.storage.base_dir) + "/experiments/"),
        ("Artifacts   ", str(settings.storage.base_dir) + "/artifacts/"),
        ("Knowledge   ", str(settings.storage.base_dir) + "/memory/"),
    ]

    for label, path in paths:
        lines.append("  ● ", style="green")
        lines.append(label, style="white")
        lines.append(f" {path}\n", style="dim yellow")

    lines.append("\n")
    lines.append("  Press Ctrl+C to stop all services.\n", style="dim italic")

    console.print(Panel(lines, border_style="dim", padding=(0, 1)))


def start(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to listen on"),
    no_frontend: bool = typer.Option(
        False, "--no-frontend", help="Skip launching the frontend dev server"
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable verbose logging"),
) -> None:
    """Start the AgentML server."""
    import uvicorn

    from agentml.api.app import create_app
    from agentml.config.settings import Settings

    settings = Settings.load()
    settings.api.host = host
    settings.api.port = port

    frontend_process = None

    if not no_frontend and settings.frontend.enabled:
        # Look for the frontend directory relative to this file
        frontend_dir = Path(__file__).resolve().parent.parent.parent.parent / "frontend"
        if (frontend_dir / "package.json").exists():
            try:
                frontend_process = subprocess.Popen(
                    ["npm", "run", "dev", "--", "--port", str(settings.frontend.port)],
                    cwd=str(frontend_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                console.print("  [dim yellow]⚠ npm not found — skipping frontend[/dim yellow]")

    # Print startup banner
    _print_startup_banner(settings, frontend_running=frontend_process is not None)

    # Graceful shutdown
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def shutdown(sig, frame):
        if frontend_process:
            frontend_process.terminate()
            frontend_process.wait(timeout=5)
        # Re-raise so uvicorn shuts down too
        if sig == signal.SIGINT and callable(original_sigint):
            original_sigint(sig, frame)
        elif sig == signal.SIGTERM and callable(original_sigterm):
            original_sigterm(sig, frame)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="debug" if debug else "warning")
