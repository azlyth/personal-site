import re

import pytest

from editor.blocks import (
    Block,
    parse_blocks,
    replace_block,
    insert_block,
    delete_block,
    move_block,
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

VIDEOS = (
    "Intro.\n"
    "\n"
    '<div class="video-row size-medium">\n'
    '<video autoplay loop muted playsinline data-sync-loop="4">\n'
    '<source src="https://img.cloudy.nyc/p/one.mp4" type="video/mp4">\n'
    "</video>\n"
    "</div>\n"
    "\n"
    "Outro.\n"
)

# Covers the four kinds IMAGES/SIMPLE never exercise: list, blockquote, code,
# hr. The fence has a language tag and a blank line inside it -- the case
# most likely to break line-range logic.
MIXED_KINDS = (
    "Intro para.\n"
    "\n"
    "- item one\n"
    "- item two\n"
    "- item three\n"
    "\n"
    "> A quoted line.\n"
    "> Another quoted line.\n"
    "\n"
    "```python\n"
    "def foo():\n"
    "\n"
    "    return 1\n"
    "```\n"
    "\n"
    "---\n"
    "\n"
    "Outro para.\n"
)

# A fenced code block whose contents look like markdown -- must stay one
# `code` block, not get split into a heading + paragraph.
CODE_WITH_FAKE_HEADING = (
    "```text\n"
    "## This looks like a heading\n"
    "but it's inside a fence\n"
    "```\n"
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


def test_parse_classifies_sized_single_image_as_img_row():
    # A single photo at a non-default size is promoted (by images.py's
    # markdown_for) to a wrapped `<div class="img-row size-...">` -- it
    # must classify as img_row (which gets the thumbnail editor with size
    # buttons), not fall through to plain paragraph/image.
    body = (
        'Intro.\n'
        '\n'
        '<div class="img-row size-small">\n'
        '<img src="https://img.cloudy.nyc/p/one.jpg" alt="one">\n'
        '</div>\n'
        '\n'
        'Outro.\n'
    )
    blocks = parse_blocks(body)
    kinds = [b.kind for b in blocks]
    assert kinds == ["paragraph", "img_row", "paragraph"]


def test_parse_does_not_classify_lookalike_class_names_as_img_row():
    # `_IMG_ROW_RE` used to be unanchored on its right edge after dropping
    # the trailing `"` to support sized rows -- it would match any class
    # merely *starting with* "img-row", like a hypothetical
    # "img-row-caption" wrapper. Pin both edges: a real (unsized or sized)
    # img-row still classifies, a same-prefix lookalike does not.
    lookalike = (
        'Intro.\n'
        '\n'
        '<div class="img-row-caption">\n'
        '<img src="https://img.cloudy.nyc/p/one.jpg" alt="one">\n'
        '</div>\n'
        '\n'
        'Outro.\n'
    )
    kinds = [b.kind for b in parse_blocks(lookalike)]
    assert kinds == ["paragraph", "html", "paragraph"]

    not_img_row = (
        'Intro.\n'
        '\n'
        '<div class="not-img-row">\n'
        '<img src="https://img.cloudy.nyc/p/one.jpg" alt="one">\n'
        '</div>\n'
        '\n'
        'Outro.\n'
    )
    kinds = [b.kind for b in parse_blocks(not_img_row)]
    assert kinds == ["paragraph", "html", "paragraph"]


def test_parse_classifies_video_row():
    blocks = parse_blocks(VIDEOS)
    kinds = [b.kind for b in blocks]
    assert kinds == ["paragraph", "video", "paragraph"]


def test_parse_classifies_list_blockquote_code_hr():
    blocks = parse_blocks(MIXED_KINDS)
    kinds = [b.kind for b in blocks]
    assert kinds == [
        "paragraph",
        "list",
        "blockquote",
        "code",
        "hr",
        "paragraph",
    ]


def test_fenced_code_with_markdown_like_content_is_one_block():
    blocks = parse_blocks(CODE_WITH_FAKE_HEADING)
    assert len(blocks) == 1
    assert blocks[0].kind == "code"
    assert blocks[0].source == CODE_WITH_FAKE_HEADING.rstrip("\n")
    assert "## This looks like a heading" in blocks[0].source


def test_replace_with_identical_source_is_byte_identical():
    # The load-bearing property: a no-op edit must not perturb the file.
    for body in (SIMPLE, IMAGES, VIDEOS, MIXED_KINDS, CODE_WITH_FAKE_HEADING):
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


def test_insert_index_beyond_length_raises():
    # index == len(blocks) appends; anything greater is a stale/bad index
    # and must raise, not silently append in a plausible-but-wrong place.
    with pytest.raises(IndexError):
        insert_block(SIMPLE, 4, "nope")


def test_image_with_escaped_bracket_alt_still_classifies_as_image():
    # markdown_for() escapes a literal `]` in a standalone image's alt as
    # `\]`. The classifier's _ONLY_IMAGE_RE must tolerate that escape --
    # otherwise saving a photo with ordinary bracket punctuation in its alt
    # text reclassifies the block from `image` to `paragraph` on the very
    # next parse, and the thumbnail editor silently stops being offered for
    # it.
    from editor.images import markdown_for

    source = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a photo of a]bracket"])
    blocks = parse_blocks(source)
    assert [b.kind for b in blocks] == ["image"]


# -- move_block --------------------------------------------------------
#
# `to_index` names a gap in the block list as the client currently sees it
# (before the move): gap 0 is above the first block, gap N is below the
# last, for N blocks. move_block is implemented as delete-then-insert, the
# same splice primitives as everything else here -- never a re-serialisation
# of the document.


def test_move_forward_to_end():
    out = move_block(SIMPLE, 0, 3)
    assert out == "## A heading\n\nSecond para.\n\nFirst para.\n"


def test_move_backward_to_start():
    out = move_block(SIMPLE, 2, 0)
    assert out == "Second para.\n\nFirst para.\n\n## A heading\n"


def test_move_to_own_position_is_byte_identical_noop():
    # The load-bearing property, per block: BOTH gaps that bracket a block's
    # current position (immediately above it and immediately below it) are
    # "where it already is" and must not perturb the file at all -- not even
    # whitespace.
    for body in (SIMPLE, IMAGES, VIDEOS, MIXED_KINDS, CODE_WITH_FAKE_HEADING):
        for block in parse_blocks(body):
            assert move_block(body, block.index, block.index) == body
            assert move_block(body, block.index, block.index + 1) == body


def test_move_does_not_reflow_untouched_blocks():
    # Same guarantee insert/delete already prove: blocks that weren't
    # touched come through with their exact source, not just the right
    # count/order.
    data = parse_blocks(SIMPLE)
    out = move_block(SIMPLE, 2, 0)
    out_blocks = parse_blocks(out)
    assert [b.source for b in out_blocks] == [
        data[2].source,
        data[0].source,
        data[1].source,
    ]


def test_move_preserves_separators_across_mixed_kinds():
    # A move that drops or duplicates a blank-line separator would silently
    # reflow the rest of the post -- move the first block (a plain
    # paragraph) to the very end and check every remaining block's source
    # is untouched, not just reordered.
    data = parse_blocks(MIXED_KINDS)
    out = move_block(MIXED_KINDS, 0, len(data))
    out_blocks = parse_blocks(out)
    assert [b.kind for b in out_blocks] == [
        "list",
        "blockquote",
        "code",
        "hr",
        "paragraph",
        "paragraph",
    ]
    assert [b.source for b in out_blocks] == [b.source for b in data[1:]] + [data[0].source]


def test_move_reorders_img_row_block_across_neighbours():
    # Photo rows are one of the most common real blocks to reorder (the
    # owner's posts have several) -- a genuine, non-no-op move, not just
    # the no-op path the img_row case otherwise only exercises. Move the
    # `.img-row` block past both of its neighbours, to the very front.
    data = parse_blocks(IMAGES)
    assert [b.kind for b in data] == ["paragraph", "image", "img_row", "paragraph"]

    out = move_block(IMAGES, 2, 0)
    out_blocks = parse_blocks(out)
    assert [b.kind for b in out_blocks] == ["img_row", "paragraph", "image", "paragraph"]

    # Every block -- not just the moved one -- must come through
    # byte-identical, not just reordered/rewrapped.
    assert out_blocks[0].source == data[2].source
    assert out_blocks[1].source == data[0].source
    assert out_blocks[2].source == data[1].source
    assert out_blocks[3].source == data[3].source


def test_move_from_index_out_of_range_raises():
    with pytest.raises(IndexError):
        move_block(SIMPLE, 99, 0)


def test_move_to_index_out_of_range_raises():
    # 3 blocks -> gaps 0..3 are valid; 4 is not.
    with pytest.raises(IndexError):
        move_block(SIMPLE, 0, 4)


def test_move_to_index_negative_raises():
    with pytest.raises(IndexError):
        move_block(SIMPLE, 0, -1)


# --- the clear marker -------------------------------------------------------
# A float wraps EVERYTHING after it until something clears, so without a
# marker "these blocks sit beside the row" would be a lie the moment the row
# is taller than the blocks chosen. The marker is invisible on the published
# page; it exists to end the wrap where the selection ends.


def test_a_clear_marker_gets_its_own_kind():
    blocks = parse_blocks('A\n\n<div class="clear-beside"></div>\n\nB')
    assert [b.kind for b in blocks] == ["paragraph", "clear", "paragraph"]


def test_a_clear_marker_is_not_mistaken_for_a_media_row():
    block = parse_blocks('<div class="clear-beside"></div>')[0]
    assert block.kind == "clear"
    assert block.kind not in ("img_row", "video")


def test_an_unrelated_div_is_still_plain_html():
    assert parse_blocks('<div class="something-else"></div>')[0].kind == "html"


# --- pair blocks: one block spanning several top-level tokens ---------------
# A paired section is a picture and a bounded run of prose side by side,
# vertically centred -- which floats cannot do, so the two have to live in one
# container. Markdown inside HTML only parses when it's separated by blank
# lines, so the wrapper necessarily spans several top-level tokens: an opening
# html block, the prose, and a closing html block. parse_blocks folds those
# back into ONE block, because the editor's model is one block per thing the
# author thinks of as a thing.

PAIR = '''<div class="pair pair-right size-medium">
<div class="pair-media">
<img src="u.jpg" alt="a">
</div>
<div class="pair-text">

First paragraph with *emphasis*.

Second paragraph.

</div>
</div>'''


def test_a_pair_is_a_single_block():
    blocks = parse_blocks(f"Before.\n\n{PAIR}\n\nAfter.")
    assert [b.kind for b in blocks] == ["paragraph", "pair", "paragraph"]


def test_a_pair_block_keeps_its_whole_source():
    blocks = parse_blocks(f"Before.\n\n{PAIR}\n\nAfter.")
    assert blocks[1].source == PAIR


def test_blocks_after_a_pair_are_indexed_past_it():
    blocks = parse_blocks(f"Before.\n\n{PAIR}\n\nAfter.")
    assert [b.index for b in blocks] == [0, 1, 2]
    assert blocks[2].source == "After."


def test_a_pair_renders_its_markdown_as_markdown():
    """The prose inside is real markdown -- that's the whole reason for the
    blank lines -- so the block's preview has to show it rendered.
    """
    html = parse_blocks(PAIR)[0].html
    assert "<em>emphasis</em>" in html
    assert 'class="pair-media"' in html


def test_two_pairs_in_one_post_stay_separate():
    body = f"{PAIR}\n\nBetween.\n\n{PAIR}"
    assert [b.kind for b in parse_blocks(body)] == ["pair", "paragraph", "pair"]


def test_an_unclosed_pair_is_left_alone():
    """Swallowing the rest of the post would be far worse than showing the
    fragments: the author can still see and repair raw html blocks.
    """
    broken = PAIR.replace("</div>\n</div>", "")
    kinds = [b.kind for b in parse_blocks(f"{broken}\n\nAfter.")]
    assert "pair" not in kinds


def test_a_stray_closer_is_just_html():
    assert parse_blocks("</div>\n</div>")[0].kind == "html"


def test_a_pair_can_be_spliced_like_any_other_block():
    body = f"Before.\n\n{PAIR}\n\nAfter."
    out = delete_block(body, 1)
    assert [b.source for b in parse_blocks(out)] == ["Before.", "After."]


def test_a_pair_can_be_moved_like_any_other_block():
    body = f"Before.\n\n{PAIR}\n\nAfter."
    out = move_block(body, 1, 0)
    blocks = parse_blocks(out)
    assert [b.kind for b in blocks] == ["pair", "paragraph", "paragraph"]
    assert blocks[0].source == PAIR


# --- the spacer -------------------------------------------------------------
# Plain breathing room between sections. Its own kind for the same reason the
# stop marker has one: an empty div would otherwise be an invisible,
# unexplainable block sitting in the middle of a post.


def test_a_spacer_gets_its_own_kind():
    blocks = parse_blocks('A\n\n<div class="post-spacer"></div>\n\nB')
    assert [b.kind for b in blocks] == ["paragraph", "spacer", "paragraph"]


def test_a_spacer_is_not_confused_with_the_stop_marker():
    assert parse_blocks('<div class="post-spacer"></div>')[0].kind == "spacer"
    assert parse_blocks('<div class="clear-beside"></div>')[0].kind == "clear"


def test_an_unrelated_div_is_not_a_spacer():
    assert parse_blocks('<div class="post-spacer-ish"></div>')[0].kind == "html"


def test_the_spacer_class_is_scoped_to_posts():
    """`.spacer` alone is already taken by templates/lab.html's game chrome,
    and base.html's styles are site-wide -- a bare rule would have given that
    flex span a height.
    """
    from editor import config

    assert 'class="spacer"' in (config.REPO / "templates" / "lab.html").read_text()


def test_a_desktop_only_spacer_is_still_a_spacer():
    """The desktop-only variant is the same block with one modifier class --
    it has to keep its kind, or the gap you deliberately added comes back as
    an unexplainable empty div in the middle of the post.
    """
    blocks = parse_blocks('A\n\n<div class="post-spacer desktop-only"></div>\n\nB')
    assert [b.kind for b in blocks] == ["paragraph", "spacer", "paragraph"]


def test_an_unknown_spacer_modifier_is_not_a_spacer():
    """Only the two shapes the editor actually writes are promoted. A class
    nothing styles would render as a spacer here and as nothing on the page.
    """
    assert parse_blocks('<div class="post-spacer sometimes"></div>')[0].kind == "html"


def test_every_spacer_the_editor_writes_parses_back_as_a_spacer():
    """editor.js hand-duplicates the spacer markup that `_SPACER_RE` matches.
    If one side gains a shape the other doesn't, the editor inserts a block
    that immediately comes back as raw html -- visible only by inserting one.
    """
    from editor import config

    js = (config.REPO / "editor" / "web" / "editor.js").read_text()
    sources = re.findall(r"^const \w*SPACER_SOURCE = '([^']+)';$", js, re.M)
    assert len(sources) == 2, sources
    for source in sources:
        assert parse_blocks(source)[0].kind == "spacer", source


def test_a_pair_with_a_justify_class_still_groups():
    """The opener's class list grows as the pair gains options; the grouper
    has to keep recognising it or the wrapper falls apart into raw fragments.
    """
    spread = PAIR.replace('size-medium"', 'size-medium justify-spread"')
    assert [b.kind for b in parse_blocks(f"Before.\n\n{spread}\n\nAfter.")] == [
        "paragraph", "pair", "paragraph",
    ]
