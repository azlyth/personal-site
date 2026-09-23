"""Pinning which photo a post shares as.

By default a post's link preview uses its LAST photo (templates/macros/
preview.html derives that at build time). The editor's star button
overrides it by writing `extra.preview_image`, and clearing the override
has to put the post back on the default rather than leave it pinned to a
photo nobody chose.
"""
import subprocess

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app
from editor.frontmatter import read_meta, split_post

client = TestClient(app)
SLUG = "preview-image-test-post"

POST = """+++
title = "Preview Image Test"
date = 2026-01-01
draft = true
+++

Body.

<div class="img-row">
<img src="https://img.cloudy.nyc/t/one.jpg" alt="One">
<img src="https://img.cloudy.nyc/t/two.jpg" alt="Two">
</div>
"""

ORIGINAL_BODY = split_post(POST)[1]


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST)
    subprocess.run(["git", "add", str(path)], cwd=config.REPO, check=True)
    try:
        yield path
    finally:
        subprocess.run(
            ["git", "reset", "--", str(path)], cwd=config.REPO, capture_output=True
        )
        path.unlink(missing_ok=True)


def meta_of(slug=SLUG):
    return client.get(f"/api/posts/{slug}").json()


def test_a_post_with_no_override_reports_none(temp_post):
    assert meta_of()["meta"]["preview_image"] == ""


def test_setting_a_preview_image_writes_it_to_extra(temp_post):
    out = client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "https://img.cloudy.nyc/t/one.jpg", "hash": meta_of()["hash"]},
    ).json()

    assert out["meta"]["preview_image"] == "https://img.cloudy.nyc/t/one.jpg"
    frontmatter = split_post(temp_post.read_text())[0]
    assert read_meta(frontmatter)["extra"]["preview_image"] == (
        "https://img.cloudy.nyc/t/one.jpg"
    )


def test_setting_a_preview_image_leaves_the_body_alone(temp_post):
    client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "https://img.cloudy.nyc/t/one.jpg", "hash": meta_of()["hash"]},
    )

    assert split_post(temp_post.read_text())[1] == ORIGINAL_BODY


def test_setting_a_preview_image_leaves_the_other_fields_alone(temp_post):
    client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "https://img.cloudy.nyc/t/one.jpg", "hash": meta_of()["hash"]},
    )

    meta = read_meta(split_post(temp_post.read_text())[0])
    assert meta["title"] == "Preview Image Test"
    assert meta["draft"] is True


def test_an_empty_preview_image_clears_the_override(temp_post):
    client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "https://img.cloudy.nyc/t/one.jpg", "hash": meta_of()["hash"]},
    )

    out = client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "", "hash": meta_of()["hash"]},
    ).json()

    assert out["meta"]["preview_image"] == ""
    assert "extra" not in read_meta(split_post(temp_post.read_text())[0])


def test_a_stale_hash_is_refused(temp_post):
    stale = meta_of()["hash"]
    client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "https://img.cloudy.nyc/t/one.jpg", "hash": stale},
    )

    res = client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "https://img.cloudy.nyc/t/two.jpg", "hash": stale},
    )

    assert res.status_code == 409


def test_setting_a_preview_image_is_undoable(temp_post):
    client.put(
        f"/api/posts/{SLUG}/meta",
        json={"preview_image": "https://img.cloudy.nyc/t/one.jpg", "hash": meta_of()["hash"]},
    )

    out = client.post(f"/api/posts/{SLUG}/undo", json={"hash": meta_of()["hash"]}).json()

    assert out["meta"]["preview_image"] == ""
