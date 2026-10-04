"""Magic-link auth: request -> verify -> session -> access, the allowlist,
expiry, reuse, logout, and the app-wide route-coverage guarantee.

Every test here builds its OWN TestClient (never the module-level `client`
name) so conftest.py's autouse sign-in fixture leaves it alone -- these
tests are exactly about the signed-out/signed-in transition itself.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from editor import config
from editor.app import app
from editor.auth import security, service, store
from editor.auth.deps import SESSION_COOKIE
from editor.auth.middleware import (
    PUBLIC_EXACT,
    PUBLIC_PREFIXES,
    TOKEN_AUTH_EXACT,
    is_public,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # The limiter is a module-level dict shared by the whole test process;
    # start every test from a clean slate so one test's requests can't trip
    # another's budget.
    service._recent.clear()
    yield
    service._recent.clear()


def _fresh():
    return TestClient(app)


def _mint_token(email="ptr.vldz@gmail.com") -> str:
    """Mint a token directly through the service layer -- the route never
    returns the raw token (it only ever leaves via the emailed link)."""
    conn = store.connect()
    try:
        return service.request_login(conn, email, datetime.now(timezone.utc), config.BASE_URL)
    finally:
        conn.close()


# --- the happy path ---------------------------------------------------------


def test_request_then_verify_then_session_then_access():
    client = _fresh()

    resp = client.post("/auth/request", json={"email": "ptr.vldz@gmail.com"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "message": "Check your email for a sign-in link."}

    token = _mint_token()
    verify = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert verify.status_code == 302
    assert SESSION_COOKIE in verify.cookies

    assert client.get("/api/posts").status_code == 200


def test_allowed_email_actually_sends(monkeypatch):
    sent = []
    monkeypatch.setattr("editor.auth.service.mailer.send_login_link", lambda *a: sent.append(a))
    resp = _fresh().post("/auth/request", json={"email": "ptr.vldz@gmail.com"})
    assert resp.status_code == 200
    assert len(sent) == 1
    assert sent[0][0] == "ptr.vldz@gmail.com"


# --- the allowlist -----------------------------------------------------------


def test_allowlist_miss_gets_the_identical_response_and_sends_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr("editor.auth.service.mailer.send_login_link", lambda *a: sent.append(a))
    client = _fresh()

    allowed = client.post("/auth/request", json={"email": "ptr.vldz@gmail.com"})
    stranger = client.post("/auth/request", json={"email": "stranger@example.com"})

    assert allowed.status_code == stranger.status_code == 200
    assert allowed.json() == stranger.json() == {
        "ok": True, "message": "Check your email for a sign-in link.",
    }
    assert len(sent) == 1  # only the allowlisted address


def test_allowlist_miss_mints_no_token():
    assert service.request_login(
        store.connect(), "stranger@example.com", datetime.now(timezone.utc), config.BASE_URL
    ) is None


# --- expiry + single-use -----------------------------------------------------


def test_expired_token_is_rejected():
    conn = store.connect()
    raw = security.new_token()
    now = datetime.now(timezone.utc)
    store.create_login_token(
        conn, security.hash_token(raw), "ptr.vldz@gmail.com",
        (now - timedelta(minutes=20)).isoformat(),
        (now - timedelta(minutes=5)).isoformat(),
    )
    conn.close()

    resp = _fresh().get(f"/auth/verify?token={raw}", follow_redirects=False)
    assert resp.status_code == 400
    assert SESSION_COOKIE not in resp.cookies


def test_unknown_token_is_rejected():
    resp = _fresh().get("/auth/verify?token=not-a-real-token", follow_redirects=False)
    assert resp.status_code == 400


def test_token_is_rejected_once_spent_outside_the_grace_window():
    token = _mint_token()
    conn = store.connect()
    now = datetime.now(timezone.utc)
    assert service.complete_login(conn, token, now) is not None
    later = now + timedelta(seconds=service.REDEEM_GRACE_S + 5)
    assert service.complete_login(conn, token, later) is None
    conn.close()


def test_token_is_reusable_within_the_grace_window():
    """A device that fetches the same magic link twice, moments apart, gets
    logged in both times rather than "link expired" on the second fetch."""
    token = _mint_token()
    conn = store.connect()
    now = datetime.now(timezone.utc)
    first = service.complete_login(conn, token, now)
    soon = now + timedelta(seconds=10)
    second = service.complete_login(conn, token, soon)
    conn.close()
    assert first is not None
    assert second is not None
    assert first != second  # each redemption mints its own session


# --- logout + 401s ------------------------------------------------------------


def test_logout_clears_the_session_and_the_cookie():
    client = _fresh()
    token = _mint_token()
    client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert client.get("/api/posts").status_code == 200

    logout = client.post("/auth/logout")
    assert logout.status_code == 204

    assert client.get("/api/posts").status_code == 401


def test_api_and_upload_routes_401_when_signed_out():
    client = _fresh()
    assert client.get("/api/posts").status_code == 401
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/posts/guerilla-gardening").status_code == 401
    assert client.post("/api/posts/guerilla-gardening/images/upload").status_code == 401


# --- the page routes: sign-in card vs. the real editor -----------------------


def test_signed_out_home_page_is_the_signin_card():
    resp = _fresh().get("/")
    assert resp.status_code == 200
    assert "Sign in" in resp.text
    assert "editor.js" not in resp.text  # the real editor bundle never loads signed out


def test_signed_out_edit_route_is_also_the_signin_card():
    resp = _fresh().get("/edit/guerilla-gardening")
    assert resp.status_code == 200
    assert "Sign in" in resp.text


def test_signed_in_home_page_is_the_editor():
    client = _fresh()
    token = _mint_token()
    client.get(f"/auth/verify?token={token}", follow_redirects=False)
    resp = client.get("/")
    assert resp.status_code == 200
    assert re.search(r"editor(-[0-9a-f]{8})?\.js", resp.text)


# --- app-wide route coverage --------------------------------------------------


def _dummy_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def test_every_route_requires_auth_unless_explicitly_public():
    """Walks the live route table (not a hand-maintained list of endpoints)
    so a new route added to app.py without an explicit public exemption is
    protected by construction -- this fails the moment that stops being
    true."""
    anon = _fresh()
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if is_public(route.path) or route.path in TOKEN_AUTH_EXACT:
            continue
        url = _dummy_path(route.path)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            resp = anon.request(method, url)
            assert resp.status_code == 401, (
                f"{method} {route.path} returned {resp.status_code} signed "
                "out; expected 401 (or add it to the explicit public list "
                "in editor/auth/middleware.py if that's deliberate)"
            )
            checked += 1
    assert checked > 20, "the walk found suspiciously few routes to check"


def test_public_allowlist_is_short_and_explicit():
    # Guards against the allowlist quietly growing: every entry here is a
    # deliberate decision made in this branch, not a default that crept in.
    assert PUBLIC_EXACT == frozenset({
        "/", "/auth/request", "/auth/verify", "/favicon.svg", "/favicon.ico",
    })
    assert PUBLIC_PREFIXES == ("/static/", "/edit/")
    # Routes that skip the session check because they authenticate with a
    # shared secret instead. Each is a deliberate decision; see app.py.
    assert TOKEN_AUTH_EXACT == frozenset({"/api/import"})


def test_token_auth_routes_refuse_an_anonymous_caller(monkeypatch):
    from editor import config
    monkeypatch.setattr(config, "import_token", lambda: "configured")
    anon = _fresh()
    for path in TOKEN_AUTH_EXACT:
        assert anon.post(path, json={"text": "# A\n\nB", "name": "x"}).status_code == 401


def test_static_assets_stay_reachable_signed_out():
    # The sign-in page has to be able to load its own stylesheet.
    resp = _fresh().get("/static/editor.css")
    assert resp.status_code == 200
