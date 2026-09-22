import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "image-block-test-post"

POST = """+++
title = "Image Block Test"
date = 2026-01-01
draft = true
+++

Intro.

![alt one](https://img.cloudy.nyc/p/one.jpg)

<div class="img-row">
<img src="https://img.cloudy.nyc/p/two.jpg" alt="two">
<img src="https://img.cloudy.nyc/p/three.jpg" alt="three">
</div>

Outro.
"""


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST, encoding="utf-8")
    app.state.s3 = FakeS3()
    yield path
    path.unlink(missing_ok=True)


def _png(size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


# --- GET .../posts/{slug} exposes parsed images per block -----------------


def test_get_post_includes_images_for_standalone_image_block(temp_post):
    data = _get()
    block = data["blocks"][1]
    assert block["kind"] == "image"
    assert block["images"] == [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}]


def test_get_post_includes_images_for_img_row_block(temp_post):
    data = _get()
    block = data["blocks"][2]
    assert block["kind"] == "img_row"
    assert block["images"] == [
        {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
        {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
    ]


def test_get_post_includes_default_size_for_photo_blocks(temp_post):
    # Neither block in POST has ever had a size chosen -- both should read
    # back as the default preset, same as a video row always has *a* size
    # but these start out at the one that needs no class at all.
    data = _get()
    assert data["blocks"][1]["size"] == "full"
    assert data["blocks"][2]["size"] == "full"


def test_get_post_omits_images_for_non_photo_blocks(temp_post):
    data = _get()
    assert "images" not in data["blocks"][0]  # "Intro." paragraph


MALFORMED_SLUG = "image-block-malformed-post"

# One <img> is missing its alt attribute, so the naive tag regex only
# matches the second one -- the case that used to silently drop a photo
# (Fix 1). The block still classifies as img_row (the wrapping div is
# well-formed); it's only the photo *list* that isn't safely derivable.
MALFORMED_POST = """+++
title = "Malformed Image Block Test"
date = 2026-01-01
draft = true
+++

Intro.

<div class="img-row">
<img src="https://img.cloudy.nyc/p/two.jpg">
<img src="https://img.cloudy.nyc/p/three.jpg" alt="three">
</div>

Outro.
"""


@pytest.fixture
def malformed_post():
    path = config.BLOG_DIR / f"{MALFORMED_SLUG}.md"
    path.write_text(MALFORMED_POST, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def test_get_post_omits_images_key_for_unparseable_img_row(malformed_post):
    # The key must be *absent*, not present-and-null and not present-and-[]
    # -- the client gates the thumbnail editor on whether `images` exists at
    # all, so an unrepresentable block has to look exactly like a block that
    # was never a candidate for it, keeping the raw-source textarea as the
    # only way to edit it.
    data = client.get(f"/api/posts/{MALFORMED_SLUG}").json()
    block = data["blocks"][1]
    assert block["kind"] == "img_row"
    assert "images" not in block


# --- PUT .../blocks/{index}/images -----------------------------------------


def test_replace_block_images_rewrites_standalone_to_img_row(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [
                {"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"},
                {"url": "https://img.cloudy.nyc/p/new.jpg", "alt": "a new one"},
            ],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    out = res.json()
    block = out["blocks"][1]
    assert block["kind"] == "img_row"
    assert block["images"] == [
        {"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"},
        {"url": "https://img.cloudy.nyc/p/new.jpg", "alt": "a new one"},
    ]

    on_disk = temp_post.read_text(encoding="utf-8")
    assert '<div class="img-row">' in on_disk
    assert "https://img.cloudy.nyc/p/new.jpg" in on_disk


def test_replace_block_images_with_size_wraps_standalone_image(temp_post):
    # Picking a non-default size for the lone standalone image (block 1)
    # must promote it to a wrapped, sized `.img-row` -- that's the only way
    # a single photo can carry a size class.
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}],
            "size": "small",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    out = res.json()
    block = out["blocks"][1]
    assert block["kind"] == "img_row"
    assert block["size"] == "small"
    assert block["images"] == [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}]

    on_disk = temp_post.read_text(encoding="utf-8")
    assert '<div class="img-row size-small">' in on_disk
    assert "![alt one]" not in on_disk


def test_replace_block_images_back_to_default_size_returns_to_plain_markdown(temp_post):
    # First size it, then set it back to the default -- the block must
    # collapse back to plain markdown, not stay a `size-full` div. Proves
    # the opt-in property survives a round trip through the sized shape.
    data = _get()
    sized = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}],
            "size": "medium",
            "hash": data["hash"],
        },
    ).json()

    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}],
            "size": "full",
            "hash": sized["hash"],
        },
    )
    assert res.status_code == 200
    out = res.json()
    block = out["blocks"][1]
    assert block["kind"] == "image"
    assert block["size"] == "full"

    on_disk = temp_post.read_text(encoding="utf-8")
    assert on_disk.count("img-row") == 1  # only the original block 2 img_row remains
    assert "![alt one](https://img.cloudy.nyc/p/one.jpg)" in on_disk


