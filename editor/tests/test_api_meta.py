import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app
from editor.frontmatter import split_post

client = TestClient(app)
SLUG = "meta-test-post"

POST = """+++
title = "Meta Test"
date = 2026-01-01
draft = true
+++

Body.
"""


@pytest.fixture(autouse=True)
def temp_post():
    # `git mv` (the rename route) refuses to touch a file that isn't under
    # version control, and every real post already is -- so the fixture has
    # to `git add` the temp file to stand in for that, not just write it to
    # disk. Teardown then has to undo the stage (on the original name, the
    # renamed-post name, or both, since a failed assertion can leave the
    # rename half-applied) so a leftover staged rename doesn't get swept
    # into the next real publish.
    path = config.BLOG_DIR / f"{SLUG}.md"
    renamed = config.BLOG_DIR / "renamed-post.md"
    path.write_text(POST)
    subprocess.run(["git", "add", str(path)], cwd=config.REPO, check=True)
    try:
        yield path
    finally:
        subprocess.run(
            ["git", "reset", "--", str(path), str(renamed)],
            cwd=config.REPO, capture_output=True,
        )
        path.unlink(missing_ok=True)
        renamed.unlink(missing_ok=True)


ORIGINAL_BODY = split_post(POST)[1]


def test_set_title(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta",
        json={"title": "A Better Title", "hash": data["hash"]},
    ).json()

    assert out["meta"]["title"] == "A Better Title"
    assert 'title = "A Better Title"' in temp_post.read_text()
    assert "date = 2026-01-01" in temp_post.read_text()
    # The body must round-trip untouched -- a meta edit only rewrites the
    # frontmatter block, so the body half of split_post has to come back
    # byte-identical to what it was before the edit.
    assert "Body." in temp_post.read_text()
    assert split_post(temp_post.read_text())[1] == ORIGINAL_BODY


def test_set_draft_false(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta", json={"draft": False, "hash": data["hash"]}
    ).json()
    assert out["meta"]["draft"] is False
    assert "Body." in temp_post.read_text()
    assert split_post(temp_post.read_text())[1] == ORIGINAL_BODY


def test_set_date(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta", json={"date": "2026-02-02", "hash": data["hash"]}
    ).json()
    assert out["meta"]["date"] == "2026-02-02"
    assert "Body." in temp_post.read_text()
    assert split_post(temp_post.read_text())[1] == ORIGINAL_BODY


def test_stale_hash_refused(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    temp_post.write_text(POST.replace("Body.", "Changed."))
    res = client.put(
        f"/api/posts/{SLUG}/meta", json={"title": "Nope", "hash": data["hash"]}
    )
    assert res.status_code == 409


def test_invalid_date_returns_400_not_500(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.put(
        f"/api/posts/{SLUG}/meta", json={"date": "13/45/2026", "hash": data["hash"]}
    )
    assert res.status_code == 400
    assert "date" in res.json()["detail"].lower()
    # The rejected write must not have touched the file at all.
    assert temp_post.read_text() == POST


def test_empty_date_returns_400_not_500(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.put(
        f"/api/posts/{SLUG}/meta", json={"date": "", "hash": data["hash"]}
    )
    assert res.status_code == 400
    assert "date" in res.json()["detail"].lower()
    assert temp_post.read_text() == POST


def test_rename_moves_the_file_and_warns(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.post(
        f"/api/posts/{SLUG}/rename",
        json={"new_slug": "renamed-post", "hash": data["hash"]},
    ).json()

    assert out["slug"] == "renamed-post"
    assert "link" in out["warning"].lower()
    assert (config.BLOG_DIR / "renamed-post.md").exists()
    assert not temp_post.exists()


def test_rename_of_never_committed_post_does_not_500():
    # A post from "+ New" (create_post -> _atomic_write_text) is written
    # straight to disk with no `git add` -- unlike the `temp_post` fixture
    # above, which stages the file precisely because `git mv` refuses to
    # touch something not under version control. Renaming such a post used
    # to shell `git mv` with check=True and let git's exit 128 ("not under
    # version control") surface as a bare 500.
    created = client.post("/api/posts", json={"title": "Untracked Rename Test"}).json()
    slug = created["slug"]
    new_slug = "untracked-rename-test-renamed"
    try:
        res = client.post(
            f"/api/posts/{slug}/rename",
            json={"new_slug": new_slug, "hash": created["hash"]},
        )
        assert res.status_code == 200
        assert res.json()["slug"] == new_slug
        assert (config.BLOG_DIR / f"{new_slug}.md").exists()
        assert not (config.BLOG_DIR / f"{slug}.md").exists()
    finally:
        (config.BLOG_DIR / f"{slug}.md").unlink(missing_ok=True)
        (config.BLOG_DIR / f"{new_slug}.md").unlink(missing_ok=True)
        subprocess.run(
            [
                "git", "reset", "--",
                str(config.BLOG_DIR / f"{slug}.md"),
                str(config.BLOG_DIR / f"{new_slug}.md"),
            ],
            cwd=config.REPO, capture_output=True,
        )


def test_rename_shows_up_as_outstanding_work(temp_post):
    # /api/status (via _blog_paths/_dirty_paths) is what decides whether the
    # Publish button lights up. If a staged rename didn't show up there, the
    # old slug's now-broken URL would never get flagged for a publish.
    data = client.get(f"/api/posts/{SLUG}").json()
    client.post(
        f"/api/posts/{SLUG}/rename",
        json={"new_slug": "renamed-post", "hash": data["hash"]},
    )

    status = client.get("/api/status").json()
    assert status["clean"] is False
    assert any(p.endswith("renamed-post.md") for p in status["dirty"])
