import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "video-block-test-post"

POST = """+++
title = "Video Block Test"
date = 2026-01-01
draft = true
+++

Intro.

<div class="video-row size-medium">
<video autoplay loop muted playsinline data-sync-loop="4">
<source src="https://img.cloudy.nyc/p/one.mp4" type="video/mp4">
</video>
</div>

<div class="video-row size-small">
<video autoplay loop muted playsinline>
<source src="https://img.cloudy.nyc/p/two.mp4" type="video/mp4">
</video>
<video autoplay loop muted playsinline>
<source src="https://img.cloudy.nyc/p/three.mp4" type="video/mp4">
</video>
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


def _mp4(size="64x48", duration="0.2") -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "src.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", f"color=c=red:s={size}:d={duration}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(out),
            ],
            check=True,
        )
        return out.read_bytes()


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


# --- GET .../posts/{slug} exposes parsed videos per block ------------------


def test_get_post_includes_videos_for_single_clip_row(temp_post):
    data = _get()
    block = data["blocks"][1]
    assert block["kind"] == "video"
    assert block["size"] == "medium"
    assert block["videos"] == [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}]


def test_get_post_includes_videos_for_multi_clip_row(temp_post):
    data = _get()
    block = data["blocks"][2]
    assert block["kind"] == "video"
    assert block["size"] == "small"
    assert block["videos"] == [
        {"url": "https://img.cloudy.nyc/p/two.mp4", "sync_loop": None},
        {"url": "https://img.cloudy.nyc/p/three.mp4", "sync_loop": None},
    ]


def test_get_post_omits_videos_for_non_video_blocks(temp_post):
    data = _get()
    assert "videos" not in data["blocks"][0]  # "Intro." paragraph


MALFORMED_SLUG = "video-block-malformed-post"

# Missing the size class on the wrapper -- markdown_for always emits one, so
# this can never round-trip and the block must fall back to raw editing.
MALFORMED_POST = """+++
title = "Malformed Video Block Test"
date = 2026-01-01
draft = true
+++

Intro.

<div class="video-row">
<video autoplay loop muted playsinline>
<source src="https://img.cloudy.nyc/p/two.mp4" type="video/mp4">
</video>
</div>