def test_replace_block_images_with_size_on_img_row(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [
                {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
                {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
            ],
            "size": "medium",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    block = res.json()["blocks"][2]
    assert block["size"] == "medium"

    on_disk = temp_post.read_text(encoding="utf-8")
    assert '<div class="img-row size-medium">' in on_disk


def test_replace_block_images_without_size_field_defaults_to_full(temp_post):
    # Existing clients/tests that don't send `size` at all must keep
    # working exactly as before this feature -- same as an unsized img-row.
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [
                {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
                {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
            ],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    block = res.json()["blocks"][2]
    assert block["size"] == "full"
    on_disk = temp_post.read_text(encoding="utf-8")
    assert '<div class="img-row">' in on_disk


def test_replace_block_images_reorders(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [
                {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
                {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
            ],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    urls_in_order = [im["url"] for im in res.json()["blocks"][2]["images"]]
    assert urls_in_order == [
        "https://img.cloudy.nyc/p/three.jpg",
        "https://img.cloudy.nyc/p/two.jpg",
    ]


def test_replace_block_images_edits_alt_text(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "a much better description"}],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["images"][0]["alt"] == "a much better description"


def test_replace_block_images_empty_list_deletes_block(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={"images": [], "hash": data["hash"]},
    )
    assert res.status_code == 200
    out = res.json()
    assert len(out["blocks"]) == len(data["blocks"]) - 1
    on_disk = temp_post.read_text(encoding="utf-8")
    assert "img-row" not in on_disk
    assert "Intro." in on_disk and "Outro." in on_disk


def test_replace_block_images_preserves_neighbouring_blocks(temp_post):
    data = _get()
    out = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}],
            "hash": data["hash"],
        },
    ).json()
    assert out["blocks"][0]["source"] == data["blocks"][0]["source"]
    assert out["blocks"][2]["source"] == data["blocks"][2]["source"]
    assert out["blocks"][3]["source"] == data["blocks"][3]["source"]


def test_replace_block_images_stale_hash_refused(temp_post):
    data = _get()
    temp_post.write_text(POST.replace("Intro.", "Changed."), encoding="utf-8")

    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "x"}],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 409
    assert "Changed." in temp_post.read_text(encoding="utf-8")


def test_replace_block_images_preserves_file_mode(temp_post):
    import os

    os.chmod(temp_post, 0o644)
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "x"}],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert temp_post.stat().st_mode & 0o777 == 0o644


# --- POST .../images/upload (upload without touching the post) ------------


def test_upload_only_returns_images_without_modifying_post(temp_post):
    before = temp_post.read_text(encoding="utf-8")
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=[
            ("files", ("a.png", _png((800, 600)), "image/png")),
            ("files", ("b.png", _png((640, 480)), "image/png")),
        ],
        data={"alts": '["fresh a", "fresh b"]'},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["images"]) == 2
    assert body["images"][0]["alt"] == "fresh a"
    assert body["images"][0]["url"].startswith("https://img.cloudy.nyc/")
    assert len(app.state.s3.calls) == 2
    assert temp_post.read_text(encoding="utf-8") == before


def test_upload_only_404s_for_unknown_post(temp_post):
    res = client.post(
        "/api/posts/does-not-exist/images/upload",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]'},
    )
    assert res.status_code == 404


def test_upload_only_rejects_cross_site(temp_post):
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]'},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert res.status_code == 403
    assert not app.state.s3.calls


def test_upload_only_rejects_too_many_files(temp_post):
    from editor.app import MAX_FILES

    files = [("files", (f"{i}.png", _png((10, 10)), "image/png")) for i in range(MAX_FILES + 1)]
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=files,
        data={"alts": "[]"},
    )
    assert res.status_code == 400
    assert not app.state.s3.calls


def test_upload_only_rejects_non_image_file(temp_post):
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=[("files", ("b.png", b"not actually an image", "image/png"))],
        data={"alts": '["x"]'},
    )
    assert res.status_code == 400
    assert not app.state.s3.calls


# --- Fix 4: a bracket in alt text must not demote the block on reload -----


def test_bracket_alt_text_survives_save_and_reload_as_image(temp_post):
    # markdown_for escapes `]` in a standalone image's alt as `\]`; the
    # block classifier's own regex has to tolerate that escape or the next
    # load reclassifies the block as a plain paragraph and the thumbnail
    # editor silently disappears for it.
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "a photo of a]bracket"}],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    saved_block = res.json()["blocks"][1]
    assert saved_block["kind"] == "image"
    assert saved_block["images"] == [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "a photo of a]bracket"}]

    # Reload independently (a fresh GET, not just the PUT's own response) --
    # the classifier has to agree with itself on the bytes now sitting on
    # disk, not just in the write response.
    reloaded = _get()["blocks"][1]
    assert reloaded["kind"] == "image"
    assert reloaded["images"] == [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "a photo of a]bracket"}]


# --- `side`: floating a row beside the text that follows it -----------------


def test_get_post_includes_the_side_for_a_photo_block(temp_post):
    data = _get()
    assert data["blocks"][1]["side"] == "none"   # standalone image
    assert data["blocks"][2]["side"] == "none"   # img_row


