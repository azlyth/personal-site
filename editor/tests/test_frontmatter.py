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
