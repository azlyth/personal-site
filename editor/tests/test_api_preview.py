"""Draft Preview: build the working tree WITH drafts into editor/.preview/site
and serve it to a signed-in editor. Nothing here touches public/."""
import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import config, preview
from editor.app import app

client = TestClient(app)
anon = TestClient(app)


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "PREVIEW_DIR", tmp_path / "site")
    return tmp_path / "site"


def test_preview_post_requires_sign_in():
    assert anon.post("/api/posts/x/preview").status_code == 401


def test_preview_get_requires_sign_in():
    assert anon.get("/preview/blog/x/").status_code == 401


def test_unknown_post_404s_without_building(out, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    assert client.post("/api/posts/no-such-post-xyz/preview").status_code == 404
    assert called == []


def test_build_passes_base_url_and_output_dir(out, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        (out / "blog" / "a").mkdir(parents=True, exist_ok=True)
        (out / "blog" / "a" / "index.html").write_text("<html>hi</html>")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(config, "BASE_URL", "https://edit.example")
    monkeypatch.setattr("editor.app._post_path", lambda slug: config.BLOG_DIR / "a.md")
    r = client.post("/api/posts/a/preview")
    assert r.status_code == 200
    assert r.json() == {"url": "/preview/blog/a/"}
    (cmd,) = calls
    assert cmd[-2:] == ["https://edit.example/preview", str(out)]
    assert "public" not in " ".join(cmd).replace("preview", "")


def test_build_script_uses_drafts_and_never_public():
    text = (config.REPO / "scripts" / "build-preview.sh").read_text()
    assert "--drafts" in text
    assert "/public" not in text and "rsync" not in text


def test_failed_build_returns_the_message(out, monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, "", "Error: bad shortcode")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("editor.app._post_path", lambda slug: config.BLOG_DIR / "a.md")
    r = client.post("/api/posts/a/preview")
    assert r.status_code == 500
    assert "bad shortcode" in r.json()["detail"]


def test_serving_resolves_directory_to_index(out):
    (out / "blog" / "a").mkdir(parents=True)
    (out / "blog" / "a" / "index.html").write_text("<html>hello</html>")
    r = client.get("/preview/blog/a/")
    assert r.status_code == 200
    assert "hello" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-robots-tag"] == "noindex"


def test_serving_a_file_and_missing(out):
    (out / "main.css").parent.mkdir(parents=True)
    (out / "main.css").write_text("a{}")
    assert client.get("/preview/main.css").status_code == 200
    assert client.get("/preview/nope.css").status_code == 404


def test_traversal_is_refused(out, tmp_path):
    out.mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("secret")
    for p in ("/preview/../secret.txt", "/preview/%2e%2e/secret.txt",
              "/preview/..%2fsecret.txt"):
        r = client.get(p)
        assert r.status_code in (400, 404) and "secret" not in r.text