Outro.
"""


@pytest.fixture
def malformed_post():
    path = config.BLOG_DIR / f"{MALFORMED_SLUG}.md"
    path.write_text(MALFORMED_POST, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def test_get_post_omits_videos_key_for_unparseable_video_row(malformed_post):
    data = client.get(f"/api/posts/{MALFORMED_SLUG}").json()
    block = data["blocks"][1]
    assert block["kind"] == "video"
    assert "videos" not in block
    assert "size" not in block


# --- PUT .../blocks/{index}/videos -----------------------------------------


def test_replace_block_videos_adds_a_clip(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [
                {"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"},
                {"url": "https://img.cloudy.nyc/p/new.mp4", "sync_loop": None},
            ],
            "size": "medium",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    block = res.json()["blocks"][1]
    assert block["videos"] == [
        {"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"},
        {"url": "https://img.cloudy.nyc/p/new.mp4", "sync_loop": None},
    ]

    on_disk = temp_post.read_text(encoding="utf-8")
    assert "https://img.cloudy.nyc/p/new.mp4" in on_disk


def test_replace_block_videos_reorders(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/videos",
        json={
            "videos": [
                {"url": "https://img.cloudy.nyc/p/three.mp4", "sync_loop": None},
                {"url": "https://img.cloudy.nyc/p/two.mp4", "sync_loop": None},
            ],
            "size": "small",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    urls = [v["url"] for v in res.json()["blocks"][2]["videos"]]
    assert urls == ["https://img.cloudy.nyc/p/three.mp4", "https://img.cloudy.nyc/p/two.mp4"]


def test_replace_block_videos_changes_size(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "full",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["size"] == "full"


def test_replace_block_videos_rejects_unknown_size(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "huge",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 400


def test_replace_block_videos_empty_list_deletes_block(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={"videos": [], "size": "medium", "hash": data["hash"]},
    )
    assert res.status_code == 200
    out = res.json()
    assert len(out["blocks"]) == len(data["blocks"]) - 1
    on_disk = temp_post.read_text(encoding="utf-8")
    assert "https://img.cloudy.nyc/p/one.mp4" not in on_disk
    assert "Intro." in on_disk and "Outro." in on_disk


def test_replace_block_videos_preserves_neighbouring_blocks(temp_post):
    data = _get()
    out = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "medium",
            "hash": data["hash"],
        },
    ).json()
    assert out["blocks"][0]["source"] == data["blocks"][0]["source"]
    assert out["blocks"][2]["source"] == data["blocks"][2]["source"]
    assert out["blocks"][3]["source"] == data["blocks"][3]["source"]


def test_replace_block_videos_stale_hash_refused(temp_post):
    data = _get()
    temp_post.write_text(POST.replace("Intro.", "Changed."), encoding="utf-8")

    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "medium",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 409
    assert "Changed." in temp_post.read_text(encoding="utf-8")


# --- POST .../videos/upload (upload without touching the post) ------------


def test_upload_only_returns_videos_without_modifying_post(temp_post):
    before = temp_post.read_text(encoding="utf-8")
    res = client.post(
        f"/api/posts/{SLUG}/videos/upload",
        files=[
            ("files", ("clip-a.mp4", _mp4(), "video/mp4")),
        ],
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["videos"]) == 1
    assert body["videos"][0]["url"].startswith("https://img.cloudy.nyc/")
    assert body["videos"][0]["sync_loop"] is None
    assert len(app.state.s3.calls) == 1
    assert app.state.s3.calls[0]["ContentType"] == "video/mp4"
    assert temp_post.read_text(encoding="utf-8") == before


def test_upload_only_404s_for_unknown_post(temp_post):
    res = client.post(
        "/api/posts/does-not-exist/videos/upload",
        files=[("files", ("clip.mp4", _mp4(), "video/mp4"))],
    )
    assert res.status_code == 404


def test_upload_only_rejects_cross_site(temp_post):
    res = client.post(
        f"/api/posts/{SLUG}/videos/upload",
        files=[("files", ("clip.mp4", _mp4(), "video/mp4"))],
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert res.status_code == 403
    assert not app.state.s3.calls


def test_upload_only_rejects_too_many_files(temp_post):
    from editor.app import MAX_VIDEO_FILES

    small = _mp4(size="16x16", duration="0.1")
    files = [("files", (f"{i}.mp4", small, "video/mp4")) for i in range(MAX_VIDEO_FILES + 1)]
    res = client.post(f"/api/posts/{SLUG}/videos/upload", files=files)
    assert res.status_code == 400
    assert not app.state.s3.calls


def test_upload_only_rejects_non_video_file(temp_post):
    res = client.post(
        f"/api/posts/{SLUG}/videos/upload",
        files=[("files", ("b.mp4", b"not actually a video", "video/mp4"))],
    )
    assert res.status_code == 400
    assert not app.state.s3.calls


# --- POST .../blocks/{index}/videos/split ----------------------------------
#
# Splitting lifts one clip out of a row into a row of its own directly below,
# so the existing whole-block move can then put it anywhere. The request
# carries the row's full clip list (not just the split index) because the row
# editor holds a local working copy: reordering and then splitting has to land
# as one write, not two.

THREE_SLUG = "video-block-three-clip-post"

THREE_POST = """+++
title = "Three Clip Row"
date = 2026-01-01
draft = true
+++

Intro.

<div class="video-row size-full">
<video autoplay loop muted playsinline>
<source src="https://img.cloudy.nyc/p/a.mp4" type="video/mp4">
</video>
<video autoplay loop muted playsinline data-sync-loop="4">
<source src="https://img.cloudy.nyc/p/b.mp4" type="video/mp4">
</video>
<video autoplay loop muted playsinline>
<source src="https://img.cloudy.nyc/p/c.mp4" type="video/mp4">
</video>
</div>

