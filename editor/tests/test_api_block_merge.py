import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "merge-block-test-post"

# Block layout (index -> kind):
#   0 paragraph  "Intro."
#   1 image      one.jpg
#   2 image      solo.jpg          (standalone -- image+image merge case)
#   3 img_row    two.jpg, three.jpg
#   4 video      medium, a.mp4
#   5 video      small,  b.mp4
#   6 paragraph  "Outro."
POST = """+++
title = "Merge Block Test"
date = 2026-01-01
draft = true
+++

Intro.

![alt one](https://img.cloudy.nyc/p/one.jpg)

![alt solo](https://img.cloudy.nyc/p/solo.jpg)

<div class="img-row">
<img src="https://img.cloudy.nyc/p/two.jpg" alt="two">
<img src="https://img.cloudy.nyc/p/three.jpg" alt="three">
</div>

<div class="video-row size-medium">
<video autoplay loop muted playsinline data-sync-loop="4">
<source src="https://img.cloudy.nyc/p/a.mp4" type="video/mp4">
</video>
</div>

<div class="video-row size-small">
<video autoplay loop muted playsinline>
<source src="https://img.cloudy.nyc/p/b.mp4" type="video/mp4">
</video>
</div>

Outro.
"""


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


def _merge(index, hash_):
    return client.post(
        f"/api/posts/{SLUG}/blocks/{index}/merge",
        json={"hash": hash_},
    )


# -- happy paths --------------------------------------------------------


def test_merge_two_standalone_images_becomes_img_row(temp_post):
    data = _get()
    res = _merge(1, data["hash"])
    assert res.status_code == 200
    out = res.json()

    assert len(out["blocks"]) == len(data["blocks"]) - 1
    merged = out["blocks"][1]
    assert merged["kind"] == "img_row"
    assert merged["images"] == [
        {"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"},
        {"url": "https://img.cloudy.nyc/p/solo.jpg", "alt": "alt solo"},
    ]

    on_disk = temp_post.read_text(encoding="utf-8")
    assert "one.jpg" in on_disk and "solo.jpg" in on_disk


