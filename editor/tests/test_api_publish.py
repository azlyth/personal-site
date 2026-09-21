import subprocess

from fastapi.testclient import TestClient

from editor import app as app_module
from editor.app import app
from editor.publish import PublishResult

client = TestClient(app)


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


def test_status_only_reports_blog_paths(monkeypatch):
    monkeypatch.setattr(
        "editor.app._dirty_paths",
        lambda: ["content/blog/a.md", "templates/base.html", "editor/app.py"],
    )
    monkeypatch.setattr("editor.app._has_unpushed_commits", lambda repo: False)
    data = client.get("/api/status").json()
    assert data["dirty"] == ["content/blog/a.md"]
    assert data["clean"] is False


def test_status_reports_outstanding_when_only_unpushed_commits(monkeypatch):
    # A clean tree isn't the same as "nothing to do" -- a previous publish
    # may have committed fine and then failed to push or publish, leaving no
    # dirty files but a commit that never made it live.
    monkeypatch.setattr("editor.app._dirty_paths", lambda: [])
    monkeypatch.setattr("editor.app._has_unpushed_commits", lambda repo: True)
    data = client.get("/api/status").json()
    assert data["dirty"] == []
    assert data["unpushed"] is True
    assert data["clean"] is False


def test_publish_passes_only_blog_paths_to_git(monkeypatch):
    seen = {}

    def fake_publish(repo, paths, message):
        seen["paths"] = paths
        seen["message"] = message
        return PublishResult(True, "abc12345", True, True, "published abc12345")

    monkeypatch.setattr(
        "editor.app._dirty_paths",
        lambda: ["content/blog/a.md", "templates/base.html"],
    )
    monkeypatch.setattr("editor.app.publish", fake_publish)

    out = client.post("/api/publish", json={"message": "Update a post"}).json()

    assert seen["paths"] == ["content/blog/a.md"]
    assert out["sha"] == "abc12345"
    assert out["published"] is True


def test_publish_with_nothing_to_do(monkeypatch):
    monkeypatch.setattr("editor.app._dirty_paths", lambda: [])
    monkeypatch.setattr(
        "editor.app.publish",
        lambda repo, paths, message: PublishResult(False, None, False, False, "nothing to publish"),
    )
    out = client.post("/api/publish", json={}).json()
    assert out["committed"] is False


def test_publish_calls_publish_even_with_no_dirty_paths(monkeypatch):
    """Regression for the Critical: do_publish must not short-circuit on an
    empty path list. A clean tree with an unpushed commit is exactly the
    state a prior failed push/S3-publish leaves behind, and publish() already
    knows how to recover it -- but only if it's actually called."""
    seen = {}

    def fake_publish(repo, paths, message):
        seen["called"] = True
        seen["paths"] = paths
        return PublishResult(False, "deadbeef", True, True, "published deadbeef")

    monkeypatch.setattr("editor.app._dirty_paths", lambda: [])
    monkeypatch.setattr("editor.app.publish", fake_publish)

    out = client.post("/api/publish", json={}).json()

    assert seen.get("called") is True
    assert seen["paths"] == []
    assert out["sha"] == "deadbeef"
    assert out["published"] is True


def test_dirty_paths_parses_staged_rename(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    old = repo / "old.md"
    old.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "old.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "mv", "old.md", "new.md"], cwd=repo, check=True)

    monkeypatch.setattr("editor.app.config.REPO", repo)

    # -z reverses the human-readable order: NEW path first, then ORIGINAL,
    # as two separate NUL-terminated fields rather than joined by " -> ".
    assert app_module._dirty_paths() == ["new.md", "old.md"]


def test_dirty_paths_handles_non_ascii_filename(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    post = repo / "café.md"
    post.write_text("hola\n", encoding="utf-8")

    monkeypatch.setattr("editor.app.config.REPO", repo)

    # Plain `git status --porcelain` C-quotes this path (e.g.
    # `"caf\303\251.md"`), which would fail a startswith() prefix check.
    # -z reports it raw and unquoted.
    assert app_module._dirty_paths() == ["café.md"]
