"""Undo and Discard.

Undo walks back through `editor/history.py`'s snapshots; Discard throws the
post back to its last committed state. Both are reachable from the editor
bar, and both have to be safe to hit by accident -- Discard snapshots first,
so Undo can bring the work back.
"""

import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import config, history
from editor.app import app

client = TestClient(app)
SLUG = "undo-test-post"

POST = """+++
title = "Undo Test"
date = 2026-01-01
draft = true
+++

Intro.

Second paragraph.
"""


@pytest.fixture(autouse=True)
def temp_post(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


def _edit(index, source, hash_):
    return client.put(
        f"/api/posts/{SLUG}/blocks/{index}",
        json={"source": source, "hash": hash_},
    )


def _undo(hash_):
    return client.post(f"/api/posts/{SLUG}/undo", json={"hash": hash_})


# -- can_undo reporting ----------------------------------------------------


def test_a_freshly_loaded_post_reports_nothing_to_undo(temp_post):
    assert _get()["can_undo"] is False


def test_an_edit_makes_undo_available(temp_post):
    data = _get()
    _edit(0, "Changed.", data["hash"])
    assert _get()["can_undo"] is True


def test_the_write_response_already_reports_can_undo(temp_post):
    """The client re-renders from the write's own response, so the Undo
    button would stay disabled until the next full load otherwise.
    """
    data = _get()
    assert _edit(0, "Changed.", data["hash"]).json()["can_undo"] is True


# -- undoing ---------------------------------------------------------------


def test_undo_restores_the_previous_text(temp_post):
    data = _get()
    out = _edit(0, "Changed.", data["hash"]).json()
    assert out["blocks"][0]["source"] == "Changed."

    res = _undo(out["hash"])
    assert res.status_code == 200
    assert res.json()["blocks"][0]["source"] == "Intro."
    assert "Changed." not in temp_post.read_text(encoding="utf-8")


def test_undo_walks_back_through_several_edits(temp_post):
    out = _edit(0, "One.", _get()["hash"]).json()
    out = _edit(0, "Two.", out["hash"]).json()
    out = _edit(0, "Three.", out["hash"]).json()

    out = _undo(out["hash"]).json()
    assert out["blocks"][0]["source"] == "Two."
    out = _undo(out["hash"]).json()
    assert out["blocks"][0]["source"] == "One."
    out = _undo(out["hash"]).json()
    assert out["blocks"][0]["source"] == "Intro."


def test_undo_covers_meta_edits_too(temp_post):
    """Title/date/draft take a different write path than the block routes.
    An Undo that silently skipped them would be a trap.
    """
    data = _get()
    out = client.put(
        f"/api/posts/{SLUG}/meta", json={"title": "A New Title", "hash": data["hash"]}
    ).json()
    assert out["meta"]["title"] == "A New Title"

    restored = _undo(out["hash"]).json()
    assert restored["meta"]["title"] == "Undo Test"


def test_undo_covers_a_block_delete(temp_post):
    data = _get()
    out = client.request(
        "DELETE", f"/api/posts/{SLUG}/blocks/1", json={"hash": data["hash"]}
    ).json()
    assert len(out["blocks"]) == 1

    restored = _undo(out["hash"]).json()
    assert len(restored["blocks"]) == 2


def test_undo_with_nothing_to_undo_is_refused(temp_post):
    assert _undo(_get()["hash"]).status_code == 400


def test_undo_refuses_a_stale_hash(temp_post):
    _edit(0, "Changed.", _get()["hash"])
    assert _undo("0" * 64).status_code == 409


def test_undo_is_not_its_own_inverse(temp_post):
    """Two taps must land two steps back, not return to where you started."""
    out = _edit(0, "One.", _get()["hash"]).json()
    out = _edit(0, "Two.", out["hash"]).json()

    out = _undo(out["hash"]).json()
    assert out["blocks"][0]["source"] == "One."
    out = _undo(out["hash"]).json()
    assert out["blocks"][0]["source"] == "Intro."


# -- discard ---------------------------------------------------------------


def _discard(hash_):
    return client.post(f"/api/posts/{SLUG}/discard", json={"hash": hash_})


@pytest.fixture
def committed_post(temp_post):
    """The post as git knows it -- committed, then edited on top."""
    subprocess.run(["git", "add", "--", str(temp_post)], cwd=config.REPO, check=True)
    yield temp_post
    # Leave the index as we found it; the file itself is removed by temp_post.
    subprocess.run(["git", "reset", "--quiet", "HEAD", "--", str(temp_post)],
                   cwd=config.REPO, check=True)


def test_discard_is_refused_for_a_post_git_has_never_seen(temp_post):
    """A brand-new draft has no committed version to go back to. Refusing is
    the only safe answer -- the alternative is deleting someone's draft.
    """
    res = _discard(_get()["hash"])
    assert res.status_code == 400
    assert "never been committed" in res.json()["detail"].lower()


def test_discard_refuses_a_stale_hash(temp_post):
    assert _discard("0" * 64).status_code == 409


# -- discard, against a real (isolated) git repo ---------------------------
# config.REPO is the live blog repo, so committing a fixture into it would
# leave real commits behind. These point the app at a throwaway repo instead.


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "content" / "blog").mkdir(parents=True)
    for cmd in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(cmd, cwd=repo, check=True)
    monkeypatch.setattr(config, "REPO", repo)
    monkeypatch.setattr(config, "BLOG_DIR", repo / "content" / "blog")
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "isolated-history")
    return repo


