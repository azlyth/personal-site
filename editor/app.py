"""The blog editor service. LAN-only; see editor/guard.py."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from editor import config
from editor.blocks import delete_block, insert_block, parse_blocks, replace_block
from editor.frontmatter import join_post, read_meta, split_post
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
        frontmatter, _ = split_post(path.read_text(encoding="utf-8"))
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
    raw = raw_bytes.decode("utf-8")
    frontmatter, body = split_post(raw)
    return path, raw_bytes, frontmatter, body


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically.

    Writing in place (`path.write_text`) truncates the file immediately and
    then streams the new content, so a process kill mid-write -- and this
    machine has a documented history of that happening -- can leave a post
    empty or half-written with no way back. Instead write to a temp file in
    the same directory (so the later rename can't cross filesystems) and
    `os.replace` it onto the target; that rename is atomic, so any reader or
    crash sees either the old file or the new one, never a partial one.
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


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


class BlockEdit(BaseModel):
    source: str
    hash: str


class BlockInsert(BaseModel):
    index: int
    source: str
    hash: str


class BlockDelete(BaseModel):
    hash: str


def _write_body(slug: str, expected_hash: str, transform):
    """Rewrite a post's body, refusing if the file changed since it was read."""
    path, raw, frontmatter, body = _read_post(slug)

    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_hash:
        raise HTTPException(
            status_code=409,
            detail="post changed on disk since it was loaded; reload before saving",
        )

    try:
        new_body = transform(body)
    except IndexError:
        # The block index no longer exists -- e.g. another tab deleted it
        # after this client's view was loaded. Same recovery as a stale
        # hash: the client's view is stale, so surface the same 409 rather
        # than an unhandled 500.
        raise HTTPException(
            status_code=409,
            detail="block index no longer exists; reload before saving",
        )

    _atomic_write_text(path, join_post(frontmatter, new_body))
    return get_post(slug)


@app.put("/api/posts/{slug}/blocks/{index}")
def edit_block(slug: str, index: int, edit: BlockEdit):
    return _write_body(slug, edit.hash, lambda body: replace_block(body, index, edit.source))


@app.post("/api/posts/{slug}/blocks")
def add_block(slug: str, edit: BlockInsert):
    return _write_body(slug, edit.hash, lambda body: insert_block(body, edit.index, edit.source))


@app.delete("/api/posts/{slug}/blocks/{index}")
def remove_block(slug: str, index: int, edit: BlockDelete):
    return _write_body(slug, edit.hash, lambda body: delete_block(body, index))


@app.get("/")
@app.get("/edit/{slug}")
def editor_page(slug: str | None = None):
    return FileResponse(config.WEB_DIR / "index.html")


# Mounted last, and not at "/", so it can't shadow the routes above (a
# StaticFiles mount at the same prefix as a decorated route wins by
# registration order in Starlette, so this has to come after them).
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
