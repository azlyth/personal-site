"""The editor sets text in the blog's own two families.

Editing in place only keeps the post's look if the editor loads the same
fonts the published page does. The family names are hand-duplicated between
templates/base.html and editor/web/editor.css, like the size presets, so a
one-sided change has to fail here rather than look right in one place only.

And each family needs its own Fontshare <link>: the API honours only the
first f[] parameter of a combined URL and silently drops the rest (CLAUDE.md,
"Typography").
"""
from __future__ import annotations

import re

from editor import config

BASE = config.REPO / "templates" / "base.html"
CSS = config.REPO / "editor" / "web" / "editor.css"
INDEX = config.REPO / "editor" / "web" / "index.html"


def _first_family(text: str, var: str) -> str:
    m = re.search(rf"{re.escape(var)}\s*:\s*([^;]+);", text)
    assert m, f"{var} not defined"
    return m.group(1).split(",")[0].strip().strip("'\"")


def test_editor_uses_the_blogs_families():
    base = BASE.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for var in ("--font-text", "--font-display"):
        assert _first_family(css, var) == _first_family(base, var), var


def test_editor_loads_each_family_with_its_own_link():
    html = INDEX.read_text(encoding="utf-8")
    links = re.findall(r'<link[^>]+href="(https://api\.fontshare\.com/[^"]+)"', html)
    assert len(links) == 2, links
    assert sum("sentient" in u for u in links) == 1, links
    assert sum("switzer" in u for u in links) == 1, links
    assert not any("sentient" in u and "switzer" in u for u in links), links
