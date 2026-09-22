"""Pairing a floated row with the section beside it, and undoing that.

A float lets text flow around a picture from the top down; a pair puts the
picture and a bounded run of prose in one container so they sit level. The
bound is the run the float was already wrapping: everything up to the next
stop marker, the next picture, or the end of the post.
"""

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "pair-test-post"

# Block layout (index -> kind):
#   0 paragraph  "Intro."
#   1 img_row    floated right, medium
#   2 paragraph  "First beside."
#   3 heading    "A section heading"
#   4 paragraph  "Second beside."
#   5 clear      the stop marker
#   6 paragraph  "After the stop."
POST = """+++
title = "Pair Test"
date = 2026-01-01
draft = true
+++

Intro.

<div class="img-row size-medium beside-right">
<img src="https://img.cloudy.nyc/p/a.jpg" alt="a cat">
</div>

First beside.

## A section heading

Second beside.

<div class="clear-beside"></div>

After the stop.
"""


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


def _pair(index, hash_):
    return client.post(f"/api/posts/{SLUG}/blocks/{index}/pair", json={"hash": hash_})


def _unpair(index, hash_):
    return client.post(f"/api/posts/{SLUG}/blocks/{index}/unpair", json={"hash": hash_})


# --- pairing ---------------------------------------------------------------


def test_pairing_folds_the_row_and_its_section_into_one_block(temp_post):
    data = _get()
    res = _pair(1, data["hash"])
    assert res.status_code == 200
    blocks = res.json()["blocks"]

    assert [b["kind"] for b in blocks] == ["paragraph", "pair", "paragraph"]
    assert blocks[0]["source"] == "Intro."
    assert blocks[2]["source"] == "After the stop."


def test_pairing_stops_at_the_stop_marker(temp_post):
    """The marker is the author's own statement of where the section ends,
    so it's the boundary -- and it's consumed, since the pair's own closing
    div now does that job.
    """
    data = _get()
    blocks = _pair(1, data["hash"]).json()["blocks"]
    assert not any(b["kind"] == "clear" for b in blocks)
    assert "clear-beside" not in temp_post.read_text(encoding="utf-8")


def test_the_prose_keeps_its_markdown(temp_post):
    data = _get()
    pair = _pair(1, data["hash"]).json()["blocks"][1]
    assert "## A section heading" in pair["source"]
    assert "First beside." in pair["source"]
    assert "Second beside." in pair["source"]


def test_the_paired_prose_still_renders_as_markdown(temp_post):
    """The blank lines around it are what keep CommonMark parsing it."""
    data = _get()
    pair = _pair(1, data["hash"]).json()["blocks"][1]
    assert "<h2>" in pair["html"]
    assert "A section heading" in pair["html"]


def test_the_picture_is_carried_through_untouched(temp_post):
    data = _get()
    pair = _pair(1, data["hash"]).json()["blocks"][1]
    assert data["blocks"][1]["source"].replace(" beside-right", "") in pair["source"]


def test_pairing_keeps_the_rows_side(temp_post):
    data = _get()
    pair = _pair(1, data["hash"]).json()["blocks"][1]
    assert 'class="pair pair-right size-medium"' in pair["source"]


def test_a_pair_reports_its_parts(temp_post):
    data = _get()
    pair = _pair(1, data["hash"]).json()["blocks"][1]
    assert pair["side"] == "right"
    assert pair["size"] == "medium"
    assert "First beside." in pair["text"]
    # The media is still an ordinary row, so its own editor still works.
    assert pair["images"] == [{"url": "https://img.cloudy.nyc/p/a.jpg", "alt": "a cat"}]


def test_pairing_runs_to_the_end_when_there_is_no_stop(temp_post):
    temp_post.write_text(
        POST.replace('<div class="clear-beside"></div>\n\n', ""), encoding="utf-8"
    )
    data = _get()
    blocks = _pair(1, data["hash"]).json()["blocks"]
    assert [b["kind"] for b in blocks] == ["paragraph", "pair"]
    assert "After the stop." in blocks[1]["source"]


def test_pairing_stops_at_the_next_picture(temp_post):
    temp_post.write_text(
        POST.replace(
            '<div class="clear-beside"></div>',
            '<div class="img-row size-small">\n<img src="https://img.cloudy.nyc/p/b.jpg" alt="b">\n</div>',
        ),
        encoding="utf-8",
    )
    data = _get()
    blocks = _pair(1, data["hash"]).json()["blocks"]
    assert [b["kind"] for b in blocks] == ["paragraph", "pair", "img_row", "paragraph"]


# --- refusals --------------------------------------------------------------


def test_an_unfloated_row_cannot_be_paired(temp_post):
    """Pairing is a stronger form of "beside"; a row with no side isn't
    beside anything, and the section boundary would be meaningless.
    """
    temp_post.write_text(POST.replace(" beside-right", ""), encoding="utf-8")
    data = _get()
    assert _pair(1, data["hash"]).status_code == 400


def test_a_row_with_no_prose_after_it_cannot_be_paired(temp_post):
    temp_post.write_text(
        POST[:POST.index("First beside.")].rstrip() + "\n", encoding="utf-8"
    )
    data = _get()
    assert _pair(1, data["hash"]).status_code == 400


def test_a_paragraph_cannot_be_paired(temp_post):
    data = _get()
    assert _pair(0, data["hash"]).status_code == 400


def test_pairing_refuses_a_stale_hash(temp_post):
    assert _pair(1, "0" * 64).status_code == 409


def test_pairing_refuses_an_out_of_range_index(temp_post):
    data = _get()
    assert _pair(99, data["hash"]).status_code == 409


