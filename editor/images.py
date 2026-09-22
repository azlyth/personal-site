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
_IMG_ROW_OPEN_RE = re.compile(
    r'^<div class="img-row(?: size-(?P<size>[a-z]+))?(?: beside-(?P<side>[a-z]+))?">'
)

DEFAULT_SIZE = "full"
_VALID_SIZES = {"small", "medium", "full"}
# Which side of the text the row floats to, if any -- same vocabulary and
# same default-writes-nothing rule as videos.py's.
DEFAULT_SIDE = "none"
_VALID_SIDES = {"none", "left", "right"}


def parse_images(kind: str, source: str) -> dict | None:
    """The inverse of `markdown_for`: pull `{size, side, images}` back out of an
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

    An `.img-row` with no `size-*` class at all (every row written before
    this feature existed) defaults to `DEFAULT_SIZE` -- same discipline as
    the missing-alt case above: absence of a size class must still parse,
    or every already-published photo row would silently lose its thumbnail
    editor the moment this shipped.

    Returns `None`, not `{"size": ..., "images": []}`, when the block isn't
    safely representable. That distinction matters: an `img_row` block
    whose `<img>` tags all fail to match still has *some* photos in it, and
    an empty list would read to a caller as "an intentionally empty row"
    rather than "couldn't parse this" -- indistinguishable from a state
    that's supposed to delete the block.
    """
    if kind == "image":
        match = _MD_IMAGE_RE.match(source.strip())
        if not match:
            return None
        alt = match.group("alt").replace("\\]", "]").replace("\\[", "[")
        images = [{"url": match.group("url"), "alt": alt}]
        size = DEFAULT_SIZE
        side = DEFAULT_SIDE
    elif kind == "img_row":
        stripped = source.strip()
        open_match = _IMG_ROW_OPEN_RE.match(stripped)
        if not open_match:
            return None
        size = open_match.group("size") or DEFAULT_SIZE
        side = open_match.group("side") or DEFAULT_SIDE
        images = [
            {"url": match.group("url"), "alt": html.unescape(match.group("alt"))}
            for match in _IMG_TAG_RE.finditer(stripped)
        ]
    else:
        return None

    try:
        regenerated = markdown_for(
            [img["url"] for img in images], [img["alt"] for img in images], size, side
        )
    except ValueError:
        # size isn't one of the three real presets, the side isn't a real
        # side (or is an impossible full-width float), or urls/alts somehow
        # ended up mismatched -- either way this block isn't safely
        # representable.
        return None

    if regenerated != source.strip():
        return None
    return {"size": size, "side": side, "images": images}


def markdown_for(
    urls: list[str], alts: list[str], size: str = DEFAULT_SIZE, side: str = DEFAULT_SIDE
) -> str:
    """One image at the default size is a standalone markdown link; anything
    else -- several images, or a single image at a non-default size -- is a
    `.img-row` div.

    Sizing is opt-in for a lone photo: only picking a non-default size
    promotes it to the div shape, so a post nobody has resized stays plain
    markdown byte-for-byte. An `.img-row` at the default size still omits
    the size class entirely (not `size-full`) for the same reason on the
    multi-photo side -- every row written before this feature existed has
    no class at all, and this keeps those byte-identical too.

    `side` floats the row so the text after it flows alongside, as a third
    class after the size (`img-row size-small beside-right`). The default
    `none` writes nothing. A side is only legal below full width -- there'd
    be no column left for the text -- so a floated row is always the
    wrapped div shape and never collides with the lone-default-photo rule
    above.

    Alt text is free-form input typed by a person, so it's escaped for
    whichever context it lands in: `]`/`[` (and a collapsed newline) for the
    markdown link, HTML entities (and a collapsed newline) for the <img> tag.
    """
    if len(urls) != len(alts):
        raise ValueError(
            f"urls and alts must be the same length (got {len(urls)} urls, {len(alts)} alts)"
        )
    if size not in _VALID_SIZES:
        raise ValueError(f"unknown image row size {size!r} (must be one of {sorted(_VALID_SIZES)})")
    if side not in _VALID_SIDES:
        raise ValueError(f"unknown image row side {side!r} (must be one of {sorted(_VALID_SIDES)})")
    if side != DEFAULT_SIDE and size == DEFAULT_SIZE:
        raise ValueError(
            "a full-width row can't float beside text -- there is no column left for the text "
            "to flow into. Pick 'small' or 'medium'."
        )

    if len(urls) == 1 and size == DEFAULT_SIZE:
        alt = alts[0].replace("\n", " ").replace("[", "\\[").replace("]", "\\]")
        return f"![{alt}]({urls[0]})"

    class_attr = "img-row" if size == DEFAULT_SIZE else f"img-row size-{size}"
    if side != DEFAULT_SIDE:
        class_attr += f" beside-{side}"
    lines = [f'<div class="{class_attr}">']
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
