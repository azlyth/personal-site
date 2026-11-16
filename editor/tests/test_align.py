"""Paragraph alignment: a centred block is a wrapper with markdown inside.

On disk:

    <div class="align-center">

    <the block's markdown, unchanged>

    </div>

The blank lines are the mechanism (CommonMark only parses markdown inside an
HTML block once a blank line has closed it -- same as the pair). Left is the
default and writes no wrapper, so every existing post stays byte-identical.
`blocks.py` folds the three top-level tokens back into ONE block of the inner
kind that reports `align: "center"` and its inner `text`.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app
from editor.blocks import (
    ALIGN_CENTER_OPEN,
    aligned_source,
    delete_block,
    insert_block,
    move_block,
    parse_blocks,
    replace_block,
)
from editor.frontmatter import split_post

client = TestClient(app)
SLUG = "zz-align-test-post"


def centred(inner: str) -> str:
    return f'<div class="align-center">\n\n{inner}\n\n</div>'


PARA = "Find the code at https://example.com/thing."
HEADING = "## A centred heading"
LIST = "- one\n- two\n- three"
QUOTE = "> A quote, centred."


@pytest.mark.parametrize("inner, kind", [
    (PARA, "paragraph"), (HEADING, "heading"), (LIST, "list"), (QUOTE, "blockquote"),
])
def test_a_centred_block_is_one_block_of_its_inner_kind(inner, kind):
    body = f"Before.\n\n{centred(inner)}\n\nAfter.\n"
    blocks = parse_blocks(body)
    assert [b.kind for b in blocks] == ["paragraph", kind, "paragraph"]
    b = blocks[1]
    assert b.align == "center"
    assert b.text == inner
    assert b.source == centred(inner)
    # Regenerating the wrapper from what was parsed is byte-exact.
    assert aligned_source(b.text, "center") == b.source
    assert 'class="align-center"' in b.html


@pytest.mark.parametrize("inner", [PARA, HEADING, LIST, QUOTE])
def test_round_trip_parse_then_regenerate_is_the_original(inner):
    body = f"Before.\n\n{centred(inner)}\n\nAfter.\n"
    for b in parse_blocks(body):
        # Writing every block back as itself leaves the post unchanged.
        assert replace_block(body, b.index, aligned_source(b.text or b.source, b.align or "left")) == body


def test_left_blocks_report_left_and_have_no_wrapper():
    blocks = parse_blocks("Plain.\n\n## Head\n\n- a\n\n> q\n")
    assert [b.align for b in blocks] == ["left"] * 4
    assert all(b.text is None for b in blocks)
    assert aligned_source("Plain.", "left") == "Plain."


def test_alignment_is_only_for_text_kinds():
    # A pair, a row, a spacer, code: no alignment at all.
    body = (
        '<div class="post-spacer"></div>\n\n'
        "```\ncode\n```\n\n"
        '<div class="img-row size-small">\n<img src="https://img.cloudy.nyc/p/a.jpg" alt="a">\n</div>\n'
    )
    assert [b.align for b in parse_blocks(body)] == [None, None, None]


def test_a_wrapper_around_something_that_is_not_prose_is_not_grouped():
    body = '<div class="align-center">\n\n<div class="post-spacer"></div>\n\n</div>\n'
    blocks = parse_blocks(body)
    assert len(blocks) == 3
    assert all(b.align != "center" for b in blocks)


def test_an_unclosed_opener_stays_ungrouped():
    body = f"{ALIGN_CENTER_OPEN}\n\nCentred, but nobody closed it.\n\nMore text.\n"
    blocks = parse_blocks(body)
    assert [b.kind for b in blocks] == ["html", "paragraph", "paragraph"]
    assert blocks[0].source == ALIGN_CENTER_OPEN
    assert all(b.align != "center" for b in blocks)


def test_a_wrapper_without_its_blank_lines_is_not_grouped():
    # Not the shape the editor writes, so it isn't claimed: raw fragments.
    body = '<div class="align-center">\n\nText.\n</div>\n'
    blocks = parse_blocks(body)
    assert all(b.align != "center" for b in blocks)


def test_several_paragraphs_inside_one_wrapper_stay_one_block():
    inner = "First line.\n\nSecond line."
    blocks = parse_blocks(f"{centred(inner)}\n")
    assert len(blocks) == 1
    assert blocks[0].kind == "paragraph"
    assert blocks[0].text == inner


def test_aligned_source_normalises_like_parse_blocks():
    # parse_blocks rstrips every block, so the wrapper is built from the
    # rstripped text; leading blank lines are dropped too.
    assert aligned_source("\n\nHello  \n\n", "center") == centred("Hello")
    # Saving a centred block empty removes it, like any block saved empty.
    assert aligned_source("   \n", "center") == ""


def test_saving_text_edits_keeps_the_wrapper():
    body = f"Before.\n\n{centred(PARA)}\n\nAfter.\n"
    out = replace_block(body, 1, aligned_source("New words.", "center"))
    assert out == f"Before.\n\n{centred('New words.')}\n\nAfter.\n"
    assert parse_blocks(out)[1].text == "New words."


def test_left_removes_the_wrapper():
    body = f"Before.\n\n{centred(PARA)}\n\nAfter.\n"
    out = replace_block(body, 1, aligned_source(PARA, "left"))
    assert out == f"Before.\n\n{PARA}\n\nAfter.\n"


def test_center_adds_the_wrapper():
    body = f"Before.\n\n{PARA}\n\nAfter.\n"
    out = replace_block(body, 1, aligned_source(PARA, "center"))
    assert out == f"Before.\n\n{centred(PARA)}\n\nAfter.\n"


def test_a_centred_block_moves_and_deletes_as_one():
    body = f"A.\n\n{centred(PARA)}\n\nB.\n"
    assert delete_block(body, 1) == "A.\n\nB.\n"
    moved = move_block(body, 1, 3)
    assert moved == f"A.\n\nB.\n\n{centred(PARA)}\n"
    inserted = insert_block(body, 2, "Between.")
    assert inserted == f"A.\n\n{centred(PARA)}\n\nBetween.\n\nB.\n"


def test_a_pair_is_untouched_by_alignment_grouping():
    pair = (
        '<div class="pair pair-right size-medium">\n<div class="pair-media">\n'
        '<div class="img-row size-medium">\n'
        '<img src="https://img.cloudy.nyc/p/a.jpg" alt="a cat">\n</div>\n</div>\n'
        '<div class="pair-text">\n\nWords beside the cat.\n\n</div>\n</div>'
    )
    blocks = parse_blocks(f"{pair}\n\n{centred(PARA)}\n")
    assert [b.kind for b in blocks] == ["pair", "paragraph"]
    assert blocks[0].align is None
    assert blocks[1].align == "center"


# --- the API --------------------------------------------------------------

POST = f"""+++
title = "Align Test Post"
date = 2026-01-01
draft = true
+++

