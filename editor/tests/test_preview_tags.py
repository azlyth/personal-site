"""The social-preview and feed metadata the site renders.

A link to a post is often read before the post is: Reddit, iMessage and
every feed aggregator ask for the page and show whatever `og:`/`<meta>`
tags they find. These tests build the real templates with Zola and assert
on the bytes that reach those crawlers.

The build runs against a COPY of the site (templates, static, config) in a
temp dir, with `content/blog` replaced by fixtures. Writing fixture posts
into the real `content/blog` would work, but `scripts/build-site.sh` and
the editor's Publish both render the *working tree* -- a publish racing
this test would put "Preview fixture" on cloudy.nyc. A copy makes that
impossible rather than unlikely.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASE_URL = "https://cloudy.nyc"
ZOLA_IMAGE = "personal-site-zola"

# Every fixture is `draft = false` and dated, so all of them reach the feed.
FIXTURES = {
    # Two photos: the preview image defaults to the LAST one, and the
    # description to the first paragraph -- not the second, and not the
    # markup of the row.
    "two-photos.md": """+++
title = "Two Photos"
date = 2026-01-05
+++

The first paragraph, which is the one that becomes the description.

A second paragraph that must not appear in the description.

<div class="img-row">
<img src="https://img.cloudy.nyc/t/one.jpg" alt="One">
<img src="https://img.cloudy.nyc/t/two.jpg" alt="Two">
</div>
""",
    # An explicit pick beats the last-image default.
    "chosen-photo.md": """+++
title = "Chosen Photo"
date = 2026-01-04

[extra]
preview_image = "https://img.cloudy.nyc/t/one.jpg"
+++

Body text.

<div class="img-row">
<img src="https://img.cloudy.nyc/t/one.jpg" alt="One">
<img src="https://img.cloudy.nyc/t/two.jpg" alt="Two">
</div>
""",
    # No photo anywhere: fall back to the site's own image rather than
    # sharing as a blank card.
    "no-photos.md": """+++
title = "No Photos"
date = 2026-01-03
+++

Just words here.
""",
    # A hand-written description in frontmatter wins over the first paragraph.
    "described.md": """+++
title = "Described"
description = "Hand written summary."
date = 2026-01-02
+++

The first paragraph, which must lose to the frontmatter.
""",
    # A root-relative image (the shape the 2016 posts use) has to become
    # absolute -- a crawler resolving og:image does not have the page's base.
    "relative-photo.md": """+++
title = "Relative Photo"
date = 2026-01-01
+++

Words.

![How it works](/content/images/2016/11/demo.gif)
""",
    # The post opens with the photo row, so "the first paragraph" is not
    # the first thing in the rendered content.
    "photo-first.md": """+++
title = "Photo First"
date = 2025-12-31
+++

<div class="img-row">
<img src="https://img.cloudy.nyc/t/lead.jpg" alt="Lead">
</div>

The paragraph under the photo.
""",
    # Inline markup and escaped characters: the description is plain text a
    # human reads, so tags come out and entities come back.
    "entities.md": """+++
title = "Entities"
date = 2025-12-30
+++

