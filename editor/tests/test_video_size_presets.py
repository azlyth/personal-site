"""`.video-row.size-{small,medium,full}` is hand-duplicated across two
files: `templates/base.html` (what the published site uses) and
`editor/web/editor.css` (what the editor uses), each with a comment saying
they're kept in sync manually. If someone edits one and not the other, the
editor shows one size and the published page another -- and it would only
surface after publishing, when it's a live-site visual bug rather than a
failing test. This asserts the two never drift instead of trusting the
comment.
"""
from __future__ import annotations

import re

from editor import config

_SIZE_RE = re.compile(r'\.video-row\.size-(?P<name>[a-z]+)\s*\{\s*max-width:\s*(?P<value>[^;]+?)\s*;')


def _sizes(text: str) -> dict[str, str]:
    return {m.group("name"): m.group("value") for m in _SIZE_RE.finditer(text)}


def test_video_row_size_presets_match_between_site_and_editor():
    site_css = (config.REPO / "templates" / "base.html").read_text(encoding="utf-8")
    editor_css = (config.REPO / "editor" / "web" / "editor.css").read_text(encoding="utf-8")

    site_sizes = _sizes(site_css)
    editor_sizes = _sizes(editor_css)

    # Fails loudly (rather than vacuously passing on two empty dicts) if
    # either file's markup changes shape and the regex stops matching.
    assert site_sizes == {"small": "240px", "medium": "420px", "full": "100%"}
    assert editor_sizes == site_sizes