Outro.
"""


@pytest.fixture
def three_clip_post():
    path = config.BLOG_DIR / f"{THREE_SLUG}.md"
    path.write_text(THREE_POST, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def _three():
    return client.get(f"/api/posts/{THREE_SLUG}").json()


def _clips(block):
    return [v["url"] for v in block["videos"]]


def _split(slug, index, data, split, videos=None, size=None, side=None):
    block = data["blocks"][index]
    return client.post(
        f"/api/posts/{slug}/blocks/{index}/videos/split",
        json={
            "videos": videos if videos is not None else block["videos"],
            "size": size if size is not None else block["size"],
            # Echoed back the same way `size` is: `side` server-side defaults
            # to unfloated for back-compat, so a caller that drops it turns a
            # floated row into a centred one as a side effect of splitting.
            "side": side if side is not None else block["side"],
            "split": split,
            "hash": data["hash"],
        },
    )


def test_split_middle_clip_leaves_the_others_in_order(three_clip_post):
    data = _three()
    res = _split(THREE_SLUG, 1, data, 1)

    assert res.status_code == 200
    blocks = res.json()["blocks"]
    assert _clips(blocks[1]) == ["https://img.cloudy.nyc/p/a.mp4", "https://img.cloudy.nyc/p/c.mp4"]


def test_split_puts_the_clip_in_a_new_row_directly_below(three_clip_post):
    data = _three()
    res = _split(THREE_SLUG, 1, data, 1)

    blocks = res.json()["blocks"]
    assert len(blocks) == len(data["blocks"]) + 1
    assert blocks[2]["kind"] == "video"
    assert blocks[2]["videos"] == [{"url": "https://img.cloudy.nyc/p/b.mp4", "sync_loop": "4"}]


def test_split_new_row_inherits_the_source_row_size(three_clip_post):
    data = _three()
    res = _split(THREE_SLUG, 1, data, 1)

    blocks = res.json()["blocks"]
    assert blocks[1]["size"] == "full"
    assert blocks[2]["size"] == "full"


def test_split_preserves_neighbouring_blocks(three_clip_post):
    data = _three()
    res = _split(THREE_SLUG, 1, data, 0)

    assert res.status_code == 200
    blocks = res.json()["blocks"]
    assert blocks[0]["kind"] != "video"
    assert blocks[-1]["kind"] != "video"

    on_disk = three_clip_post.read_text(encoding="utf-8")
    assert "Intro." in on_disk
    assert "Outro." in on_disk


def test_split_from_a_two_clip_row_yields_two_single_clip_rows(temp_post):
    data = _get()
    res = _split(SLUG, 2, data, 0)

    assert res.status_code == 200
    blocks = res.json()["blocks"]
    assert _clips(blocks[2]) == ["https://img.cloudy.nyc/p/three.mp4"]
    assert _clips(blocks[3]) == ["https://img.cloudy.nyc/p/two.mp4"]


def test_split_rejects_a_single_clip_row(temp_post):
    data = _get()
    before = temp_post.read_text(encoding="utf-8")
    res = _split(SLUG, 1, data, 0)

    assert res.status_code == 400
    assert temp_post.read_text(encoding="utf-8") == before


def test_split_rejects_an_out_of_range_clip_index(three_clip_post):
    data = _three()
    before = three_clip_post.read_text(encoding="utf-8")
    res = _split(THREE_SLUG, 1, data, 3)

    assert res.status_code == 400
    assert three_clip_post.read_text(encoding="utf-8") == before


def test_split_rejects_a_stale_hash(three_clip_post):
    data = _three()
    data["hash"] = "0" * 64
    before = three_clip_post.read_text(encoding="utf-8")
    res = _split(THREE_SLUG, 1, data, 1)

    assert res.status_code == 409
    assert three_clip_post.read_text(encoding="utf-8") == before


def test_split_rejects_an_unknown_size(three_clip_post):
    data = _three()
    before = three_clip_post.read_text(encoding="utf-8")
    res = _split(THREE_SLUG, 1, data, 1, size="huge")

    assert res.status_code == 400
    assert three_clip_post.read_text(encoding="utf-8") == before


def test_split_applies_a_pending_reorder_in_the_same_write(three_clip_post):
    """The row editor only commits on Done, so a local reorder plus a split
    arrives as one request and both halves must land."""
    data = _three()
    reordered = [
        {"url": "https://img.cloudy.nyc/p/c.mp4", "sync_loop": None},
        {"url": "https://img.cloudy.nyc/p/a.mp4", "sync_loop": None},
        {"url": "https://img.cloudy.nyc/p/b.mp4", "sync_loop": "4"},
    ]
    res = _split(THREE_SLUG, 1, data, 2, videos=reordered)

    assert res.status_code == 200
    blocks = res.json()["blocks"]
    assert _clips(blocks[1]) == ["https://img.cloudy.nyc/p/c.mp4", "https://img.cloudy.nyc/p/a.mp4"]
    assert _clips(blocks[2]) == ["https://img.cloudy.nyc/p/b.mp4"]


def test_split_leaves_both_rows_losslessly_parseable(three_clip_post):
    """Both resulting rows must still round-trip through parse_videos, or the
    client silently falls back to a raw textarea for them."""
    data = _three()
    _split(THREE_SLUG, 1, data, 1)

    after = _three()
    for block in after["blocks"][1:3]:
        assert block["kind"] == "video"
        assert "videos" in block


# --- `side`: floating a row beside the text that follows it -----------------


def test_get_post_includes_the_side_for_a_video_row(temp_post):
    assert _get()["blocks"][1]["side"] == "none"


def test_replace_block_videos_sets_a_side(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "medium",
            "side": "right",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["side"] == "right"
    assert 'class="video-row size-medium beside-right"' in temp_post.read_text(encoding="utf-8")


def test_replace_block_videos_omitting_side_leaves_the_row_unfloated(temp_post):
    """Back-compat: a client that predates this feature never sends `side`,
    and must not have its rows silently floated.
    """
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "medium",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["side"] == "none"
    assert "beside-" not in temp_post.read_text(encoding="utf-8")


def test_replace_block_videos_rejects_an_unknown_side(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "medium",
            "side": "sideways",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 400


def test_replace_block_videos_rejects_a_full_width_float(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "full",
            "side": "right",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 400


def test_split_out_clip_is_never_floated(three_clip_post):
    """A float exists in relation to the text that follows that row, and a
    split-out clip is on its way somewhere else entirely -- so it lands
    unfloated while the row it left keeps its side.
    """
    three_clip_post.write_text(
        THREE_POST.replace('class="video-row size-full"', 'class="video-row size-medium beside-right"'),
        encoding="utf-8",
    )
    data = _three()
    assert data["blocks"][1]["side"] == "right"

    res = _split(THREE_SLUG, 1, data, 1)
    assert res.status_code == 200
    blocks = res.json()["blocks"]
    assert blocks[1]["side"] == "right"
    assert blocks[2]["side"] == "none"


# --- floating is just a side, nothing more ---------------------------------
# Page widths are fluid, so how much text fits beside a row isn't knowable
# when the post is written. The row picks a side and the text flows around
# it; nothing is moved and no marker is inserted.


def test_floating_a_row_moves_nothing_and_adds_nothing(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "medium",
            "side": "right",
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    out = res.json()

    assert out["blocks"][1]["side"] == "right"
    assert len(out["blocks"]) == len(data["blocks"])
    # Every other block is byte-identical and still in its original place.
    for i, before in enumerate(data["blocks"]):
        if i != 1:
            assert out["blocks"][i]["source"] == before["source"]


def test_floating_writes_no_clear_marker(temp_post):
    """Markers were how a fixed set of chosen blocks was fenced off. Choosing
    a side instead means the text simply wraps, so nothing needs fencing --
    and an invisible div appearing in the post would be unexplainable litter.
    """
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/videos",
        json={
            "videos": [{"url": "https://img.cloudy.nyc/p/one.mp4", "sync_loop": "4"}],
            "size": "medium",
            "side": "right",
            "hash": data["hash"],
        },
    )
    assert not any(b["kind"] == "clear" for b in res.json()["blocks"])
    assert "clear-beside" not in temp_post.read_text(encoding="utf-8")
