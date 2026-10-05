"""POST /api/posts/{slug}/images/place -- the Add photo button's insert.

The button uploads first (`/images/upload`, no post write) and only then
places the photos at a gap the person tapped. This route is the second half:
it takes the URLs the upload handed back, turns them into a block with the
same `markdown_for` every other photo route uses, and inserts it through
`_write_body` (hash check, history snapshot, atomic write).
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from editor import config, history
from editor.app import app
from editor.blocks import parse_blocks
from editor.frontmatter import split_post
from editor.images import is_uploaded_url

client = TestClient(app)
SLUG = "place-test-post"

POST = """+++
title = "Place Test"
date = 2026-01-01
draft = true
+++

Intro.

Middle.

Outro.
"""

A = f"https://img.cloudy.nyc/{SLUG}/0123abcd.jpg"
B = f"https://img.cloudy.nyc/{SLUG}/a-cat-on-a-wall-89abcdef.jpg"


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def temp_post(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST, encoding="utf-8")
    app.state.s3 = FakeS3()
    yield path
    path.unlink(missing_ok=True)


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


def _place(index, images, hash_=None):
    return client.post(
        f"/api/posts/{SLUG}/images/place",
        json={"index": index, "hash": hash_ or _get()["hash"], "images": images},
    )


def _blocks(path):
    return parse_blocks(split_post(path.read_text())[1])


def test_one_photo_inserts_a_standalone_image_at_the_index(temp_post):
    res = _place(1, [{"url": A, "alt": ""}])

    assert res.status_code == 200
    blocks = _blocks(temp_post)
    assert [b.source for b in blocks] == ["Intro.", f"![]({A})", "Middle.", "Outro."]
    # The payload is the post, and the new block is editable as photos --
    # the client opens its thumbnail strip straight away for the alt text.
    data = res.json()
    assert data["blocks"][1]["kind"] == "image"
    assert data["blocks"][1]["images"] == [{"url": A, "alt": ""}]
    assert data["hash"] == _get()["hash"]


def test_several_photos_insert_one_img_row(temp_post):
    res = _place(2, [{"url": A, "alt": ""}, {"url": B, "alt": "a cat"}])

    assert res.status_code == 200
    blocks = _blocks(temp_post)
    assert len(blocks) == 4
    assert blocks[2].source == (
        f'<div class="img-row">\n<img src="{A}" alt="">\n'
        f'<img src="{B}" alt="a cat">\n</div>'
    )
    assert res.json()["blocks"][2]["images"] == [
        {"url": A, "alt": ""}, {"url": B, "alt": "a cat"},
    ]


def test_index_zero_puts_it_above_the_first_block(temp_post):
    assert _place(0, [{"url": A, "alt": ""}]).status_code == 200
    assert [b.source for b in _blocks(temp_post)][:2] == [f"![]({A})", "Intro."]


def test_index_equal_to_the_block_count_appends(temp_post):
    assert _place(3, [{"url": A, "alt": ""}]).status_code == 200
    assert [b.source for b in _blocks(temp_post)][-2:] == ["Outro.", f"![]({A})"]


def test_alt_text_is_escaped_by_the_shared_markup_code(temp_post):
    _place(0, [{"url": A, "alt": "a [bracket]"}])
    assert _blocks(temp_post)[0].source == f"![a \\[bracket\\]]({A})"


def test_a_stale_hash_is_a_409_and_writes_nothing(temp_post):
    res = _place(1, [{"url": A, "alt": ""}], hash_="0" * 64)
    assert res.status_code == 409
    assert temp_post.read_text() == POST


def test_an_index_past_the_end_is_a_409_and_writes_nothing(temp_post):
    # The client's view of the gaps is stale -- same answer as every block
    # route gives a block index that no longer exists.
    assert _place(9, [{"url": A, "alt": ""}]).status_code == 409
    assert temp_post.read_text() == POST


def test_a_negative_index_is_refused(temp_post):
    assert _place(-1, [{"url": A, "alt": ""}]).status_code in (400, 422)
    assert temp_post.read_text() == POST


@pytest.mark.parametrize("url", [
    "https://evil.example/x/0123abcd.jpg",
    "http://img.cloudy.nyc/place-test-post/0123abcd.jpg",
    "https://img.cloudy.nyc.evil.example/place-test-post/0123abcd.jpg",
    # Another post's folder: not something this post's upload produced.
    "https://img.cloudy.nyc/other-post/0123abcd.jpg",
    "https://img.cloudy.nyc/place-test-post/0123abcd.png",
    "https://img.cloudy.nyc/place-test-post/0123abc.jpg",
    "https://img.cloudy.nyc/place-test-post/../x/0123abcd.jpg",
    "https://img.cloudy.nyc/place-test-post/UPPER-0123abcd.jpg",
    'https://img.cloudy.nyc/place-test-post/0123abcd.jpg" onerror="alert(1)',
    "https://img.cloudy.nyc/place-test-post/0123abcd.jpg)\n\n<script>x</script>",
    "https://img.cloudy.nyc/place-test-post/0123abcd.jpg?x=1",
    "",
])
def test_a_url_this_editor_did_not_upload_is_a_400(temp_post, url):
    res = _place(1, [{"url": A, "alt": ""}, {"url": url, "alt": ""}])
    assert res.status_code == 400
    assert temp_post.read_text() == POST


def test_an_empty_list_is_a_400(temp_post):
    assert _place(1, []).status_code == 400
    assert temp_post.read_text() == POST


def test_more_photos_than_one_upload_allows_is_a_400(temp_post):
    from editor.app import MAX_FILES

    too_many = [{"url": A, "alt": ""}] * (MAX_FILES + 1)
    assert _place(1, too_many).status_code == 400
    assert temp_post.read_text() == POST


def test_undo_takes_the_placed_photo_back_out(temp_post):
    data = _place(1, [{"url": A, "alt": ""}]).json()
    assert data["can_undo"] is True

    res = client.post(f"/api/posts/{SLUG}/undo", json={"hash": data["hash"]})
    assert res.status_code == 200
    assert temp_post.read_text() == POST


def test_an_unknown_post_is_a_404():
    res = client.post(
        "/api/posts/no-such-post/images/place",
        json={"index": 0, "hash": "x", "images": [{"url": A, "alt": ""}]},
    )
    assert res.status_code == 404


def test_it_requires_a_session(temp_post):
    anon = TestClient(app)
    res = anon.post(
        f"/api/posts/{SLUG}/images/place",
        json={"index": 0, "hash": _get()["hash"], "images": [{"url": A, "alt": ""}]},
    )
    assert res.status_code == 401
    assert temp_post.read_text() == POST


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def test_what_the_upload_route_returns_is_accepted_by_place(temp_post):
    """The round trip the button makes: whatever `/images/upload` hands back
    (empty alts, so a bare hash key, and an alt'd key too) must place."""
    up = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=[("files", ("a.png", _png(), "image/png")),
               ("files", ("b.png", _png(), "image/png"))],
        data={"alts": '["", "A long alt text that runs on well past forty characters"]'},
    )
    assert up.status_code == 200
    images = up.json()["images"]

    res = _place(3, images)
    assert res.status_code == 200
    assert res.json()["blocks"][3]["images"] == images


