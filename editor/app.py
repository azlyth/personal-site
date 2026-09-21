"""The blog editor service. LAN-only; see editor/guard.py."""
from __future__ import annotations

import datetime
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from editor import config
from editor.blocks import delete_block, insert_block, parse_blocks, replace_block
from editor.frontmatter import join_post, read_meta, set_meta, split_post
from editor.guard import assert_not_publicly_routed
from editor.publish import _has_unpushed_commits, publish

assert_not_publicly_routed(config.HOSTNAME, config.CLOUDFLARED_CONFIG)

app = FastAPI(title="blog editor")

BLOG_PREFIX = "content/blog/"


class PublishRequest(BaseModel):
    message: str | None = None


def _dirty_paths() -> list[str]:
    """Paths git reports as dirty, via the NUL-separated porcelain format.

    Plain `git status --porcelain` C-quotes paths with non-ASCII characters,
    quotes, or backslashes (e.g. `"content/blog/caf\\303\\251-post.md"`), so
    a `startswith("content/blog/")` check silently fails and the post is
    dropped with no error. `-z` emits raw, unquoted, NUL-separated paths
    instead, which avoids that.

    Renames matter too: `git mv` (the slug-change route) makes git report a
    rename as TWO consecutive NUL-terminated fields -- `XY <new>\\0<orig>\\0`
    -- the NEW path first, then the ORIGINAL, not joined by `" -> "` the way
    the human-readable format does it. Both paths still need staging: the new
    path for the addition, the original for the deletion.
    """
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z"],
        cwd=config.REPO, check=True, capture_output=True, text=True,
    ).stdout

    fields = out.split("\0")
    if fields and fields[-1] == "":
        fields.pop()

    paths: list[str] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in code or "C" in code:
            # Rename/copy: the next field is the original path.
            if i < len(fields):
                paths.append(fields[i])
                i += 1
    return paths


def _blog_paths() -> list[str]:
    return [p for p in _dirty_paths() if p.startswith(BLOG_PREFIX)]


@app.get("/api/status")
def status():
    dirty = _blog_paths()
    unpushed = _has_unpushed_commits(config.REPO)
    outstanding = bool(dirty) or unpushed
    return {"dirty": dirty, "unpushed": unpushed, "clean": not outstanding}


@app.post("/api/publish")
def do_publish(request: PublishRequest):
    paths = _blog_paths()
    # Don't short-circuit on empty paths: a clean tree with an unpushed
    # commit is exactly the state a prior publish() left behind after a
    # failed push or S3 publish, and publish() already knows how to finish
    # that -- returning "nothing to publish" here would strand it.
    message = request.message or (
        f"Update {len(paths)} post(s) from the editor" if paths
        else "Publish from the editor"
    )
    result = publish(config.REPO, paths, message)
    return result.__dict__


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

    `tempfile.mkstemp` creates its file at mode 0600 regardless of umask,
    and `os.replace` swaps the directory entry rather than copying content
    into the existing inode -- so without an explicit chmod, the destination
    ends up being the temp file and silently inherits 0600, turning every
    edited post owner-only. `zola build` runs as a different UID in a
    container, so a 0600 post fails the build with no obvious link back to
    the edit that caused it. Carry the target's existing mode over (or a
    sensible default for a not-yet-existing post) onto the temp file
    *before* the replace, so there's no window where the file exists at the
    wrong mode.
    """
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = 0o644  # new post (Task 12); matches every existing post's mode

    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.chmod(tmp_path, mode)
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


class MetaEdit(BaseModel):
    hash: str
    title: str | None = None
    date: str | None = None
    draft: bool | None = None


class Rename(BaseModel):
    new_slug: str
    hash: str


@app.put("/api/posts/{slug}/meta")
def edit_meta(slug: str, edit: MetaEdit):
    path, raw, frontmatter, body = _read_post(slug)

    # `raw` is bytes (see _read_post) -- the hash guard has to match it
    # exactly, the same way _write_body hashes it, not a str.encode() of a
    # decode-then-re-encode round trip.
    if hashlib.sha256(raw).hexdigest() != edit.hash:
        raise HTTPException(
            status_code=409,
            detail="post changed on disk since it was loaded; reload before saving",
        )

    updates = edit.model_dump(exclude={"hash"}, exclude_none=True)
    for key, value in updates.items():
        if key == "date":
            value = datetime.date.fromisoformat(value)
        frontmatter = set_meta(frontmatter, key, value)

    _atomic_write_text(path, join_post(frontmatter, body))
    return get_post(slug)


@app.post("/api/posts/{slug}/rename")
def rename_post(slug: str, rename: Rename):
    path, raw, _, _ = _read_post(slug)

    if hashlib.sha256(raw).hexdigest() != rename.hash:
        raise HTTPException(status_code=409, detail="post changed on disk; reload")

    new_slug = re.sub(r"[^a-z0-9-]+", "-", rename.new_slug.lower()).strip("-")
    if not new_slug:
        raise HTTPException(status_code=400, detail="slug is empty after sanitising")

    target = config.BLOG_DIR / f"{new_slug}.md"
    if target.exists():
        raise HTTPException(status_code=409, detail=f"{new_slug} already exists")

    # git mv keeps the file's history attached to the new name, and stages
    # the rename -- _dirty_paths already knows how to parse that (an "R  "
    # porcelain entry) when the post is next published.
    subprocess.run(
        ["git", "mv", str(path.relative_to(config.REPO)), str(target.relative_to(config.REPO))],
        cwd=config.REPO, check=True, capture_output=True, text=True,
    )

    return {
        "slug": new_slug,
        "warning": f"/blog/{slug}/ will 404 — any existing links to it will break.",
    }


@app.get("/")
@app.get("/edit/{slug}")
def editor_page(slug: str | None = None):
    return FileResponse(config.WEB_DIR / "index.html")


# Mounted last, and not at "/", so it can't shadow the routes above (a
# StaticFiles mount at the same prefix as a decorated route wins by
# registration order in Starlette, so this has to come after them).
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
