"""Drafts never reach the published site.

Two locks: Zola leaves `draft = true` pages out of `zola build`, and
scripts/check-drafts.py, which scripts/build-site.sh runs before promoting
a build, refuses one that contains a draft anyway. These tests pin both,
against real Zola builds of a COPY of the site (see zola_site.py).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .zola_site import REPO, built_copy

CHECKER = REPO / "scripts" / "check-drafts.py"

PLAIN_DRAFT = """+++
title = "Draft fixture plain"
date = 2026-10-04
draft = true
+++
Not for publishing.
"""

# The layout the editor writes once a preview photo is pinned: the draft
# flag above the [extra] table.
EXTRA_DRAFT = """+++
title = "Draft fixture with extra"
date = 2026-10-03
draft = true

[extra]
preview_image = "fixture.jpg"
+++
Not for publishing.
"""

# The trap: the flag landed inside [extra], so Zola publishes the post.
MISPLACED_DRAFT = """+++
title = "Draft fixture misplaced"
date = 2026-10-02

[extra]
preview_image = "fixture.jpg"
draft = true
+++
Not for publishing.
"""


def add_drafts(*posts: tuple[str, str]):
    def prepare(root: Path) -> None:
        for name, text in posts:
            (root / "content" / "blog" / name).write_text(text)
    return prepare


def run_checker(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(CHECKER), str(root / "content"), str(root / "out")],
        capture_output=True, text=True,
    )


def feed_titles(root: Path) -> list[str]:
    feed = (root / "out" / "rss.xml").read_text()
    return re.findall(r"<item>.*?<title>([^<]*)</title>", feed, re.S)


DRAFTS = add_drafts(
    ("draft-fixture-plain.md", PLAIN_DRAFT),
    ("draft-fixture-extra.md", EXTRA_DRAFT),
)


def test_zola_leaves_drafts_out_and_the_checker_passes():
    with built_copy(DRAFTS) as root:
        titles = feed_titles(root)
        assert titles, "the feed has no items at all"
        assert not [t for t in titles if "Draft fixture" in t]
        assert not (root / "out" / "blog" / "draft-fixture-plain").exists()
        assert not (root / "out" / "blog" / "draft-fixture-extra").exists()
        result = run_checker(root)
        assert result.returncode == 0, result.stderr


def test_the_checker_catches_a_build_that_includes_drafts():
    """The second lock: if drafts get built anyway, the build is refused."""
    with built_copy(DRAFTS, zola_args=("--drafts",)) as root:
        assert "Draft fixture plain" in feed_titles(root)  # the leak is real
        result = run_checker(root)
        assert result.returncode == 1
        assert "draft-fixture-plain.md: is a draft but was built" in result.stderr
        assert "'Draft fixture plain' is in rss.xml" in result.stderr
        assert "draft-fixture-extra.md: is a draft but was built" in result.stderr


def test_the_checker_catches_a_draft_flag_inside_extra():
    with built_copy(add_drafts(("draft-fixture-misplaced.md", MISPLACED_DRAFT))) as root:
        # Zola really does publish it -- that's why this is an error.
        assert "Draft fixture misplaced" in feed_titles(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "`draft` is inside [extra]" in result.stderr


def test_the_real_content_passes():
    """Today's posts: every frontmatter parses, no flag is misplaced."""
    result = subprocess.run(
        ["python3", str(CHECKER), str(REPO / "content"), "/nonexistent"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_build_site_runs_the_checker_before_promoting():
    script = (REPO / "scripts" / "build-site.sh").read_text()
    check = script.index("check-drafts.py")
    assert check < script.index('rsync -a --delete "$TMP_ABS/"')


# A draft that already has another link: Zola builds no redirect for it
# either, and the checker catches one if a build leaks it.
ALIASED_DRAFT = """+++
title = "Draft fixture aliased"
date = 2026-10-01
draft = true
aliases = ["/blog/draft-fixture-old-link/"]
+++
Not for publishing.
"""


def test_a_drafts_aliases_are_not_built():
    with built_copy(add_drafts(("draft-fixture-aliased.md", ALIASED_DRAFT))) as root:
        assert not (root / "out" / "blog" / "draft-fixture-aliased").exists()
        assert not (root / "out" / "blog" / "draft-fixture-old-link").exists()
        result = run_checker(root)
        assert result.returncode == 0, result.stderr


def test_the_checker_catches_a_leaked_draft_alias():
    prepare = add_drafts(("draft-fixture-aliased.md", ALIASED_DRAFT))
    with built_copy(prepare, zola_args=("--drafts",)) as root:
        assert (root / "out" / "blog" / "draft-fixture-old-link" / "index.html").exists()
        result = run_checker(root)
        assert result.returncode == 1
        assert "its alias /blog/draft-fixture-old-link/ was built" in result.stderr
