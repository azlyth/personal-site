"""Deleting a draft.

Drafts only: a published post has a live URL and readers, and taking it
down is a different decision from throwing away an unfinished idea.
"""

import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import app as app_module
from editor import config, history
from editor.app import app
from editor.publish import commit_paths

client = TestClient(app)

DRAFT = '+++\ntitle = "D"\ndate = 2026-01-01\ndraft = true\n+++\n\nBody.\n'
PUBLISHED = '+++\ntitle = "P"\ndate = 2026-01-01\n+++\n\nBody.\n'


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def site(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "content" / "blog").mkdir(parents=True)
    _git(repo, "init", "--quiet", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    monkeypatch.setattr(config, "REPO", repo)
    monkeypatch.setattr(config, "BLOG_DIR", repo / "content" / "blog")
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    return repo


def write(repo, slug, text, *, commit=False):
    path = repo / "content" / "blog" / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    if commit:
        _git(repo, "add", "--", str(path))
        _git(repo, "commit", "--quiet", "-m", f"add {slug}")
    return path


def delete(slug, hash_):
    return client.request("DELETE", f"/api/posts/{slug}", json={"hash": hash_})


def test_delete_refuses_a_published_post(site):
    path = write(site, "live", PUBLISHED)
    data = client.get("/api/posts/live").json()
    res = delete("live", data["hash"])
    assert res.status_code == 400
    assert "draft" in res.json()["detail"].lower()
    assert path.exists()


def test_delete_refuses_a_draft_flag_hidden_in_extra(site):
    # Zola publishes this one -- it is not a draft, whatever it says.
    path = write(site, "sneaky", PUBLISHED.replace("+++\n\n", "[extra]\ndraft = true\n+++\n\n"))
    data = client.get("/api/posts/sneaky").json()
    assert delete("sneaky", data["hash"]).status_code == 400
    assert path.exists()


def test_delete_refuses_a_stale_hash(site):
    path = write(site, "draft", DRAFT)
    assert delete("draft", "stale").status_code == 409
    assert path.exists()


def test_delete_404s_a_missing_post(site):
    assert delete("nope", "x").status_code == 404


def test_delete_removes_an_untracked_draft(site):
    path = write(site, "draft", DRAFT)
    data = client.get("/api/posts/draft").json()
    res = delete("draft", data["hash"])
    assert res.status_code == 200
    assert not path.exists()
    assert _git(site, "status", "--porcelain") == ""
    assert client.get("/api/posts/draft").status_code == 404


def test_delete_stages_the_removal_of_a_tracked_draft(site):
    path = write(site, "draft", DRAFT, commit=True)
    data = client.get("/api/posts/draft").json()
    assert delete("draft", data["hash"]).status_code == 200
    assert not path.exists()
    assert _git(site, "status", "--porcelain") == "D  content/blog/draft.md\n"


def test_a_deleted_draft_publishes(site):
    # The Publish path minus the push: the staged deletion is reported as
    # outstanding work and commit_paths commits it, even though the path
    # now exists neither on disk nor in the index.
    write(site, "keep", PUBLISHED, commit=True)
    write(site, "draft", DRAFT, commit=True)
    data = client.get("/api/posts/draft").json()
    delete("draft", data["hash"])

    paths = app_module._blog_paths()
    assert paths == ["content/blog/draft.md"]
    assert client.get("/api/status").json()["clean"] is False
    assert commit_paths(site, paths, "delete draft")
    assert _git(site, "ls-tree", "-r", "--name-only", "HEAD").split() == ["content/blog/keep.md"]


def test_delete_removes_a_staged_but_uncommitted_draft(site):
    # A renamed "+ New" post is staged but never committed -- `git rm`
    # refuses that without -f.
    _git(site, "commit", "--quiet", "--allow-empty", "-m", "root")
    path = write(site, "draft", DRAFT)
    _git(site, "add", "--", str(path))
    data = client.get("/api/posts/draft").json()
    assert delete("draft", data["hash"]).status_code == 200
    assert not path.exists()
    assert _git(site, "status", "--porcelain") == ""


def test_delete_drops_the_undo_history(site):
    write(site, "draft", DRAFT)
    data = client.get("/api/posts/draft").json()
    edited = client.put("/api/posts/draft/meta", json={"title": "E", "hash": data["hash"]}).json()
    assert (history.HISTORY_DIR / "draft").is_dir()
    delete("draft", edited["hash"])
    assert not (history.HISTORY_DIR / "draft").exists()
