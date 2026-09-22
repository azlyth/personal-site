import io

import pytest
from PIL import Image

from editor import config
from editor.images import process_image, image_key, markdown_for, parse_images, upload


def _jpeg_with_exif(size=(2400, 1800)) -> bytes:
    img = Image.new("RGB", size, (120, 140, 90))
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"   # Make
    exif[0x8825] = {}             # GPSInfo slot
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_process_strips_exif():
    out = process_image(_jpeg_with_exif())
    assert dict(Image.open(io.BytesIO(out)).getexif()) == {}


def test_process_caps_longest_edge():
    out = process_image(_jpeg_with_exif((2400, 1800)), max_edge=1600)
    assert max(Image.open(io.BytesIO(out)).size) == 1600


def test_process_leaves_small_images_alone():
    small = _jpeg_with_exif((400, 300))
    out = process_image(small, max_edge=1600)
    assert Image.open(io.BytesIO(out)).size == (400, 300)


def test_key_is_descriptive_and_content_addressed():
    data = _jpeg_with_exif()
    key = image_key("guerilla-gardening", "Brick Border!", data)
    assert key.startswith("guerilla-gardening/brick-border-")
    assert key.endswith(".jpg")


def test_same_bytes_produce_the_same_key():
    data = _jpeg_with_exif()
    assert image_key("p", "a", data) == image_key("p", "a", data)


def test_key_without_alt_text_still_works():
    key = image_key("p", "", _jpeg_with_exif())
    assert key.startswith("p/")
    assert key.endswith(".jpg")


def test_single_image_renders_standalone():
    out = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a cat"])
    assert out == "![a cat](https://img.cloudy.nyc/p/a.jpg)"


def test_single_image_default_size_stays_plain_markdown():
    # Sizing is opt-in: a lone photo at the default preset never becomes a
    # wrapped div, so untouched posts round-trip byte-for-byte.
    out = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a cat"], "full")
    assert out == "![a cat](https://img.cloudy.nyc/p/a.jpg)"


def test_single_image_non_default_size_wraps_in_img_row():
    # Only a non-default choice promotes a standalone image to the div shape
    # -- that's the only way it can carry a size class at all.
    out = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a cat"], "small")
    assert out == (
        '<div class="img-row size-small">\n'
        '<img src="https://img.cloudy.nyc/p/a.jpg" alt="a cat">\n'
        "</div>"
    )


def test_multiple_images_render_as_img_row():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["a", "b"],
    )
    assert out.startswith('<div class="img-row">')
    assert out.rstrip().endswith("</div>")
    assert out.count("<img ") == 2


def test_multiple_images_default_size_has_no_size_class():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["a", "b"],
        "full",
    )
    assert out.startswith('<div class="img-row">')
    assert "size-" not in out.splitlines()[0]


def test_multiple_images_non_default_size_includes_class():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["a", "b"],
        "medium",
    )
    assert out.startswith('<div class="img-row size-medium">')


def test_markdown_for_rejects_unknown_size():
    with pytest.raises(ValueError):
        markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a"], "huge")


def test_single_image_alt_with_bracket_does_not_break_the_link():
    out = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a photo of [me]"])
    assert out == "![a photo of \\[me\\]](https://img.cloudy.nyc/p/a.jpg)"


def test_img_row_alt_with_quote_does_not_break_the_tag():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ['the 30" monitor', "b"],
    )
    line = [l for l in out.splitlines() if l.startswith("<img ")][0]
    assert line.count('alt="') == 1
    assert line.endswith('">')
    assert 'alt="the 30&quot; monitor"' in line


def test_img_row_alt_with_lt_and_amp_is_escaped():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["A & B < C", "b"],
    )
    line = [l for l in out.splitlines() if l.startswith("<img ")][0]
    assert "&amp;" in line
    assert "&lt;" in line
    assert line.count('alt="') == 1
    assert line.endswith('">')


def test_single_image_alt_with_newline_is_collapsed():
    out = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["line one\nline two"])
    assert "\n" not in out
    assert out == "![line one line two](https://img.cloudy.nyc/p/a.jpg)"


