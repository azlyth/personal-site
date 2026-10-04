"""A post's other links really are redirects once Zola builds them.

The editor stores them as Zola's top-level `aliases`, canonical
`/blog/<slug>/`; Zola 0.20 writes `<alias>/index.html`, a meta-refresh to the
post's primary URL. Real builds of a COPY of the site (see zola_site.py).
"""
from __future__ import annotations

from pathlib import Path

from .zola_site import BASE_URL, build_copy

PUBLISHED = """+++
title = "Links fixture"
date = 2026-10-01
aliases = ["/blog/links-fixture-old/"]
+++
Published.
"""

DRAFT = """+++
title = "Links fixture draft"
date = 2026-10-01
draft = true
aliases = ["/blog/links-fixture-draft-old/"]
+++
Not published.
"""


def prepare(root: Path) -> None:
    blog = root / "content" / "blog"
    (blog / "links-fixture.md").write_text(PUBLISHED)
    (blog / "links-fixture-draft.md").write_text(DRAFT)


def test_aliases_build_to_redirects_and_a_drafts_do_not():
    pages = build_copy(prepare)

    assert "blog/links-fixture/index.html" in pages
    redirect = pages["blog/links-fixture-old/index.html"]
    target = f"{BASE_URL}/blog/links-fixture/"
    assert f'http-equiv="refresh" content="0; url={target}"' in redirect
    assert f'rel="canonical" href="{target}"' in redirect

    assert not [p for p in pages if p.startswith("blog/links-fixture-draft")]
