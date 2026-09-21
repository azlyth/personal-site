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

from editor.images import _slugify

VIDEO_HOST = "img.cloudy.nyc"
CACHE_CONTROL = "public, max-age=31536000, immutable"

WIDTH = 640
CRF = 26


def process_video(data: bytes) -> bytes:
    """Re-encode a clip the same way scripts/upload-video.py does -- muted
    H.264 scaled to `WIDTH` wide -- but from/to bytes so a request handler
    can call it without ever writing into the post or a durable path.
    """
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in"
        dst = Path(tmp) / "out.mp4"
        src.write_bytes(data)
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-i", str(src),
                # -map_metadata -1 drops container/global metadata. Phone
                # clips carry GPS (TAG:location/location-eng) and device
                # info (TAG:com.android.model/manufacturer) at the format
                # level, and ffmpeg copies it across a re-encode by
                # default -- this is the video equivalent of images.py's
                # EXIF strip. Verified empirically with ffprobe: on real
                # Pixel clips these tags live only in format_tags, never
                # stream_tags, so -map_metadata -1 alone is sufficient.
                "-map_metadata", "-1",
                "-vf", f"scale={WIDTH}:-2",
                "-an", "-c:v", "libx264", "-crf", str(CRF),
                "-preset", "medium", "-profile:v", "high",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
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

_VIDEO_ROW_OPEN_RE = re.compile(r'^<div class="video-row size-(?P<size>[a-z]+)">')
_VIDEO_TAG_RE = re.compile(
    r'<video autoplay loop muted playsinline(?: data-sync-loop="(?P<sync>[^"]*)")?>\n'
    r'<source src="(?P<url>[^"]*)" type="video/mp4">\n'
    r'</video>'
)


def parse_videos(kind: str, source: str) -> dict | None:
    """The inverse of `markdown_for`: pull `{size, videos}` back out of a
    `video` block's markdown source.

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

    videos = [
        {"url": match.group("url"), "sync_loop": match.group("sync")}
        for match in _VIDEO_TAG_RE.finditer(stripped)
    ]
    if not videos:
        return None

    try:
        regenerated = markdown_for(videos, size)
    except ValueError:
        # size isn't one of the three real presets, or somehow videos ended
        # up empty -- either way this block isn't safely representable.
        return None

    return {"size": size, "videos": videos} if regenerated == stripped else None


def markdown_for(videos: list[dict], size: str) -> str:
    """A `.video-row` wrapper around one or more `<video>` clips.

    Every row gets the wrapper -- unlike images, a single video is still
    wrapped (`videos.py` has no standalone-video shape) so it always has a
    size to control. `sync_loop`, when present, is carried through onto
    `data-sync-loop` verbatim (another feature keys off that exact string);
    when it's `None` the attribute is omitted entirely, not written empty.
    """
    if size not in _VALID_SIZES:
        raise ValueError(f"unknown video row size {size!r} (must be one of {sorted(_VALID_SIZES)})")
    if not videos:
        raise ValueError("videos must be non-empty -- an empty row should be deleted, not written")

    lines = [f'<div class="video-row size-{size}">']
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
