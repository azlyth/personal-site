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
