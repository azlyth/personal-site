"""Refuse to run if this service has been exposed to the internet.

The editor can commit to the repo, push to GitHub and write to S3. The only
thing keeping that private is the network boundary, so a misconfiguration that
routes it through the tunnel should fail loudly at boot rather than quietly
becoming a public write endpoint.

This parses cloudflared/config.yml as YAML and walks its `ingress` list
structurally, rather than pattern-matching the raw text. A regex keyed on one
literal layout (`hostname: <bare-value>` alone on its own line) is trivially
evaded by anything else that is still legal, tunnel-ready YAML: a quoted
value, a trailing comment, or a flow-style mapping. All three parse to the
exact same structure that `yaml.safe_load` would hand back for the plain
form, so matching on the parsed structure is safe by construction instead of
by coincidence of formatting.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def assert_not_publicly_routed(hostname: str, cloudflared_config: Path) -> None:
    # cloudflared_config is expected at <http-routing repo>/cloudflared/config.yml.
    # If the repo directory itself is missing, that hardcoded sibling-path
    # assumption is broken (moved repo, typo, bad checkout) and there is no way
    # to verify anything from here — refuse to start rather than assume safety.
    http_routing_dir = cloudflared_config.parent.parent
    if not http_routing_dir.exists():
        raise RuntimeError(
            f"Cannot verify {hostname} is not publicly routed: "
            f"{http_routing_dir} does not exist. The editor assumes http-routing "
            "is a sibling checkout at a fixed path; that assumption is broken, "
            "so refusing to start rather than silently treating this as safe."
        )

    # The directory exists but there's no config.yml in it at all: that
    # genuinely means no tunnel is configured, which is safe.
    if not cloudflared_config.exists():
        return

    try:
        data = yaml.safe_load(cloudflared_config.read_text())
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"Cannot verify {hostname} is not publicly routed: "
            f"{cloudflared_config} is not valid YAML ({exc}). Refusing to start "
            "rather than treat an unparseable tunnel config as safe."
        ) from exc

    ingress = (data or {}).get("ingress") or []
    for entry in ingress:
        if isinstance(entry, dict) and entry.get("hostname") == hostname:
            raise RuntimeError(
                f"{hostname} is publicly routed via {cloudflared_config}. "
                "The editor can write to git and S3 and must stay LAN-only. "
                "Remove the tunnel ingress entry before starting this service."
            )
