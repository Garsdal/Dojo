"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dojo._version import __version__
from dojo.api.deps import build_lab
from dojo.api.routers import (
    agent,
    config,
    domains,
    experiments,
    health,
    knowledge,
    tracking,
)
from dojo.config.settings import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifecycle — load persisted data on startup, clean up on shutdown."""
    if hasattr(app.state, "lab"):
        await agent.load_runs(app.state.lab)
    yield
    if hasattr(app.state, "lab"):
        await app.state.lab.tracking.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Application settings. Loads defaults if not provided.

    Returns:
        Configured FastAPI application.
    """
    if settings is None:
        settings = Settings.load()

    app = FastAPI(
        title="Dojo.ml",
        description="AI-powered experiment orchestration",
        version=__version__,
        lifespan=_lifespan,
    )

    # CORS — allow the React dev server through
    frontend_port = settings.frontend.port
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://localhost:{frontend_port}",
            f"http://127.0.0.1:{frontend_port}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Wire up the lab environment
    app.state.lab = build_lab(settings)
    app.state.settings = settings

    # Register routers
    app.include_router(health.router)
    app.include_router(domains.router)
    app.include_router(experiments.router)
    app.include_router(knowledge.router)
    app.include_router(tracking.router)
    app.include_router(config.router)
    app.include_router(agent.router)

    return app
