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
    assert first["kind"] == "paragraph"
    assert "<p>" in first["html"]


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
