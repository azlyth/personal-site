"""SQLite storage for magic-link auth: login tokens + sessions.

Stdlib sqlite3, at the small gitignored file `editor.config.AUTH_DB`. This
app's write volume is trivial (one login every so often, on a LAN, for one
person), so there's no pool or WAL tuning the way spruce's app/db.py has --
every call opens and closes its own connection.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from editor import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS login_token (
    hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.AUTH_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def create_login_token(conn, token_hash: str, email: str, created_at: str, expires_at: str) -> None:
    conn.execute(
        "INSERT INTO login_token (hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash, email, created_at, expires_at),
    )
    conn.commit()


def consume_login_token(conn, token_hash: str, now_iso: str, grace_since_iso: str) -> str | None:
    """Redeem a token: valid if unexpired and (never used OR first used
    within the grace window). Returns the email, or None if the token is
    unknown, expired, or was spent outside the grace window.

    Marks it used on FIRST redemption only -- a second fetch inside the
    grace window (a device that opens the same link twice, ~150ms apart, in
    two different contexts) does not push `used_at` forward, so the window
    stays anchored to the first use and can't be kept alive by re-fetching.
    """
    row = conn.execute(
        "SELECT email, expires_at, used_at FROM login_token WHERE hash = ?",
        (token_hash,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < now_iso:
        return None
    if row["used_at"] is None:
        conn.execute(
            "UPDATE login_token SET used_at = ? WHERE hash = ?", (now_iso, token_hash)
        )
        conn.commit()
        return row["email"]
    if row["used_at"] >= grace_since_iso:
        return row["email"]
    return None


def create_session(conn, session_id: str, email: str, created_at: str, expires_at: str) -> None:
    conn.execute(
        "INSERT INTO session (id, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (session_id, email, created_at, expires_at),
    )
    conn.commit()


def email_for_session(conn, session_id: str | None, now_iso: str) -> str | None:
    if not session_id:
        return None
    row = conn.execute(
        "SELECT email FROM session WHERE id = ? AND expires_at > ?",
        (session_id, now_iso),
    ).fetchone()
    return row["email"] if row else None


def delete_session(conn, session_id: str) -> None:
    conn.execute("DELETE FROM session WHERE id = ?", (session_id,))
    conn.commit()


def purge_expired(conn, now_iso: str, grace_since_iso: str) -> None:
    """Housekeeping, run once per successful login -- same pattern as
    spruce's repo.purge_expired_auth."""
    conn.execute("DELETE FROM session WHERE expires_at <= ?", (now_iso,))
    conn.execute(
        "DELETE FROM login_token WHERE expires_at <= ? AND (used_at IS NULL OR used_at <= ?)",
        (now_iso, grace_since_iso),
    )
    conn.commit()