Left paragraph.

{centred(PARA)}

After.
"""


@pytest.fixture
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST, encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(config.REPO / "editor" / ".history" / SLUG, ignore_errors=True)


def test_api_reports_align_and_inner_text(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    left, mid, after = data["blocks"]
    assert left["align"] == "left" and "text" not in left
    assert mid["kind"] == "paragraph"
    assert mid["align"] == "center"
    assert mid["text"] == PARA
    assert mid["source"] == centred(PARA)


def test_api_put_of_a_regenerated_wrapper_round_trips(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.put(f"/api/posts/{SLUG}/blocks/1",
                     json={"source": aligned_source("Changed.", "center"), "hash": data["hash"]})
    assert res.status_code == 200
    assert res.json()["blocks"][1]["text"] == "Changed."
    assert temp_post.read_text(encoding="utf-8") == POST.replace(PARA, "Changed.")


# --- the class exists in both stylesheets ---------------------------------

def test_align_center_is_styled_on_the_site_and_in_the_editor():
    site = (config.REPO / "templates" / "base.html").read_text(encoding="utf-8")
    editor = (config.REPO / "editor" / "web" / "editor.css").read_text(encoding="utf-8")
    rule = re.compile(r"\.align-center\s*\{[^}]*text-align:\s*center")
    assert rule.search(site), "base.html has no .align-center rule"
    assert rule.search(editor), "editor.css has no .align-center rule"
    # A centred list keeps its bullets attached to the text.
    bullets = re.compile(r"\.align-center\s+:is\(ul,\s*ol\)\s*\{[^}]*list-style-position:\s*inside")
    assert bullets.search(site) and bullets.search(editor)


def test_the_editor_writes_the_opener_blocks_py_recognises():
    js = (config.REPO / "editor" / "web" / "editor.js").read_text(encoding="utf-8")
    m = re.search(r"const ALIGN_CENTER_OPEN = '([^']*)';", js)
    assert m, "editor.js has no ALIGN_CENTER_OPEN"
    assert m.group(1) == ALIGN_CENTER_OPEN


# --- every existing post is untouched -------------------------------------

def _posts():
    return sorted(config.BLOG_DIR.glob("*.md"))


def test_every_existing_post_parses_and_regenerates_byte_identically():
    posts = _posts()
    assert posts, "no posts found"
    for path in posts:
        text = path.read_text(encoding="utf-8")
        _, body = split_post(text)
        blocks = parse_blocks(body)
        for b in blocks:
            # The text editor sends back aligned_source(text, align); for an
            # untouched block that must be exactly the source on disk.
            regenerated = aligned_source(b.text, b.align) if b.align == "center" else b.source
            assert regenerated == b.source, (path.name, b.index)
            # And splicing it back in is a no-op -- wherever the block's lines
            # are exactly its source (parse_blocks rstrips each block, so a
            # line ending in stray spaces was never round-trippable, before
            # alignment or since).
            original = "\n".join(body.split("\n")[b.start_line:b.end_line])
            if original == b.source:
                assert replace_block(body, b.index, regenerated) == body, (path.name, b.index)
        # Grouping only ever claims the editor's own opener: a post without
        # one parses exactly as it did before alignment existed.
        if ALIGN_CENTER_OPEN not in body:
            assert all(b.align != "center" for b in blocks), path.name
