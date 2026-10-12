"""Magic-link auth endpoints: request a link, verify it, log out."""
from __future__ import annotations

import html as html_lib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from editor import config
from editor.auth import service, store
from editor.auth.deps import SESSION_COOKIE, get_db

router = APIRouter()
logger = logging.getLogger("editor.auth")

# Identical whether the address is allowlisted, rate-limited, or a genuine
# send -- so nobody can tell which address is on the list by watching the API.
CHECK_EMAIL = {"ok": True, "message": "Check your email for a sign-in link."}


class LoginRequest(BaseModel):
    # 254 is the RFC ceiling for an address; anything longer is a probe.
    email: str = Field(max_length=254)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "-"


@router.post("/auth/request")
def auth_request(body: LoginRequest, request: Request, conn=Depends(get_db)):
    email = body.email.strip().lower()
    ip = _client_ip(request)
    if service.rate_limited(email, ip):
        logger.warning("login rate-limited email=%s ip=%s", email, ip)
        return CHECK_EMAIL

    now = datetime.now(timezone.utc)
    token = service.request_login(conn, email, now, config.BASE_URL)
    if token:
        logger.info("login link requested email=%s", email)
    else:
        logger.info("login requested for a non-allowlisted address ip=%s", ip)
    return CHECK_EMAIL


@router.get("/auth/verify")
def auth_verify_page(token: str):
    """The emailed link. It must not spend the token: phones load this URL
    more than once (an email app's prefetch, or Chrome dropping its first
    load to reopen the link in an installed PWA), and the load that spent
    the token never reaches the screen -- the second load then reports the
    link as already used. This page POSTs the token back, and only that
    spends it."""
    safe_token = html_lib.escape(token, quote=True)
    resp = HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<title>Signing in</title>"
        "<h1>Signing in</h1>"
        '<form id="redeem" method="post" action="/auth/verify">'
        f'<input type="hidden" name="token" value="{safe_token}">'
        '<button type="submit">Sign in</button>'
        "</form>"
        '<script>document.getElementById("redeem").submit();</script>'
    )
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@router.post("/auth/verify")
def auth_verify(request: Request, token: str = Form(...), conn=Depends(get_db)):
    now = datetime.now(timezone.utc)
    sid = service.complete_login(conn, token, now)
    if sid is None:
        # A spent token, but if this browser already has a live session
        # (a second submit, the back button), send it home instead of to
        # an error.
        existing = request.cookies.get(SESSION_COOKIE)
        if existing and service.current_email(conn, existing, now):
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8>"
            "<h1>Sign-in link expired</h1>"
            "<p>That link is invalid or already used. Request a new one.</p>",
            status_code=400,
        )
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE, sid,
        httponly=True, secure=config.cookie_secure(), samesite="lax",
        max_age=60 * 60 * 24 * service.SESSION_TTL_DAYS, path="/",
    )
    return resp


@router.post("/auth/logout")
def auth_logout(request: Request, conn=Depends(get_db)):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        store.delete_session(conn, sid)
    resp = Response(status_code=204)
    resp.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True,
        secure=config.cookie_secure(), samesite="lax",
    )
    return resp
