"""Index a markdown body into editable blocks and splice edits back in.

The editor never converts rendered HTML back to markdown. Instead every
top-level markdown token carries a source line range (markdown-it-py's
`token.map`), so an edit is a line splice into the original text: the bytes
outside the edited range are untouched by construction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark").enable("table")

# Tokens markdown-it emits for a top-level node, mapped to our `kind`.
_KIND_BY_TOKEN = {
    "paragraph_open": "paragraph",
    "heading_open": "heading",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "blockquote_open": "blockquote",
    "fence": "code",
    "code_block": "code",
    "html_block": "html",
    "hr": "hr",
}

_IMG_ROW_RE = re.compile(r'<div\s+class="img-row"', re.I)
# The alt group allows an escaped `\]` (or `\[`, or any other `\x`) as well
# as any plain non-bracket character, so a standalone image whose alt text
# contains a literal `]` -- which `images.markdown_for` renders as `\]` --
# still classifies as `image` rather than falling through to `paragraph`.
# `[^\]]*` (matching zero or more non-`]` characters) would stop at that
# escaped bracket's `]` and never reach the real `](url)` closer.
_ONLY_IMAGE_RE = re.compile(r"^!\[(?:\\.|[^\]\\])*\]\([^)]*\)$")


@dataclass
class Block:
    index: int
    kind: str
    source: str
    start_line: int  # 0-based, inclusive
    end_line: int    # 0-based, exclusive
    html: str


def _lines(body: str) -> list[str]:
    return body.split("\n")


def _refine_kind(kind: str, source: str) -> str:
    """Promote the two shapes that get a dedicated editor UI."""
    stripped = source.strip()
    if kind == "html" and _IMG_ROW_RE.search(stripped):
        return "img_row"
    if kind == "paragraph" and _ONLY_IMAGE_RE.match(stripped):
        return "image"
    return kind


def parse_blocks(body: str) -> list[Block]:
    """Split a markdown body into top-level blocks with source ranges."""
    lines = _lines(body)
    tokens = _md.parse(body)

    blocks: list[Block] = []
    depth = 0
    for token in tokens:
        # Only consider tokens at nesting depth 0 -- a paragraph inside a list
        # item is part of that list's block, not a block of its own.
        if depth == 0 and token.type in _KIND_BY_TOKEN and token.map:
            start, end = token.map
            # markdown-it's list tokens fold the blank separator line after
            # the list into their own map (used to decide tight/loose), so
            # end_line can overrun the list's actual content by one blank
            # line. Trim trailing blank lines from the consumed range so it
            # never eats a separator that belongs between blocks.
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            source = "\n".join(lines[start:end]).rstrip()
            kind = _refine_kind(_KIND_BY_TOKEN[token.type], source)
            blocks.append(
                Block(
                    index=len(blocks),
                    kind=kind,
                    source=source,
                    start_line=start,
                    end_line=end,
                    html=_md.render(source),
                )
            )
        depth += token.nesting

    return blocks


def _splice(body: str, start: int, end: int, replacement: list[str]) -> str:
    lines = _lines(body)
    return "\n".join(lines[:start] + replacement + lines[end:])


def _require(blocks: list[Block], index: int) -> Block:
    if index < 0 or index >= len(blocks):
        raise IndexError(f"no block at index {index}")
    return blocks[index]


def replace_block(body: str, index: int, new_source: str) -> str:
    """Replace block `index`'s source lines with `new_source`."""
    block = _require(parse_blocks(body), index)
    return _splice(body, block.start_line, block.end_line, new_source.split("\n"))


def insert_block(body: str, index: int, new_source: str) -> str:
    """Insert a new block before `index`. `index == len(blocks)` appends."""
    blocks = parse_blocks(body)
    new_lines = new_source.split("\n")

    if index == len(blocks):
        trailing = "" if body.endswith("\n") else "\n"
        return body + trailing + "\n" + new_source + "\n"

    block = _require(blocks, index)
    return _splice(body, block.start_line, block.start_line, new_lines + [""])


def delete_block(body: str, index: int) -> str:
    """Remove block `index` along with the blank line that separated it."""
    blocks = parse_blocks(body)
    block = _require(blocks, index)

    end = block.end_line
    lines = _lines(body)
    # Absorb one trailing blank separator so deleting doesn't leave a gap.
    if end < len(lines) and lines[end].strip() == "":
        end += 1

    return _splice(body, block.start_line, end, [])