def test_merge_image_with_img_row(temp_post):
    data = _get()
    # After the previous merge would shift indices; here we merge the
    # original index-2 (solo.jpg image) with index-3 (two/three img_row)
    # directly against the freshly loaded, unmerged post.
    res = _merge(2, data["hash"])
    assert res.status_code == 200
    merged = res.json()["blocks"][2]
    assert merged["kind"] == "img_row"
    # Order preserved: the upper block's item(s) first, then the lower's.
    assert merged["images"] == [
        {"url": "https://img.cloudy.nyc/p/solo.jpg", "alt": "alt solo"},
        {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
        {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
    ]


def test_merge_preserves_neighbouring_blocks(temp_post):
    data = _get()
    out = _merge(1, data["hash"]).json()
    assert out["blocks"][0]["source"] == data["blocks"][0]["source"]
    # Everything after the merged pair shifts down by one position but is
    # otherwise byte-identical.
    assert out["blocks"][2]["source"] == data["blocks"][3]["source"]
    assert out["blocks"][3]["source"] == data["blocks"][4]["source"]
    assert out["blocks"][4]["source"] == data["blocks"][5]["source"]
    assert out["blocks"][5]["source"] == data["blocks"][6]["source"]


def test_merge_two_video_rows_keeps_upper_size_and_order(temp_post):
    data = _get()
    res = _merge(4, data["hash"])
    assert res.status_code == 200
    out = res.json()

    assert len(out["blocks"]) == len(data["blocks"]) - 1
    merged = out["blocks"][4]
    assert merged["kind"] == "video"
    # Upper row (index 4) was "medium"; lower (index 5) was "small". Merge
    # keeps the UPPER row's size.
    assert merged["size"] == "medium"
    assert merged["videos"] == [
        {"url": "https://img.cloudy.nyc/p/a.mp4", "sync_loop": "4"},
        {"url": "https://img.cloudy.nyc/p/b.mp4", "sync_loop": None},
    ]

    on_disk = temp_post.read_text(encoding="utf-8")
    assert "a.mp4" in on_disk and "b.mp4" in on_disk


# -- refusals -------------------------------------------------------------


def test_merge_incompatible_family_photo_and_video_is_refused(temp_post):
    data = _get()
    # index 3 is the img_row, index 4 is a video row directly below it.
    res = _merge(3, data["hash"])
    assert res.status_code in (400, 409)
    assert temp_post.read_text(encoding="utf-8") == POST


def test_merge_no_block_below_is_refused(temp_post):
    data = _get()
    last_index = len(data["blocks"]) - 1
    res = _merge(last_index, data["hash"])
    assert res.status_code in (400, 404, 409)
    assert temp_post.read_text(encoding="utf-8") == POST


def test_merge_out_of_range_index_returns_409(temp_post):
    data = _get()
    res = _merge(99, data["hash"])
    assert res.status_code == 409
    assert temp_post.read_text(encoding="utf-8") == POST


def test_merge_stale_hash_is_refused(temp_post):
    data = _get()
    temp_post.write_text(POST.replace("Intro.", "Changed elsewhere."), encoding="utf-8")

    res = _merge(1, data["hash"])
    assert res.status_code == 409
    assert "Changed elsewhere." in temp_post.read_text(encoding="utf-8")


def test_merge_refuses_when_lower_block_is_unparseable(temp_post):
    # Second video row is missing its size class -- videos.parse_videos
    # can't losslessly round-trip it, so merging into it must refuse rather
    # than silently drop whatever's really in there.
    malformed = POST.replace(
        '<div class="video-row size-small">\n'
        '<video autoplay loop muted playsinline>\n'
        '<source src="https://img.cloudy.nyc/p/b.mp4" type="video/mp4">\n'
        "</video>\n"
        "</div>",
        '<div class="video-row">\n'
        '<video autoplay loop muted playsinline>\n'
        '<source src="https://img.cloudy.nyc/p/b.mp4" type="video/mp4">\n'
        "</video>\n"
        "</div>",
    )
    assert malformed != POST
    temp_post.write_text(malformed, encoding="utf-8")

    data = _get()
    res = _merge(4, data["hash"])
    assert res.status_code in (400, 409)
    assert temp_post.read_text(encoding="utf-8") == malformed


def test_merge_refuses_when_upper_block_is_unparseable(temp_post):
    malformed = POST.replace(
        '<div class="video-row size-medium">\n'
        '<video autoplay loop muted playsinline data-sync-loop="4">\n'
        '<source src="https://img.cloudy.nyc/p/a.mp4" type="video/mp4">\n'
        "</video>\n"
        "</div>",
        '<div class="video-row">\n'
        '<video autoplay loop muted playsinline data-sync-loop="4">\n'
        '<source src="https://img.cloudy.nyc/p/a.mp4" type="video/mp4">\n'
        "</video>\n"
        "</div>",
    )
    assert malformed != POST
    temp_post.write_text(malformed, encoding="utf-8")

    data = _get()
    res = _merge(4, data["hash"])
    assert res.status_code in (400, 409)
    assert temp_post.read_text(encoding="utf-8") == malformed


# -- document-boundary cases ------------------------------------------------
#
# Every fixture above has a trailing "Outro." paragraph, so every merge so
# far has been mid-document -- delete_block's trailing-blank absorption
# always had something after the deleted block to absorb into. Two edge
# cases were only hand-traced, not covered by name: merging the literal last
# two blocks of a document (nothing after to absorb a separator from), and a
# post that's nothing but the two blocks being merged (nothing before OR
# after). This project has twice shipped a bug that only a from-scratch
# fixture caught (parse_blocks eating a list's trailing separator,
# join_post reformatting a body with no blank line after frontmatter), so
# these get named tests rather than trusting the trace.

LAST_PAIR_SLUG = "merge-block-last-pair-test-post"

POST_LAST_PAIR = """+++
title = "Merge Last Pair Test"
date = 2026-01-01
draft = true
+++

Intro.

<div class="video-row size-medium">
<video autoplay loop muted playsinline data-sync-loop="4">
<source src="https://img.cloudy.nyc/p/a.mp4" type="video/mp4">
</video>
</div>

<div class="video-row size-small">
<video autoplay loop muted playsinline>
<source src="https://img.cloudy.nyc/p/b.mp4" type="video/mp4">
</video>
</div>
"""


@pytest.fixture
def last_pair_post():
    path = config.BLOG_DIR / f"{LAST_PAIR_SLUG}.md"
    path.write_text(POST_LAST_PAIR, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def test_merge_final_two_blocks_of_a_document(last_pair_post):
    data = client.get(f"/api/posts/{LAST_PAIR_SLUG}").json()
    assert len(data["blocks"]) == 3  # Intro. paragraph, then the two rows.

    res = client.post(
        f"/api/posts/{LAST_PAIR_SLUG}/blocks/1/merge",
        json={"hash": data["hash"]},
    )
    assert res.status_code == 200
    out = res.json()

    assert len(out["blocks"]) == 2
    merged = out["blocks"][1]
    assert merged["kind"] == "video"
    assert merged["size"] == "medium"  # upper row's preset, per the rule
    assert [v["url"] for v in merged["videos"]] == [
        "https://img.cloudy.nyc/p/a.mp4",
        "https://img.cloudy.nyc/p/b.mp4",
    ]

    # Reparse independently -- a fresh GET against the bytes actually on
    # disk, not just the merge response -- so a well-formed *response* with
    # a malformed file underneath it can't slip through.
    reloaded = client.get(f"/api/posts/{LAST_PAIR_SLUG}").json()
    assert len(reloaded["blocks"]) == 2
    assert reloaded["blocks"][1]["videos"] == merged["videos"]

    on_disk = last_pair_post.read_text(encoding="utf-8")
    assert on_disk.count('<div class="video-row') == 1
    assert not on_disk.rstrip("\n").endswith("\n\n")  # no stray trailing blank


TWO_BLOCK_ONLY_SLUG = "merge-block-two-block-only-test-post"

POST_TWO_BLOCKS_ONLY = """+++
title = "Merge Two Block Only Test"
date = 2026-01-01
draft = true
+++

![alt one](https://img.cloudy.nyc/p/one.jpg)

![alt two](https://img.cloudy.nyc/p/two.jpg)
"""


@pytest.fixture
def two_block_only_post():
    path = config.BLOG_DIR / f"{TWO_BLOCK_ONLY_SLUG}.md"
    path.write_text(POST_TWO_BLOCKS_ONLY, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def test_merge_a_post_consisting_of_exactly_two_blocks(two_block_only_post):
    # Nothing before, nothing after -- the whole body is the pair being
    # merged, so the result must be a single well-formed block, not an
    # empty file or a stray separator either side.
    data = client.get(f"/api/posts/{TWO_BLOCK_ONLY_SLUG}").json()
    assert len(data["blocks"]) == 2

    res = client.post(
        f"/api/posts/{TWO_BLOCK_ONLY_SLUG}/blocks/0/merge",
        json={"hash": data["hash"]},
    )
    assert res.status_code == 200
    out = res.json()

    assert len(out["blocks"]) == 1
    assert out["blocks"][0]["kind"] == "img_row"
    assert out["blocks"][0]["images"] == [
        {"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"},
        {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "alt two"},
    ]

    # Independent reparse of the bytes on disk, same discipline as above.
    reloaded = client.get(f"/api/posts/{TWO_BLOCK_ONLY_SLUG}").json()
    assert len(reloaded["blocks"]) == 1
    assert reloaded["blocks"][0]["images"] == out["blocks"][0]["images"]
