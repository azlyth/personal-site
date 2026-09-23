"""`.video-row.size-{small,medium,full}` and `.img-row.size-{small,medium,full}`
are hand-duplicated across two files: `templates/base.html` (what the
published site uses) and `editor/web/editor.css` (what the editor uses),
each with a comment saying they're kept in sync manually. If someone edits
one and not the other, the editor shows one size and the published page
another -- and it would only surface after publishing, when it's a live-site
visual bug rather than a failing test. This asserts the two never drift
instead of trusting the comment.
"""
from __future__ import annotations

import re

from editor import config

_SIZE_RE = re.compile(
    r'\.(?P<row>video-row|img-row)\.size-(?P<name>[a-z]+)\s*\{\s*max-width:\s*(?P<value>[^;]+?)\s*;'
)


def _sizes(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {"video-row": {}, "img-row": {}}
    for m in _SIZE_RE.finditer(text):
        out[m.group("row")][m.group("name")] = m.group("value")
    return out


def test_video_row_size_presets_match_between_site_and_editor():
    site_css = (config.REPO / "templates" / "base.html").read_text(encoding="utf-8")
    editor_css = (config.REPO / "editor" / "web" / "editor.css").read_text(encoding="utf-8")

    site_sizes = _sizes(site_css)
    editor_sizes = _sizes(editor_css)

    # Fails loudly (rather than vacuously passing on two empty dicts) if
    # either file's markup changes shape and the regex stops matching.
    assert site_sizes["video-row"] == {"small": "15rem", "medium": "26.25rem", "full": "100%"}
    assert editor_sizes["video-row"] == site_sizes["video-row"]


def test_img_row_size_presets_match_between_site_and_editor():
    site_css = (config.REPO / "templates" / "base.html").read_text(encoding="utf-8")
    editor_css = (config.REPO / "editor" / "web" / "editor.css").read_text(encoding="utf-8")

    site_sizes = _sizes(site_css)
    editor_sizes = _sizes(editor_css)

    # Same widths as the video presets -- there's no reason a photo row
    # should cap at a different size than a video row.
    assert site_sizes["img-row"] == {"small": "15rem", "medium": "26.25rem", "full": "100%"}
    assert editor_sizes["img-row"] == site_sizes["img-row"]


_PAIR_RE = re.compile(
    r"\.pair\.size-(?P<name>[a-z]+)\s+\.pair-media\s*\{\s*width:\s*(?P<value>[^;]+?)\s*;"
)


def _pair_widths(text: str) -> dict[str, str]:
    """`width: auto` is skipped -- that's the narrow-screen reset, which is a
    grouped selector and would otherwise overwrite the real width."""
    out: dict[str, str] = {}
    for m in _PAIR_RE.finditer(text):
        if m.group("value") != "auto":
            out[m.group("name")] = m.group("value")
    return out


def test_pair_media_widths_match_between_site_and_editor():
    """The pair's picture column drifted in exactly the way the row presets
    did (px here, rem there) and had no test to say so."""
    site_css, editor_css = _css_pair()

    assert _pair_widths(site_css) == {"small": "15rem", "medium": "26.25rem"}
    assert _pair_widths(editor_css) == _pair_widths(site_css)


# --- the float ("beside") rules are duplicated across the same two files ----

# A rule whose selector mentions `.beside-`, plus its declaration block.
# Both files group the two row types (`.img-row.beside-left,
# .video-row.beside-left { ... }` -- they float identically), so the whole
# selector list is captured once and split below; matching one selector at a
# time would consume the group and never try the second name in it.
#
# Excluding `;` as well as braces from the selector keeps a match from running
# back through the previous rule's declarations, and comments are stripped
# first (they mention `beside-` too). Deliberately keyed on `.beside-` rather
# than parsing rules generically: base.html is a Tera template, and its
# `{{ ... }}` expressions defeat any regex that pairs braces on its own.
_BESIDE_RULE_RE = re.compile(r"(?P<sel>[^{};]*\.beside-[^{};]*)\{(?P<body>[^{}]*)\}")
_BESIDE_SEL_RE = re.compile(r"^\.(?P<row>video-row|img-row)\.beside-(?P<side>left|right)$")
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _floats(text: str) -> dict[str, str]:
    """Map `<row>.beside-<side>` to the float direction it declares.

    `float: none` is skipped -- that's the narrow-screen reset, which has its
    own test below, and it would otherwise overwrite the real direction.
    """
    out: dict[str, str] = {}
    for rule in _BESIDE_RULE_RE.finditer(_COMMENT_RE.sub("", text)):
        direction = re.search(r"float:\s*([a-z]+)\s*;", rule.group("body"))
        if not direction or direction.group(1) == "none":
            continue
        for selector in rule.group("sel").split(","):
            m = _BESIDE_SEL_RE.match(selector.strip())
            if m:
                out[f"{m.group('row')}.beside-{m.group('side')}"] = direction.group(1)
    return out


def _narrow_blocks(css: str) -> list[str]:
    """The FULL body of every `max-width: 700px` media query.

    Brace-counted rather than regex-matched: a non-greedy `.*?` up to the
    next closing brace stops at the end of the first rule INSIDE the query,
    which silently hides everything after it.
    """
    bodies = []
    for m in re.finditer(r"@media\s*\(max-width:\s*700px\)\s*\{", css):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        bodies.append(css[m.end():i - 1])
    return bodies


def _css_pair() -> tuple[str, str]:
    return (
        (config.REPO / "templates" / "base.html").read_text(encoding="utf-8"),
        (config.REPO / "editor" / "web" / "editor.css").read_text(encoding="utf-8"),
    )


def test_beside_float_directions_match_between_site_and_editor():
    site_css, editor_css = _css_pair()
    expected = {
        "img-row.beside-left": "left",
        "img-row.beside-right": "right",
        "video-row.beside-left": "left",
        "video-row.beside-right": "right",
    }
    assert _floats(site_css) == expected
    assert _floats(editor_css) == expected


def test_both_stylesheets_unfloat_a_beside_row_on_a_narrow_screen():
    """A 240px float against a phone leaves an unreadable measure beside it,
    so both files have to drop back to a centred row -- and the editor has to
    agree, or a tablet in portrait previews a layout the phone won't get.
    """
    for css in _css_pair():
        # Either file can hold several 700px blocks (base.html's timeline has
        # its own), so look for one that unfloats rather than assuming which.
        blocks = _narrow_blocks(css)
        assert blocks, "no 700px breakpoint found"
        assert any("beside-" in b and "float: none" in b for b in blocks)


def test_a_heading_after_a_floated_row_does_not_clear():
    """A section title has to be able to sit beside a photo, so the blanket
    heading clear is overridden after a float. The text simply flows around
    the row and reclaims the full width once past it -- how much ends up
    alongside depends on the reading width, which is the point.
    """
    site_css, _ = _css_pair()
    override = re.search(
        r":is\(\.img-row,\s*\.video-row\):is\(\.beside-left,\s*\.beside-right\)"
        r"\s*~\s*:is\(h1,\s*h2,\s*h3,\s*h4\)\s*\{(?P<body>[^}]*)\}",
        site_css,
    )
    assert override, "no heading override found after a floated row in base.html"
    assert re.search(r"clear:\s*none\s*;", override.group("body"))


def test_the_clear_marker_is_what_ends_a_run():
    """The marker carries the clear that headings no longer do."""
    site_css, _ = _css_pair()
    marker = re.search(r"\.clear-beside\s*\{(?P<body>[^}]*)\}", site_css)
    assert marker, "no .clear-beside rule in base.html"
    assert re.search(r"clear:\s*both\s*;", marker.group("body"))


def test_a_floated_rows_block_is_what_floats():
    """The BLOCK floats, not the row inside it.

    When the row alone floated it escaped its block, leaving a full-width,
    zero-height box lying across the picture: hovering the photo lit up
    whichever paragraph overlapped it, that paragraph's absolutely-positioned
    controls landed on top of the photo, and the photo's own controls
    appeared at the top-right of its invisible block. Floating the block
    gives it the picture's real dimensions so hover, clicks and controls all
    land on the picture.
    """
    _, editor_css = _css_pair()
    for side in ("left", "right"):
        bodies = [
            m.group("body") for m in re.finditer(
                rf"\.block\.beside-{side}\s*\{{(?P<body>[^}}]*)\}}", editor_css
            )
        ]
        assert bodies, f".block.beside-{side} has no rule"
        assert any(re.search(rf"float:\s*{side}\s*;", b) for b in bodies), bodies

    # And the row inside stops floating, or it would fight its own block.
    inner = re.search(
        r"\.block\.beside-left \.img-row,[^{]*\{(?P<body>[^}]*)\}", editor_css
    )
    assert inner, "no rule neutralising the row inside a floated block"
    assert re.search(r"float:\s*none\s*;", inner.group("body"))


def test_a_floated_block_measures_the_row_it_holds():
    """So a photo in the editor is the width it will be once published."""
    _, editor_css = _css_pair()
    widths = dict(
        re.findall(r"\.block\.size-(\w+)\s*\{\s*--row-w:\s*([^;]+?)\s*;", editor_css)
    )
    # Compared against the row presets rather than re-listing the numbers: a
    # third hand-written copy is a third place to forget, which is the exact
    # failure this file exists to catch.
    assert widths == _sizes(editor_css)["img-row"]

    sized = re.search(r"\.block\.beside-left,\s*\.block\.beside-right\s*\{(?P<body>[^}]*)\}", editor_css)
    assert sized, "no shared rule for a floated block"
    # The block adds its own padding/border on top of the row's width, so the
    # picture inside still measures exactly the published width.
    assert "var(--row-w)" in sized.group("body")
    assert "border-box" in sized.group("body")


def test_the_post_body_contains_its_own_floats():
    """A float belongs to the prose, not to the page.

    `.container` already establishes a block formatting context so a float
    can't escape the page entirely, but the post body inside it did not --
    so a photo taller than the writing next to it pushed past the end of the
    post and the "All posts" link and footer rode up alongside the picture.
    """
    site_css, _ = _css_pair()
    rule = re.search(r"\.blog-post-body\s*\{(?P<body>[^}]*)\}", site_css)
    assert rule, "no .blog-post-body rule in base.html"
    assert re.search(r"display:\s*flow-root\s*;", rule.group("body"))


def test_a_floated_row_clears_earlier_floats():
    """Two pictures close together must not sit alongside EACH OTHER.

    Without a clear, a second float slots into whatever space is left beside
    the first -- so two rows pair up, the prose is squeezed into a gutter
    between them, and a heading breaks one word per line. Each floated row
    starts its own wrap region instead.
    """
    site_css, editor_css = _css_pair()
    for css, selector in (
        (site_css, r"\.img-row\.beside-left,\s*\.video-row\.beside-left"),
        (editor_css, r"\.block\.beside-left"),
    ):
        rule = re.search(rf"{selector}\s*(?:,[^{{}}]*?)?\{{(?P<body>[^}}]*)\}}", css)
        assert rule, f"no rule matching {selector}"
        assert re.search(r"clear:\s*both\s*;", rule.group("body")), rule.group("body")


def test_a_floated_block_outranks_the_paragraphs_it_overlaps():
    """Or the picture can't be hovered or clicked.

    Every `.block` is `position: relative` so its controls can be absolutely
    positioned inside it -- and positioned boxes paint above floats. A
    following paragraph's box still spans the full column even though its
    text wraps away from the picture, so without a z-index it covers the
    photo: hovering lights up the paragraph and clicking opens a textarea.
    """
    _, editor_css = _css_pair()
    rule = re.search(
        r"\.block\.beside-left,\s*\.block\.beside-right\s*\{(?P<body>[^}]*)\}", editor_css
    )
    assert rule, "no shared rule for a floated block"
    assert re.search(r"z-index:\s*[1-9]", rule.group("body")), rule.group("body")


# --- paired sections --------------------------------------------------------


def _pair_rules(css):
    """Every declaration block per `.pair*` selector, in source order.

    A list rather than one body per selector: the narrow-screen media query
    re-declares `.pair`, and keeping only the last match would hide the real
    rule behind its own override.

    Selectors are stripped -- the character class that lets a descendant
    selector through also swallows the space before the brace.
    """
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"(?P<sel>\.pair[\w.\- >]*)\s*\{(?P<body>[^}]*)\}", css):
        out.setdefault(m.group("sel").strip(), []).append(m.group("body"))
    return out


