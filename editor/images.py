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
