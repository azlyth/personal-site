import shutil

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "editor-test-post"

POST = """+++
title = "Editor Test Post"
date = 2026-01-01
draft = true
+++

First para.

## A heading

Second para.
"""


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST)
    yield path
    path.unlink(missing_ok=True)


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


def test_edit_block_persists_to_disk(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Rewritten.", "hash": data["hash"]},
    )
    assert res.status_code == 200
    assert "Rewritten." in temp_post.read_text()
    assert "## A heading" in temp_post.read_text()


def test_edit_returns_fresh_hash_and_blocks(temp_post):
    data = _get()
    out = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Rewritten.", "hash": data["hash"]},
    ).json()
    assert out["hash"] != data["hash"]
    assert out["blocks"][0]["source"] == "Rewritten."


def test_stale_hash_is_refused(temp_post):
    data = _get()
    temp_post.write_text(POST.replace("First para.", "Changed elsewhere."))

    res = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Mine.", "hash": data["hash"]},
    )

    assert res.status_code == 409
    assert "Changed elsewhere." in temp_post.read_text()


def test_insert_block(temp_post):
    data = _get()
    out = client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": "Inserted.", "hash": data["hash"]},
    ).json()
    assert out["blocks"][1]["source"] == "Inserted."
    assert len(out["blocks"]) == len(data["blocks"]) + 1


def test_delete_block(temp_post):
    data = _get()
    out = client.request(
        "DELETE",
        f"/api/posts/{SLUG}/blocks/1",
        json={"hash": data["hash"]},
    ).json()
    assert len(out["blocks"]) == len(data["blocks"]) - 1
    assert "## A heading" not in temp_post.read_text()
