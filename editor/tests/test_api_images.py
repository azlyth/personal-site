import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "image-test-post"

POST = """+++
title = "Image Test"
date = 2026-01-01
draft = true
+++

Intro.

Outro.
"""


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def temp_post():
    path = config.BLOG_DIR / f"{SLUG}.md"
    path.write_text(POST)
    app.state.s3 = FakeS3()
    yield path
    path.unlink(missing_ok=True)


def _png(size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def test_single_upload_inserts_standalone_image(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["a cat"]', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 200
    text = temp_post.read_text()
    assert "![a cat](https://img.cloudy.nyc/" in text
    assert app.state.s3.calls[0]["CacheControl"] == "public, max-age=31536000, immutable"


def test_multiple_uploads_insert_an_img_row(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    client.post(
        f"/api/posts/{SLUG}/images",
        files=[
            ("files", ("a.png", _png((800, 600)), "image/png")),
            ("files", ("b.png", _png((640, 480)), "image/png")),
        ],
        data={"alts": '["a", "b"]', "index": "1", "hash": data["hash"]},
    )

    text = temp_post.read_text()
    assert '<div class="img-row">' in text
    assert text.count("<img ") == 2
    assert len(app.state.s3.calls) == 2


def test_uploaded_bytes_are_reencoded_as_jpeg(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]', "index": "1", "hash": data["hash"]},
    )

    body = app.state.s3.calls[0]["Body"]
    assert Image.open(io.BytesIO(body)).format == "JPEG"


def test_stale_hash_refused(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    temp_post.write_text(POST.replace("Intro.", "Changed."))

    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 409
    assert not app.state.s3.calls


def test_malformed_alts_json_is_rejected(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": "{not valid json", "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 400
    assert not app.state.s3.calls
    assert temp_post.read_text() == POST


def test_alts_scalar_json_is_rejected(temp_post):
    # A bare JSON string like '"x"' parses fine but is not a list -- indexing
    # into it (alt_list[0], alt_list[1], ...) walks its *characters*, silently
    # producing wrong alt text instead of erroring. Must be rejected outright.
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '"x"', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 400
    assert not app.state.s3.calls
    assert temp_post.read_text() == POST


def test_non_image_file_is_rejected_by_name(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[
            ("files", ("a.png", _png(), "image/png")),
            ("files", ("b.png", b"not actually an image", "image/png")),
        ],
        data={"alts": '["a", "b"]', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 400
    assert "b.png" in res.json()["detail"]
    # The post is untouched -- no partial insert -- even though the first
    # file in the batch was a valid image and its S3 PUT already fired
    # (an orphaned-but-harmless, content-addressed object is fine here).
    assert temp_post.read_text() == POST


def test_oversized_file_is_rejected(temp_post):
    from editor.app import MAX_UPLOAD_BYTES

    data = client.get(f"/api/posts/{SLUG}").json()
    oversized = b"\x00" * (MAX_UPLOAD_BYTES + 1)
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[("files", ("huge.png", oversized, "image/png"))],
        data={"alts": '["x"]', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 400
    assert "huge.png" in res.json()["detail"]
    assert not app.state.s3.calls
    assert temp_post.read_text() == POST


def test_too_many_files_is_rejected(temp_post):
    from editor.app import MAX_FILES

    data = client.get(f"/api/posts/{SLUG}").json()
    files = [
        ("files", (f"{i}.png", _png((10, 10)), "image/png")) for i in range(MAX_FILES + 1)
    ]
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=files,
        data={"alts": "[]", "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 400
    assert not app.state.s3.calls
    assert temp_post.read_text() == POST


def test_fewer_alts_than_files_pads_with_empty_string(temp_post):
    data = client.get(f"/api/posts/{SLUG}").json()
    res = client.post(
        f"/api/posts/{SLUG}/images",
        files=[
            ("files", ("a.png", _png((800, 600)), "image/png")),
            ("files", ("b.png", _png((640, 480)), "image/png")),
        ],
        data={"alts": '["only-one"]', "index": "1", "hash": data["hash"]},
    )

    assert res.status_code == 200
    text = temp_post.read_text()
    assert 'alt="only-one"' in text
    assert 'alt="">' in text
