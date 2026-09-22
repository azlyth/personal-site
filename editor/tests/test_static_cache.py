"""The editor's own JS/CSS must revalidate.

StaticFiles sends an ETag and Last-Modified but no Cache-Control, and with no
Cache-Control a browser falls back to *heuristic* freshness -- commonly 10% of
the file's age since Last-Modified. A long-unchanged editor.js therefore earns
a multi-hour freshness window, and the tablet keeps running the old editor
after a deploy without ever asking the Pi. `no-cache` means "revalidate", not
"don't store", so the ETag still answers with a cheap 304 when nothing changed.
"""

from fastapi.testclient import TestClient

from editor.app import app

client = TestClient(app)


def test_static_js_must_revalidate():
    res = client.get("/static/editor.js")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"


def test_static_css_must_revalidate():
    res = client.get("/static/editor.css")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"


def test_static_still_sends_an_etag():
    """Without this, no-cache would mean a full re-download every load."""
    res = client.get("/static/editor.js")
    assert res.headers.get("etag")


def test_unchanged_static_revalidates_to_304():
    etag = client.get("/static/editor.js").headers["etag"]
    res = client.get("/static/editor.js", headers={"If-None-Match": etag})
    assert res.status_code == 304


def test_api_responses_are_left_alone():
    """The hook is scoped to /static -- it shouldn't rewrite API headers."""
    res = client.get("/api/status")
    assert res.status_code == 200
    assert "cache-control" not in res.headers
