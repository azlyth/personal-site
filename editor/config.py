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


def load_aws_env() -> dict:
    """Read the gitignored .aws.env written by personal-cloud-infra."""
    env: dict[str, str] = {}
    path = REPO / ".aws.env"
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env