def test_a_pair_is_a_centred_two_column_box_in_both_stylesheets():
    """The whole reason pairs exist: a float can only start text at the top
    of a picture, so a section meant to sit level with its picture needs the
    two in one container that can centre them.
    """
    for css in _css_pair():
        bodies = _pair_rules(css).get(".pair", [])
        assert bodies, "no .pair rule"
        assert any(re.search(r"display:\s*(flex|grid)\s*;", b) for b in bodies), bodies
        assert any(re.search(r"align-items:\s*center\s*;", b) for b in bodies), bodies


def test_a_pair_puts_the_picture_on_the_chosen_side():
    """`pair-left` means the picture is on the left, so the text column has
    to come first in visual order for `pair-right` -- the markup always has
    the media first.
    """
    for css in _css_pair():
        bodies = _pair_rules(css).get(".pair-right .pair-media", [])
        assert bodies, "no rule reordering the media for a right-hand pair"
        assert any(re.search(r"order:\s*[1-9]", b) for b in bodies), bodies


def test_a_pair_stacks_on_a_narrow_screen():
    """Same reason a floated row unfloats: below the reading column's width
    there is no room for two things side by side.
    """
    for css in _css_pair():
        blocks = _narrow_blocks(css)
        assert any(".pair" in b and "flex-direction: column" in b for b in blocks), \
            "no narrow-screen stacking rule for .pair"