def _write(repo, text):
    path = repo / "content" / "blog" / "committed.md"
    path.write_text(text, encoding="utf-8")
    return path


def _commit(repo, path):
    subprocess.run(["git", "add", "--", str(path)], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "add post"], cwd=repo, check=True)


def test_discard_restores_the_last_committed_version(git_repo):
    path = _write(git_repo, POST)
    _commit(git_repo, path)

    data = client.get("/api/posts/committed").json()
    client.put("/api/posts/committed/blocks/0",
               json={"source": "Wrecked.", "hash": data["hash"]})
    assert "Wrecked." in path.read_text(encoding="utf-8")

    current = client.get("/api/posts/committed").json()
    res = client.post("/api/posts/committed/discard", json={"hash": current["hash"]})
    assert res.status_code == 200
    assert res.json()["blocks"][0]["source"] == "Intro."
    assert path.read_text(encoding="utf-8") == POST


def test_discard_is_itself_undoable(git_repo):
    """Snapshotting before the restore is what makes Discard safe to hit by
    accident -- otherwise the big red button is the one action with no way back.
    """
    path = _write(git_repo, POST)
    _commit(git_repo, path)

    data = client.get("/api/posts/committed").json()
    edited = client.put("/api/posts/committed/blocks/0",
                        json={"source": "Wanted this after all.", "hash": data["hash"]}).json()

    discarded = client.post("/api/posts/committed/discard",
                            json={"hash": edited["hash"]}).json()
    assert discarded["blocks"][0]["source"] == "Intro."

    restored = client.post("/api/posts/committed/undo",
                           json={"hash": discarded["hash"]}).json()
    assert restored["blocks"][0]["source"] == "Wanted this after all."


def test_discard_is_refused_for_a_staged_but_uncommitted_post(git_repo):
    """`git add` puts a path in the index, so a tracked-ness check passes for
    a post that HEAD has never held -- and `git checkout HEAD --` on it fails.
    rename_post() stages exactly like this, so the state is reachable.
    """
    path = _write(git_repo, POST)
    subprocess.run(["git", "commit", "--quiet", "--allow-empty", "-m", "root"],
                   cwd=git_repo, check=True)
    subprocess.run(["git", "add", "--", str(path)], cwd=git_repo, check=True)

    data = client.get("/api/posts/committed").json()
    res = client.post("/api/posts/committed/discard", json={"hash": data["hash"]})
    assert res.status_code == 400
    assert "never been committed" in res.json()["detail"].lower()
