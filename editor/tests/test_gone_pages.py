"""The pages the old posts' dead links point to instead of the dead thing.

Five links in the 2016 posts went somewhere that no longer exists. Three of
them were DOMAINS that have since lapsed -- no DNS at all -- which is the
case worth guarding: anyone can register `ptrvldz.me` today, and a post
still linking there would send readers to whatever they put on it. So each
dead destination gets a small page under /gone/ saying what used to be
there, and the post links to that instead.
"""
from __future__ import annotations

import re
import tomllib

import pytest

from editor.frontmatter import split_post
from editor.tests.zola_site import BASE_URL, REPO, build_copy

GONE = REPO / "content" / "gone"
BLOG = REPO / "content" / "blog"

# slug -> (the dead URL, the post that linked to it). Pinned here, not just
# read from content/gone, so deleting a page fails a test instead of
# silently putting a dead link back.
EXPECTED = {
    "ptrvldz-me": ("https://ptrvldz.me", "blog/back-online.md"),
    "git-ptrvldz-me": ("https://git.ptrvldz.me", "blog/back-online.md"),
    "redub-audio": ("http://redub.audio", "blog/working-with-electron.md"),
    "react-native-lock": (
        "https://github.com/auth0/react-native-lock", "blog/react-native-ssh.md"
    ),
    "hooks-play-store": (
        "https://play.google.com/store/apps/details?id=com.hooks", "blog/hooks.md"
    ),
}

# Not dead, just moved -- the post points at the live copy instead.
MOVED_FROM = "http://sircmpwn.github.io/2016/11/24/Electron-considered-harmful.html"
MOVED_TO = "https://drewdevault.com/2016/11/24/Electron-considered-harmful.html"

# Only these three were ever captured by the Wayback Machine (checked against
# the CDX API on 2026-09-23); the other two pages must not offer a link to
# an archive page that says "not archived".
ARCHIVED = {"ptrvldz-me", "redub-audio", "react-native-lock"}


def extra(slug: str) -> dict:
    frontmatter, _ = split_post((GONE / f"{slug}.md").read_text())
    return tomllib.loads(frontmatter).get("extra", {})


def post_text(from_path: str) -> str:
    return (REPO / "content" / from_path).read_text()


# --- the source ----------------------------------------------------------

@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_every_dead_link_has_a_gone_page(slug):
    was, source = EXPECTED[slug]
    assert extra(slug)["was"] == was
    assert extra(slug)["from"] == source


def test_no_post_links_to_a_dead_url():
    """Markdown link targets only: the Docker post mentions git.ptrvldz.me
    inside a compose file, which is code, not a link."""
    dead = [was for was, _ in EXPECTED.values()] + [MOVED_FROM]
    for post in BLOG.glob("*.md"):
        text = post.read_text()
        for url in dead:
            assert f"]({url}" not in text, f"{post.name} still links to {url}"


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_the_post_links_to_its_gone_page(slug):
    """Otherwise the page exists and nothing reaches it."""
    _, source = EXPECTED[slug]
    assert f"](/gone/{slug}/)" in post_text(source)


def test_the_moved_article_points_to_its_new_home():
    assert f"]({MOVED_TO})" in post_text("blog/working-with-electron.md")


# --- the rendered pages --------------------------------------------------

@pytest.fixture(scope="module")
def site() -> dict[str, str]:
    """The REAL site, unmodified: each gone page names a real post."""
    return build_copy()


def page(site, slug):
    return site[f"gone/{slug}/index.html"]


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_a_gone_page_says_what_is_gone(site, slug):
    title = tomllib.loads(split_post((GONE / f"{slug}.md").read_text())[0])["title"]
    assert re.search(r"<h1[^>]*>\s*%s is gone\.\s*</h1>" % re.escape(title), page(site, slug))


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_a_gone_page_is_not_indexed(site, slug):
    assert '<meta name="robots" content="noindex">' in page(site, slug)


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_the_main_button_goes_back_to_the_post(site, slug):
    _, source = EXPECTED[slug]
    permalink = f"{BASE_URL}/blog/{source.removeprefix('blog/').removesuffix('.md')}/"
    assert re.search(
        r'<a class="gone-back" href="%s">' % re.escape(permalink), page(site, slug)
    )


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_a_gone_page_also_offers_the_home_page(site, slug):
    assert f'href="{BASE_URL}/"' in page(site, slug)


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_a_gone_page_never_links_to_the_dead_thing(site, slug):
    """The whole point: a lapsed domain can belong to anyone now."""
    was, _ = EXPECTED[slug]
    assert f'href="{was}' not in page(site, slug)


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_the_wayback_link_appears_only_where_there_is_a_capture(site, slug):
    has_link = 'href="https://web.archive.org/web/' in page(site, slug)
    assert has_link == (slug in ARCHIVED)


def test_gone_pages_stay_out_of_the_feed(site):
    """As ITEMS. The posts' own links to /gone/ are rightly inside their
    <content:encoded>, so a substring check would be testing the wrong thing."""
    item_links = re.findall(r"<item>.*?<link>([^<]*)</link>", site["rss.xml"], re.S)
    assert item_links, "the feed has no items at all"
    assert not [link for link in item_links if "/gone/" in link]


def test_the_gone_section_has_no_index_page(site):
    """Hidden: the only way in is a post's dead link."""
    assert "gone/index.html" not in site


def test_gone_pages_stay_out_of_the_sitemap(site):
    """A noindexed URL in the sitemap is a contradiction Search Console
    flags as an error, so templates/sitemap.xml filters them out -- while
    every real post stays in."""
    locs = re.findall(r"<loc>([^<]*)</loc>", site["sitemap.xml"])
    assert not [loc for loc in locs if "/gone/" in loc]
    for md in BLOG.glob("*.md"):
        if md.name != "_index.md":
            assert f"{BASE_URL}/blog/{md.stem}/" in locs
    assert site["sitemap.xml"].startswith("<?xml")