def test_move_mode_costs_no_layout():
    """Picking a block up must not move the page.

    Move mode used to swap the block list for its own previews and insert a
    banner and N+1 drop targets, so everything shifted down exactly when you
    were trying to aim at it. Now it renders the real blocks and OVERLAYS the
    rest: the banner is fixed, the zones are absolutely positioned inside a
    layer, and out-of-flow boxes take up no space.
    """
    _, editor_css = _css_pair()
    for selector, expected in (
        (r"\.move-banner", "fixed"),
        (r"\.move-layer", "absolute"),
        (r"\.move-target", "absolute"),
    ):
        rule = re.search(rf"^{selector}\s*\{{(?P<body>[^}}]*)\}}", editor_css, re.M)
        assert rule, f"no {selector} rule"
        assert re.search(rf"position:\s*{expected}\s*;", rule.group("body")), rule.group("body")

    # The zones live in a containing block that is itself positioned, or
    # they'd resolve against the viewport and sit anywhere but the gaps.
    blocks_rule = re.search(r"#blocks\s*\{(?P<body>[^}]*)\}", editor_css)
    assert blocks_rule and "position: relative" in blocks_rule.group("body")


def test_a_text_blocks_box_stops_at_a_floated_picture():
    """Or the block you're hovering runs underneath the picture.

    A block beside a float keeps the full column width -- only its LINE boxes
    shorten -- so its border and hover background slid under the photo and
    vanished. A block formatting context doesn't overlap a float: the box
    narrows to the space actually left for it, which is where the text ends.
    """
    _, editor_css = _css_pair()
    rule = re.search(r"^\.block\s*\{(?P<body>[^}]*)\}", editor_css, re.M)
    assert rule, "no .block rule"
    assert re.search(r"display:\s*flow-root\s*;", rule.group("body")), rule.group("body")


