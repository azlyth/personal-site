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
form, so matching on the parsed structure removes that whole class of
formatting-based bypass.

Structural parsing alone is not sufficient, though: DNS/cloudflared routing
is case-insensitive and treats a trailing dot as equivalent to the bare form,
and a wildcard ingress entry (`*.suffix`) covers our host without ever
string-matching it. So each configured hostname is also lowercased and
stripped of a trailing dot before comparison, and a `*.suffix` entry is
treated as a match whenever our (normalized) hostname ends with `.suffix`.
That wildcard handling is intentionally narrow — literal `*.` prefix only,
no general glob support — because a broader matcher is itself a new source of
bugs in a security control.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def _normalize(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _covers(configured_hostname: str, hostname: str) -> bool:
    """True if an ingress entry's hostname would route `hostname`.

    Handles exact matches after normalizing case and a trailing dot, plus the
    narrow `*.suffix` wildcard form cloudflared supports.
    """
    configured = _normalize(configured_hostname)
    target = _normalize(hostname)
    if configured == target:
        return True
    if configured.startswith("*."):
        suffix = configured[1:]  # e.g. "*.cloudy.nyc" -> ".cloudy.nyc"
        if target.endswith(suffix):
            return True
    return False


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

    if data is not None and not isinstance(data, dict):
        raise RuntimeError(
            f"Cannot verify {hostname} is not publicly routed: "
            f"{cloudflared_config} does not contain a YAML mapping at its top "
            "level. Refusing to start rather than treat an unexpected config "
            "shape as safe."
        )

    ingress = (data or {}).get("ingress") or []
    for entry in ingress:
        if not isinstance(entry, dict):
            continue
        configured_hostname = entry.get("hostname")
        if isinstance(configured_hostname, str) and _covers(configured_hostname, hostname):
            raise RuntimeError(
                f"{hostname} is publicly routed via {cloudflared_config}. "
                "The editor can write to git and S3 and must stay LAN-only. "
                "Remove the tunnel ingress entry before starting this service."
            )
