"""App-wide auth gate: every route is protected unless explicitly public.

A new route added anywhere in app.py automatically requires a valid session
-- there is no per-route opt-in to forget, and the route-coverage test
(tests/test_auth.py) walks the live route table and proves it. The two page
routes ("/" and "/edit/{slug}") are the deliberate exception: they stay
reachable signed out so the handler itself can render the sign-in card
instead of a 401 (see app.py's editor_page) -- "every page route shows only
a sign-in page" means those routes answer 200 with different content, not
401. Static assets are public for the same reason the sign-in page needs its
own CSS/JS to render at all; `/auth/request` and `/auth/verify` are the two
endpoints the sign-in page itself calls. `/api/import` is the one route that
authenticates with a shared secret instead of a session (TOKEN_AUTH_EXACT).
"""
from __future__ import annotations

from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from editor.auth import service, store
from editor.auth.deps import SESSION_COOKIE

# Exact paths that need no session at all.
PUBLIC_EXACT = frozenset({
    "/",
    "/auth/request",
    "/auth/verify",
    "/favicon.svg",
    "/favicon.ico",
})

# Path prefixes that need no session: static assets (code, not data) and the
# per-post editor page (content-gated inside the handler, not here).
PUBLIC_PREFIXES = ("/static/", "/edit/")

# Exact paths that skip the session check because the route authenticates
# itself with a shared secret instead (app.py's import_post: Platen's
# server-to-server send-to-blog). Not "public": the route refuses any
# caller without the token, and is off entirely when none is configured.
TOKEN_AUTH_EXACT = frozenset({"/api/import"})


def is_public(path: str) -> bool:
    return path in PUBLIC_EXACT or any(path.startswith(p) for p in PUBLIC_PREFIXES)


def _email_for_request(request) -> str | None:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    conn = store.connect()
    try:
        return service.current_email(conn, sid, datetime.now(timezone.utc))
    finally:
        conn.close()


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        email = _email_for_request(request)
        # Stashed even on public paths -- the page routes read this to
        # decide sign-in card vs. the real editor shell.
        request.state.user_email = email
        if (
            email is None
            and not is_public(request.url.path)
            and request.url.path not in TOKEN_AUTH_EXACT
        ):
            return JSONResponse({"detail": "Sign in required."}, status_code=401)
        return await call_next(request)
