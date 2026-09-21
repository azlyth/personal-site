"""Refuse to run if this service has been exposed to the internet.

The editor can commit to the repo, push to GitHub and write to S3. The only
thing keeping that private is the network boundary, so a misconfiguration that
routes it through the tunnel should fail loudly at boot rather than quietly
becoming a public write endpoint.
"""
from __future__ import annotations

import re
from pathlib import Path


def assert_not_publicly_routed(hostname: str, cloudflared_config: Path) -> None:
    if not cloudflared_config.exists():
        return

    pattern = re.compile(
        rf"^\s*-?\s*hostname:\s*{re.escape(hostname)}\s*$", re.MULTILINE
    )
    if pattern.search(cloudflared_config.read_text()):
        raise RuntimeError(
            f"{hostname} is publicly routed via {cloudflared_config}. "
            "The editor can write to git and S3 and must stay LAN-only. "
            "Remove the tunnel ingress entry before starting this service."
        )
