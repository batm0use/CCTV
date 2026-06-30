from __future__ import annotations

import base64
import secrets
import threading
import time

from fastapi import Request
from fastapi.responses import Response

from shared.config import AuthConfig

# Maps session token → Unix timestamp of creation (time.time()).
_sessions: dict[str, float] = {}
_sessions_lock = threading.Lock()

COOKIE_NAME = "cctv_session"


class NotAuthenticatedError(Exception):
    """
    Raised by require_auth when a request carries no valid session or credentials.

    Caught by the exception handler registered in build_app(), which redirects
    browser clients to /login and returns a 401 JSON response to API clients.
    """


def create_session() -> str:
    """
    Generate a new session token and record its creation time.

    Returns:
        A 64-character hex token suitable for use as a cookie value.
    """
    token = secrets.token_hex(32)
    with _sessions_lock:
        _sessions[token] = time.time()

    return token


def invalidate_session(token: str) -> None:
    """
    Remove a session token from the in-memory store on logout.

    No-op if the token is not present (e.g. already expired or unknown).

    Args:
        token: The session token to invalidate.
    """
    with _sessions_lock:
        _sessions.pop(token, None)


def _is_valid_session(token: str, lifetime_seconds: float) -> bool:
    """
    Return True if the token exists and has not yet exceeded its lifetime.

    Expired tokens are removed from the store on first access (lazy cleanup).

    Args:
        token: Session token from the request cookie.
        lifetime_seconds: Maximum age in seconds before the session is rejected.

    Returns:
        True if the session is active and unexpired, False otherwise.
    """
    with _sessions_lock:
        created_at = _sessions.get(token)
        if created_at is None:
            return False

        if time.time() - created_at > lifetime_seconds:
            del _sessions[token]

            return False

        return True


def open_session(response: Response) -> None:
    """
    Create a new session and attach its cookie to the outgoing response.

    Encapsulates token generation and all cookie flags (httponly, samesite,
    secure) so the router layer has no knowledge of session internals.

    Args:
        response: Outgoing HTTP response to set the session cookie on.
    """
    token = create_session()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=False,  # False = sent over both HTTP (LAN) and HTTPS (RPi Connect)
    )


def close_session(request: Request, response: Response) -> None:
    """
    Invalidate the session from the incoming request and clear its cookie.

    No-op if no session cookie is present.

    Args:
        request: Incoming HTTP request to read the session cookie from.
        response: Outgoing HTTP response to clear the cookie on.
    """
    token = request.cookies.get(COOKIE_NAME)
    if token:
        invalidate_session(token)
    response.delete_cookie(COOKIE_NAME)


def verify_credentials(username: str, password: str, config: AuthConfig) -> bool:
    """
    Check a username/password pair against the configured credentials.

    Args:
        username: Supplied username.
        password: Supplied password.
        config: AuthConfig loaded from cctv.conf.

    Returns:
        True if both username and password match exactly.
    """
    return username == config.username and password == config.password


def require_auth(request: Request) -> None:
    """
    FastAPI dependency that enforces authentication on every protected route.

    Accepts two credential forms:
    - Session cookie (``cctv_session``): set by POST /login for browser clients.
      Expires after auth.session_lifetime_hours (default 24 h).
    - HTTP Basic auth header: used by the laptop sync agent, validated directly
      against the credentials in cctv.conf without creating a session.

    Raises:
        NotAuthenticatedError: If neither credential form is present or valid.
    """
    auth_config: AuthConfig = request.app.state.config.auth
    lifetime_seconds = auth_config.session_lifetime_hours * 3600

    # Browser session cookie
    token = request.cookies.get(COOKIE_NAME)
    if token and _is_valid_session(token, lifetime_seconds):
        return

    # HTTP Basic auth for the laptop sync agent (stateless)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, _, password = decoded.partition(":")
            if verify_credentials(username, password, auth_config):
                return
        except Exception:
            pass

    raise NotAuthenticatedError()
