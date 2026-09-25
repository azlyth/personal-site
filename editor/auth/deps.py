"""FastAPI dependencies for magic-link auth.

Most routes are already gated by the app-wide AuthMiddleware (see
editor/auth/middleware.py) -- these are for the handful of places that need
the actual signed-in email, or the DB connection to write one.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Request

from editor.auth import service, store

SESSION_COOKIE = "editor_session"


def get_db():
    conn = store.connect()
    try:
        yield conn
    finally:
        conn.close()


def current_email(request: Request, conn=Depends(get_db)) -> str | None:
    sid = request.cookies.get(SESSION_COOKIE)
    return service.current_email(conn, sid, datetime.now(timezone.utc))