@pytest.mark.parametrize("alt", [
    "", "x", "a cat", "Ends in a dash after the cut -- exactly forty chars long!",
    "émoji 🙂 and ünïcode", "---", "a" * 200,
])
def test_every_key_image_key_can_make_validates(alt):
    from editor.images import image_key

    key = image_key(SLUG, alt, b"some bytes")
    assert is_uploaded_url(f"https://img.cloudy.nyc/{key}", SLUG)


# -- alt text can't break the block out ------------------------------------
# Every kind of line break becomes a space (a blank line would end the image
# paragraph or the .img-row's html block, and whatever followed would be
# markup of its own), and a backslash is escaped before the brackets so a
# trailing one can't escape the closing `]`.

BREAKS = ["\r", "\n", "\v", "\f", "\x85", " ", " "]


def _only_block(path, kind):
    blocks = _blocks(path)
    kinds = [b.kind for b in blocks]
    assert kinds.count(kind) == 1 and "html" not in kinds, kinds
    assert all("<script" not in b.html for b in blocks)
    assert all('href="javascript' not in b.html for b in blocks)
    return blocks


def test_a_script_after_line_breaks_stays_inside_one_image(temp_post):
    res = _place(1, [{"url": A, "alt": "x\r\r<script>alert(1)</script>"}])
    assert res.status_code == 200
    blocks = _only_block(temp_post, "image")
    assert len(blocks) == 4
    assert res.json()["blocks"][1]["images"][0]["url"] == A


def test_a_link_after_line_breaks_stays_inside_one_row(temp_post):
    res = _place(1, [{"url": A, "alt": "x\r\r[c](javascript:alert(1))"}, {"url": B, "alt": ""}])
    assert res.status_code == 200
    blocks = _only_block(temp_post, "img_row")
    assert len(blocks) == 4
    assert len(res.json()["blocks"][1]["images"]) == 2


@pytest.mark.parametrize("brk", BREAKS)
def test_every_line_break_becomes_a_space(temp_post, brk):
    res = _place(1, [{"url": A, "alt": f"a{brk}{brk}b"}])
    assert res.status_code == 200
    assert _blocks(temp_post)[1].source == f"![a  b]({A})"
    assert res.json()["blocks"][1]["images"] == [{"url": A, "alt": "a  b"}]


@pytest.mark.parametrize("alt", ["trailing\\", "mid\\dle", "\\[x\\]", "a\\\\b"])
def test_a_backslash_still_parses_as_an_image(temp_post, alt):
    res = _place(1, [{"url": A, "alt": alt}])
    assert res.status_code == 200
    block = res.json()["blocks"][1]
    assert block["kind"] == "image"
    assert block["images"] == [{"url": A, "alt": alt}]


def test_an_alt_over_500_characters_is_refused(temp_post):
    assert _place(1, [{"url": A, "alt": "a" * 501}]).status_code in (400, 422)
    assert temp_post.read_text() == POST
    assert _place(1, [{"url": A, "alt": "a" * 500}]).status_code == 200
