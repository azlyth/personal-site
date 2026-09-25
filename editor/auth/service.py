"""Auth orchestration: request a magic link, verify it, manage sessions.

Mirrors spruce's app/services/auth.py + app/routers/auth.py (32-byte urlsafe
tokens, sha256-hashed at rest, 15-minute expiry, a 60s reuse grace window for
a device that fetches the same link twice, opaque 30-day sessions). Simpler
than spruce's version because there's no per-user account table here -- just
one allowlisted operator and an in-memory rate limiter.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from editor import config
from editor.auth import mailer, security, store

TOKEN_TTL_MIN = 15
SESSION_TTL_DAYS = 30

# How long a magic link stays redeemable after its FIRST use -- see
# store.consume_login_token's docstring for why (a device that opens the
# same link twice in two different contexts a moment apart).
REDEEM_GRACE_S = 60

RATE_MAX_EMAIL = 5
RATE_MAX_IP = 30
RATE_WINDOW_S = 900

# Per-process, in-memory: key -> [monotonic hit times]. Resets on restart,
# which is fine -- this only ever needs to survive one 15-minute window.
_recent: dict[str, list[float]] = {}


def _rate_ok(key: str, now_mono: float, cap: int) -> bool:
    if len(_recent) > 500:  # bound memory: drop buckets with no live hits
        for k in [k for k, v in _recent.items() if not v or now_mono - v[-1] >= RATE_WINDOW_S]:
            del _recent[k]
    hits = [t for t in _recent.get(key, []) if now_mono - t < RATE_WINDOW_S]
    if len(hits) >= cap:
        _recent[key] = hits
        return False
    hits.append(now_mono)
    _recent[key] = hits
    return True


def rate_limited(email: str, ip: str) -> bool:
    """True if this request should be refused for exceeding the rate limit.
    Checked (and both budgets consumed) regardless of whether `email` is
    allowlisted, so the allowlist can't be probed by watching which counter
    moves."""
    now_mono = time.monotonic()
    email_ok = _rate_ok(f"e|{email}", now_mono, RATE_MAX_EMAIL)
    ip_ok = _rate_ok(f"ip|{ip}", now_mono, RATE_MAX_IP)
    return not (email_ok and ip_ok)


def request_login(conn, email: str, now: datetime, base_url: str) -> str | None:
    """Mint + email a single-use token if `email` is allowlisted. Returns
    the raw token (tests only -- never exposed via the API), or None if the
    address isn't allowed. Either way the caller returns the identical
    "check your email" response; on a miss, nothing is stored or sent."""
    if email not in config.ALLOWED_EMAILS:
        return None
    raw = security.new_token()
    expires = now + timedelta(minutes=TOKEN_TTL_MIN)
    store.create_login_token(
        conn, security.hash_token(raw), email, now.isoformat(), expires.isoformat()
    )
    link = f"{base_url}/auth/verify?token={raw}"
    mailer.send_login_link(email, link)
    return raw


def complete_login(conn, raw_token: str, now: datetime) -> str | None:
    """Redeem a token and start a session. Returns the new session id, or
    None if the token is unknown/expired/already spent outside the grace
    window. Redeemable again within REDEEM_GRACE_S of the first use -- every
    redemption inside the window mints its own session."""
    grace_since = (now - timedelta(seconds=REDEEM_GRACE_S)).isoformat()
    email = store.consume_login_token(
        conn, security.hash_token(raw_token), now.isoformat(), grace_since
    )
    if email is None:
        return None
    sid = security.new_session_id()
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    store.create_session(conn, sid, email, now.isoformat(), expires.isoformat())
    store.purge_expired(conn, now.isoformat(), grace_since)
    return sid


def current_email(conn, session_id: str | None, now: datetime) -> str | None:
    return store.email_for_session(conn, session_id, now.isoformat())
