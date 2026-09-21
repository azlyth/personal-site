"""Prepare uploaded photos and put them in S3.

Same pipeline as scripts/upload-image.py: re-encoding is what strips EXIF (and
with it, the GPS coordinates a phone camera attaches), and content-addressed
keys make the far-future Cache-Control safe -- different bytes always get a
different URL.
"""
from __future__ import annotations

import hashlib
import html
import io
import re

from PIL import Image, ImageOps

IMAGE_HOST = "img.cloudy.nyc"
CACHE_CONTROL = "public, max-age=31536000, immutable"


def process_image(data: bytes, max_edge: int = 1600, quality: int = 85) -> bytes:
    img = Image.open(io.BytesIO(data))
    # Apply the orientation tag before dropping EXIF, or phone photos rotate.
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    width, height = img.size
    longest = max(width, height)
    if longest > max_edge:
        scale = max_edge / longest
        img = img.resize((round(width * scale), round(height * scale)), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40]


def image_key(post_slug: str, alt_text: str, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:8]
    stem = _slugify(alt_text)
    name = f"{stem}-{digest}" if stem else digest
    return f"{post_slug}/{name}.jpg"


_MD_IMAGE_RE = re.compile(r"^!\[(?P<alt>.*)\]\((?P<url>[^)]*)\)$", re.S)
_IMG_TAG_RE = re.compile(r'<img\s+src="(?P<url>[^"]*)"\s+alt="(?P<alt>[^"]*)"\s*/?>')


def parse_images(kind: str, source: str) -> list[dict] | None:
    """The inverse of `markdown_for`: pull `{url, alt}` pairs back out of an
    `image` or `img_row` block's markdown source, undoing the escaping
    `markdown_for` applied on the way in.

    Enumerating every shape hand-written (or otherwise non-canonical) markup
    can take -- a missing `alt`, single-quoted attributes, an extra element
    inside an `.img-row`, a future format this parser doesn't know -- is a
    losing game, and getting it wrong is dangerous: the caller feeds
    whatever this returns straight into the thumbnail editor, and an image
    this parser silently dropped is gone the moment the user hits Done.
    Instead of trying to match harder, verify losslessness generically:
    regenerate markup from the parsed pairs via `markdown_for` and require
    it to reproduce `source` exactly. Anything that doesn't -- including
    shapes nobody's thought of yet -- returns `None`, and the caller must
    fall back to editing the block as raw source.

    Returns `None`, not `[]`, when the block isn't safely representable.
    That distinction matters: an `img_row` block whose `<img>` tags all
    fail to match still has *some* photos in it, and `[]` would read to a
    caller as "an intentionally empty row" rather than "couldn't parse
    this" -- indistinguishable from a state that's supposed to delete the
    block.
    """
    if kind == "image":
        match = _MD_IMAGE_RE.match(source.strip())
        if not match:
            return None
        alt = match.group("alt").replace("\\]", "]").replace("\\[", "[")
        images = [{"url": match.group("url"), "alt": alt}]
    elif kind == "img_row":
        images = [
            {"url": match.group("url"), "alt": html.unescape(match.group("alt"))}
            for match in _IMG_TAG_RE.finditer(source)
        ]
    else:
        return None

    try:
        regenerated = markdown_for([img["url"] for img in images], [img["alt"] for img in images])
    except ValueError:
        # Unreachable in practice -- urls/alts come from the same list
        # comprehension above and are always equal length -- but stay
        # defensive rather than let a future refactor turn this into a 500.
        return None

    return images if regenerated == source.strip() else None


def markdown_for(urls: list[str], alts: list[str]) -> str:
    """One image is a standalone; several become an .img-row.

    Alt text is free-form input typed by a person, so it's escaped for
    whichever context it lands in: `]`/`[` (and a collapsed newline) for the
    markdown link, HTML entities (and a collapsed newline) for the <img> tag.
    """
    if len(urls) != len(alts):
        raise ValueError(
            f"urls and alts must be the same length (got {len(urls)} urls, {len(alts)} alts)"
        )

    if len(urls) == 1:
        alt = alts[0].replace("\n", " ").replace("[", "\\[").replace("]", "\\]")
        return f"![{alt}]({urls[0]})"

    lines = ['<div class="img-row">']
    for url, alt in zip(urls, alts):
        safe_alt = html.escape(alt.replace("\n", " "), quote=True)
        lines.append(f'<img src="{url}" alt="{safe_alt}">')
    lines.append("</div>")
    return "\n".join(lines)


def upload(data: bytes, key: str, bucket: str, client) -> str:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType="image/jpeg",
        CacheControl=CACHE_CONTROL,
    )
    return f"https://{IMAGE_HOST}/{key}"
