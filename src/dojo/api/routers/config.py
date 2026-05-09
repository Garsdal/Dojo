"""Config router — expose configuration to the frontend."""

from fastapi import APIRouter, Request

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_config(request: Request) -> dict:
    """Return public configuration for the frontend."""
    settings = request.app.state.settings
    return {
        "api": {"host": settings.api.host, "port": settings.api.port},
        "storage": {"base_dir": str(settings.storage.base_dir)},
        "tracking": {"enabled": settings.tracking.enabled},
    }