def test_a_stacked_pair_puts_the_picture_after_the_text():
    """On a phone the section reads first and the picture follows it.

    Stacked, a picture on top pushes the words it belongs to off the screen
    -- you scroll past a photo to find out what it's of. The order only has
    to be forced for `pair-left`, whose media is first in markup; but both
    sides are written out so the rule says what it means.
    """
    for css in _css_pair():
        narrow = [b for b in _narrow_blocks(css) if ".pair" in b]
        assert narrow, "no narrow-screen pair rules"
        body = "\n".join(narrow)
        rule = re.search(
            r"\.pair-left \.pair-media,\s*\.pair-right \.pair-media\s*\{(?P<body>[^}]*)\}", body
        )
        assert rule, body
        assert re.search(r"order:\s*2\s*;", rule.group("body")), rule.group("body")


def test_the_spacer_is_the_same_height_in_both_stylesheets():
    """A spacer that previews shorter than it publishes is a gap you tune by
    guesswork. The editor sets it on the block itself, since a spacer block
    renders a label rather than its own html.
    """
    site_css, editor_css = _css_pair()
    site = re.search(r"\.post-spacer\s*\{\s*height:\s*([^;]+?)\s*;", site_css)
    editor = re.search(r"\.block\.spacer-block\s*\{\s*min-height:\s*([^;]+?)\s*;", editor_css)
    assert site, "no .post-spacer rule in base.html"
    assert editor, "no .spacer-block height in editor.css"
    assert site.group(1) == editor.group(1) == "2.5rem"


