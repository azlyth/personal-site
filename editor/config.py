"""Paths and settings for the editor service."""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTTP_ROUTING = REPO.parent / "http-routing"
CLOUDFLARED_CONFIG = HTTP_ROUTING / "cloudflared" / "config.yml"

HOSTNAME = os.environ.get("EDITOR_HOSTNAME", "edit.cloudy.nyc")
PORT = int(os.environ.get("EDITOR_PORT", "8804"))
BLOG_DIR = REPO / "content" / "blog"

# Where the published site actually lives. Duplicated from
# `scripts/build-site.sh`'s BASE_URL default -- that script is what renders
# the live site, and config.toml's `base_url` is only the fallback it
# overrides. A test pins the two together, because a link built from the
# wrong base points at a host that doesn't answer.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://cloudy.nyc")
WEB_DIR = REPO / "editor" / "web"

# --- auth ------------------------------------------------------------------

# Only this address gets a magic link by default; anyone else's request
# still returns the same "check your email" response (see editor/auth) but
# nothing is sent. Comma-separated so a second address can be added without
# a code change.
ALLOWED_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("EDITOR_ALLOWED_EMAILS", "ptr.vldz@gmail.com").split(",")
    if e.strip()
)

# Where auth.verify's links point. Distinct from SITE_BASE_URL, which is the
# published *blog's* origin -- this one is the editor's own.
BASE_URL = os.environ.get("EDITOR_BASE_URL", "https://edit.cloudy.nyc")

# A small gitignored sqlite file holding login tokens (hashed) and sessions.
AUTH_DB = Path(os.environ.get("EDITOR_AUTH_DB", str(REPO / ".editor-auth.db")))


def cookie_secure() -> bool:
    """Read live (not cached at import) so tests can flip it via monkeypatch
    -- a `Secure` cookie is silently dropped by an http:// TestClient, the
    same reason spruce's test suite disables it in tests."""
    return os.environ.get("EDITOR_COOKIE_SECURE", "true").lower() != "false"


def _read_env_file(name: str) -> dict:
    env: dict[str, str] = {}
    path = REPO / name
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def load_aws_env() -> dict:
    """Read the gitignored .aws.env written by personal-cloud-infra."""
    return _read_env_file(".aws.env")


def load_smtp_env() -> dict:
    """Read the gitignored .editor-smtp.env written by personal-cloud-infra's
    `make sync-blog-editor`: SMTP_HOST/PORT/USERNAME/PASSWORD/MAIL_FROM. Same
    KEY=VALUE parsing as load_aws_env. Absent -- a fresh checkout, a test
    run, dev before the sync has run -- means "log the link instead of
    sending it" (see editor/auth/mailer.py)."""
    return _read_env_file(".editor-smtp.env")


def import_token() -> str:
    """The shared secret Platen sends as X-Import-Token (see app.py's
    import_post). Read live, not at import, so tests can monkeypatch it.
    The env var wins over the gitignored .editor-import.env. Empty means
    the import route is switched off."""
    return (
        os.environ.get("EDITOR_IMPORT_TOKEN")
        or _read_env_file(".editor-import.env").get("EDITOR_IMPORT_TOKEN", "")
    ).strip()


def claude_bin() -> str:
    """The claude CLI the proofreader runs. Absolute by default: the systemd
    unit's PATH has no ~/.local/bin, which is how recipes' prod parser broke
    on 2026-09-13. Read live so tests can override it."""
    return os.environ.get("EDITOR_CLAUDE_BIN", "/home/peter/.local/bin/claude")


def proofread_model() -> str:
    """Optional --model for the proofreader; empty means the CLI default."""
    return os.environ.get("EDITOR_PROOFREAD_MODEL", "").strip()
