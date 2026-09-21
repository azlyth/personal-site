"""The blog editor service. LAN-only; see editor/guard.py."""
from __future__ import annotations

import hashlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from editor import config
from editor.blocks import parse_blocks
from editor.frontmatter import read_meta, split_post
from editor.guard import assert_not_publicly_routed

assert_not_publicly_routed(config.HOSTNAME, config.CLOUDFLARED_CONFIG)

app = FastAPI(title="blog editor")


@app.get("/healthz")
def healthz():
    return {"ok": True}


# "/" and "/edit/{slug}" serve the editor page (see editor_page below), so
# there's a real <head> with a <link rel="icon"> in editor/web/index.html.
# The browser still fires an implicit GET /favicon.ico for any tab on this
# origin regardless of what the page declares, so this route stays as the
# fallback; it 307s to the real SVG below.
@app.get("/favicon.svg", include_in_schema=False)
def favicon_svg():
    return FileResponse(config.WEB_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    return RedirectResponse("/favicon.svg")


@app.get("/api/posts")
def list_posts():
    posts = []
    for path in sorted(config.BLOG_DIR.glob("*.md")):
        if path.name == "_index.md":
            continue
        frontmatter, _ = split_post(path.read_text())
        meta = read_meta(frontmatter)
        posts.append(
            {
                "slug": path.stem,
                "title": meta.get("title", path.stem),
                "date": str(meta.get("date", "")),
                "draft": bool(meta.get("draft", False)),
            }
        )
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def _post_path(slug: str):
    path = config.BLOG_DIR / f"{slug}.md"
    if not path.exists() or path.name == "_index.md":
        raise HTTPException(status_code=404, detail=f"no post {slug!r}")
    return path


def _read_post(slug: str):
    path = _post_path(slug)
    raw_bytes = path.read_bytes()
    raw = raw_bytes.decode()
    frontmatter, body = split_post(raw)
    return path, raw_bytes, frontmatter, body


@app.get("/api/posts/{slug}")
def get_post(slug: str):
    # Hash the bytes actually on disk, not a decode-then-re-encode round
    # trip through str -- Task 8 uses this hash as the staleness guard that
    # decides whether to accept a write, so it needs to match the file
    # exactly.
    _, raw_bytes, frontmatter, body = _read_post(slug)
    meta = read_meta(frontmatter)
    return {
        "slug": slug,
        "meta": {
            "title": meta.get("title", slug),
            "date": str(meta.get("date", "")),
            "draft": bool(meta.get("draft", False)),
        },
        "hash": hashlib.sha256(raw_bytes).hexdigest(),
        "blocks": [
            {"index": b.index, "kind": b.kind, "source": b.source, "html": b.html}
            for b in parse_blocks(body)
        ],
    }


@app.get("/")
@app.get("/edit/{slug}")
def editor_page(slug: str | None = None):
    return FileResponse(config.WEB_DIR / "index.html")


# Mounted last, and not at "/", so it can't shadow the routes above (a
# StaticFiles mount at the same prefix as a decorated route wins by
# registration order in Starlette, so this has to come after them).
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
