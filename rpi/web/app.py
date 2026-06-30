from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from shared.config import AppConfig
from web.auth import NotAuthenticatedError
from web.routers import all_routers

TEMPLATES_DIR: Path = Path(__file__).parent / "templates"


def build_app(config: AppConfig) -> FastAPI:
    """
    Create and configure the FastAPI application instance.

    Registers the NotAuthenticatedError handler so that unauthenticated
    browser requests redirect to /login and API requests receive a 401 JSON
    response. Stores config and templates on app.state. The database is
    accessed via shared.db.get() directly by the service layer.

    Args:
        config: Application configuration loaded from cctv.conf.

    Returns:
        Configured FastAPI application ready for Uvicorn.
    """
    application = FastAPI(title="CCTV", docs_url=None, redoc_url=None)
    application.state.config = config
    application.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @application.exception_handler(NotAuthenticatedError)
    async def handle_not_authenticated(
        request: Request, _exc: NotAuthenticatedError
    ) -> RedirectResponse | JSONResponse:
        """
        Convert an unauthenticated request into an appropriate response.

        Browser clients (Accept: text/html) are redirected to /login.
        API clients (e.g. the laptop sync agent) receive a 401 JSON response.

        Args:
            request: The incoming HTTP request.
            _exc: The NotAuthenticatedError raised by require_auth.

        Returns:
            RedirectResponse to /login for browser clients, or a 401
            JSONResponse for API clients.
        """
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login", status_code=302)

        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    for router in all_routers:
        application.include_router(router)

    return application