A [linked](https://example.com) word, **bold**, and `a "quoted" & <fenced> bit`.
""",
    # A post opening with a heading: "the first paragraph" means the
    # paragraph, not the heading glued to the front of it.
    "heading-first.md": """+++
title = "Heading First"
date = 2025-12-28
+++

## The goal

The paragraph that follows the heading.
""",
    # Markdown soft-wraps inside a paragraph become real newlines in the
    # rendered <p>. A meta tag's content is one line.
    "soft-wrapped.md": """+++
title = "Soft Wrapped"
date = 2025-12-27
+++

A paragraph broken
across three
source lines.
""",
    # Longer than the cap, so it truncates -- on a word boundary, with an
    # ellipsis, because a card cut mid-word reads as broken.
    "long-paragraph.md": """+++
title = "Long Paragraph"
date = 2025-12-29
+++

%s
""" % (" ".join(["wordy"] * 60)),
}


def _meta(page: str, attr: str, value: str) -> str | None:
    """The `content` of the first <meta> whose `attr` equals `value`.

    Unescaped, because the value a crawler reads is the unescaped one --
    a description containing a quote MUST appear as `&quot;` in the source.
    """
    pattern = re.compile(
        r'<meta\s+%s="%s"\s+content="([^"]*)"' % (attr, re.escape(value)), re.I
    )
    match = pattern.search(page)
    return html.unescape(match.group(1)) if match else None


def og(page: str, prop: str) -> str | None:
    return _meta(page, "property", f"og:{prop}")


@pytest.fixture(scope="module")
def site() -> dict[str, str]:
    """Build the site from a copy and return {output path: text}."""
    if shutil.which("docker") is None:
        pytest.skip("docker is needed to run Zola")

    with tempfile.TemporaryDirectory(prefix="preview-tags-") as tmp:
        root = Path(tmp)
        shutil.copy(REPO / "config.toml", root / "config.toml")
        shutil.copytree(REPO / "templates", root / "templates")
        shutil.copytree(REPO / "static", root / "static")
        shutil.copytree(REPO / "content", root / "content")

        blog = root / "content" / "blog"
        for post in blog.glob("*.md"):
            if post.name != "_index.md":
                post.unlink()
        for name, text in FIXTURES.items():
            (blog / name).write_text(text)

        out = root / "out"
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "--user", f"{__import__('os').getuid()}:{__import__('os').getgid()}",
                "-e", "HOME=/tmp",
                "-v", f"{root}:/project",
                "-w", "/project",
                "--entrypoint", "zola",
                ZOLA_IMAGE,
                "build", "--base-url", BASE_URL,
                "--output-dir", "/project/out", "--force",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"zola build failed:\n{result.stdout}\n{result.stderr}")

        return {
            str(path.relative_to(out)): path.read_text()
            for path in out.rglob("*")
            if path.is_file() and path.suffix in (".html", ".xml")
        }


def post(site: dict[str, str], slug: str) -> str:
    return site[f"blog/{slug}/index.html"]


# --- the preview image -------------------------------------------------

def test_preview_image_defaults_to_the_last_photo(site):
    assert og(post(site, "two-photos"), "image") == "https://img.cloudy.nyc/t/two.jpg"


def test_a_chosen_preview_image_wins(site):
    assert og(post(site, "chosen-photo"), "image") == "https://img.cloudy.nyc/t/one.jpg"


def test_the_fallback_card_is_the_size_every_platform_crops_to():
    """1200x630 is what summary_large_image is cropped to everywhere.

    The fallback is the one og:image a crawler is guaranteed to fetch -- it
    stands in for every text-only post -- so a missing or wrongly-shaped
    file is a broken card on most of the site, not one page.
    """
    from PIL import Image

    card = REPO / "static" / "og-card.jpg"
    assert card.exists(), "run scripts/build-og-card.py"
    assert Image.open(card).size == (1200, 630)


def test_a_post_with_no_photos_falls_back_to_the_site_image(site):
    assert og(post(site, "no-photos"), "image") == f"{BASE_URL}/og-card.jpg"


def test_a_relative_photo_becomes_absolute(site):
    assert og(post(site, "relative-photo"), "image") == (
        f"{BASE_URL}/content/images/2016/11/demo.gif"
    )


# --- the description ---------------------------------------------------

def test_description_is_the_first_paragraph(site):
    assert og(post(site, "two-photos"), "description") == (
        "The first paragraph, which is the one that becomes the description."
    )


def test_a_frontmatter_description_wins(site):
    assert og(post(site, "described"), "description") == "Hand written summary."


def test_the_first_paragraph_is_found_under_a_leading_photo(site):
    assert og(post(site, "photo-first"), "description") == "The paragraph under the photo."


def test_description_is_plain_text(site):
    """Tags stripped, entities decoded -- a card shows text, not markup."""
    assert og(post(site, "entities"), "description") == (
        'A linked word, bold, and a "quoted" & <fenced> bit.'
    )


def test_a_long_description_truncates_on_a_word_boundary(site):
    desc = og(post(site, "long-paragraph"), "description")
    assert desc.endswith("…")
    assert len(desc) <= 201
    assert not desc.rstrip("…").endswith("word")  # no half a word before the cut


def test_a_leading_heading_is_not_part_of_the_description(site):
    assert og(post(site, "heading-first"), "description") == (
        "The paragraph that follows the heading."
    )


def test_the_description_is_one_line(site):
    """A soft-wrapped source paragraph must not put newlines in a meta tag."""
    assert og(post(site, "soft-wrapped"), "description") == (
        "A paragraph broken across three source lines."
    )


def test_a_short_description_is_not_truncated(site):
    assert not og(post(site, "no-photos"), "description").endswith("…")


# --- the rest of the head ---------------------------------------------

def test_urls_are_not_slash_escaped(site):
    """Tera escapes `/` to `&#x2F;` by default.

    A conforming HTML parser decodes it, but the tag is unreadable and
    every crawler that reaches for the URL with a regex gets it wrong.
    """
    html_text = post(site, "two-photos")
    assert 'content="https://img.cloudy.nyc/t/two.jpg"' in html_text
    assert "&#x2F;" not in html_text


def test_a_post_carries_the_standard_meta_description(site):
    html = post(site, "two-photos")
    assert _meta(html, "name", "description") == og(html, "description")


def test_a_post_is_an_article_at_its_own_url(site):
    html = post(site, "two-photos")
    assert og(html, "type") == "article"
    assert og(html, "url") == f"{BASE_URL}/blog/two-photos/"
    assert og(html, "title") == "Two Photos"
    assert f'<link rel="canonical" href="{BASE_URL}/blog/two-photos/">' in html


def test_a_post_publishes_its_date(site):
    html = post(site, "two-photos")
    assert _meta(html, "property", "article:published_time").startswith("2026-01-05")


def test_a_post_asks_for_a_large_twitter_card(site):
    assert _meta(post(site, "two-photos"), "name", "twitter:card") == "summary_large_image"


def test_the_home_page_is_a_website_with_the_site_image(site):
    html = site["index.html"]
    assert og(html, "type") == "website"
    assert og(html, "image") == f"{BASE_URL}/og-card.jpg"
    assert og(html, "description") == "Personal blog and technical writings"


def test_every_page_advertises_the_feed(site):
    for name in ("index.html", "blog/two-photos/index.html"):
        assert (
            '<link rel="alternate" type="application/rss+xml" '
            f'title="Peter @ WWW" href="{BASE_URL}/rss.xml">'
        ) in site[name]


# --- the feed ----------------------------------------------------------

def feed_item(site: dict[str, str], title: str) -> str:
    items = site["rss.xml"].split("<item>")
    for item in items[1:]:
        if f"<title>{title}</title>" in item:
            return item
    raise AssertionError(f"no feed item titled {title!r}")


def test_the_feed_description_is_the_summary_not_the_whole_post(site):
    item = feed_item(site, "Two Photos")
    description = re.search(r"<description>(.*?)</description>", item, re.S).group(1)
    assert html.unescape(description).strip() == (
        "The first paragraph, which is the one that becomes the description."
    )


def test_the_feed_still_carries_the_full_post(site):
    item = feed_item(site, "Two Photos")
    encoded = re.search(r"<content:encoded>(.*?)</content:encoded>", item, re.S).group(1)
    assert "A second paragraph that must not appear in the description." in encoded
    assert "img.cloudy.nyc/t/two.jpg" in encoded


def test_the_feed_carries_the_preview_image(site):
    item = feed_item(site, "Two Photos")
    assert '<media:content url="https://img.cloudy.nyc/t/two.jpg"' in item
    assert '<media:thumbnail url="https://img.cloudy.nyc/t/two.jpg"' in item


def test_the_feed_declares_the_namespaces_it_uses(site):
    channel = site["rss.xml"]
    assert 'xmlns:content="http://purl.org/rss/1.0/modules/content/"' in channel
    assert 'xmlns:media="http://search.yahoo.com/mrss/"' in channel
