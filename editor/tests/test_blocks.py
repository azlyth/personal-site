import pytest

from editor.blocks import (
    Block,
    parse_blocks,
    replace_block,
    insert_block,
    delete_block,
)

SIMPLE = "First para.\n\n## A heading\n\nSecond para.\n"

IMAGES = (
    "Intro.\n"
    "\n"
    "![alt text](https://img.cloudy.nyc/p/one.jpg)\n"
    "\n"
    '<div class="img-row">\n'
    '<img src="https://img.cloudy.nyc/p/two.jpg" alt="two">\n'
    '<img src="https://img.cloudy.nyc/p/three.jpg" alt="three">\n'
    "</div>\n"
    "\n"
    "Outro.\n"
)


def test_parse_splits_top_level_blocks():
    blocks = parse_blocks(SIMPLE)
    assert [b.kind for b in blocks] == ["paragraph", "heading", "paragraph"]
    assert [b.index for b in blocks] == [0, 1, 2]


def test_parse_captures_raw_source_not_html():
    blocks = parse_blocks(SIMPLE)
    assert blocks[1].source == "## A heading"
    assert "<h2" in blocks[1].html


def test_parse_classifies_image_and_img_row():
    blocks = parse_blocks(IMAGES)
    kinds = [b.kind for b in blocks]
    assert kinds == ["paragraph", "image", "img_row", "paragraph"]


def test_replace_with_identical_source_is_byte_identical():
    # The load-bearing property: a no-op edit must not perturb the file.
    for body in (SIMPLE, IMAGES):
        for block in parse_blocks(body):
            assert replace_block(body, block.index, block.source) == body


def test_replace_changes_only_the_target_block():
    out = replace_block(SIMPLE, 0, "Rewritten.")
    assert out == "Rewritten.\n\n## A heading\n\nSecond para.\n"


def test_replace_accepts_multiline_replacement():
    out = replace_block(SIMPLE, 0, "Line one.\nLine two.")
    assert out == "Line one.\nLine two.\n\n## A heading\n\nSecond para.\n"
    assert [b.kind for b in parse_blocks(out)] == ["paragraph", "heading", "paragraph"]


def test_insert_before_index():
    out = insert_block(SIMPLE, 1, "Inserted.")
    assert out == "First para.\n\nInserted.\n\n## A heading\n\nSecond para.\n"


def test_insert_at_end_appends():
    out = insert_block(SIMPLE, 3, "Appended.")
    assert out == "First para.\n\n## A heading\n\nSecond para.\n\nAppended.\n"


def test_delete_removes_block_and_its_separator():
    out = delete_block(SIMPLE, 1)
    assert out == "First para.\n\nSecond para.\n"


def test_body_without_trailing_newline_round_trips():
    body = "Only para."
    blocks = parse_blocks(body)
    assert replace_block(body, 0, blocks[0].source) == body


def test_index_out_of_range_raises():
    with pytest.raises(IndexError):
        replace_block(SIMPLE, 99, "nope")