# --- unpairing -------------------------------------------------------------


def test_unpairing_restores_the_row_and_the_blocks(temp_post):
    data = _get()
    paired = _pair(1, data["hash"]).json()

    res = _unpair(1, paired["hash"])
    assert res.status_code == 200
    blocks = res.json()["blocks"]
    assert [b["kind"] for b in blocks] == [
        "paragraph", "img_row", "paragraph", "heading", "paragraph", "clear", "paragraph",
    ]


def test_unpairing_gives_the_row_its_float_back(temp_post):
    data = _get()
    paired = _pair(1, data["hash"]).json()
    blocks = _unpair(1, paired["hash"]).json()["blocks"]
    assert blocks[1]["side"] == "right"


def test_unpairing_puts_the_stop_marker_back(temp_post):
    """Or the section's boundary would be lost and the following text would
    start wrapping around the picture.
    """
    data = _get()
    paired = _pair(1, data["hash"]).json()
    blocks = _unpair(1, paired["hash"]).json()["blocks"]
    assert blocks[5]["kind"] == "clear"


def test_pair_then_unpair_is_a_round_trip(temp_post):
    before = temp_post.read_text(encoding="utf-8")
    data = _get()
    paired = _pair(1, data["hash"]).json()
    _unpair(1, paired["hash"])
    assert temp_post.read_text(encoding="utf-8") == before


def test_unpairing_something_that_is_not_a_pair_is_refused(temp_post):
    data = _get()
    assert _unpair(0, data["hash"]).status_code == 400


def test_unpairing_refuses_a_stale_hash(temp_post):
    data = _get()
    _pair(1, data["hash"])
    assert _unpair(1, "0" * 64).status_code == 409


# --- editing a pair ---------------------------------------------------------


def _paired(temp_post):
    data = _get()
    return _pair(1, data["hash"]).json()


def test_editing_a_pairs_prose(temp_post):
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": "Rewritten prose.\n\nWith a second paragraph.",
            "size": "medium",
            "side": "right",
            "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    )
    assert res.status_code == 200
    pair = res.json()["blocks"][1]
    assert pair["kind"] == "pair"
    assert pair["text"] == "Rewritten prose.\n\nWith a second paragraph."


def test_editing_a_pairs_side_and_size(temp_post):
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": paired["blocks"][1]["text"],
            "size": "small",
            "side": "left",
            "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    )
    assert res.status_code == 200
    pair = res.json()["blocks"][1]
    assert (pair["side"], pair["size"]) == ("left", "small")
    assert 'class="pair pair-left size-small"' in pair["source"]


def test_editing_a_pairs_picture(temp_post):
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": paired["blocks"][1]["text"],
            "size": "medium",
            "side": "right",
            "images": [{"url": "https://img.cloudy.nyc/p/new.jpg", "alt": "new"}],
            "hash": paired["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["images"] == [
        {"url": "https://img.cloudy.nyc/p/new.jpg", "alt": "new"}
    ]


def test_a_pair_cannot_be_emptied_of_prose(temp_post):
    """An empty text column is a picture with a stray box beside it -- the
    author wanted an ordinary row, which is what Unpair gives them.
    """
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": "   ",
            "size": "medium",
            "side": "right",
            "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    )
    assert res.status_code == 400


def test_editing_a_pair_refuses_a_stale_hash(temp_post):
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": "x", "size": "medium", "side": "right",
            "images": paired["blocks"][1]["images"], "hash": "0" * 64,
        },
    )
    assert res.status_code == 409


def test_an_edited_pair_still_round_trips(temp_post):
    """Or its own editor would drop to a raw textarea on the next reload."""
    paired = _paired(temp_post)
    out = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": "Fresh *prose* with a [link](https://example.com).",
            "size": "small",
            "side": "left",
            "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    ).json()
    reloaded = _get()["blocks"][1]
    assert reloaded["text"] == out["blocks"][1]["text"]
    assert "<em>prose</em>" in reloaded["html"]


# --- justify ---------------------------------------------------------------


def test_a_new_pair_is_centred(temp_post):
    assert _paired(temp_post)["blocks"][1]["justify"] == "center"


def test_editing_a_pairs_justify(temp_post):
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": paired["blocks"][1]["text"],
            "size": "medium",
            "side": "right",
            "justify": "spread",
            "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    )
    assert res.status_code == 200
    pair = res.json()["blocks"][1]
    assert pair["justify"] == "spread"
    assert 'class="pair pair-right size-medium justify-spread"' in pair["source"]


def test_a_pairs_justify_survives_a_reload(temp_post):
    paired = _paired(temp_post)
    client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": paired["blocks"][1]["text"], "size": "medium", "side": "right",
            "justify": "top", "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    )
    assert _get()["blocks"][1]["justify"] == "top"


def test_an_unknown_justify_is_refused(temp_post):
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": paired["blocks"][1]["text"], "size": "medium", "side": "right",
            "justify": "sideways", "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    )
    assert res.status_code == 400


def test_omitting_justify_leaves_a_pair_centred(temp_post):
    """Back-compat: a caller that predates this never sends it."""
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": paired["blocks"][1]["text"], "size": "medium", "side": "right",
            "images": paired["blocks"][1]["images"], "hash": paired["hash"],
        },
    )
    assert res.json()["blocks"][1]["justify"] == "center"


def test_evenly_is_a_justify_option(temp_post):
    paired = _paired(temp_post)
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/pair",
        json={
            "text": paired["blocks"][1]["text"], "size": "medium", "side": "right",
            "justify": "evenly", "images": paired["blocks"][1]["images"],
            "hash": paired["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["justify"] == "evenly"
