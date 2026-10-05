"""Test-wide setup for the editor's pytest suite.

Two environment overrides MUST happen before `editor.config`/`editor.app` is
first imported by any test module. conftest.py is imported by pytest at
collection time, ahead of the test files in this directory, so setting them
here at module scope (not inside a fixture) is what makes them land in time:

- `EDITOR_AUTH_DB` points the auth sqlite file at a throwaway tmp path, so
  the test suite never touches or seeds the real gitignored file this
  service uses once deployed.
- `EDITOR_COOKIE_SECURE=false` lets TestClient's http://testserver keep the
  session cookie across requests -- a `Secure` cookie is silently dropped by
  an http-only client, same reason spruce's test suite flips the same
  setting (see spruce/tests/conftest.py).
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault(
    "EDITOR_AUTH_DB",
    os.path.join(tempfile.mkdtemp(prefix="editor-auth-test-"), "auth.db"),
)
os.environ.setdefault("EDITOR_COOKIE_SECURE", "false")

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from editor.auth import security, store  # noqa: E402
from editor.auth.deps import SESSION_COOKIE  # noqa: E402

_SESSION_EMAIL = "ptr.vldz@gmail.com"


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """No test may send a real sign-in email. The suite often runs in the
    live checkout, where .editor-smtp.env holds real SES creds, and a test
    that requests a link for the allowlisted address would email Peter on
    every run (it did, repeatedly, on 2026-10-04). Tests that want to see
    the call patch send_login_link again on top of this."""
    monkeypatch.setattr("editor.auth.mailer.send_login_link", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _signed_in_module_client(request):
    """Every test file that predates this auth work does its work through a
    module-level `client = TestClient(app)` with no session at all --
    retrofitting a login into ~250 pre-existing tests one by one would be
    enormous churn for no behavioural gain, so this gives that client a
    valid session cookie automatically instead. Auth-specific tests build
    their own local TestClient (a different name, e.g. `anon`) and are
    untouched by this -- the check below only ever fires for the literal
    name `client`."""
    client = getattr(request.module, "client", None)
    if client is None:
        yield
        return

    conn = store.connect()
    try:
        sid = security.new_session_id()
        now = datetime.now(timezone.utc)
        store.create_session(
            conn, sid, _SESSION_EMAIL, now.isoformat(),
            (now + timedelta(days=30)).isoformat(),
        )
    finally:
        conn.close()

    client.cookies.set(SESSION_COOKIE, sid)
    try:
        yield
    finally:
        client.cookies.clear()
