"""The blog editor service. LAN-only; see editor/guard.py."""
from __future__ import annotations

from fastapi import FastAPI

from editor import config
from editor.frontmatter import read_meta, split_post
from editor.guard import assert_not_publicly_routed

assert_not_publicly_routed(config.HOSTNAME, config.CLOUDFLARED_CONFIG)

app = FastAPI(title="blog editor")


@app.get("/healthz")
def healthz():
    return {"ok": True}


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
