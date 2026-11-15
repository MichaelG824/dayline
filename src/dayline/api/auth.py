"""Google sign-in + allowlisted session for the FastAPI surface.

The UI is a personal app: any Google account can complete OAuth (that is the
ownership proof), but only the address in ``ALLOWED_EMAIL`` may call
``/api/*``. Unauthenticated requests 401; signed-in-but-not-allowlisted
requests 403. If ``ALLOWED_EMAIL`` is unset, nobody is allowlisted. A
liveness probe and the OAuth endpoints stay public.

Session is an HS256 JWT in the ``dayline_session`` cookie (also accepted as
``Authorization: Bearer``). The secret must be stable across scale-to-zero
restarts - a random-per-boot secret would sign everyone out on every cold start.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

SESSION_COOKIE = "dayline_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
DEFAULT_PUBLIC_URL = "http://localhost:3000"

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

_PUBLIC_EXACT = frozenset(
    {
        "/api/health",
        "/api/auth/google",
        "/api/auth/callback",
        "/api/auth/logout",
        "/api/auth/me",
    }
)


@dataclass(frozen=True, slots=True)
class Identity:
    email: str
    sub: str


def allowed_email() -> str:
    return os.environ.get("ALLOWED_EMAIL", "").strip().lower()


def email_allowed(email: str) -> bool:
    allowed = allowed_email()
    if not allowed:
        return False
    return email.strip().lower() == allowed


def public_url() -> str:
    return os.environ.get("PUBLIC_URL", DEFAULT_PUBLIC_URL).rstrip("/")


def google_redirect_uri() -> str:
    override = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    return override or f"{public_url()}/api/auth/callback"


def auth_secret() -> str:
    secret = os.environ.get("AUTH_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "AUTH_SECRET is not set. Generate a long random string and put it in "
            "the environment (same value for the API and the Next.js UI)."
        )
    return secret


def cookie_secure() -> bool:
    return public_url().startswith("https://")


def cors_origins() -> list[str]:
    origins = [
        "http://localhost:3000",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3003",
        "http://127.0.0.1:3004",
    ]
    pub = public_url()
    if pub and pub not in origins:
        origins.append(pub)
    extra = os.environ.get("CORS_ORIGINS", "")
    for item in extra.split(","):
        origin = item.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


# Live-session previews authenticate with the token in their path, since the
# sandboxed app never sends the session cookie (services/mock_preview.py).
_PUBLIC_PREFIXES = ("/api/preview/",)


def is_public_path(path: str) -> bool:
    return path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIXES)


class AppCORSMiddleware(CORSMiddleware):
    """CORS for Dayline's own pages, except the live preview: its sandboxed
    app sends ``Origin: null``, and the preview answers that itself
    (``services/mock_preview.py``)."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(_PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def issue_session(email: str, sub: str) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "email": email,
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(seconds=SESSION_MAX_AGE_SECONDS),
    }
    return jwt.encode(payload, auth_secret(), algorithm="HS256")


def identity_from_token(token: str) -> Identity | None:
    try:
        payload = jwt.decode(token, auth_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    email = payload.get("email")
    sub = payload.get("sub")
    if not isinstance(email, str) or not email.strip():
        return None
    if not isinstance(sub, str) or not sub:
        sub = email
    return Identity(email=email.strip(), sub=sub)


def identity_from_request(request: HTTPConnection) -> Identity | None:
    """The signed-in identity of an HTTP request or a WebSocket connection."""
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    token: str | None = None
    if header and header.lower().startswith("bearer "):
        token = header[7:].strip() or None
    if not token:
        raw = request.cookies.get(SESSION_COOKIE)
        token = raw.strip() if raw else None
    if not token:
        return None
    return identity_from_token(token)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def make_oauth_state() -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "n": secrets.token_urlsafe(16),
        "exp": now + timedelta(minutes=10),
        "iat": now,
    }
    return jwt.encode(payload, auth_secret(), algorithm="HS256")


def oauth_state_valid(state: str | None) -> bool:
    if not state:
        return False
    try:
        jwt.decode(state, auth_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return False
    return True


def google_client_id() -> str:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID is not set. Create a Web application OAuth client "
            "in Google Cloud Console and put the client id in the environment."
        )
    return client_id


def google_client_secret() -> str:
    secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_SECRET is not set. Create a Web application OAuth "
            "client in Google Cloud Console and put the client secret in the "
            "environment."
        )
    return secret


def google_authorize_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": google_client_id(),
            "redirect_uri": google_redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{_GOOGLE_AUTH_URL}?{query}"


def websocket_auth_problem(connection: HTTPConnection) -> str | None:
    """Why a WebSocket must be refused, or ``None`` if it may connect.

    ``AuthGateMiddleware`` only sees HTTP requests, so WebSocket routes call
    this themselves. Browsers send cookies with cross-site WebSocket
    handshakes and CORS does not apply, so the ``Origin`` must also be one of
    ours (cross-site WebSocket hijacking).
    """
    origin = connection.headers.get("origin")
    if origin and origin.rstrip("/") not in cors_origins():
        return "Origin not allowed"
    try:
        identity = identity_from_request(connection)
    except RuntimeError as exc:
        return str(exc)
    if identity is None:
        return "Sign in required"
    if not email_allowed(identity.email):
        return "This account is not allowed to use Dayline"
    return None


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated / not-allowlisted ``/api/*`` calls.

    Public: ``/api/health`` and ``/api/auth/*`` (OAuth, me, logout). Everything
    else under ``/api`` needs a valid session whose email matches
    ``ALLOWED_EMAIL``.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/") or is_public_path(path):
            return await call_next(request)
        try:
            identity = identity_from_request(request)
        except RuntimeError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=500)
        if identity is None:
            return JSONResponse({"detail": "Sign in required"}, status_code=401)
        if not email_allowed(identity.email):
            return JSONResponse(
                {"detail": "This account is not allowed to use Dayline"},
                status_code=403,
            )
        request.state.identity = identity
        return await call_next(request)


def exchange_google_code(code: str) -> Identity:
    """Prove ownership: exchange the Google auth code and read the account email."""
    try:
        with httpx.Client(timeout=15.0) as client:
            token_response = client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": google_client_id(),
                    "client_secret": google_client_secret(),
                    "redirect_uri": google_redirect_uri(),
                    "grant_type": "authorization_code",
                },
            )
            token_response.raise_for_status()
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise RuntimeError("Google token response did not include an access_token.")
            userinfo = client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo.raise_for_status()
            body = userinfo.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Google token/userinfo request failed: {exc}") from exc

    email = body.get("email")
    sub = body.get("sub")
    verified = body.get("email_verified")
    if verified is False:
        raise RuntimeError("Google account email is not verified.")
    if not isinstance(email, str) or not email.strip():
        raise RuntimeError("Google userinfo did not include an email.")
    if not isinstance(sub, str) or not sub:
        sub = email.strip()
    return Identity(email=email.strip(), sub=sub)
