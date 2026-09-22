import os
import shutil

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "editor-test-post"

# The one shape blocks.py recognises as a stop-wrap marker.
CLEAR_SOURCE = '<div class="clear-beside"></div>'
SPACER_SOURCE = '<div class="post-spacer"></div>' 

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
    path.write_text(POST, encoding="utf-8")
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
    on_disk = temp_post.read_text(encoding="utf-8")
    assert "Rewritten." in on_disk
    assert "## A heading" in on_disk


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
    temp_post.write_text(POST.replace("First para.", "Changed elsewhere."), encoding="utf-8")

    res = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Mine.", "hash": data["hash"]},
    )

    assert res.status_code == 409
    assert "Changed elsewhere." in temp_post.read_text(encoding="utf-8")


def test_stale_index_returns_409_not_500(temp_post):
    """Two tabs open on the same post: one deletes a block, the other then
    acts on the now-stale index. blocks.py raises IndexError for that on
    purpose -- nothing should let it surface as an unhandled 500."""
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/99",
        json={"source": "Mine.", "hash": data["hash"]},
    )
    assert res.status_code == 409
    # And the file on disk is untouched -- the bad index never reached a write.
    assert temp_post.read_text(encoding="utf-8") == POST


def test_edit_preserves_file_mode(temp_post):
    """tempfile.mkstemp creates its file at 0600 regardless of umask, and
    os.replace swaps the directory entry rather than copying into the
    existing inode -- so an atomic write that doesn't explicitly carry the
    mode over silently turns every edited post owner-only. That matters
    because zola build runs as a different UID in a container; a 0600 post
    would fail to build with an error that points at Zola, not the editor
    that caused it."""
    os.chmod(temp_post, 0o644)
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/0",
        json={"source": "Rewritten.", "hash": data["hash"]},
    )
    assert res.status_code == 200
    assert temp_post.stat().st_mode & 0o777 == 0o644


def test_insert_block(temp_post):
    data = _get()
    out = client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": "Inserted.", "hash": data["hash"]},
    ).json()
    assert out["blocks"][1]["source"] == "Inserted."
    assert len(out["blocks"]) == len(data["blocks"]) + 1

    # The whole point of splicing into source ranges rather than
    # reconstructing markdown is that blocks you didn't touch come through
    # byte-identical. Prove the neighbours actually did, not just that the
    # count changed.
    assert out["blocks"][0]["source"] == data["blocks"][0]["source"]
    assert out["blocks"][2]["source"] == data["blocks"][1]["source"]
    assert out["blocks"][3]["source"] == data["blocks"][2]["source"]


def test_delete_block(temp_post):
    data = _get()
    out = client.request(
        "DELETE",
        f"/api/posts/{SLUG}/blocks/1",
        json={"hash": data["hash"]},
    ).json()
    assert len(out["blocks"]) == len(data["blocks"]) - 1
    assert "## A heading" not in temp_post.read_text(encoding="utf-8")

    # Same guarantee as the insert test: the surrounding blocks must be
    # untouched, not just present.
    assert out["blocks"][0]["source"] == data["blocks"][0]["source"]
    assert out["blocks"][1]["source"] == data["blocks"][2]["source"]


def test_move_block_persists_to_disk(temp_post):
    data = _get()
    res = client.post(
        f"/api/posts/{SLUG}/blocks/0/move",
        json={"to_index": 3, "hash": data["hash"]},
    )
    assert res.status_code == 200
    out = res.json()
    assert [b["source"] for b in out["blocks"]] == [
        data["blocks"][1]["source"],
        data["blocks"][2]["source"],
        data["blocks"][0]["source"],
    ]
    on_disk = temp_post.read_text(encoding="utf-8")
    assert on_disk.index("First para.") > on_disk.index("Second para.")


def test_move_block_to_same_position_is_a_noop(temp_post):
    data = _get()
    res = client.post(
        f"/api/posts/{SLUG}/blocks/1/move",
        json={"to_index": 1, "hash": data["hash"]},
    )
    assert res.status_code == 200
    on_disk = temp_post.read_text(encoding="utf-8")
    assert on_disk == POST


def test_move_block_stale_hash_is_refused(temp_post):
    data = _get()
    temp_post.write_text(POST.replace("First para.", "Changed elsewhere."), encoding="utf-8")

    res = client.post(
        f"/api/posts/{SLUG}/blocks/0/move",
        json={"to_index": 2, "hash": data["hash"]},
    )

    assert res.status_code == 409
    assert "Changed elsewhere." in temp_post.read_text(encoding="utf-8")


def test_move_block_stale_from_index_returns_409_not_500(temp_post):
    data = _get()
    res = client.post(
        f"/api/posts/{SLUG}/blocks/99/move",
        json={"to_index": 0, "hash": data["hash"]},
    )
    assert res.status_code == 409
    assert temp_post.read_text(encoding="utf-8") == POST


def test_move_block_out_of_range_to_index_returns_409_not_500(temp_post):
    data = _get()
    res = client.post(
        f"/api/posts/{SLUG}/blocks/0/move",
        json={"to_index": 99, "hash": data["hash"]},
    )
    assert res.status_code == 409
    assert temp_post.read_text(encoding="utf-8") == POST


# --- the stop-wrap marker --------------------------------------------------
# Inserted by hand from the editor to end a float's wrap early, so a new
# section can start clean at full width (and pair with its own picture)
# instead of continuing to run alongside the previous one.


def test_the_stop_wrap_marker_inserts_as_its_own_kind(temp_post):
    data = _get()
    res = client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": CLEAR_SOURCE, "hash": data["hash"]},
    )
    assert res.status_code == 200
    blocks = res.json()["blocks"]
    assert blocks[1]["kind"] == "clear"
    assert len(blocks) == len(data["blocks"]) + 1


def test_the_stop_wrap_marker_round_trips_through_the_file(temp_post):
    """It has to come back as `clear`, not as raw html -- that's what gets it
    the labelled divider in the editor instead of an invisible empty block.
    """
    data = _get()
    client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": CLEAR_SOURCE, "hash": data["hash"]},
    )
    assert CLEAR_SOURCE in temp_post.read_text(encoding="utf-8")
    assert _get()["blocks"][1]["kind"] == "clear"


def test_the_stop_wrap_marker_can_be_deleted_like_any_block(temp_post):
    data = _get()
    added = client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": CLEAR_SOURCE, "hash": data["hash"]},
    ).json()

    removed = client.request(
        "DELETE", f"/api/posts/{SLUG}/blocks/1", json={"hash": added["hash"]}
    ).json()
    assert not any(b["kind"] == "clear" for b in removed["blocks"])
    assert len(removed["blocks"]) == len(data["blocks"])


def test_the_spacer_inserts_as_its_own_kind(temp_post):
    data = _get()
    res = client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": SPACER_SOURCE, "hash": data["hash"]},
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["kind"] == "spacer"


def test_the_spacer_round_trips_and_deletes(temp_post):
    data = _get()
    added = client.post(
        f"/api/posts/{SLUG}/blocks",
        json={"index": 1, "source": SPACER_SOURCE, "hash": data["hash"]},
    ).json()
    assert SPACER_SOURCE in temp_post.read_text(encoding="utf-8")
    assert _get()["blocks"][1]["kind"] == "spacer"

    removed = client.request(
        "DELETE", f"/api/posts/{SLUG}/blocks/1", json={"hash": added["hash"]}
    ).json()
    assert not any(b["kind"] == "spacer" for b in removed["blocks"])
