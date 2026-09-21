"""`.video-row.size-{small,medium,full}` and `.img-row.size-{small,medium,full}`
are hand-duplicated across two files: `templates/base.html` (what the
published site uses) and `editor/web/editor.css` (what the editor uses),
each with a comment saying they're kept in sync manually. If someone edits
one and not the other, the editor shows one size and the published page
another -- and it would only surface after publishing, when it's a live-site
visual bug rather than a failing test. This asserts the two never drift
instead of trusting the comment.
"""
from __future__ import annotations

import re

from editor import config

_SIZE_RE = re.compile(
    r'\.(?P<row>video-row|img-row)\.size-(?P<name>[a-z]+)\s*\{\s*max-width:\s*(?P<value>[^;]+?)\s*;'
)


def _sizes(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {"video-row": {}, "img-row": {}}
    for m in _SIZE_RE.finditer(text):
        out[m.group("row")][m.group("name")] = m.group("value")
    return out


def test_video_row_size_presets_match_between_site_and_editor():
    site_css = (config.REPO / "templates" / "base.html").read_text(encoding="utf-8")
    editor_css = (config.REPO / "editor" / "web" / "editor.css").read_text(encoding="utf-8")

    site_sizes = _sizes(site_css)
    editor_sizes = _sizes(editor_css)

    # Fails loudly (rather than vacuously passing on two empty dicts) if
    # either file's markup changes shape and the regex stops matching.
    assert site_sizes["video-row"] == {"small": "240px", "medium": "420px", "full": "100%"}
    assert editor_sizes["video-row"] == site_sizes["video-row"]


def test_img_row_size_presets_match_between_site_and_editor():
    site_css = (config.REPO / "templates" / "base.html").read_text(encoding="utf-8")
    editor_css = (config.REPO / "editor" / "web" / "editor.css").read_text(encoding="utf-8")

    site_sizes = _sizes(site_css)
    editor_sizes = _sizes(editor_css)

    # Same widths as the video presets -- there's no reason a photo row
    # should cap at a different size than a video row.
    assert site_sizes["img-row"] == {"small": "240px", "medium": "420px", "full": "100%"}
    assert editor_sizes["img-row"] == site_sizes["img-row"]
