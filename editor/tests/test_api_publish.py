import subprocess

from fastapi.testclient import TestClient

from editor import app as app_module
from editor.app import BLOG_PREFIX, app
from editor.publish import PublishResult

client = TestClient(app)


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


def _repo_with_remote(tmp_path):
    """A repo with a real (local, bare) origin, an initial `content/blog/a.md`
    commit already pushed, and `main` checked out -- lets tests exercise the
    real `git rev-list @{upstream}..HEAD -- content/blog/` check without
    touching any actual network remote."""
    work = tmp_path / "work"
    work.mkdir()
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True)
    (work / "content" / "blog").mkdir(parents=True)
    (work / "content" / "blog" / "a.md").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", "content/blog/a.md"], cwd=work, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=work, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=work, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "main"], cwd=work, check=True)
    return work


def test_status_only_reports_blog_paths(monkeypatch):
    monkeypatch.setattr(
        "editor.app._dirty_paths",
        lambda: ["content/blog/a.md", "templates/base.html", "editor/app.py"],
    )
    monkeypatch.setattr("editor.app._has_unpushed_commits", lambda repo, pathspec=None: False)
    data = client.get("/api/status").json()
    assert data["dirty"] == ["content/blog/a.md"]
    assert data["clean"] is False


def test_status_reports_outstanding_when_only_unpushed_commits(monkeypatch):
    # A clean tree isn't the same as "nothing to do" -- a previous publish
    # may have committed fine and then failed to push or publish, leaving no
    # dirty files but a commit that never made it live.
    monkeypatch.setattr("editor.app._dirty_paths", lambda: [])
    monkeypatch.setattr("editor.app._has_unpushed_commits", lambda repo, pathspec=None: True)
    data = client.get("/api/status").json()
    assert data["dirty"] == []
    assert data["unpushed"] is True
    assert data["clean"] is False


def test_status_clean_when_unpushed_commits_are_all_non_blog(tmp_path, monkeypatch):
    # This repo accumulates unrelated in-progress code commits constantly
    # (the editor's own development, a concurrent session). None of them are
    # blog work, so the button must not light up over them.
    repo = _repo_with_remote(tmp_path)
    (repo / "notes.txt").write_text("wip\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "unrelated code work"], cwd=repo, check=True)

    monkeypatch.setattr("editor.app.config.REPO", repo)

    data = client.get("/api/status").json()
    assert data["dirty"] == []
    assert data["unpushed"] is False
    assert data["clean"] is True


def test_status_outstanding_when_unpushed_commit_touches_blog(tmp_path, monkeypatch):
    repo = _repo_with_remote(tmp_path)
    (repo / "content" / "blog" / "a.md").write_text("edited\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "edit a post"], cwd=repo, check=True)

    monkeypatch.setattr("editor.app.config.REPO", repo)

    data = client.get("/api/status").json()
    assert data["dirty"] == []
    assert data["unpushed"] is True
    assert data["clean"] is False


def test_status_outstanding_when_blog_commit_has_later_code_commit_on_top(tmp_path, monkeypatch):
    repo = _repo_with_remote(tmp_path)
    (repo / "content" / "blog" / "a.md").write_text("edited\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "edit a post"], cwd=repo, check=True)
    (repo / "notes.txt").write_text("wip\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "unrelated code work on top"], cwd=repo, check=True)

    monkeypatch.setattr("editor.app.config.REPO", repo)

    # The blog commit is still unpublished even though a later, unrelated
    # commit landed on top of it -- the later commit must not mask it.
    data = client.get("/api/status").json()
    assert data["unpushed"] is True
    assert data["clean"] is False


def test_publish_passes_only_blog_paths_to_git(monkeypatch):
    seen = {}

    def fake_publish(repo, paths, message, pathspec=None):
        seen["paths"] = paths
        seen["message"] = message
        seen["pathspec"] = pathspec
        return PublishResult(True, "abc12345", True, True, "published abc12345")

    monkeypatch.setattr(
        "editor.app._dirty_paths",
        lambda: ["content/blog/a.md", "templates/base.html"],
    )
    monkeypatch.setattr("editor.app.publish", fake_publish)

    out = client.post("/api/publish", json={"message": "Update a post"}).json()

    assert seen["paths"] == ["content/blog/a.md"]
    assert seen["pathspec"] == BLOG_PREFIX
    assert out["sha"] == "abc12345"
    assert out["published"] is True


def test_publish_with_nothing_to_do(monkeypatch):
    monkeypatch.setattr("editor.app._dirty_paths", lambda: [])
    monkeypatch.setattr(
        "editor.app.publish",
        lambda repo, paths, message, pathspec=None: PublishResult(False, None, False, False, "nothing to publish"),
    )
    out = client.post("/api/publish", json={}).json()
    assert out["committed"] is False


def test_publish_calls_publish_even_with_no_dirty_paths(monkeypatch):
    """Regression for the Critical: do_publish must not short-circuit on an
    empty path list. A clean tree with an unpushed commit is exactly the
    state a prior failed push/S3-publish leaves behind, and publish() already
    knows how to recover it -- but only if it's actually called."""
    seen = {}

    def fake_publish(repo, paths, message, pathspec=None):
        seen["called"] = True
        seen["paths"] = paths
        seen["pathspec"] = pathspec
        return PublishResult(False, "deadbeef", True, True, "published deadbeef")

    monkeypatch.setattr("editor.app._dirty_paths", lambda: [])
    monkeypatch.setattr("editor.app.publish", fake_publish)

    out = client.post("/api/publish", json={}).json()

    assert seen.get("called") is True
    assert seen["paths"] == []
    assert seen["pathspec"] == BLOG_PREFIX
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
