#!/usr/bin/env python3
"""Turn the hand-drawn cat (design/cat-favicon-source.png) into the favicon set.

The drawing is black ink on white with a pink tongue. Three masks are pulled out
of it -- ink, tongue, and the filled head silhouette -- so the icon can sit on a
transparent background and stay legible on light and dark tab strips.

Needs potrace for the SVG. Run: python3 scripts/build-favicons.py
"""
import subprocess
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "design" / "cat-favicon-source.png"
OUT = ROOT / "static"

INK = (26, 26, 26)
TONGUE = (255, 152, 151)

# Crop box on the source. The bottom edge cuts the head at y=250, where both
# sides of the outline are still present -- below that the jaw is open and the
# silhouette can't be closed.
CROP = (15, -12, 277, 250)
WHISKERS = {6, 7, 8, 9, 10, 11}  # component ids, dropped from the 16px icon


def masks(img):
    """Split the drawing into (ink, tongue) boolean masks."""
    a = np.asarray(img.convert("RGB")).astype(int)
    lum = a @ [0.299, 0.587, 0.114]
    ink = lum < 140
    tongue = (a[:, :, 0] > 200) & ((a[:, :, 0] - a[:, :, 1]) > 40) & ~ink
    return ink, tongue


def label(mask):
    h, w = mask.shape
    lab = np.zeros((h, w), int)
    n = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not lab[y, x]:
                n += 1
                lab[y, x] = n
                q = deque([(y, x)])
                while q:
                    cy, cx = q.popleft()
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                                lab[ny, nx] = n
                                q.append((ny, nx))
    return lab, n


def crop(mask, box):
    """Crop a boolean mask, padding with False where the box runs off-canvas."""
    img = Image.fromarray((mask * 255).astype("uint8"))
    return np.asarray(img.crop(box)) > 128


def silhouette(ink):
    """Filled head shape: everything the outline encloses, plus the outline."""
    sealed = ink.copy()
    sealed[-1, :] = True  # close the cropped-off jaw along the bottom edge
    h, w = sealed.shape
    outside = np.zeros_like(sealed)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not sealed[y, x] and not outside[y, x]:
                outside[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if not sealed[y, x] and not outside[y, x]:
                outside[y, x] = True
                q.append((y, x))
    while q:
        cy, cx = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and not sealed[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                q.append((ny, nx))
    return ~outside


def to_img(mask):
    return Image.fromarray((mask * 255).astype("uint8"))


def render(head, tongue, ink, size, background=None):
    """Composite the three masks down to one RGBA icon."""
    box = (size, size)
    h = to_img(head).resize(box, Image.LANCZOS)
    t = to_img(tongue).resize(box, Image.LANCZOS)
    i = to_img(ink).resize(box, Image.LANCZOS)
    out = Image.new("RGBA", box, (255, 255, 255, 0) if background is None else background)
    out.paste(Image.new("RGBA", box, (255, 255, 255, 255)), (0, 0), h)
    out.paste(Image.new("RGBA", box, TONGUE + (255,)), (0, 0), t)
    out.paste(Image.new("RGBA", box, INK + (255,)), (0, 0), i)
    return out


def trace(mask, colour, scale=1):
    """potrace a boolean mask into a bare <path d="..."> string."""
    h, w = mask.shape
    pbm = ROOT / ".favicon-trace.pbm"
    svg = ROOT / ".favicon-trace.svg"
    with open(pbm, "wb") as f:
        f.write(b"P4\n%d %d\n" % (w, h))
        f.write(np.packbits(mask, axis=1).tobytes())
    subprocess.run(
        ["potrace", "-s", "-a", "1.0", "-t", "2", "-O", "0.2",
         "-W", f"{w * scale}pt", "-H", f"{h * scale}pt", "-o", str(svg), str(pbm)],
        check=True,
    )
    body = svg.read_text()
    paths = []
    for chunk in body.split('<path')[1:]:
        d = chunk.split('d="')[1].split('"')[0]
        paths.append(d)
    transform = body.split('<g transform="')[1].split('"')[0]
    pbm.unlink()
    svg.unlink()
    return f'<g transform="{transform}" fill="{colour}" fill-rule="evenodd">' + \
        "".join(f'<path d="{d}"/>' for d in paths) + "</g>"


def main():
    src = Image.open(SRC)
    ink_full, tongue_full = masks(src)
    lab, n = label(ink_full)

    ink = crop(ink_full, CROP)
    tongue = crop(tongue_full, CROP)
    head = silhouette(ink)

    # 16px can't hold the whiskers -- they grey out into the outline. Drop them
    # and fatten what's left so the cat still reads at tab size.
    bare = crop(ink_full & ~np.isin(lab, list(WHISKERS)), CROP)
    tiny_ink = np.asarray(to_img(bare).filter(ImageFilter.MaxFilter(3))) > 128
    tiny_tongue = np.asarray(to_img(tongue).filter(ImageFilter.MaxFilter(3))) > 128

    OUT.mkdir(exist_ok=True)
    size = ink.shape[0]

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">'
        + trace(head, "#ffffff")
        + trace(tongue, "#%02x%02x%02x" % TONGUE)
        + trace(ink, "#%02x%02x%02x" % INK)
        + "</svg>"
    )
    (OUT / "favicon.svg").write_text(svg)

    # Loose PNGs are only for eyeballing the result; the site ships the three
    # files below.
    preview = ROOT / "design" / "preview"
    preview.mkdir(parents=True, exist_ok=True)
    for px in (32, 48, 180, 512):
        render(head, tongue, ink, px).save(preview / f"cat-{px}.png")

    # Apple wants an opaque square -- iOS composites on black otherwise.
    render(head, tongue, ink, 180, background=(255, 255, 255, 255)).save(
        OUT / "apple-touch-icon.png"
    )

    ico_16 = render(silhouette(tiny_ink), tiny_tongue, tiny_ink, 16)
    ico_16.save(preview / "cat-16.png")
    # Pillow drops requested sizes larger than the base image, so the .ico is
    # saved from the 48px frame with the smaller ones handed in explicitly.
    render(head, tongue, ink, 48).save(
        OUT / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[ico_16, render(head, tongue, ink, 32)],
    )
    print(f"wrote favicon.svg ({len(svg)} bytes), favicon.ico, apple-touch-icon.png "
          f"in {OUT}, previews in {preview}")


if __name__ == "__main__":
    main()
