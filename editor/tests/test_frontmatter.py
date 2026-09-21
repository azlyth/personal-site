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


def test_split_separates_frontmatter_and_body():
    fm, body = split_post(POST)
    assert 'title = "Guerrilla Gardening"' in fm
    assert body == "Body starts here.\n"


def test_join_is_the_inverse_of_split():
    fm, body = split_post(POST)
    assert join_post(fm, body) == POST


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
