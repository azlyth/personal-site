"""A paired section: a picture and a bounded run of prose, side by side and
vertically centred.

Same discipline as images.py/videos.py -- `parse_pair` is only trusted when
what it parsed regenerates the source byte-for-byte, so a hand-edited or
otherwise non-canonical pair falls back to raw editing instead of being
silently rewritten into something smaller.
"""

import pytest

from editor.pairs import markdown_for, parse_pair

TEXT = "First paragraph with *emphasis*.\n\nSecond paragraph."


ROW = ('<div class="img-row size-medium">\n'
       '<img src="https://img.cloudy.nyc/p/a.jpg" alt="a cat">\n'
       "</div>")


def _photo(**over):
    args = dict(media_source=ROW, text=TEXT, side="right", size="medium")
    args.update(over)
    return markdown_for(**args)


# --- markdown_for -----------------------------------------------------------


def test_the_wrapper_carries_the_side_and_size():
    assert _photo().startswith('<div class="pair pair-right size-medium">')


def test_the_prose_is_separated_by_blank_lines():
    """That separation is the whole mechanism: without it CommonMark treats
    the text as literal HTML and the markdown never renders.
    """
    out = _photo()
    assert '<div class="pair-text">\n\nFirst paragraph' in out
    assert "Second paragraph.\n\n</div>" in out


def test_the_media_column_holds_the_row_verbatim():
    """Carried through untouched so pairing never regenerates the picture --
    and so the existing row editors still recognise it.
    """
    assert f'<div class="pair-media">\n{ROW}\n</div>' in _photo()


def test_it_closes_with_the_two_divs_the_parser_looks_for():
    assert _photo().endswith("</div>\n</div>")


def test_a_video_pairs_too():
    clip = ('<div class="video-row size-small">\n'
            '<video autoplay loop muted playsinline>\n'
            '<source src="https://img.cloudy.nyc/p/a.mp4" type="video/mp4">\n'
            "</video>\n"
            "</div>")
    out = markdown_for(media_source=clip, text=TEXT, side="left", size="small")
    assert '<div class="pair pair-left size-small">' in out
    assert clip in out


def test_it_rejects_an_unknown_side():
    with pytest.raises(ValueError):
        _photo(side="sideways")


def test_it_rejects_an_unknown_size():
    with pytest.raises(ValueError):
        _photo(size="huge")


def test_it_rejects_a_full_width_pair():
    """Full width leaves no second column -- the same reason a full-width row
    can't float.
    """
    with pytest.raises(ValueError):
        _photo(size="full")


def test_it_rejects_empty_prose():
    """An empty text column is a picture with a stray box beside it; the
    author wanted an ordinary row.
    """
    with pytest.raises(ValueError):
        _photo(text="   ")


# --- parse_pair -------------------------------------------------------------


def test_parse_pair_round_trips():
    assert parse_pair("pair", _photo()) == {
        "side": "right",
        "size": "medium",
        "justify": "center",
        "media_source": ROW,
        "text": TEXT,
    }


def test_parse_pair_keeps_multi_paragraph_prose_intact():
    out = parse_pair("pair", _photo(text="One.\n\nTwo.\n\nThree."))
    assert out["text"] == "One.\n\nTwo.\n\nThree."


def test_parse_pair_reads_the_left_side_back():
    assert parse_pair("pair", _photo(side="left"))["side"] == "left"


def test_parse_pair_rejects_a_different_kind():
    assert parse_pair("paragraph", "Some text.") is None


def test_parse_pair_rejects_markup_it_cannot_reproduce():
    """The guard that matters: anything this can't regenerate byte-for-byte
    must fall back to raw editing rather than being rewritten smaller.
    """
    hand_edited = _photo().replace(
        '<div class="pair-media">', '<div class="pair-media" data-note="hand">'
    )
    assert parse_pair("pair", hand_edited) is None


def test_parse_pair_rejects_an_unknown_size_class():
    assert parse_pair("pair", _photo().replace("size-medium", "size-enormous")) is None


def test_parse_pair_survives_prose_containing_a_div():
    """A code fence or inline html in the prose must not be mistaken for the
    wrapper's own closing tags.
    """
    text = "Before.\n\n    <div>indented code</div>\n\nAfter."
    parsed = parse_pair("pair", markdown_for(
        media_source=ROW, text=text, side="right", size="medium"))
    assert parsed is not None
    assert parsed["text"] == text


# --- justify: how the prose sits against the picture ------------------------
# Centred is right when the section is short. When it nearly fills the
# picture's height, "spread" reads better: first block against the top edge,
# last against the bottom, the slack shared out between them.


def test_justify_defaults_to_centred_and_writes_no_class():
    assert _photo().startswith('<div class="pair pair-right size-medium">')


def test_spread_adds_a_justify_class():
    out = _photo(justify="spread")
    assert out.startswith('<div class="pair pair-right size-medium justify-spread">')


def test_top_adds_a_justify_class():
    assert _photo(justify="top").startswith(
        '<div class="pair pair-right size-medium justify-top">'
    )


def test_it_rejects_an_unknown_justify():
    with pytest.raises(ValueError):
        _photo(justify="sideways")


def test_parse_pair_reads_the_justify_back():
    assert parse_pair("pair", _photo(justify="spread"))["justify"] == "spread"


def test_parse_pair_reports_no_justify_class_as_centred():
    assert parse_pair("pair", _photo())["justify"] == "center"


def test_parse_pair_rejects_an_unknown_justify_class():
    assert parse_pair("pair", _photo().replace(
        'size-medium"', 'size-medium justify-sideways"')) is None
