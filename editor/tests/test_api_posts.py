from fastapi.testclient import TestClient

from editor.app import app

client = TestClient(app)


def test_list_posts_includes_the_gardening_post():
    slugs = [p["slug"] for p in client.get("/api/posts").json()]
    assert "guerilla-gardening" in slugs


def test_get_post_returns_blocks_and_hash():
    data = client.get("/api/posts/guerilla-gardening").json()

    assert data["meta"]["title"] == "Guerrilla Gardening"
    assert len(data["hash"]) == 64
    assert len(data["blocks"]) > 5

    first = data["blocks"][0]
    assert first["index"] == 0
    # Deliberately NOT asserting which KIND leads the post: this reads the
    # real gardening post, and the block order there is editorial. It was a
    # paragraph until a photo row was floated above it, and a test that
    # breaks when the author rearranges their own writing is testing the
    # content, not the code. What has to hold is that every block indexes
    # from zero and carries rendered html.
    assert first["html"].strip()
    assert all(b["index"] == i for i, b in enumerate(data["blocks"]))
    assert any(b["kind"] == "paragraph" for b in data["blocks"])


def test_get_post_marks_image_rows():
    data = client.get("/api/posts/guerilla-gardening").json()
    kinds = {b["kind"] for b in data["blocks"]}
    assert "img_row" in kinds
    assert "image" in kinds


def test_unknown_post_404s():
    assert client.get("/api/posts/does-not-exist").status_code == 404


def test_path_traversal_404s():
    # _post_path is safe today by accident of the framework -- Starlette's
    # {slug} converter rejects raw and percent-encoded slashes before our
    # code runs, and the mandatory ".md" suffix defeats a bare "..". Pin
    # that behavior here so it can't regress silently if the route
    # signature ever changes.
    assert client.get("/api/posts/../../etc/passwd").status_code == 404
    assert client.get("/api/posts/..%2f..%2fetc%2fpasswd").status_code == 404
    assert client.get("/api/posts/..%252f..%252fetc%252fpasswd").status_code == 404


# --- the link to the live post ---------------------------------------------


def test_a_post_reports_its_public_url():
    data = client.get("/api/posts/guerilla-gardening").json()
    assert data["url"] == "https://cloudy.nyc/blog/guerilla-gardening/"


def test_the_public_base_matches_what_publishing_actually_uses():
    """`scripts/build-site.sh` is what renders the live site, and its
    BASE_URL default is the real one -- config.toml's `base_url` is only the
    fallback that script overrides. A link built from the wrong base points
    at a host that doesn't answer, which is worse than no link.
    """
    import re

    from editor import config

    script = (config.REPO / "scripts" / "build-site.sh").read_text(encoding="utf-8")
    match = re.search(r'BASE_URL="\$\{BASE_URL:-(?P<url>[^}"]+)\}"', script)
    assert match, "couldn't find BASE_URL's default in build-site.sh"
    assert config.SITE_BASE_URL == match.group("url")
