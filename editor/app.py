"""The blog editor service. LAN-only; see editor/guard.py."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse

from editor import config
from editor.frontmatter import read_meta, split_post
from editor.guard import assert_not_publicly_routed

assert_not_publicly_routed(config.HOSTNAME, config.CLOUDFLARED_CONFIG)

app = FastAPI(title="blog editor")


@app.get("/healthz")
def healthz():
    return {"ok": True}


# There is no front end here — "/" is a JSON 404 — so there's no <head> to put
# a <link rel="icon"> in. The browser still fires an implicit GET
# /favicon.ico for whatever tab has this origin open, so that's the only way
# to get a tab icon; it 307s to the real SVG below.
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
