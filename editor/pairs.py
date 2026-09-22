"""A paired section: a picture and a bounded run of prose, side by side and
vertically centred.

This exists because floats cannot centre. A floated row lets the text flow
around it starting at the top of the picture, which is right for prose that
simply continues past a photo -- but a *section* meant to sit level with its
picture needs the two in one container, and that is what this writes.

The blank lines around the prose are the whole mechanism, not formatting:
CommonMark only parses markdown inside an HTML block once a blank line has
closed that block, so without them the text would render as literal HTML and
every link and emphasis in the section would die. The cost is that the
wrapper spans several top-level tokens, which `blocks.py::_group_pairs` folds
back into one block.

The media column holds an ordinary `.img-row`/`.video-row` div, verbatim.
That is deliberate: pairing and unpairing then move the row's source in and
out without regenerating it at all, and the existing thumbnail editors keep
working on a paired picture because it is still exactly the markup they
already parse.

Same trust discipline as `images.py` / `videos.py`: `parse_pair` returns
`None` for anything it cannot regenerate byte-for-byte, and the caller falls
back to editing raw source rather than rewriting a pair into a reduced one.
"""
from __future__ import annotations

import re

_VALID_SIDES = {"left", "right"}
# `full` is deliberately absent: a full-width pair leaves no second column,
# the same reason a full-width row can't float.
_VALID_SIZES = {"small", "medium"}
# How the prose sits against the picture, in flexbox terms:
#   center  -> the default, and writes no class
#   top     -> flex-start
#   spread  -> space-between: first block flush with the picture's top edge,
#              last flush with the bottom, all the slack between them
#   evenly  -> space-evenly: equal gaps everywhere, including above the first
#              block and below the last
DEFAULT_JUSTIFY = "center"
_VALID_JUSTIFY = {"center", "spread", "evenly", "top"}

_PAIR_RE = re.compile(
    r'^<div class="pair pair-(?P<side>[a-z]+) size-(?P<size>[a-z]+)(?: justify-(?P<justify>[a-z]+))?">\n'
    r'<div class="pair-media">\n'
    r"(?P<media>.*?)\n"
    r"</div>\n"
    r'<div class="pair-text">\n'
    r"\n"
    r"(?P<text>.*?)"
    r"\n\n"
    r"</div>\n"
    r"</div>$",
    re.S,
)


def parse_pair(kind: str, source: str) -> dict | None:
    """Pull `{side, size, media_html, text}` back out of a pair's source.

    Returns `None` when the block isn't a pair, or when what was parsed
    doesn't regenerate the source exactly -- see the module docstring.
    """
    if kind != "pair":
        return None

    match = _PAIR_RE.match(source.strip())
    if not match:
        return None

    parsed = {
        "side": match.group("side"),
        "size": match.group("size"),
        "justify": match.group("justify") or DEFAULT_JUSTIFY,
        "media_source": match.group("media"),
        "text": match.group("text"),
    }

    try:
        regenerated = markdown_for(**parsed)
    except ValueError:
        # Not one of the real sides/sizes, or empty prose -- either way this
        # block isn't safely representable.
        return None

    return parsed if regenerated == source.strip() else None


def markdown_for(
    media_source: str, text: str, side: str, size: str, justify: str = DEFAULT_JUSTIFY
) -> str:
    """Build a paired section around a media row.

    `media_source` is a whole `.img-row`/`.video-row` div exactly as it would
    appear on its own -- carried verbatim so pairing and unpairing never
    regenerate it, and so the row editors still recognise a paired picture.
    """
    if side not in _VALID_SIDES:
        raise ValueError(f"unknown pair side {side!r} (must be one of {sorted(_VALID_SIDES)})")
    if size not in _VALID_SIZES:
        raise ValueError(
            f"unknown pair size {size!r} (must be one of {sorted(_VALID_SIZES)}) -- "
            "a full-width pair leaves no column for the text"
        )
    if not text.strip():
        raise ValueError(
            "a pair needs prose beside the picture -- an empty text column is "
            "just a row, and should be written as one"
        )
    if justify not in _VALID_JUSTIFY:
        raise ValueError(
            f"unknown pair justify {justify!r} (must be one of {sorted(_VALID_JUSTIFY)})"
        )
    if not media_source.strip():
        raise ValueError("a pair needs a picture or a clip")

    classes = f"pair pair-{side} size-{size}"
    if justify != DEFAULT_JUSTIFY:
        classes += f" justify-{justify}"

    return (
        f'<div class="{classes}">\n'
        '<div class="pair-media">\n'
        f"{media_source.strip()}\n"
        "</div>\n"
        '<div class="pair-text">\n'
        "\n"
        f"{text.strip()}\n"
        "\n"
        "</div>\n"
        "</div>"
    )