def test_a_desktop_only_spacer_collapses_on_a_narrow_screen():
    """The whole point of the variant: breathing room where there is width to
    spare, nothing on a phone, where the post is already a single column and
    the gap just reads as a scroll of blank screen. Pinned inside the same
    700px breakpoint the floats and pairs use, so "mobile" means one thing.
    """
    site_css, _ = _css_pair()
    narrow = [b for b in _narrow_blocks(site_css) if "post-spacer" in b]
    assert narrow, "no narrow-screen spacer rule in base.html"
    rule = re.search(
        r"\.post-spacer\.desktop-only\s*\{(?P<body>[^}]*)\}", "\n".join(narrow)
    )
    assert rule, narrow
    assert re.search(r"height:\s*0\s*;", rule.group("body")), rule.group("body")


def test_the_editor_marks_a_desktop_only_spacer_rather_than_hiding_it():
    """The editor is used on a tablet, above the breakpoint -- so a desktop-only
    spacer must still occupy its real height there. What changes is that it says
    so, or the two spacer kinds are indistinguishable in the one place you pick
    between them.
    """
    _, editor_css = _css_pair()
    rule = re.search(
        r"\.block\.spacer-block\.desktop-only\s*\{(?P<body>[^}]*)\}", editor_css
    )
    assert rule, "no desktop-only spacer rule in editor.css"
    assert "height: 0" not in rule.group("body")


def test_a_distributed_pair_stretches_only_its_text_column():
    """The slack goes between the prose blocks, not into the picture.

    Distributing needs the text column to be as tall as the picture, but
    stretching the PAIR would stretch the media column too -- and
    `.img-row img` carries `height: 100%; object-fit: cover`, so the photo
    would be cropped to whatever height the prose happened to want.
    """
    for css in _css_pair():
        for mode, expected in (("spread", "space-between"), ("evenly", "space-evenly")):
            bodies = [
                m.group("body") for m in re.finditer(
                    rf"\.pair\.justify-{mode} \.pair-text[^{{]*\{{(?P<body>[^}}]*)\}}", css
                )
            ]
            assert bodies, f"no .justify-{mode} .pair-text rule"
            joined = "\n".join(bodies)
            assert re.search(r"align-self:\s*stretch\s*;", joined), joined
            # A block box can't distribute its children; it has to be a column.
            assert re.search(r"flex-direction:\s*column\s*;", joined), joined
            assert re.search(rf"justify-content:\s*{expected}\s*;", joined), joined


def test_a_top_justified_pair_aligns_the_columns_to_the_top():
    for css in _css_pair():
        rule = re.search(r"\.pair\.justify-top\s*\{(?P<body>[^}]*)\}", css)
        assert rule, "no .justify-top rule"
        assert re.search(r"align-items:\s*flex-start\s*;", rule.group("body"))
