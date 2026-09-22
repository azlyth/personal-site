"""Prepare uploaded video clips and put them in S3.

Mirrors editor/images.py's shape exactly: a `parse_videos`/`markdown_for`
pair that is only trusted when the parse provably round-trips
byte-for-byte, plus `process_video`/`video_key`/`upload` for the actual
transcode-and-store pipeline (same bucket and host as photos -- videos and
photos share img.cloudy.nyc, see scripts/upload-video.py).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

from editor.ffmpeg_args import STRIP_METADATA, encode_args, is_hdr, video_filter
from editor.images import _slugify

VIDEO_HOST = "img.cloudy.nyc"
CACHE_CONTROL = "public, max-age=31536000, immutable"


def process_video(data: bytes) -> bytes:
    """Re-encode a clip the same way scripts/upload-video.py does -- both use
    editor/ffmpeg_args.py -- but from/to bytes so a request handler can call
    it without ever writing into the post or a durable path.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in"
        dst = Path(tmp) / "out.mp4"
        src.write_bytes(data)
        hdr = is_hdr(str(src))
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(src),
                *STRIP_METADATA,
                "-vf", video_filter(hdr),
                *encode_args(hdr),
                str(dst),
            ],
            capture_output=True,
        )
        if result.returncode != 0 or not dst.exists():
            stderr = result.stderr.decode("utf-8", "replace").strip()
            raise ValueError(f"ffmpeg could not process this clip: {stderr[:500]}")
        return dst.read_bytes()


def video_key(post_slug: str, name_hint: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:8]
    stem = _slugify(name_hint)
    name = f"{stem}-{digest}" if stem else digest
    return f"{post_slug}/{name}.mp4"


_VALID_SIZES = {"small", "medium", "full"}
# Which side of the text the row floats to, if any. Orthogonal to size: a
# row is "medium, floated right", not a fourth size. `none` is the default
# and writes no class, so nothing published before this existed changes.
_VALID_SIDES = {"none", "left", "right"}
DEFAULT_SIDE = "none"

_VIDEO_ROW_OPEN_RE = re.compile(
    r'^<div class="video-row size-(?P<size>[a-z]+)(?: beside-(?P<side>[a-z]+))?">'
)
_VIDEO_TAG_RE = re.compile(
    r'<video autoplay loop muted playsinline(?: data-sync-loop="(?P<sync>[^"]*)")?>\n'
    r'<source src="(?P<url>[^"]*)" type="video/mp4">\n'
    r'</video>'
)


def parse_videos(kind: str, source: str) -> dict | None:
    """The inverse of `markdown_for`: pull `{size, side, videos}` back out
    of a `video` block's markdown source.

    Same discipline as `images.parse_images` and for the same reason: a
    hand-edited or otherwise non-canonical `<video>` tag this parser
    doesn't recognise must not be silently dropped from the row. Instead of
    trying to match every shape, regenerate markup from what was parsed via
    `markdown_for` and require it to reproduce `source` exactly -- anything
    that doesn't returns `None`, and the caller falls back to raw source
    editing. Returns `None`, not `{"size": ..., "videos": []}`, when every
    `<video>` in an otherwise well-formed row fails to match -- an empty
    list would read as "an intentionally empty row" to a caller, and the
    client's Done button deletes an "empty" block outright.
    """
    if kind != "video":
        return None

    stripped = source.strip()
    open_match = _VIDEO_ROW_OPEN_RE.match(stripped)
    if not open_match:
        return None
    size = open_match.group("size")
    side = open_match.group("side") or DEFAULT_SIDE

    videos = [
        {"url": match.group("url"), "sync_loop": match.group("sync")}
        for match in _VIDEO_TAG_RE.finditer(stripped)
    ]
    if not videos:
        return None

    try:
        regenerated = markdown_for(videos, size, side)
    except ValueError:
        # size isn't one of the three real presets, the side isn't one of
        # the three real sides (or is an impossible full-width float), or
        # somehow videos ended up empty -- either way this block isn't
        # safely representable.
        return None

    if regenerated != stripped:
        return None
    return {"size": size, "side": side, "videos": videos}


def markdown_for(videos: list[dict], size: str, side: str = DEFAULT_SIDE) -> str:
    """A `.video-row` wrapper around one or more `<video>` clips.

    Every row gets the wrapper -- unlike images, a single video is still
    wrapped (`videos.py` has no standalone-video shape) so it always has a
    size to control. `sync_loop`, when present, is carried through onto
    `data-sync-loop` verbatim (another feature keys off that exact string);
    when it's `None` the attribute is omitted entirely, not written empty.

    `side` floats the row so the text after it flows alongside. It is a
    third class *after* the size (`video-row size-medium beside-right`) and
    the default `none` writes nothing at all -- that is what keeps every
    row published before this feature existed byte-identical, the same
    reason `.img-row` omits `size-full`.
    """
    if size not in _VALID_SIZES:
        raise ValueError(f"unknown video row size {size!r} (must be one of {sorted(_VALID_SIZES)})")
    if side not in _VALID_SIDES:
        raise ValueError(f"unknown video row side {side!r} (must be one of {sorted(_VALID_SIDES)})")
    if side != DEFAULT_SIDE and size == "full":
        raise ValueError(
            "a full-width row can't float beside text -- there is no column left for the text "
            "to flow into. Pick 'small' or 'medium'."
        )
    if not videos:
        raise ValueError("videos must be non-empty -- an empty row should be deleted, not written")

    class_attr = f"video-row size-{size}"
    if side != DEFAULT_SIDE:
        class_attr += f" beside-{side}"
    lines = [f'<div class="{class_attr}">']
    for video in videos:
        attrs = "autoplay loop muted playsinline"
        sync_loop = video.get("sync_loop")
        if sync_loop is not None:
            attrs += f' data-sync-loop="{sync_loop}"'
        lines.append(f"<video {attrs}>")
        lines.append(f'<source src="{video["url"]}" type="video/mp4">')
        lines.append("</video>")
    lines.append("</div>")
    return "\n".join(lines)


def upload(data: bytes, key: str, bucket: str, client) -> str:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType="video/mp4",
        CacheControl=CACHE_CONTROL,
    )
    return f"https://{VIDEO_HOST}/{key}"
