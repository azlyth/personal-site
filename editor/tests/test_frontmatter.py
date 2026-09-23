import datetime

import pytest

from editor.frontmatter import split_post, join_post, read_meta, set_meta

POST = (
    "+++\n"
    'title = "Guerrilla Gardening"\n'
    "date = 2026-09-20\n"
    "draft = false\n"
    "+++\n"
    "\n"
    "Body starts here.\n"
)

# Older posts in this repo have no blank line between the closing +++ and
# the body's first line. split_post/join_post must preserve that style
# byte-for-byte too, not normalise it to the blank-line style.
POST_NO_BLANK_LINE = (
    "+++\n"
    'title = "No Blank Line"\n'
    "date = 2016-11-24\n"
    "draft = false\n"
    "+++\n"
    "Body starts immediately.\n"
)

# A multi-line TOML string in the frontmatter that contains a line starting
# with "+++". A bare substring search for "\n+++" would treat that line as
# the closing delimiter and truncate the frontmatter early; the real
# terminator must be a line that is exactly "+++" and nothing else.
POST_WITH_PLUSSES_IN_FRONTMATTER_STRING = (
    "+++\n"
    'title = """\n'
    "+++ inside a string, not a delimiter\n"
    '"""\n'
    "date = 2026-09-20\n"
    "+++\n"
    "\n"
    "Body.\n"
)

# A "+++" line inside a fenced code block in the body. The real terminator
# comes first, so this must not affect where the split happens.
POST_WITH_PLUSSES_IN_BODY_CODE_BLOCK = (
    "+++\n"
    'title = "x"\n'
    "+++\n"
    "\n"
    "```\n"
    "+++\n"
    "```\n"
)


def test_split_separates_frontmatter_and_body():
    fm, body = split_post(POST)
    assert 'title = "Guerrilla Gardening"' in fm
    assert body == "\nBody starts here.\n"


def test_split_preserves_no_blank_line_style():
    fm, body = split_post(POST_NO_BLANK_LINE)
    assert 'title = "No Blank Line"' in fm
    assert body == "Body starts immediately.\n"


def test_join_is_the_inverse_of_split():
    fm, body = split_post(POST)
    assert join_post(fm, body) == POST


def test_join_is_the_inverse_of_split_no_blank_line():
    fm, body = split_post(POST_NO_BLANK_LINE)
    assert join_post(fm, body) == POST_NO_BLANK_LINE


@pytest.mark.parametrize("text", [POST, POST_NO_BLANK_LINE])
def test_round_trip_is_byte_exact_for_both_separator_styles(text):
    fm, body = split_post(text)
    assert join_post(fm, body) == text


def test_read_meta_returns_values():
    fm, _ = split_post(POST)
    meta = read_meta(fm)
    assert meta["title"] == "Guerrilla Gardening"
    assert meta["draft"] is False
    assert meta["date"] == datetime.date(2026, 9, 20)


def test_set_meta_changes_only_the_target_field():
    fm, _ = split_post(POST)
    out = set_meta(fm, "title", "A New Title")
    assert 'title = "A New Title"' in out
    assert "date = 2026-09-20" in out
    assert "draft = false" in out


def test_set_meta_preserves_field_order():
    fm, _ = split_post(POST)
    out = set_meta(fm, "draft", True)
    assert out.index("title") < out.index("date") < out.index("draft")


def test_missing_delimiters_raises():
    with pytest.raises(ValueError):
        split_post("no frontmatter here\n")


def test_unterminated_frontmatter_raises():
    with pytest.raises(ValueError):
        split_post('+++\ntitle = "x"\n')


def test_bare_opening_delimiter_with_no_newline_raises():
    # Degenerate case of the same "unterminated" branch: the file is
    # exactly "+++" with nothing after it at all, not even a newline.
    with pytest.raises(ValueError):
        split_post("+++")


def test_plusses_inside_frontmatter_string_do_not_terminate_early():
    fm, body = split_post(POST_WITH_PLUSSES_IN_FRONTMATTER_STRING)
    assert '+++ inside a string, not a delimiter' in fm
    assert 'date = 2026-09-20' in fm
    assert body == "\nBody.\n"
    assert join_post(fm, body) == POST_WITH_PLUSSES_IN_FRONTMATTER_STRING


def test_plusses_inside_body_code_block_do_not_affect_split():
    fm, body = split_post(POST_WITH_PLUSSES_IN_BODY_CODE_BLOCK)
    assert fm == 'title = "x"'
    assert body == "\n```\n+++\n```\n"
    assert join_post(fm, body) == POST_WITH_PLUSSES_IN_BODY_CODE_BLOCK


# --- [extra] ------------------------------------------------------------
#
# `extra.preview_image` -- the photo the editor's star button pins as a
# post's link preview -- is the first nested value the editor writes, so
# these cover the table-creation cases `set_meta` never had to.

POST_WITH_EXTRA = (
    "+++\n"
    'title = "Has Extra"\n'
    "date = 2026-09-22\n"
    "draft = false\n"
    "\n"
    "[extra]\n"
    'preview_image = "https://img.cloudy.nyc/a/one.jpg"\n'
    "+++\n"
    "\n"
    "Body.\n"
)


def test_set_extra_creates_the_table_when_there_is_none():
    from editor.frontmatter import set_extra

    out = set_extra(split_post(POST)[0], "preview_image", "https://img/x.jpg")

    assert read_meta(out)["extra"]["preview_image"] == "https://img/x.jpg"
    assert read_meta(out)["title"] == "Guerrilla Gardening"


def test_set_extra_replaces_an_existing_value():
    from editor.frontmatter import set_extra

    out = set_extra(split_post(POST_WITH_EXTRA)[0], "preview_image", "https://img/two.jpg")

    assert read_meta(out)["extra"]["preview_image"] == "https://img/two.jpg"


def test_clear_extra_removes_the_key():
    from editor.frontmatter import clear_extra

    out = clear_extra(split_post(POST_WITH_EXTRA)[0], "preview_image")

    # And the table itself, now that it holds nothing -- an empty `[extra]`
    # left behind is noise in every future diff of the post.
    assert "extra" not in read_meta(out)
    assert read_meta(out)["title"] == "Has Extra"


def test_clear_extra_is_a_no_op_when_there_is_no_table():
    from editor.frontmatter import clear_extra

    out = clear_extra(split_post(POST)[0], "preview_image")

    assert read_meta(out)["title"] == "Guerrilla Gardening"


def test_a_top_level_key_set_after_extra_exists_stays_top_level():
    """The trap TOML tables set for anything that appends.

    Once `[extra]` is in the document, a naively appended `draft = true`
    lands INSIDE it -- Zola then sees no draft flag at all and publishes a
    post that was meant to stay hidden. scripts/build-site.sh documents the
    same hazard for its generated feed keys.
    """
    from editor.frontmatter import set_extra

    out = set_extra(split_post(POST)[0], "preview_image", "https://img/x.jpg")
    out = set_meta(out, "draft", True)

    meta = read_meta(out)
    assert meta["draft"] is True
    assert "draft" not in meta["extra"]
