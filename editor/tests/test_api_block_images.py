import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from editor import config
from editor.app import app

client = TestClient(app)
SLUG = "image-block-test-post"

POST = """+++
title = "Image Block Test"
date = 2026-01-01
draft = true
+++

Intro.

![alt one](https://img.cloudy.nyc/p/one.jpg)

<div class="img-row">
<img src="https://img.cloudy.nyc/p/two.jpg" alt="two">
<img src="https://img.cloudy.nyc/p/three.jpg" alt="three">
</div>

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
    path.write_text(POST, encoding="utf-8")
    app.state.s3 = FakeS3()
    yield path
    path.unlink(missing_ok=True)


def _png(size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def _get():
    return client.get(f"/api/posts/{SLUG}").json()


# --- GET .../posts/{slug} exposes parsed images per block -----------------


def test_get_post_includes_images_for_standalone_image_block(temp_post):
    data = _get()
    block = data["blocks"][1]
    assert block["kind"] == "image"
    assert block["images"] == [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}]


def test_get_post_includes_images_for_img_row_block(temp_post):
    data = _get()
    block = data["blocks"][2]
    assert block["kind"] == "img_row"
    assert block["images"] == [
        {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
        {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
    ]


def test_get_post_omits_images_for_non_photo_blocks(temp_post):
    data = _get()
    assert "images" not in data["blocks"][0]  # "Intro." paragraph


# --- PUT .../blocks/{index}/images -----------------------------------------


def test_replace_block_images_rewrites_standalone_to_img_row(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [
                {"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"},
                {"url": "https://img.cloudy.nyc/p/new.jpg", "alt": "a new one"},
            ],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    out = res.json()
    block = out["blocks"][1]
    assert block["kind"] == "img_row"
    assert block["images"] == [
        {"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"},
        {"url": "https://img.cloudy.nyc/p/new.jpg", "alt": "a new one"},
    ]

    on_disk = temp_post.read_text(encoding="utf-8")
    assert '<div class="img-row">' in on_disk
    assert "https://img.cloudy.nyc/p/new.jpg" in on_disk


def test_replace_block_images_reorders(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={
            "images": [
                {"url": "https://img.cloudy.nyc/p/three.jpg", "alt": "three"},
                {"url": "https://img.cloudy.nyc/p/two.jpg", "alt": "two"},
            ],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    urls_in_order = [im["url"] for im in res.json()["blocks"][2]["images"]]
    assert urls_in_order == [
        "https://img.cloudy.nyc/p/three.jpg",
        "https://img.cloudy.nyc/p/two.jpg",
    ]


def test_replace_block_images_edits_alt_text(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "a much better description"}],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert res.json()["blocks"][1]["images"][0]["alt"] == "a much better description"


def test_replace_block_images_empty_list_deletes_block(temp_post):
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/2/images",
        json={"images": [], "hash": data["hash"]},
    )
    assert res.status_code == 200
    out = res.json()
    assert len(out["blocks"]) == len(data["blocks"]) - 1
    on_disk = temp_post.read_text(encoding="utf-8")
    assert "img-row" not in on_disk
    assert "Intro." in on_disk and "Outro." in on_disk


def test_replace_block_images_preserves_neighbouring_blocks(temp_post):
    data = _get()
    out = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "alt one"}],
            "hash": data["hash"],
        },
    ).json()
    assert out["blocks"][0]["source"] == data["blocks"][0]["source"]
    assert out["blocks"][2]["source"] == data["blocks"][2]["source"]
    assert out["blocks"][3]["source"] == data["blocks"][3]["source"]


def test_replace_block_images_stale_hash_refused(temp_post):
    data = _get()
    temp_post.write_text(POST.replace("Intro.", "Changed."), encoding="utf-8")

    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "x"}],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 409
    assert "Changed." in temp_post.read_text(encoding="utf-8")


def test_replace_block_images_preserves_file_mode(temp_post):
    import os

    os.chmod(temp_post, 0o644)
    data = _get()
    res = client.put(
        f"/api/posts/{SLUG}/blocks/1/images",
        json={
            "images": [{"url": "https://img.cloudy.nyc/p/one.jpg", "alt": "x"}],
            "hash": data["hash"],
        },
    )
    assert res.status_code == 200
    assert temp_post.stat().st_mode & 0o777 == 0o644


# --- POST .../images/upload (upload without touching the post) ------------


def test_upload_only_returns_images_without_modifying_post(temp_post):
    before = temp_post.read_text(encoding="utf-8")
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=[
            ("files", ("a.png", _png((800, 600)), "image/png")),
            ("files", ("b.png", _png((640, 480)), "image/png")),
        ],
        data={"alts": '["fresh a", "fresh b"]'},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["images"]) == 2
    assert body["images"][0]["alt"] == "fresh a"
    assert body["images"][0]["url"].startswith("https://img.cloudy.nyc/")
    assert len(app.state.s3.calls) == 2
    assert temp_post.read_text(encoding="utf-8") == before


def test_upload_only_404s_for_unknown_post(temp_post):
    res = client.post(
        "/api/posts/does-not-exist/images/upload",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]'},
    )
    assert res.status_code == 404


def test_upload_only_rejects_cross_site(temp_post):
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={"alts": '["x"]'},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert res.status_code == 403
    assert not app.state.s3.calls


def test_upload_only_rejects_too_many_files(temp_post):
    from editor.app import MAX_FILES

    files = [("files", (f"{i}.png", _png((10, 10)), "image/png")) for i in range(MAX_FILES + 1)]
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=files,
        data={"alts": "[]"},
    )
    assert res.status_code == 400
    assert not app.state.s3.calls


def test_upload_only_rejects_non_image_file(temp_post):
    res = client.post(
        f"/api/posts/{SLUG}/images/upload",
        files=[("files", ("b.png", b"not actually an image", "image/png"))],
        data={"alts": '["x"]'},
    )
    assert res.status_code == 400
    assert not app.state.s3.calls
