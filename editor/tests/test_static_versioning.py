"""The editor page must point at content-addressed asset paths.

`no-cache` on /static only governs responses served from now on -- it cannot
reach a copy a browser already holds under an earlier heuristic freshness
window. Stamping the content hash into the PATH (not a `?v=` query string)
sidesteps that: the page names a URL the browser has never seen, so there is
nothing cached to reuse. A path hash also lets the asset carry a far-future
`immutable` Cache-Control safely -- the same reasoning `editor/images.py`
already uses for S3 keys (`stem-<8 hex>.ext`), and a `?v=` query can't safely
carry `immutable` since some caches don't key on it.
"""

import re

from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)

_HASHED_PATH = re.compile(r"^/static/(?P<stem>[\w.-]+?)-(?P<hash>[0-9a-f]{8})\.(?P<ext>\w+)$")


def _asset_url(html: str, filename: str) -> str:
    stem, _, ext = filename.rpartition(".")
    match = re.search(rf'["\'](/static/{re.escape(stem)}-[0-9a-f]{{8}}\.{re.escape(ext)})["\']', html)
    assert match, f"{filename} not referenced as a hashed path in the page"
    return match.group(1)


def test_editor_page_hashes_the_script_path():
    _asset_url(client.get("/").text, "editor.js")


def test_editor_page_hashes_the_stylesheet_path():
    _asset_url(client.get("/").text, "editor.css")


def test_edit_route_hashes_assets_too():
    _asset_url(client.get("/edit/whatever").text, "editor.js")


def test_hashed_path_serves_the_current_asset():
    url = _asset_url(client.get("/").text, "editor.js")
    res = client.get(url)
    assert res.status_code == 200
    assert "splitBlockVideo" in res.text


def test_hashed_path_is_cached_immutably():
    url = _asset_url(client.get("/").text, "editor.js")
    res = client.get(url)
    assert res.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_hash_changes_when_the_asset_changes():
    """Without this the stamp could be a constant and cache nothing new."""
    path = config.WEB_DIR / "editor.js"
    original = path.read_bytes()
    before = _asset_url(client.get("/").text, "editor.js")
    try:
        path.write_bytes(original + b"\n// cache-bust probe\n")
        after = _asset_url(client.get("/").text, "editor.js")
    finally:
        path.write_bytes(original)
    assert before != after


def test_unhashed_static_request_still_serves_and_revalidates():
    """A direct request to the plain (unhashed) name -- e.g. a browser tab
    still holding an old page -- must keep working, just without the
    immutable long-cache treatment."""
    res = client.get("/static/editor.js")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"


def test_editor_page_itself_must_revalidate():
    """A heuristically cached shell would keep naming the OLD asset hashes and
    defeat the versioning entirely."""
    assert client.get("/").headers["cache-control"] == "no-cache"
