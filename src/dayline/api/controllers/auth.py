"""Google OAuth start/callback, session inspect, logout."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from dayline.api import auth as authlib

router = APIRouter()


@router.get("/api/auth/google")
def google_login() -> RedirectResponse:
    try:
        state = authlib.make_oauth_state()
        url = authlib.google_authorize_url(state)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/api/auth/callback")
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    login_error = f"{authlib.public_url()}/login?error=google"
    if error or not code:
        return RedirectResponse(login_error, status_code=302)
    if not authlib.oauth_state_valid(state):
        return RedirectResponse(f"{authlib.public_url()}/login?error=state", status_code=302)
    try:
        identity = authlib.exchange_google_code(code)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Google sign-in failed: {exc}") from exc

    dest = "/" if authlib.email_allowed(identity.email) else "/not-allowed"
    response = RedirectResponse(f"{authlib.public_url()}{dest}", status_code=302)
    authlib.set_session_cookie(response, authlib.issue_session(identity.email, identity.sub))
    return response


@router.get("/api/auth/me")
def me(request: Request) -> dict[str, str | bool]:
    identity = authlib.identity_from_request(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return {
        "email": identity.email,
        "allowed": authlib.email_allowed(identity.email),
    }


@router.post("/api/auth/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    authlib.clear_session_cookie(response)
    return response