def test_img_row_alt_with_newline_is_collapsed():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["line one\nline two", "b"],
    )
    line = [l for l in out.splitlines() if l.startswith("<img ")][0]
    assert "\n" not in line
    assert 'alt="line one line two"' in line


def test_markdown_for_raises_on_length_mismatch():
    with pytest.raises(ValueError, match=r"2.*1|1.*2"):
        markdown_for(
            ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
            ["only one alt"],
        )


def test_parse_images_single_markdown_image():
    out = parse_images("image", "![a cat](https://img.cloudy.nyc/p/a.jpg)")
    assert out == {
        "size": "full",
        "images": [{"url": "https://img.cloudy.nyc/p/a.jpg", "alt": "a cat"}],
    }


def test_parse_images_img_row_multiple():
    source = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg", "https://img.cloudy.nyc/p/c.jpg"],
        ["a", "b", "c"],
    )
    out = parse_images("img_row", source)
    assert out == {
        "size": "full",
        "images": [
            {"url": "https://img.cloudy.nyc/p/a.jpg", "alt": "a"},
            {"url": "https://img.cloudy.nyc/p/b.jpg", "alt": "b"},
            {"url": "https://img.cloudy.nyc/p/c.jpg", "alt": "c"},
        ],
    }


def test_parse_images_round_trips_escaped_markdown_alt():
    # markdown_for escapes `[`/`]` in a standalone image's alt text; parsing
    # it back out must undo that, not leave the backslashes in.
    source = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a photo of [me]"])
    out = parse_images("image", source)
    assert out == {
        "size": "full",
        "images": [{"url": "https://img.cloudy.nyc/p/a.jpg", "alt": "a photo of [me]"}],
    }


def test_parse_images_img_row_round_trips_html_escaped_alt():
    source = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ['the 30" monitor & more <thing>', "b"],
    )
    out = parse_images("img_row", source)
    assert out["images"][0] == {"url": "https://img.cloudy.nyc/p/a.jpg", "alt": 'the 30" monitor & more <thing>'}
    assert out["images"][1] == {"url": "https://img.cloudy.nyc/p/b.jpg", "alt": "b"}


def test_parse_images_img_row_parses_size_class():
    source = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["a", "b"],
        "small",
    )
    out = parse_images("img_row", source)
    assert out["size"] == "small"
    assert out["images"] == [
        {"url": "https://img.cloudy.nyc/p/a.jpg", "alt": "a"},
        {"url": "https://img.cloudy.nyc/p/b.jpg", "alt": "b"},
    ]


def test_parse_images_img_row_without_size_class_defaults_to_full():
    # Existing published posts have plain `<div class="img-row">` with no
    # size class at all -- this must still parse (and round-trip) rather
    # than falling back to raw-source editing just because it predates the
    # size feature.
    source = (
        '<div class="img-row">\n'
        '<img src="https://img.cloudy.nyc/p/a.jpg" alt="a">\n'
        '<img src="https://img.cloudy.nyc/p/b.jpg" alt="b">\n'
        "</div>"
    )
    out = parse_images("img_row", source)
    assert out == {
        "size": "full",
        "images": [
            {"url": "https://img.cloudy.nyc/p/a.jpg", "alt": "a"},
            {"url": "https://img.cloudy.nyc/p/b.jpg", "alt": "b"},
        ],
    }


def test_parse_images_single_sized_image_round_trips_as_img_row():
    # The wrinkle: picking a non-default size for a lone photo promotes it
    # to the wrapped div shape (blocks.py then classifies it img_row, not
    # image) -- parse_images has to round-trip that shape too.
    source = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a cat"], "small")
    out = parse_images("img_row", source)
    assert out == {
        "size": "small",
        "images": [{"url": "https://img.cloudy.nyc/p/a.jpg", "alt": "a cat"}],
    }


