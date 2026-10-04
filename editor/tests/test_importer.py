"""importer.convert: Platen text -> (title, block-split markdown body).

Every fixture's body is also run through blocks.parse_blocks, the editor's
own block model, so these prove the post really arrives as separate heading
and paragraph blocks -- not just that the string looks right.
"""
import pytest

from editor.blocks import parse_blocks
from editor.importer import EmptyImport, convert


def kinds(body: str) -> list[str]:
    return [b.kind for b in parse_blocks(body)]


def test_first_h1_is_the_title_and_leaves_the_body():
    title, body = convert("# Spruce, the tracker\n\n## tldr\n\nIt cleans.\n", "2026-09-15 2252")
    assert title == "Spruce, the tracker"
    assert body == "## tldr\n\nIt cleans.\n"
    assert kinds(body) == ["heading", "paragraph"]


def test_no_h1_falls_back_to_the_doc_name():
    title, body = convert("Just a paragraph.\n", "2026-09-15 2252.md")
    assert title == "2026-09-15 2252"
    assert body == "Just a paragraph.\n"


def test_h1_not_on_the_first_line_is_demoted_not_taken_as_title():
    title, body = convert("Intro.\n\n# Later\n\nMore.\n", "doc")
    assert title == "doc"
    assert body == "Intro.\n\n## Later\n\nMore.\n"
    assert kinds(body) == ["paragraph", "heading", "paragraph"]


def test_leading_blank_lines_before_the_title_are_ignored():
    title, _ = convert("\n\n# Title\n\nBody.\n", "doc")
    assert title == "Title"


def test_single_line_breaks_become_separate_paragraphs():
    _, body = convert("# T\n\nOne.\nTwo.\nThree.\n", "doc")
    assert body == "One.\n\nTwo.\n\nThree.\n"
    assert kinds(body) == ["paragraph", "paragraph", "paragraph"]


def test_runs_of_blank_lines_collapse_to_one():
    _, body = convert("# T\n\n\n\nOne.\n\n\n\n\nTwo.\n\n\n", "doc")
    assert body == "One.\n\nTwo.\n"


def test_crlf_and_trailing_spaces_are_normalized():
    _, body = convert("# T\r\n\r\nOne.   \r\nTwo.\t\r\n", "doc")
    assert body == "One.\n\nTwo.\n"


def test_leading_indent_does_not_make_a_code_block():
    _, body = convert("# T\n\n    Indented four.\n\tTabbed.\n", "doc")
    assert body == "Indented four.\n\nTabbed.\n"
    assert kinds(body) == ["paragraph", "paragraph"]


def test_lower_headings_pass_through():
    _, body = convert("# T\n\n## Two\n\n### Three\n\nText.\n", "doc")
    assert body == "## Two\n\n### Three\n\nText.\n"
    assert kinds(body) == ["heading", "heading", "paragraph"]


def test_heading_directly_followed_by_text_splits():
    _, body = convert("# T\n\n## Head\nText right under it.\n", "doc")
    assert kinds(body) == ["heading", "paragraph"]


def test_inline_markup_is_untouched():
    _, body = convert("# T\n\nSome **bold**, *em*, _em_ and `code`.\n", "doc")
    assert body == "Some **bold**, *em*, _em_ and `code`.\n"


def test_hash_without_space_is_not_a_heading():
    _, body = convert("# T\n\n#hashtag stays text.\n", "doc")
    assert body == "#hashtag stays text.\n"


def test_blank_heading_line_is_dropped_not_demoted():
    _, body = convert("# T\n\n#\n\nText.\n", "doc")
    assert body == "Text.\n"
    assert kinds(body) == ["paragraph"]


def test_title_only_is_rejected():
    with pytest.raises(EmptyImport):
        convert("# Only a title\n\n\n", "doc")


def test_blank_doc_is_rejected():
    with pytest.raises(EmptyImport):
        convert("  \n\n", "doc")


def test_peters_real_doc_shape():
    text = (
        "# Spruce, the litter cleaning tracker\n\n## tldr\n\nA short summary.\n\n"
        "## NYC means garbage for many\n\nFirst para.\n\nSecond para.\n"
    )
    title, body = convert(text, "2026-09-15 2252")
    assert title == "Spruce, the litter cleaning tracker"
    assert kinds(body) == ["heading", "paragraph", "heading", "paragraph", "paragraph"]
