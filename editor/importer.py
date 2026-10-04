"""Turn a Platen document into a blog post: a title and a block-split body.

Pure: no I/O. app.py's import_post does the writing.

Platen text is plain markdown-ish prose: `#` headings and paragraphs, with
inline **strong**, *em* and `code` (the only things its renderer knows).
The blog editor treats each top-level markdown block as one editable block,
so the job here is to make every heading and every paragraph its own block:

- The first non-blank line, if it is `# Title`, becomes the post title. The
  title is the page's h1, so it leaves the body. Otherwise the doc's name is
  the title.
- Every non-blank line becomes its own block, separated by one blank line.
  A single line break would otherwise be a soft break that merges lines into
  one paragraph -- the "one giant block" this exists to prevent.
- Leading whitespace is dropped: four spaces of indent is a code block in
  CommonMark, and Platen has no code blocks.
- A `# ` heading later in the body becomes `## `: one h1 per page.
- A line that is only `#` characters (`#`, `##`, a stripped `# `, ...) carries
  no text and is dropped rather than demoted -- demoting it would still leave
  an empty heading in the body.
"""
from __future__ import annotations

import re

_H1 = re.compile(r"^#[ \t]+(.+)$")
_BODY_H1 = re.compile(r"^#(?=[ \t])")
_BLANK_HEADING = re.compile(r"^#+$")


class EmptyImport(ValueError):
    """Nothing is left to post once the title is taken out."""


def convert(text: str, name: str) -> tuple[str, str]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.strip() for line in raw if line.strip()]

    title = ""
    if lines:
        match = _H1.match(lines[0])
        if match:
            title = match.group(1).strip()
            lines = lines[1:]
    if not title:
        title = re.sub(r"\.md$", "", name.strip())

    lines = [line for line in lines if not _BLANK_HEADING.match(line)]
    if not lines:
        raise EmptyImport("The document has nothing to post after its title.")

    body = [_BODY_H1.sub("##", line) for line in lines]
    return title, "\n\n".join(body) + "\n"
