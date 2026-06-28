from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from shared.config import AppConfig
from web.routers import all_routers

TEMPLATES_DIR: Path = Path(__file__).parent / "templates"


def build_app(
    config: AppConfig,
    db_connection: sqlite3.Connection,
) -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    Stores config, db_connection, and templates on app.state so routers
    can access them via request.app.state without constructor injection.

    Args:
        config: Application configuration loaded from cctv.conf.
        db_connection: Open SQLite connection shared with the recorder thread.

    Returns:
        Configured FastAPI application ready for Uvicorn.
    """
    application = FastAPI(title="CCTV", docs_url=None, redoc_url=None)
    application.state.config = config
    application.state.db_connection = db_connection
    application.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    for router in all_routers:
        application.include_router(router)

    return application