def test_replace_block_images_sets_a_side(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [
                {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
                {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
            ],
            "size": "medium",
            "side": "left",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][2]["side"] == "left"
    assert 'class="img-row size-medium beside-left"' in temp_post.read_text(encoding="utf-8")


def test_floating_a_standalone_image_promotes_it_to_a_sized_row(temp_post):
    """Markdown has nowhere to hang a class, so choosing a side -- like
    choosing a size -- is what converts `![alt](url)` into a div.
    """
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}],
            "size": "small",
            "side": "right",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    on_disk = temp_post.read_text(encoding="utf-8")
    assert '<div class="img-row size-small beside-right">' in on_disk
    assert "![alt one]" not in on_disk


def test_replace_block_images_omitting_side_leaves_the_row_unfloated(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"}],
            "size": "medium",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][2]["side"] == "none"
    assert "beside-" not in temp_post.read_text(encoding="utf-8")


def test_replace_block_images_rejects_an_unknown_side(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"}],
            "size": "medium",
            "side": "sideways",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 400


def test_replace_block_images_rejects_a_full_width_float(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"}],
            "size": "full",
            "side": "right",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 400


# --- splitting a photo out of a row ----------------------------------------
# Mirrors the video row's "Split out" exactly: `move_block` moves blocks and
# not items, so a photo sharing a row has no way to reach a distant part of
# the post. Splitting lifts it into a row of its own directly below, which an
# ordinary move can then place anywhere.


def _split(index, data, split, images=None, size=None, side=None):
    block = data["blocks"][index]
    return client.post(
        f"/api/posts/{SLUG}/blocks/{index}/images/split",
        json={
            "images": images if images is not None else block["images"],
            "size": size if size is not None else block["size"],
            "side": side if side is not None else block["side"],
            "split": split,
            "hash": data["hash"],
        },
    )


def test_split_lifts_one_photo_into_a_row_below(temp_post):
    data = _get()
    res = _split(2, data, 0)
    assert res.status_code == 200
    blocks = res.json()["blocks"]

    assert len(blocks) == len(data["blocks"]) + 1
    assert [i["url"] for i in blocks[2]["images"]] == ["https://img.cloudy.nyc/p/three.jpg"]
    assert [i["url"] for i in blocks[3]["images"]] == ["https://img.cloudy.nyc/p/two.jpg"]


def test_split_keeps_the_alt_text_with_its_photo(temp_post):
    data = _get()
    blocks = _split(2, data, 1).json()["blocks"]
    assert blocks[3]["images"] == [{"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"}]


def test_split_new_row_inherits_the_source_row_size(temp_post):
    data = _get()
    sized = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={"images": data["blocks"][2]["images"], "size": "small", "hash": data["hash"]},
    ).json()

    blocks = _split(2, sized, 0).json()["blocks"]
    assert blocks[2]["size"] == "small"
    assert blocks[3]["size"] == "small"


def test_split_out_photo_is_never_floated(temp_post):
    """Same rule as the video split: a float exists in relation to the text
    that follows that row, and this photo is on its way somewhere else.
    """
    data = _get()
    floated = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": data["blocks"][2]["images"],
            "size": "medium",
            "side": "right",
            "hash": data["hash"],
        },
    ).json()
    assert floated["blocks"][2]["side"] == "right"

    blocks = _split(2, floated, 0).json()["blocks"]
    assert blocks[2]["side"] == "right"
    assert blocks[3]["side"] == "none"


def test_split_preserves_neighbouring_blocks(temp_post):
    data = _get()
    out = _split(2, data, 0).json()
    assert out["blocks"][0]["source"] == data["blocks"][0]["source"]
    assert out["blocks"][1]["source"] == data["blocks"][1]["source"]
    assert out["blocks"][4]["source"] == data["blocks"][3]["source"]


def test_split_applies_a_pending_reorder_in_the_same_write(temp_post):
    """The row editor keeps a local working copy and only commits on Done, so
    reordering and then splitting has to arrive as one request or the reorder
    is lost.
    """
    data = _get()
    reordered = [
        {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
        {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
    ]
    blocks = _split(2, data, 0, images=reordered).json()["blocks"]
    assert [i["url"] for i in blocks[2]["images"]] == ["https://img.cloudy.nyc/p/two.jpg"]
    assert [i["url"] for i in blocks[3]["images"]] == ["https://img.cloudy.nyc/p/three.jpg"]


def test_split_rejects_a_single_photo_row(temp_post):
    """It already IS its own row, and letting it through would hit the
    "empty list deletes the block" rule and delete it instead of splitting.
    """
    data = _get()
    res = _split(1, data, 0, images=[{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}])
    assert res.status_code == 400


def test_split_rejects_an_out_of_range_photo_index(temp_post):
    data = _get()
    assert _split(2, data, 7).status_code == 400


def test_split_rejects_a_stale_hash(temp_post):
    data = _get()
    data["hash"] = "0" * 64
    assert _split(2, data, 0).status_code == 409


def test_split_leaves_both_rows_losslessly_parseable(temp_post):
    data = _get()
    blocks = _split(2, data, 0).json()["blocks"]
    assert "images" in blocks[2] and "images" in blocks[3]
