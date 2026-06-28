from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from shared.config import AppConfig
from web.routers import all_routers

TEMPLATES_DIR: Path = Path(__file__).parent / "templates"


def build_app(config: AppConfig) -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    Stores config and templates on app.state. The database is accessed
    via shared.db.get() directly by the service layer.

    Args:
        config: Application configuration loaded from cctv.conf.

    Returns:
        Configured FastAPI application ready for Uvicorn.
    """
    application = FastAPI(title="CCTV", docs_url=None, redoc_url=None)
    application.state.config = config
    application.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    for router in all_routers:
        application.include_router(router)

    return application
