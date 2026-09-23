#!/usr/bin/env python3
"""Cut static/og-card.jpg -- the picture a link to this site shares as.

`templates/macros/preview.html` falls back to this for any page with no
photo of its own: the home page, the blog index, /lab, /timeline, and every
text-only post. It is a crop of static/home.jpg rather than a second
photograph, so the card and the home page are visibly the same place.

**1200x630 (1.91:1) is the size to hit, and it is not arbitrary.** That is
what Facebook, Slack, iMessage and X all crop `summary_large_image` to, and a
square source (home.jpg is 1600x1600) gets centre-cropped by each of them
slightly differently -- so the framing is decided here, once, rather than by
whoever happens to be rendering the card.

Re-run after changing home.jpg: python3 scripts/build-og-card.py
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "static" / "home.jpg"
OUT = ROOT / "static" / "og-card.jpg"

WIDTH, HEIGHT = 1200, 630

# Where the 1.91:1 window sits on the square source. Measured, not centred:
# a centred crop clips the cat's ears against the top edge, and the frame
# wants the keyboard along the bottom third with the skyline behind it.
CROP_TOP = 660

# 88 rather than 85: this one image is fetched by crawlers and rendered large
# on someone else's screen, and the file is a few KB either way.
QUALITY = 88


def main() -> None:
    src = Image.open(SRC)
    width, _ = src.size
    height = round(width / (WIDTH / HEIGHT))

    card = src.crop((0, CROP_TOP, width, CROP_TOP + height))
    card = card.resize((WIDTH, HEIGHT), Image.LANCZOS)
    # Re-encoding is what strips EXIF here, the same as editor/images.py --
    # home.jpg is a phone photo taken in the flat this site is written in.
    card.convert("RGB").save(OUT, "JPEG", quality=QUALITY, optimize=True)
    print(f"wrote {OUT} ({WIDTH}x{HEIGHT}, {OUT.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
