#!/usr/bin/env python3
"""Refuse a build that would publish a draft.

Usage: check-drafts.py <content-dir> <build-output-dir>

Zola leaves `draft = true` pages out of `zola build` on its own. This is the
second lock, run by scripts/build-site.sh between building and promoting, so
a draft can't reach cloudy.nyc even if that stops holding: someone builds
with --drafts, a Zola upgrade changes the default, or a template starts
listing pages some other way.

Fails (exit 1) when:
  - a draft's page exists in the build output,
  - a draft's title is an <item> in rss.xml,
  - a `draft` key sits inside [extra] (or any table) instead of at the top
    level. Zola reads only the top-level key, so that post is published
    while its author believes it's hidden. The editor's frontmatter code
    guards against writing this; a hand edit can still do it.
  - a post's frontmatter can't be parsed. Failing closed: an unreadable
    file can't be proven not to be a draft.
"""
from __future__ import annotations

import re
import sys
import tomllib
from html import unescape
from pathlib import Path


def frontmatter(md: Path) -> dict:
    text = md.read_text(encoding="utf-8")
    match = re.match(r"\A\+\+\+\s*\n(.*?)\n\+\+\+\s*(\n|\Z)", text, re.S)
    if not match:
        raise ValueError("no +++ TOML frontmatter")
    return tomllib.loads(match.group(1))


def url_path(md: Path, content: Path, meta: dict) -> str:
    """Where Zola would put the page, relative to the output root."""
    if meta.get("path"):
        return meta["path"].strip("/")
    rel = md.relative_to(content)
    section = rel.parent
    if md.name == "index.md":  # a page bundle: blog/post/index.md
        section, stem = section.parent, section.name
    else:
        stem = md.stem
    slug = meta.get("slug") or stem
    return str(section / slug.lower()).strip("./")


def nested_draft_tables(meta: dict, prefix: str = "") -> list[str]:
    found = []
    for key, value in meta.items():
        if isinstance(value, dict):
            name = f"{prefix}{key}"
            if "draft" in value:
                found.append(f"[{name}]")
            found += nested_draft_tables(value, f"{name}.")
    return found


def feed_item_titles(out: Path) -> set[str]:
    feed = out / "rss.xml"
    if not feed.exists():
        return set()
    items = re.findall(r"<item>.*?<title>([^<]*)</title>", feed.read_text(encoding="utf-8"), re.S)
    return {unescape(t).strip() for t in items}


def check(content: Path, out: Path) -> list[str]:
    problems = []
    titles = feed_item_titles(out)

    for md in sorted(content.rglob("*.md")):
        if md.name == "_index.md":
            continue
        rel = md.relative_to(content.parent)
        try:
            meta = frontmatter(md)
        except (ValueError, tomllib.TOMLDecodeError) as exc:
            problems.append(f"{rel}: can't read frontmatter ({exc})")
            continue

        misplaced = nested_draft_tables(meta)
        if misplaced:
            problems.append(
                f"{rel}: `draft` is inside {', '.join(misplaced)}, where Zola "
                "ignores it. Move it above the first [table]."
            )

        if meta.get("draft") is not True:
            continue

        page = out / url_path(md, content, meta)
        if page.exists():
            problems.append(f"{rel}: is a draft but was built to {page.relative_to(out)}/")
        title = str(meta.get("title", "")).strip()
        if title and title in titles:
            problems.append(f"{rel}: is a draft but {title!r} is in rss.xml")

    return problems


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    content, out = Path(sys.argv[1]), Path(sys.argv[2])
    problems = check(content, out)
    for problem in problems:
        print(f"draft check: {problem}", file=sys.stderr)
    if problems:
        print("draft check FAILED -- refusing to publish this build", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
