from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from web import auth as web_auth

router = APIRouter()


@router.get("/login")
async def login_page(request: Request) -> Response:
    """
    Render the login page.

    Args:
        request: Incoming HTTP request.

    Returns:
        HTML TemplateResponse for login.html.
    """
    return request.app.state.templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    """
    Validate credentials and issue a session cookie on success.

    On valid credentials, delegates session creation and cookie handling to
    web_auth.open_session() and redirects to the root URL. On failure,
    re-renders login.html with an error message and returns HTTP 401.

    Args:
        request: Incoming HTTP request.
        username: Form field submitted by the login form.
        password: Form field submitted by the login form.

    Returns:
        RedirectResponse (302) to / on success, or login.html (401) on failure.
    """
    config = request.app.state.config.auth
    if web_auth.verify_credentials(username, password, config):
        response = RedirectResponse(url="/", status_code=302)
        web_auth.open_session(response)

        return response

    return request.app.state.templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid credentials"},
        status_code=401,
    )


@router.get("/logout")
async def logout(request: Request) -> Response:
    """
    Invalidate the current session and redirect to the login page.

    Delegates session invalidation and cookie cleanup to
    web_auth.close_session().

    Args:
        request: Incoming HTTP request.

    Returns:
        RedirectResponse (302) to /login with the session cookie cleared.
    """
    response = RedirectResponse(url="/login", status_code=302)
    web_auth.close_session(request, response)

    return response
