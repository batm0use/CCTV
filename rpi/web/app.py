from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from shared.config import AppConfig
from web.routes.api import build_api_router
from web.routes.footage import build_footage_router
from web.routes.live import build_live_router

TEMPLATES_DIR: Path = Path(__file__).parent / "templates"


def build_app(
    config: AppConfig,
    db_connection: sqlite3.Connection,
) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Registers all route groups and passes config and the shared DB
    connection as dependencies via router-level state.

    Args:
        config: Application configuration loaded from cctv.conf.
        db_connection: Open SQLite connection shared with the recorder thread.

    Returns:
        Configured FastAPI application ready for Uvicorn.
    """
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    application = FastAPI(title="CCTV", docs_url=None, redoc_url=None)

    application.include_router(
        build_live_router(config=config, templates=templates)
    )
    application.include_router(
        build_footage_router(
            config=config,
            db_connection=db_connection,
            templates=templates,
        )
    )
    application.include_router(
        build_api_router(config=config, db_connection=db_connection)
    )

    return application