def test_parse_images_malformed_or_unparseable_block_returns_none():
    # None, not [] -- an img_row block that fails to round-trip must not be
    # mistaken for a photo list with zero photos (see the img-row-with-no-
    # matching-tags test below for why that distinction is load-bearing).
    assert parse_images("image", "not an image at all") is None
    assert parse_images("image", "") is None
    assert parse_images("img_row", '<div class="img-row">nothing here</div>') is None
    assert parse_images("img_row", "") is None


def test_parse_images_unknown_kind_returns_none():
    assert parse_images("paragraph", "Some text.") is None


# --- Losslessness: parse_images must refuse anything it can't reproduce
# byte-for-byte via markdown_for, rather than silently returning a reduced
# list. A regex extension can never enumerate every hand-editable shape, so
# the check has to be generic: regenerate and compare, not pattern-match
# harder. Each case below is something the naive tag regex used to accept
# a *subset* of matches for -- which is worse than rejecting outright,
# because the client would show a photo editor with the wrong photos and
# Done would happily delete the ones that didn't parse.


def test_parse_images_img_without_alt_is_not_lossless():
    source = (
        '<div class="img-row">\n'
        '<img src="https://img.cloudy.nyc/p/a.jpg">\n'
        '<img src="https://img.cloudy.nyc/p/b.jpg" alt="b">\n'
        "</div>"
    )
    assert parse_images("img_row", source) is None


def test_parse_images_single_quoted_attrs_is_not_lossless():
    source = (
        '<div class="img-row">\n'
        "<img src='https://img.cloudy.nyc/p/a.jpg' alt='a'>\n"
        '<img src="https://img.cloudy.nyc/p/b.jpg" alt="b">\n'
        "</div>"
    )
    assert parse_images("img_row", source) is None


def test_parse_images_extra_wrapper_inside_img_row_is_not_lossless():
    # Both <img> tags parse fine on their own, but there's a third element
    # in the row (e.g. a caption) that a regenerated .img-row wouldn't
    # reproduce -- the mismatch has to catch this even though every <img>
    # tag matched individually.
    source = (
        '<div class="img-row">\n'
        '<div class="caption">Some caption</div>\n'
        '<img src="https://img.cloudy.nyc/p/a.jpg" alt="a">\n'
        '<img src="https://img.cloudy.nyc/p/b.jpg" alt="b">\n'
        "</div>"
    )
    assert parse_images("img_row", source) is None


def test_parse_images_img_row_with_no_matching_tags_returns_none_not_empty_list():
    # The critical case: every <img> in the row fails to match (e.g. a
    # `data-src` typo), so the naive parser found zero images -- but the
    # block is still classified img_row. Returning [] here would make an
    # already-populated photo row look like an intentionally empty one, and
    # the client's Done button deletes an "empty" block outright.
    source = '<div class="img-row">\n<img data-src="https://img.cloudy.nyc/p/a.jpg" alt="a">\n</div>'
    assert parse_images("img_row", source) is None


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_upload_sets_immutable_cache_headers():
    client = FakeS3()
    url = upload(b"bytes", "p/a.jpg", "img.cloudy.nyc", client)

    call = client.calls[0]
    assert call["Bucket"] == "img.cloudy.nyc"
    assert call["Key"] == "p/a.jpg"
    assert call["ContentType"] == "image/jpeg"
    assert call["CacheControl"] == "public, max-age=31536000, immutable"
    assert url == "https://img.cloudy.nyc/p/a.jpg"


def test_cli_upload_path_shares_the_content_addressed_key():
    """scripts/upload-image.py used to build its own `<slug>/<name>.jpg` key
    with no content hash, while still setting an immutable Cache-Control --
    re-uploading a corrected photo under the same name reused the URL, so
    Cloudflare's edge and every browser kept serving the old bytes forever.
    It must go through `image_key`, the same as the tablet editor."""
    script = (config.REPO / "scripts" / "upload-image.py").read_text(encoding="utf-8")

    assert "image_key(" in script, "upload-image.py must use the shared content-addressed key"
    assert "f\"{post_slug}/{name}.jpg\"" not in script, "upload-image.py still builds an unhashed key"
