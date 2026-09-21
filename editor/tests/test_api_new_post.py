import datetime

import pytest
from fastapi.testclient import TestClient

from editor import config
from editor.app import app
from editor.frontmatter import join_post, split_post

client = TestClient(app)
CREATED: list = []


@pytest.fixture(autouse=True)
def cleanup():
    yield
    for slug in CREATED:
        (config.BLOG_DIR / f"{slug}.md").unlink(missing_ok=True)
    CREATED.clear()


def _create(title: str):
    res = client.post("/api/posts", json={"title": title})
    if res.status_code == 200:
        CREATED.append(res.json()["slug"])
    return res


def test_creates_a_post_with_a_slug_from_the_title():
    out = _create("A Brand New Post!").json()
    assert out["slug"] == "a-brand-new-post"
    assert (config.BLOG_DIR / "a-brand-new-post.md").exists()


def test_new_post_is_a_draft_dated_today():
    out = _create("Draft Check").json()
    assert out["meta"]["draft"] is True
    assert out["meta"]["date"] == datetime.date.today().isoformat()


def test_new_post_has_an_editable_starter_block():
    out = _create("Starter Block").json()
    assert len(out["blocks"]) >= 1


def test_duplicate_titles_get_distinct_slugs():
    first = _create("Same Title").json()["slug"]
    second = _create("Same Title").json()["slug"]
    assert first != second
    assert second.startswith(first)


def test_title_that_sanitises_to_nothing_is_rejected():
    assert client.post("/api/posts", json={"title": "!!!"}).status_code == 400


def test_title_with_a_quote_produces_valid_toml():
    # A naive f-string like f'title = "{title}"' would break as soon as the
    # title itself contains a double quote -- the frontmatter would stop
    # parsing as valid TOML. The route has to escape it properly (tomlkit),
    # not string-interpolate it.
    out = _create('A "Quoted" Title').json()
    assert out["meta"]["title"] == 'A "Quoted" Title'


def test_new_post_round_trips_byte_identical_through_split_and_join():
    # Every existing post's file round-trips byte-for-byte through
    # split_post/join_post (see test_frontmatter.py). A freshly created post
    # must too, or join_post's assumptions about separator style have been
    # violated at creation time.
    slug = _create("Round Trip Check").json()["slug"]
    raw = (config.BLOG_DIR / f"{slug}.md").read_text(encoding="utf-8")
    fm, body = split_post(raw)
    assert join_post(fm, body) == raw
