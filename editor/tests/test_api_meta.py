import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

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


def test_set_title(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta",
        json={"title": "A Better Title", "hash": data["hash"]},
    ).json()

    assert out["meta"]["title"] == "A Better Title"
    assert 'title = "A Better Title"' in temp_post.read_text()
    assert "date = 2026-01-01" in temp_post.read_text()


def test_set_draft_false(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta", json={"draft": False, "hash": data["hash"]}
    ).json()
    assert out["meta"]["draft"] is False


def test_set_date(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    out = client.put(
        f"/api/posts/{SLUG}/meta", json={"date": "2026-02-02", "hash": data["hash"]}
    ).json()
    assert out["meta"]["date"] == "2026-02-02"


def test_stale_hash_refused(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    temp_post.write_text(POST.replace("Body.", "Changed."))
    res = client.put(
        f"/api/posts/{SLUG}/meta", json={"title": "Nope", "hash": data["hash"]}
    )
    assert res.status_code == 409


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
