"""The blog editor service. LAN-only; see editor/guard.py."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import boto3
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from PIL import UnidentifiedImageError

import tomlkit

from editor import config, videos
from editor.blocks import delete_block, insert_block, move_block, parse_blocks, replace_block
from editor.frontmatter import join_post, read_meta, set_meta, split_post
from editor.guard import assert_not_publicly_routed
from editor.images import image_key, markdown_for, parse_images, process_image, upload
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
    # Scoped to content/blog/: this repo accumulates unrelated unpushed code
    # commits constantly (the editor's own development, a concurrent
    # session), and an unscoped check would count those as outstanding blog
    # work forever -- lighting up the Publish button with nothing for it to
    # actually do.
    unpushed = _has_unpushed_commits(config.REPO, BLOG_PREFIX)
    outstanding = bool(dirty) or unpushed
    return {"dirty": dirty, "unpushed": unpushed, "clean": not outstanding}


@app.post("/api/publish")
def do_publish(request: PublishRequest):
    paths = _blog_paths()
    # Don't short-circuit on empty paths: a clean tree with an unpushed
    # commit is exactly the state a prior publish() left behind after a
    # failed push or S3 publish, and publish() already knows how to finish
    # that -- returning "nothing to publish" here would strand it. The
    # pathspec keeps that recovery scoped to blog work, same reasoning as
    # status() above -- otherwise this would push and re-publish over
    # unrelated in-progress code commits.
    message = request.message or (
        f"Update {len(paths)} post(s) from the editor" if paths
        else "Publish from the editor"
    )
    result = publish(config.REPO, paths, message, pathspec=BLOG_PREFIX)
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


class NewPost(BaseModel):
    title: str


@app.post("/api/posts")
def create_post(new: NewPost):
    slug = re.sub(r"[^a-z0-9]+", "-", new.title.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="title has no usable characters")

    # De-duplicate rather than overwrite: losing an existing post to a title
    # collision would be silent data loss.
    candidate, n = slug, 2
    while (config.BLOG_DIR / f"{candidate}.md").exists():
        candidate = f"{slug}-{n}"
        n += 1

    # Build the frontmatter with tomlkit rather than f-string interpolation
    # -- a title containing a double quote (or a backslash) would otherwise
    # produce invalid TOML that read_meta can't parse back. Same class of
    # bug as the alt-text escaping elsewhere in this project.
    doc = tomlkit.document()
    doc["title"] = new.title
    doc["date"] = datetime.date.today()
    doc["draft"] = True
    frontmatter = tomlkit.dumps(doc)

    # Blank-line-before-body style, matching every current post (see
    # test_frontmatter.py) and join_post's separator handling.
    body = "\nStart writing.\n"

    _atomic_write_text(config.BLOG_DIR / f"{candidate}.md", join_post(frontmatter, body))
    return get_post(candidate)


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
        "blocks": [_block_json(b) for b in parse_blocks(body)],
    }


def _block_json(block) -> dict:
    out = {"index": block.index, "kind": block.kind, "source": block.source, "html": block.html}
    if block.kind in ("image", "img_row"):
        # parse_images returns None for anything it can't losslessly
        # reproduce -- omit the key entirely rather than sending `null` or
        # `[]`, both of which the client (or any other consumer) could
        # mistake for "this photo block is empty" instead of "this block
        # isn't safely editable as a photo list; fall back to raw source."
        parsed = parse_images(block.kind, block.source)
        if parsed is not None:
            out["images"] = parsed["images"]
            out["size"] = parsed["size"]
    elif block.kind == "video":
        # Same discipline as parse_images -- see videos.parse_videos.
        parsed = videos.parse_videos(block.kind, block.source)
        if parsed is not None:
            out["videos"] = parsed["videos"]
            out["size"] = parsed["size"]
    return out


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


class BlockMove(BaseModel):
    to_index: int
    hash: str


@app.post("/api/posts/{slug}/blocks/{index}/move")
def move_block_route(slug: str, index: int, edit: BlockMove):
    # Both `index` (stale if another tab deleted/moved something first) and
    # `edit.to_index` (a gap that no longer exists) raise IndexError from
    # move_block -- _write_body already turns that into the same 409 as
    # every other block edit route, not an unhandled 500.
    return _write_body(slug, edit.hash, lambda body: move_block(body, index, edit.to_index))


class BlockMerge(BaseModel):
    hash: str


# Kinds that belong to the "photo" family -- an `image`/`img_row` pair (in
# either order) can merge into one `img_row`. `video` is its own family and
# never mixes with photos: the markup and semantics differ (a <video> row
# isn't representable as an <img> row or vice versa), so a photo+video pair
# must refuse rather than silently drop one side.
_PHOTO_KINDS = {"image", "img_row"}


def _merge_source(upper, lower) -> str | None:
    """Combine two adjacent media blocks into one row's markdown, upper's
    items first. Returns `None` if the pair can't be merged at all --
    different families, or either side fails to parse losslessly.

    `parse_images`/`parse_videos` already refuse (return `None`) for any
    block that can't be regenerated byte-for-byte from what they parsed --
    the same guard that keeps the per-block thumbnail/row editors from
    trading a hand-edited or otherwise non-canonical block for a reduced
    one. A merge reuses that guard rather than parsing more loosely: acting
    on a partial parse here would delete media just as surely as it would
    there.
    """
    if upper.kind in _PHOTO_KINDS and lower.kind in _PHOTO_KINDS:
        upper_parsed = parse_images(upper.kind, upper.source)
        lower_parsed = parse_images(lower.kind, lower.source)
        if upper_parsed is None or lower_parsed is None:
            return None
        combined = upper_parsed["images"] + lower_parsed["images"]
        # Keep the UPPER row's size preset, not the lower's -- same rule as
        # the video merge below, for the same reason (the owner is acting
        # from the upper block).
        return markdown_for(
            [img["url"] for img in combined], [img["alt"] for img in combined], upper_parsed["size"]
        )

    if upper.kind == "video" and lower.kind == "video":
        upper_parsed = videos.parse_videos(upper.kind, upper.source)
        lower_parsed = videos.parse_videos(lower.kind, lower.source)
        if upper_parsed is None or lower_parsed is None:
            return None
        combined = upper_parsed["videos"] + lower_parsed["videos"]
        # Keep the UPPER row's size preset, not the lower's -- the owner is
        # acting from the upper block, so that's the one whose framing wins.
        return videos.markdown_for(combined, upper_parsed["size"])

    return None


@app.post("/api/posts/{slug}/blocks/{index}/merge")
def merge_block_route(slug: str, index: int, edit: BlockMerge):
    """Merge block `index` with the block immediately below it into a
    single row. Reuses blocks.py's splice primitives exactly the way
    edit_block_images/edit_block_videos do -- replace the upper block's
    source with the combined markup, then delete the lower block -- never a
    from-scratch re-serialisation of the document.
    """

    def transform(body: str) -> str:
        blocks = parse_blocks(body)
        # A stale/out-of-range index or a block with nothing below it (the
        # last block, or an index that no longer has a successor because
        # another tab deleted it) is the same "client's view is stale or
        # was never valid" shape move_block already raises IndexError for --
        # _write_body turns that into a 409, not an unhandled 500.
        if index < 0 or index + 1 >= len(blocks):
            raise IndexError(f"no block pair at index {index}")

        merged_source = _merge_source(blocks[index], blocks[index + 1])
        if merged_source is None:
            raise HTTPException(
                status_code=400,
                detail="these two blocks can't be merged",
            )

        out = replace_block(body, index, merged_source)
        return delete_block(out, index + 1)

    return _write_body(slug, edit.hash, transform)


class ImageItem(BaseModel):
    url: str
    alt: str


class BlockImagesEdit(BaseModel):
    images: list[ImageItem]
    # Same three presets as a video row's size. Defaults to the no-class
    # preset so callers that predate this feature (and existing tests) that
    # never send `size` at all keep behaving exactly as before.
    size: str = "full"
    hash: str


@app.put("/api/posts/{slug}/blocks/{index}/images")
def edit_block_images(slug: str, index: int, edit: BlockImagesEdit):
    """Rewrite an `image`/`img_row` block from a thumbnail-editor's list.

    All markup generation stays server-side (`markdown_for` already owns the
    escaping and the standalone-vs-.img-row decision); the client only ever
    sends back the URLs/alts/size it's editing. An empty list deletes the
    block rather than writing out a `<div class="img-row"></div>` with
    nothing in it.
    """

    def transform(body: str) -> str:
        if not edit.images:
            return delete_block(body, index)
        urls = [image.url for image in edit.images]
        alts = [image.alt for image in edit.images]
        try:
            new_source = markdown_for(urls, alts, edit.size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return replace_block(body, index, new_source)

    return _write_body(slug, edit.hash, transform)


class VideoItem(BaseModel):
    url: str
    sync_loop: str | None = None


class BlockVideosEdit(BaseModel):
    videos: list[VideoItem]
    size: str
    hash: str


@app.put("/api/posts/{slug}/blocks/{index}/videos")
def edit_block_videos(slug: str, index: int, edit: BlockVideosEdit):
    """Rewrite a `video` block from the row editor's clip list -- same shape
    as `edit_block_images` above, right down to an empty list deleting the
    block. All markup generation stays server-side (`videos.markdown_for`).
    """

    def transform(body: str) -> str:
        if not edit.videos:
            return delete_block(body, index)
        clips = [{"url": video.url, "sync_loop": video.sync_loop} for video in edit.videos]
        try:
            new_source = videos.markdown_for(clips, edit.size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return replace_block(body, index, new_source)

    return _write_body(slug, edit.hash, transform)


class BlockVideoSplit(BlockVideosEdit):
    split: int


@app.post("/api/posts/{slug}/blocks/{index}/videos/split")
def split_block_video(slug: str, index: int, edit: BlockVideoSplit):
    """Lift one clip out of a `video` row into a row of its own directly below.

    The whole point is to make a clip reachable by `move_block`, which moves
    blocks and not clips -- so splitting is how a clip gets out of a row it
    shares and into somewhere else entirely.

    Takes the row's full clip list rather than just `split`, because the row
    editor keeps a local working copy and only commits on Done: reordering and
    then splitting has to land as a single write, not two that could interleave.
    Both halves happen inside one `transform`, so `_write_body` gives them one
    hash check and one atomic replace -- a two-request version could have its
    second half 409 and strand the post half-split.

    A one-clip row is rejected rather than treated as a no-op: it already *is*
    its own row, and routing it through the usual "empty list deletes the
    block" rule would silently delete it instead of splitting it.
    """

    if len(edit.videos) < 2:
        raise HTTPException(
            status_code=400,
            detail="a row with fewer than two clips is already its own row",
        )
    if not 0 <= edit.split < len(edit.videos):
        raise HTTPException(status_code=400, detail=f"no clip at index {edit.split}")

    clips = [{"url": video.url, "sync_loop": video.sync_loop} for video in edit.videos]
    moved = clips.pop(edit.split)

    try:
        remaining_source = videos.markdown_for(clips, edit.size)
        moved_source = videos.markdown_for([moved], edit.size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def transform(body: str) -> str:
        # replace_block leaves the block count unchanged, so index + 1 is
        # still the gap immediately below this row when insert_block runs.
        body = replace_block(body, index, remaining_source)
        return insert_block(body, index + 1, moved_source)

    return _write_body(slug, edit.hash, transform)


def _s3():
    """Lazily build the client so tests can inject a fake before first use."""
    if not hasattr(app.state, "s3") or app.state.s3 is None:
        env = config.load_aws_env()
        app.state.s3 = boto3.client(
            "s3",
            aws_access_key_id=env.get("PERSONAL_SITE_IMAGES_ACCESS_KEY_ID"),
            aws_secret_access_key=env.get("PERSONAL_SITE_IMAGES_SECRET_ACCESS_KEY"),
            region_name=env.get("AWS_REGION", "us-east-1"),
        )
    return app.state.s3


# This Pi runs the rest of the fleet too (Nextcloud, several other services),
# so a burst of full-resolution camera-roll photos from the tablet is worth
# bounding even though this route is LAN-only. 20MB is generous for a single
# phone photo; 12 files is generous for one upload batch.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_FILES = 12


def _too_large(position: int, total: int, filename: str | None, size_bytes: float) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=(
            f"photo {position + 1} of {total} "
            f"({filename}) is too large "
            f"({size_bytes / 1_000_000:.1f}MB; max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB)"
        ),
    )


def _assert_same_origin(request: Request) -> None:
    # The JSON routes are implicitly guarded by CORS preflight (a
    # cross-origin fetch with a JSON body triggers one, and the browser
    # never sends the real request if it fails), but a multipart
    # POST -- what these routes take -- is a browser "simple request" that
    # never asks first. A page the tablet happens to have open could POST
    # here directly. Sec-Fetch-Site is sent by every browser this LAN app
    # needs to support and can't be forged by page JS, so reject anything
    # explicitly marked as not same-origin. Absent entirely (curl, very old
    # browsers) it's let through -- these routes are LAN-only already, and
    # those clients don't carry a stolen browser session to begin with.
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site is not None and sec_fetch_site != "same-origin":
        raise HTTPException(status_code=403, detail="cross-site requests are not allowed")


def _parse_alts(alts: str, file_count: int) -> list[str]:
    try:
        alt_list = json.loads(alts)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="alts must be valid JSON")
    if not isinstance(alt_list, list):
        # A bare JSON scalar (e.g. '"x"') parses without error, and indexing
        # into it below would walk its characters instead of raising --
        # silently mislabeling every photo. Reject anything but a list.
        raise HTTPException(
            status_code=400, detail="alts must be a JSON array of strings"
        )
    # Pad explicitly rather than relying on the position < len(alt_list)
    # guard at each use site -- one place that decides what a missing alt
    # becomes.
    return list(alt_list) + [""] * max(0, file_count - len(alt_list))


async def _upload_files(slug: str, files: list[UploadFile], alts: str) -> tuple[list[str], list[str]]:
    """Shared upload pipeline for both `/images` (insert a block) and
    `/images/upload` (hand URLs back for the thumbnail editor to splice in
    itself). Enforces the same caps and re-encoding either way.
    """
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"too many files ({len(files)}); max {MAX_FILES} per upload",
        )

    alt_list = _parse_alts(alts, len(files))
    bucket = config.load_aws_env().get("PERSONAL_SITE_IMAGES_BUCKET", "img.cloudy.nyc")

    urls, used_alts = [], []
    for position, upload_file in enumerate(files):
        alt = alt_list[position]

        # Check the size the multipart parser already recorded *before*
        # reading -- rejecting after `.read()` would have already buffered
        # the whole oversized file in memory, which is exactly what the cap
        # is meant to prevent.
        if upload_file.size is not None and upload_file.size > MAX_UPLOAD_BYTES:
            raise _too_large(position, len(files), upload_file.filename, upload_file.size)

        data = await upload_file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            # Backstop for the rare case `.size` wasn't populated (e.g. a
            # part with no Content-Length) -- costs nothing since the file
            # was read either way.
            raise _too_large(position, len(files), upload_file.filename, len(data))

        try:
            processed = process_image(data)
        except (UnidentifiedImageError, OSError) as exc:
            # The post file is never touched here -- callers only write
            # after every file in the batch has processed successfully, so a
            # later bad file can't leave a partial insert. An earlier valid
            # photo in the same request may already be sitting in S3 by this
            # point; that's an orphaned but harmless object (content-
            # addressed), not a partial edit to the post.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"photo {position + 1} of {len(files)} "
                    f"({upload_file.filename}) is not a valid image: {exc}"
                ),
            )
        key = image_key(slug, alt, processed)
        urls.append(upload(processed, key, bucket, _s3()))
        used_alts.append(alt)

    return urls, used_alts


@app.post("/api/posts/{slug}/images")
async def add_images(
    request: Request,
    slug: str,
    index: int = Form(...),
    hash: str = Form(...),
    alts: str = Form("[]"),
    files: list[UploadFile] = File(...),
):
    _assert_same_origin(request)

    # It would need this post's exact sha256 (the `hash` check below) to
    # pass, which is computable from the public GitHub repo, so the
    # same-origin check above isn't the only thing standing in the way --
    # this isn't purely theoretical.
    _, raw, _, _ = _read_post(slug)
    if hashlib.sha256(raw).hexdigest() != hash:
        raise HTTPException(
            status_code=409,
            detail="post changed on disk since it was loaded; reload before saving",
        )

    urls, used_alts = await _upload_files(slug, files, alts)

    snippet = markdown_for(urls, used_alts)
    return _write_body(slug, hash, lambda body: insert_block(body, index, snippet))


@app.post("/api/posts/{slug}/images/upload")
async def upload_images(
    request: Request,
    slug: str,
    alts: str = Form("[]"),
    files: list[UploadFile] = File(...),
):
    """Upload photos without touching the post -- used by the thumbnail
    editor to add photos to an *existing* image/img_row block, which then
    saves the whole list via `PUT .../blocks/{index}/images`. Same
    protections as `/images` (EXIF strip, size/count caps, same-origin
    check), just no post write and no `hash` staleness check since nothing
    here can conflict with a concurrent edit.
    """
    _assert_same_origin(request)
    _post_path(slug)  # 404s for an unknown slug rather than uploading into the void

    urls, used_alts = await _upload_files(slug, files, alts)
    return {"images": [{"url": url, "alt": alt} for url, alt in zip(urls, used_alts)]}


# A raw phone clip is much bigger than a raw phone photo before ffmpeg gets a
# chance to shrink it -- a few seconds of 4K video easily clears 100MB, so
# this needs real headroom, not MAX_UPLOAD_BYTES. Still bounded: this Pi
# runs the rest of the fleet, and ffmpeg re-encodes one clip at a time in
# this same request, so a handful of files is already a while to wait on a
# LAN tablet.
MAX_VIDEO_UPLOAD_BYTES = 250 * 1024 * 1024
MAX_VIDEO_FILES = 6


def _video_too_large(position: int, total: int, filename: str | None, size_bytes: float) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=(
            f"clip {position + 1} of {total} "
            f"({filename}) is too large "
            f"({size_bytes / 1_000_000:.1f}MB; max {MAX_VIDEO_UPLOAD_BYTES // (1024 * 1024)}MB)"
        ),
    )


async def _upload_video_files(slug: str, files: list[UploadFile]) -> list[str]:
    """Video counterpart to `_upload_files`: process each clip through
    ffmpeg (`videos.process_video`) and upload it, same caps-then-read
    discipline as the photo pipeline. No alt text -- `<video>` carries none.
    """
    if len(files) > MAX_VIDEO_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"too many clips ({len(files)}); max {MAX_VIDEO_FILES} per upload",
        )

    bucket = config.load_aws_env().get("PERSONAL_SITE_IMAGES_BUCKET", "img.cloudy.nyc")

    urls: list[str] = []
    for position, upload_file in enumerate(files):
        if upload_file.size is not None and upload_file.size > MAX_VIDEO_UPLOAD_BYTES:
            raise _video_too_large(position, len(files), upload_file.filename, upload_file.size)

        data = await upload_file.read()
        if len(data) > MAX_VIDEO_UPLOAD_BYTES:
            raise _video_too_large(position, len(files), upload_file.filename, len(data))

        try:
            processed = videos.process_video(data)
        except ValueError as exc:
            # Same non-post-touching guarantee as _upload_files: nothing
            # here has written to the post yet, so a bad clip partway
            # through a batch can't leave a partial edit behind.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"clip {position + 1} of {len(files)} "
                    f"({upload_file.filename}) could not be processed: {exc}"
                ),
            )

        name_hint = Path(upload_file.filename or "").stem
        key = videos.video_key(slug, name_hint, processed)
        urls.append(videos.upload(processed, key, bucket, _s3()))

    return urls


@app.post("/api/posts/{slug}/videos/upload")
async def upload_videos(
    request: Request,
    slug: str,
    files: list[UploadFile] = File(...),
):
    """Upload clips without touching the post -- the video-row editor's
    "+ Add clip" button, same role as `/images/upload` for photos: it hands
    URLs back for the client to fold into the row it's editing, which then
    saves the whole list via `PUT .../blocks/{index}/videos`.
    """
    _assert_same_origin(request)
    _post_path(slug)  # 404s for an unknown slug rather than uploading into the void

    urls = await _upload_video_files(slug, files)
    # A freshly added clip has no data-sync-loop -- that's only meaningful
    # for clips deliberately cut to a matching duration (see
    # scripts/upload-video.py), which this ad hoc upload path doesn't do.
    return {"videos": [{"url": url, "sync_loop": None} for url in urls]}


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
            try:
                value = datetime.date.fromisoformat(value)
            except ValueError:
                # Same pattern as _write_body's stale-index catch: a bad
                # value from a direct API call (or a future UI change) is a
                # client error, not a crash -- surface a clean 400 instead
                # of letting fromisoformat's ValueError 500 out.
                raise HTTPException(
                    status_code=400,
                    detail=f"date must be in YYYY-MM-DD format, got {value!r}",
                )
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
    # porcelain entry) when the post is next published. But git mv refuses
    # (exit 128, "not under version control") a path that isn't tracked
    # yet, and a post from "+ New" is exactly that: create_post only
    # _atomic_write_texts the file, it never `git add`s it. `git add`
    # first so the path is always known to git by the time `git mv` runs --
    # a no-op for an already-tracked post, and it composes with git mv's
    # index rename instead of duplicating that logic with a plain
    # Path.rename fallback.
    subprocess.run(
        ["git", "add", "--", str(path.relative_to(config.REPO))],
        cwd=config.REPO, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "mv", str(path.relative_to(config.REPO)), str(target.relative_to(config.REPO))],
        cwd=config.REPO, check=True, capture_output=True, text=True,
    )

    return {
        "slug": new_slug,
        "warning": f"/blog/{slug}/ will 404 — any existing links to it will break.",
    }


# Rewrites /static/<stem>.<ext> in the page to /static/<stem>-<content hash>.<ext>,
# same "stem-<8 hex sha256>.ext" shape editor/images.py uses for S3 keys --
# one hashing convention in the repo rather than a second, query-string one.
_ASSET_REF = re.compile(r'(?P<attr>href|src)="/static/(?P<stem>[\w.-]+?)\.(?P<ext>\w+)"')

# Matches a path RevalidatedStaticFiles.get_response produced by the stamping
# above -- used to recognise a hashed request and strip it back to the real
# on-disk filename.
_HASHED_ASSET = re.compile(r"^(?P<stem>[\w.-]+?)-(?P<hash>[0-9a-f]{8})\.(?P<ext>\w+)$")


@app.get("/")
@app.get("/edit/{slug}")
def editor_page(slug: str | None = None):
    """Serve the shell with content-addressed asset paths.

    `RevalidatedStaticFiles` only governs responses served from now on; it
    cannot reach a copy the browser already holds under an earlier heuristic
    freshness window, which is how a tablet keeps running last week's
    editor.js after a deploy. Stamping the content hash into the PATH
    sidesteps that: the page names a URL the browser has never seen, so there
    is nothing cached to reuse. The two mechanisms are complementary -- the
    hash fixes the changeover, no-cache keeps steady-state loads honest.

    The page itself is `no-cache` for the same bootstrap reason: a
    heuristically cached shell would keep naming the OLD hashes and defeat
    the whole scheme.
    """
    html = (config.WEB_DIR / "index.html").read_text(encoding="utf-8")

    def stamp(match: re.Match) -> str:
        stem, ext = match.group("stem"), match.group("ext")
        asset = config.WEB_DIR / f"{stem}.{ext}"
        if not asset.exists():
            return match.group(0)
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:8]
        return f'{match.group("attr")}="/static/{stem}-{digest}.{ext}"'

    return HTMLResponse(
        _ASSET_REF.sub(stamp, html),
        headers={"Cache-Control": "no-cache"},
    )


class RevalidatedStaticFiles(StaticFiles):
    """Serves /static, resolving a hashed filename back to the real asset.

    A hashed request (`editor-38d62b2d.js`, produced by `editor_page`'s
    `stamp`) gets a far-future `immutable` Cache-Control, same as the
    content-hashed S3 objects `editor/images.py`/`editor/videos.py` upload --
    the URL changes whenever the bytes do, so nothing stale can ever be
    addressed. The hash in the request is NOT verified against the current
    file's hash before serving: unlike the S3 objects, only one copy of
    editor.js exists on disk, so there is no "version" to look up by hash --
    it is purely a cache-busting token on top of the single current file. A
    request naming a now-stale hash (e.g. a bfcache'd tab reloading after a
    deploy) simply gets today's file, which is correct: that tab was going to
    end up on the current editor either way, and it never had that hash's
    bytes cached under that exact URL to begin with.

    A request for the plain, unhashed name (`editor.js` — a browser tab still
    holding an old page that never got the hashed URL) still resolves, but
    with StaticFiles' base ETag/Last-Modified plus `no-cache`. StaticFiles
    sends no Cache-Control of its own, and with none a browser falls back to
    *heuristic* freshness -- commonly 10% of the file's age since
    Last-Modified, which is how a long-unchanged editor.js earns itself a
    multi-hour window and a just-shipped feature looks "cached" and missing.
    `no-cache` means "revalidate", not "don't store": the ETag still does the
    work and an unchanged file costs one 304 over the LAN. Set in
    `get_response` rather than `file_response` so it lands on that 304 too.
    """

    async def get_response(self, path, scope):
        hashed = _HASHED_ASSET.match(path)
        real_path = f'{hashed.group("stem")}.{hashed.group("ext")}' if hashed else path
        response = await super().get_response(real_path, scope)
        if hashed:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


# Mounted last, and not at "/", so it can't shadow the routes above (a
# StaticFiles mount at the same prefix as a decorated route wins by
# registration order in Starlette, so this has to come after them).
app.mount("/static", RevalidatedStaticFiles(directory=config.WEB_DIR), name="static")
