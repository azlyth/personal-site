#!/usr/bin/env python3
"""Check that an open text block stays open until you say Done (tablet sizes).

The bugs this pins, all from editing on the tablet:

- Tapping a long paragraph opened a textarea sized by its count of SOURCE
  lines, so a one-line paragraph that wraps to fifteen visual lines became a
  two-row box that scrolled. The block collapsed, the following blocks slid
  up into the space the text had filled, and the next tap "on the text"
  landed outside the field, blurred it, and blur closed the editor.
- Blur closing the editor at all: any tap that missed the field (the
  block's padding, a menu, the insert menu's Cancel) ended editing. An open
  editor now closes only on its Done button, or by opening another block.
- flushPendingEdit() found "the open textarea" with a selector that also
  matched a paired section's prose field, and saved that prose over the
  WHOLE pair block -- deleting its picture -- whenever a control was tapped
  with the pair editor open.

Runs in real headless Chromium with touch emulation, at three tablet
viewports, against a scratch draft written into content/blog and a scratch
uvicorn of THIS checkout on a free port with its own auth db under
~/.cache. All of them are removed afterwards; processes are killed by PID.

Needs `websocket-client` (installed for the system python3, not the venv)
and /usr/bin/chromium.

Usage: python3 scripts/verify-edit-tap.py [--shots DIR] [--shot-prefix NAME] [--viewport WxH ...]
  --shots writes DIR/<prefix>-<width>.png of the long paragraph open for
  editing at each viewport, and <prefix>-<width>-menu.png with the insert
  menu open.
Exits non-zero if any check fails.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import websocket

REPO = Path(__file__).resolve().parent.parent
BLOG = REPO / "content" / "blog"
SLUG = "zz-edit-tap-scratch"
POST = BLOG / f"{SLUG}.md"

LONG = (
    "This paragraph is one long source line on purpose, because that is the "
    "shape the bug needed: a paragraph with no hard line breaks wraps to many "
    "lines on screen but counts as a single line in the markdown. "
) * 6
PAIR = (
    '<div class="pair pair-right size-medium">\n<div class="pair-media">\n'
    '<div class="img-row size-medium">\n'
    '<img src="https://img.cloudy.nyc/p/a.jpg" alt="a cat">\n</div>\n</div>\n'
    '<div class="pair-text">\n\nWords beside the cat.\n\n</div>\n</div>'
)
BODY = (
    "+++\ntitle = \"Edit tap scratch\"\ndate = 2026-10-04\ndraft = true\n+++\n\n"
    "A short opening paragraph.\n\n"
    f"{LONG.strip()}\n\n"
    "A closing paragraph that follows the long one.\n\n"
    f"{PAIR}\n\n"
    "- one\n- two\n\n"
    "After the list.\n\n"
    "## A heading set in Sentient\n\n"
    "Final words.\n"
)
# Block indices in BODY.
FIRST, LONG_IDX, CLOSING, PAIR_IDX, LIST_IDX, AFTER_LIST, HEADING, FINAL = 0, 1, 2, 3, 4, 5, 6, 7

VIEWPORTS = [(1024, 1366), (1366, 1024), (820, 1180)]


def venv_python() -> str:
    for candidate in (
        os.environ.get("EDITOR_PYTHON"),
        REPO / "editor" / ".venv" / "bin" / "python",
        Path.home() / "projects/personal/personal-site/editor/.venv/bin/python",
    ):
        if candidate and Path(candidate).exists():
            return str(candidate)
    sys.exit("no editor venv python found; set EDITOR_PYTHON")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except urllib.error.HTTPError:
            return  # any status (healthz is behind auth) means it's up
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"{url} never answered")


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=30)
        self.n = 0

    def __call__(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        res = self("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in res:
            raise RuntimeError(f"JS error: {res['exceptionDetails']}")
        return res["result"].get("value")

    def tap(self, x: float, y: float, settle: float = 0.5) -> None:
        # A real touch tap: touchstart/touchend, then the synthesised
        # mousedown (which is what moves focus) and click.
        self("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        self("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        time.sleep(settle)

    def rect(self, selector: str) -> dict | None:
        return json.loads(self.js(
            f"(() => {{ const e = document.querySelector({json.dumps(selector)});"
            " if (!e) return 'null'; const r = e.getBoundingClientRect();"
            " if (!r.width || !r.height) return 'null';"
            " return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height}); })()"))

    def tap_el(self, selector: str, settle: float = 0.5) -> bool:
        # Scroll it into view first, like a person would.
        self.js(f"document.querySelector({json.dumps(selector)})"
                "?.scrollIntoView({block: 'center'})")
        time.sleep(0.15)
        r = self.rect(selector)
        if not r:
            return False
        self.tap(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2, settle)
        return True


STATE = """(() => {
  const ta = document.querySelector('.block.editing textarea');
  const ed = ta && ta.closest('.block');
  const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect();
    return {x: b.x, y: b.y, w: b.width, h: b.height, r: b.right, b: b.bottom}; };
  const bar = document.getElementById('edit-bar');
  const shown = bar && !bar.hidden;
  const menu = document.querySelector('.insert-choice');
  const buttons = shown ? [...bar.querySelectorAll('button')].map((b) => r(b)) : [];
  const ctl = shown ? bar.querySelectorAll('.block-controls') : [];
  return JSON.stringify({
    editing: ed ? Number(ed.dataset.index) : null,
    focused: !!ta && document.activeElement === ta,
    value: ta ? ta.value : null,
    ta: ta && {...r(ta), client: ta.clientHeight, scroll: ta.scrollHeight},
    font: ta ? getComputedStyle(ta).fontFamily : null,
    block: r(ed),
    bar: shown ? r(bar) : null,
    done: shown ? r(bar.querySelector('.edit-done')) : null,
    barControls: [...ctl].map((c) => Number(c.dataset.index)),
    menu: r(menu),
    buttons,
    vw: innerWidth, vh: innerHeight, sy: scrollY,
  });
})()"""


def state(cdp: CDP) -> dict:
    return json.loads(cdp.js(STATE))


def block_sel(i: int) -> str:
    return f'.block[data-index="{i}"]'


def load(cdp: CDP, base: str) -> None:
    POST.write_text(BODY)
    cdp("Page.navigate", url=f"{base}/edit/{SLUG}")
    for _ in range(80):
        time.sleep(0.25)
        try:
            if cdp.js(f"!!document.querySelector('{block_sel(PAIR_IDX)}')"):
                time.sleep(0.3)
                return
        except RuntimeError:
            pass
    raise RuntimeError("editor never rendered the scratch post")


def open_long(cdp: CDP) -> dict:
    cdp.js(f"document.querySelector('{block_sel(LONG_IDX)}').scrollIntoView({{block: 'start'}});"
           "scrollBy(0, -120)")
    time.sleep(0.2)
    b = cdp.rect(block_sel(LONG_IDX))
    # Two-thirds of the way down the paragraph: a spot that is text before
    # the tap, i.e. exactly where a reader aims.
    cdp.tap(b["x"] + b["w"] / 2, b["y"] + b["h"] * 0.66)
    return b


def overlaps(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return a["x"] < b["r"] - 1 and b["x"] < a["r"] - 1 and a["y"] < b["b"] - 1 and b["y"] < a["b"] - 1


def run_viewport(cdp, base, w, h, results, shots, prefix, only=()):
    cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
        deviceScaleFactor=1, mobile=True)
    cdp("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

    def check(name, ok, detail=None):
        results.append((f"{w}x{h} {name}", bool(ok), detail))

    def want(group):
        return not only or group in only

    if want("tap"):
        run_tap_cases(cdp, base, w, h, check, shots, prefix)
    if want("inplace"):
        run_in_place_cases(cdp, base, w, h, check, shots, prefix)
    if want("media"):
        run_media_cases(cdp, base, w, h, check, shots, prefix)
    if want("review"):
        run_review_cases(cdp, base, w, h, check)
    if want("align"):
        run_align_cases(cdp, base, w, h, check, shots, prefix)


def run_tap_cases(cdp, base, w, h, check, shots, prefix):

    def editing_long(s):
        return s["editing"] == LONG_IDX

    # --- open -------------------------------------------------------------
    load(cdp, base)
    before = open_long(cdp)
    s = state(cdp)
    check("open: editing and focused", editing_long(s) and s["focused"], s)
    if s["ta"]:
        check("open: textarea shows all its text",
              s["ta"]["client"] >= s["ta"]["scroll"] - 1, s["ta"])
        check("open: block keeps its height (within 25%)",
              s["block"]["h"] >= before["h"] * 0.75,
              {"before": before["h"], "after": s["block"]["h"]})
        check("open: the bar never overlaps the text",
              s["bar"] and not overlaps(s["bar"], s["ta"]), s)
        check("open: every bar button is a 44px target",
              s["buttons"] and all(b["w"] >= 43.5 and b["h"] >= 43.5 for b in s["buttons"]),
              s["buttons"])
        check("open: the bar sits at the bottom of the window with Done on screen",
              s["bar"] and abs(s["bar"]["b"] - s["vh"]) <= 1 and s["done"]
              and s["done"]["y"] >= 0 and s["done"]["b"] <= s["vh"]
              and s["done"]["x"] >= 0 and s["done"]["r"] <= s["vw"], s)
        check("open: the bar holds this block's controls and nothing else's",
              s["barControls"] == [LONG_IDX], s["barControls"])
    if shots:
        png = cdp("Page.captureScreenshot", format="png")["data"]
        Path(shots, f"{prefix}-{w}.png").write_bytes(base64.b64decode(png))

    # --- tap-again: the same spot as the opening tap, which was text --------
    cdp.tap(before["x"] + before["w"] / 2, before["y"] + before["h"] * 0.66)
    s = state(cdp)
    check("tap-again: same spot keeps editing", editing_long(s) and s["focused"], s)

    # --- tap-in -----------------------------------------------------------
    if not editing_long(s):
        load(cdp, base)
        open_long(cdp)
        s = state(cdp)
    if s["ta"]:
        t = s["ta"]
        cdp.tap(t["x"] + t["w"] / 2, t["y"] + t["h"] - 8)
        s = state(cdp)
        check("tap-in: still editing", editing_long(s) and s["focused"], s)

    # --- tap-pad: the block's own left padding, beside the field -----------
    if not editing_long(s):
        load(cdp, base)
        open_long(cdp)
        s = state(cdp)
    if s["block"]:
        b = s["block"]
        cdp.tap(b["x"] + 3, s["ta"]["y"] + s["ta"]["h"] / 2)
        s = state(cdp)
        check("tap-pad: still editing", editing_long(s) and s["focused"], s)

    # --- keyboard: type, shrink the viewport, restore ----------------------
    if not editing_long(s):
        load(cdp, base)
        open_long(cdp)
    cdp("Emulation.setDeviceMetricsOverride", width=w, height=int(h * 0.55),
        deviceScaleFactor=1, mobile=True)
    time.sleep(0.4)
    cdp("Input.insertText", text=" Typed while the keyboard was up.")
    time.sleep(0.2)
    cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
        deviceScaleFactor=1, mobile=True)
    time.sleep(0.4)
    s = state(cdp)
    check("keyboard: still editing", editing_long(s) and s["focused"], s)
    if s["ta"]:
        check("keyboard: still sized to its text",
              s["ta"]["client"] >= s["ta"]["scroll"] - 1, s["ta"])

    # --- insert menu: + then Cancel keeps the editor and its text ----------
    if not editing_long(s):
        load(cdp, base)
        open_long(cdp)
        cdp("Input.insertText", text=" Typed while the keyboard was up.")
    tapped = cdp.tap_el(PLUS, 1.0)
    s = state(cdp)
    check("insert menu: + keeps editing", tapped and editing_long(s), s)
    check("insert menu: menu doesn't cover the text",
          s["menu"] and not overlaps(s["menu"], s["ta"]), s)
    if shots:
        png = cdp("Page.captureScreenshot", format="png")["data"]
        Path(shots, f"{prefix}-{w}-menu.png").write_bytes(base64.b64decode(png))
    cancelled = cdp.tap_el(".insert-choice .insert-cancel", 0.6)
    s = state(cdp)
    check("insert menu: Cancel keeps editing, text intact",
          cancelled and editing_long(s)
          and "Typed while the keyboard was up." in (s["value"] or ""), s)

    # --- insert Above: the list shifts under the open editor -----------------
    if editing_long(s):
        cdp.tap_el(PLUS, 1.0)
        above = cdp.tap_el(".insert-choice button", 1.2)  # "↑ Above" is first
        s = state(cdp)
        check("insert above: editor follows its block down one",
              above and s["editing"] == LONG_IDX + 1
              and "Typed while the keyboard was up." in (s["value"] or ""), s)
        load(cdp, base)
        open_long(cdp)
        cdp("Input.insertText", text=" Typed while the keyboard was up.")
        s = state(cdp)

    # --- Done saves and closes --------------------------------------------
    if not editing_long(s):
        load(cdp, base)
        open_long(cdp)
        cdp("Input.insertText", text=" Typed while the keyboard was up.")
    done = cdp.tap_el(DONE, 1.0)
    s = state(cdp)
    check("done: closes the editor", done and s["editing"] is None, s)
    check("done: saves the text", "Typed while the keyboard was up." in POST.read_text())

    # --- tapping another block saves and switches -------------------------
    load(cdp, base)
    open_long(cdp)
    cdp("Input.insertText", text=" Switch text.")
    cdp.tap_el(block_sel(FIRST), 1.2)
    s = state(cdp)
    check("switch: the tapped block opens", s["editing"] == FIRST, s)
    check("switch: the first block's edit was saved", "Switch text." in POST.read_text())
    check("switch: the bar now holds the tapped block's controls, only",
          s["barControls"] == [FIRST], s["barControls"])

    # --- a control tapped with the PAIR editor open must not eat the pair ---
    load(cdp, base)
    cdp.tap_el(block_sel(PAIR_IDX), 0.6)
    cdp.js(f"document.querySelector('{block_sel(PAIR_IDX)}').dispatchEvent("
           "new MouseEvent('mouseover', {bubbles: true}))")
    # The bar is hover-only outside the text editor, so press it directly.
    cdp.js(f"document.querySelector('#edit-bar .block-controls button[title=\"Move this block\"], "
           f"{block_sel(PAIR_IDX)} .block-controls button[title=\"Move this block\"]').click()")
    time.sleep(1.0)
    check("pair: a control tap keeps the pair's picture",
          'class="pair pair-right' in POST.read_text() and "a cat" in POST.read_text(),
          POST.read_text()[-400:])


# Where a block and the one after it sit, the closed block's text face, and
# the scroll position -- read before a tap opens it.
PLACE = """((i) => {
  const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect();
    return {x: b.x, y: b.y, w: b.width, h: b.height, r: b.right, b: b.bottom}; };
  const el = document.querySelector(`.block[data-index="${i}"]`);
  const next = document.querySelector(`.block[data-index="${i + 1}"]`);
  const text = el && el.querySelector('.block-content > *');
  return JSON.stringify({block: r(el), next: r(next), sy: scrollY,
    font: text ? getComputedStyle(text).fontFamily : null});
})"""


def place(cdp, i: int) -> dict:
    return json.loads(cdp.js(f"({PLACE})({i})"))


def run_in_place_cases(cdp, base, w, h, check, shots, prefix):
    """The open block stays where it was, set in the post's own type."""

    def open_in_place(i, name):
        load(cdp, base)
        cdp.js(f"document.querySelector('{block_sel(i)}').scrollIntoView({{block: 'center'}})")
        time.sleep(0.3)
        before = place(cdp, i)
        b = before["block"]
        cdp.tap(b["x"] + b["w"] / 2, b["y"] + b["h"] / 2, 0.8)
        after = place(cdp, i)
        s = state(cdp)
        check(f"in place ({name}): opens", s["editing"] == i, s)
        check(f"in place ({name}): block top stays put (2px)",
              abs(after["block"]["y"] - b["y"]) <= 2, {"before": b, "after": after["block"]})
        check(f"in place ({name}): next block stays put (2px)",
              before["next"] and after["next"]
              and abs(after["next"]["y"] - before["next"]["y"]) <= 2,
              {"before": before["next"], "after": after["next"]})
        check(f"in place ({name}): scroll position unchanged",
              abs(after["sy"] - before["sy"]) <= 1, {"before": before["sy"], "after": after["sy"]})
        check(f"in place ({name}): the field is set in the closed block's face",
              s["font"] and s["font"] == before["font"], {"field": s["font"], "closed": before["font"]})
        return s

    for i, name in ((CLOSING, "paragraph"), (HEADING, "heading")):
        try:
            open_in_place(i, name)
        except Exception as exc:  # noqa: BLE001
            check(f"in place ({name}) ran", False, repr(exc))
        if name == "paragraph" and shots:
            png = cdp("Page.captureScreenshot", format="png")["data"]
            Path(shots, f"{prefix}-{w}-paragraph.png").write_bytes(base64.b64decode(png))

    # The last block of the post: its field sits above the bar, not under it.
    try:
        load(cdp, base)
        cdp.js("scrollTo(0, document.documentElement.scrollHeight)")
        time.sleep(0.3)
        cdp.tap_el(block_sel(FINAL), 0.8)
        cdp.js("scrollTo(0, document.documentElement.scrollHeight)")
        time.sleep(0.3)
        s = state(cdp)
        check("last block: its field sits above the bar",
              s["editing"] == FINAL and s["bar"] and s["ta"]["b"] <= s["bar"]["y"] + 0.5, s)
    except Exception as exc:  # noqa: BLE001
        check("last block ran", False, repr(exc))

    # Rotation mid-edit: the bar stays at the bottom, the block's top holds.
    if (w, h) == (1366, 1024):
        try:
            load(cdp, base)
            # Long enough that the new, taller window can still scroll to
            # where the old one was, so nothing clamps the position.
            POST.write_text(BODY + "".join(f"\nFiller paragraph {n}.\n" for n in range(40)))
            cdp("Page.reload")
            time.sleep(2.0)
            cdp.js(f"document.querySelector('{block_sel(HEADING)}').scrollIntoView({{block: 'center'}})")
            time.sleep(0.3)
            b = cdp.rect(block_sel(HEADING))
            cdp.tap(b["x"] + b["w"] / 2, b["y"] + b["h"] / 2, 0.8)
            top = cdp.rect(block_sel(HEADING))["y"]
            cdp("Emulation.setDeviceMetricsOverride", width=1024, height=1366,
                deviceScaleFactor=1, mobile=True)
            time.sleep(0.8)
            s = state(cdp)
            check("rotate: still editing, bar at the new bottom",
                  s["editing"] == HEADING and s["bar"] and abs(s["bar"]["b"] - 1366) <= 1, s)
            # Unless the page is too short to scroll that far at the new
            # size: then the browser clamps the scroll and nothing can hold it.
            clamped = cdp.js("scrollY >= document.documentElement.scrollHeight - innerHeight - 1")
            check("rotate: the block's top stays put (2px) unless the scroll is clamped",
                  s["block"] and (abs(s["block"]["y"] - top) <= 2 or (clamped and s["block"]["y"] > top)),
                  {"before": top, "after": s["block"], "clamped": clamped,
                   "sy": s["sy"], "sh": cdp.js("document.documentElement.scrollHeight")})
        except Exception as exc:  # noqa: BLE001
            check("rotate ran", False, repr(exc))
        finally:
            cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
                deviceScaleFactor=1, mobile=True)
            time.sleep(0.3)


# A second scratch post for the settings that moved into the bar: a photo
# row, a spacer, an image pair and a video pair.
MEDIA_ROW = (
    '<div class="img-row size-medium">\n'
    '<img src="https://img.cloudy.nyc/p/b.jpg" alt="b">\n'
    '<img src="https://img.cloudy.nyc/p/c.jpg" alt="c">\n</div>'
)
VIDEO_PAIR = (
    '<div class="pair pair-left size-small">\n<div class="pair-media">\n'
    '<div class="video-row size-small">\n'
    '<video autoplay loop muted playsinline data-sync-loop="4">\n'
    '<source src="https://img.cloudy.nyc/p/v.mp4" type="video/mp4">\n</video>\n</div>\n</div>\n'
    '<div class="pair-text">\n\nWords beside the clip.\n\n</div>\n</div>'
)
MEDIA_BODY = (
    "+++\ntitle = \"Edit tap scratch\"\ndate = 2026-10-04\ndraft = true\n+++\n\n"
    "Intro paragraph.\n\n"
    f"{MEDIA_ROW}\n\n"
    "A paragraph after the row.\n\n"
    '<div class="post-spacer"></div>\n\n'
    "A paragraph after the space.\n\n"
    f"{PAIR}\n\n"
    "Between the pairs, and long enough to wrap a little on a tablet so the pair "
    "below has something under it.\n\n"
    f"{VIDEO_PAIR}\n\n"
    "The end.\n"
)
M_ROW, M_SPACER, M_PAIR, M_VPAIR = 1, 3, 5, 7


def load_media(cdp: CDP, base: str) -> None:
    POST.write_text(MEDIA_BODY)
    cdp("Page.navigate", url=f"{base}/edit/{SLUG}")
    for _ in range(80):
        time.sleep(0.25)
        try:
            if cdp.js(f"!!document.querySelector('{block_sel(M_VPAIR + 1)}')"):
                time.sleep(0.3)
                return
        except RuntimeError:
            pass
    raise RuntimeError("editor never rendered the media scratch post")


def bar_button(label: str) -> str:
    return f'#edit-bar button[aria-label="{label}"]'


BAR = """(() => {
  const bar = document.getElementById('edit-bar');
  const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect();
    return {x: b.x, y: b.y, w: b.width, h: b.height, r: b.right, b: b.bottom}; };
  return JSON.stringify({
    shown: !bar.hidden,
    labels: [...bar.querySelectorAll('button')].map((b) => b.getAttribute('aria-label') || b.textContent),
    pressed: [...bar.querySelectorAll('button[aria-pressed="true"]')].map((b) => b.getAttribute('aria-label')),
    segmented: bar.querySelectorAll('.segmented').length,
    small: [...bar.querySelectorAll('button')].filter((b) => b.getBoundingClientRect().height < 43.5)
      .map((b) => b.getAttribute('aria-label') || b.textContent),
    caps: [...bar.querySelectorAll('*')].filter((n) => getComputedStyle(n).textTransform === 'uppercase').length,
    filled: [...bar.querySelectorAll('button')].filter((b) => {
      const bg = getComputedStyle(b).backgroundColor;
      return b.offsetParent && bg === 'rgb(0, 102, 204)'; }).map((b) => b.textContent),
    inBlock: document.querySelectorAll('.block.editing .framing-controls, .block.editing .size-buttons,'
      + ' .block.editing .side-buttons, .block.editing .image-editor-actions, .block.editing .wrap-control').length,
  });
})()"""


def bar(cdp) -> dict:
    return json.loads(cdp.js(BAR))


def run_media_cases(cdp, base, w, h, check, shots, prefix):
    """Rows, spacers and pairs: their settings live in the bar."""

    def tap_block(i, settle=0.8):
        cdp.js(f"document.querySelector('{block_sel(i)}').scrollIntoView({{block: 'center'}})")
        time.sleep(0.3)
        before = place(cdp, i)
        b = before["block"]
        cdp.tap(b["x"] + b["w"] / 2, b["y"] + min(b["h"] / 2, 40), settle)
        return before

    def bar_basics(name):
        b = bar(cdp)
        check(f"{name}: every bar button is a 44px target", b["shown"] and not b["small"], b)
        check(f"{name}: one filled button (Done), no all-caps",
              b["filled"] == ["Done"] and b["caps"] == 0, b)
        return b

    def case_closed():
        load_media(cdp, base)
        glyphs = cdp.js("[...document.querySelectorAll('.block .block-controls button')]"
                        ".map((b) => b.textContent)")
        check("media: closed blocks offer no ◨ layout button", glyphs and "◨" not in glyphs, glyphs)

    def case_row_open():
        load_media(cdp, base)
        before = tap_block(M_ROW)
        after = place(cdp, M_ROW)
        b = bar_basics("row")
        check("row: size and side toggles are in the bar, nothing in the block",
              b["segmented"] >= 2 and b["inBlock"] == 0, b)
        check("row: its own top stays put (2px)",
              abs(after["block"]["y"] - before["block"]["y"]) <= 2,
              {"before": before["block"], "after": after["block"]})
        check("row: offers Pair, and Done and Cancel",
              "Pair with the text beside it" in b["labels"] and "Done" in b["labels"]
              and "Cancel" in b["labels"], b["labels"])
        if shots:
            png = cdp("Page.captureScreenshot", format="png")["data"]
            Path(shots, f"{prefix}-{w}-row.png").write_bytes(base64.b64decode(png))

    def case_row_side_done():
        load_media(cdp, base)
        tap_block(M_ROW)
        cdp.tap_el(bar_button("Picture on the left, text beside it"), 0.4)
        cdp.tap_el(DONE, 1.2)
        want = MEDIA_ROW.replace('img-row size-medium"', 'img-row size-medium beside-left"')
        text = POST.read_text()
        check("row: side then Done writes what the old picker wrote",
              want in text and text == MEDIA_BODY.replace(MEDIA_ROW, want), text[:500])

    def case_row_cancel():
        load_media(cdp, base)
        tap_block(M_ROW)
        cdp.tap_el(bar_button("Picture on the right, text beside it"), 0.4)
        cdp.tap_el(bar_button("Small"), 0.4)
        cdp.tap_el(bar_button("Cancel"), 1.0)
        check("row: Cancel writes nothing and closes",
              POST.read_text() == MEDIA_BODY and not bar(cdp)["shown"])

    def case_spacer():
        load_media(cdp, base)
        tap_block(M_SPACER)
        b = bar_basics("spacer")
        check("spacer: Everywhere / Desktop only in the bar",
              "Everywhere" in b["labels"] and "Desktop only" in b["labels"]
              and b["pressed"] == ["Everywhere"], b)
        cdp.tap_el(bar_button("Desktop only"), 0.4)
        cdp.tap_el(DONE, 1.2)
        text = POST.read_text()
        check("spacer: Done writes the desktop-only spacer the old toggle wrote",
              text == MEDIA_BODY.replace('<div class="post-spacer"></div>',
                                         '<div class="post-spacer desktop-only"></div>'), text[:500])

    def case_pair_unpair():
        load_media(cdp, base)
        tap_block(M_ROW)
        b = bar(cdp)
        check("row: Pair is off until the row has a side",
              cdp.js(f"document.querySelector({json.dumps(bar_button('Pair with the text beside it'))}).disabled"), b)
        cdp.tap_el(bar_button("Picture on the left, text beside it"), 0.4)
        cdp.tap_el(bar_button("Pair with the text beside it"), 2.0)
        text = POST.read_text()
        check("row: Pair saves the side and pairs at once",
              '<div class="pair pair-left size-medium">' in text and text.count('class="pair ') == 3,
              text[:700])
        load_media(cdp, base)
        tap_block(M_PAIR)
        cdp.tap_el(bar_button("Unpair"), 2.0)
        text = POST.read_text()
        check("pair: Unpair acts at once",
              'class="pair pair-right' not in text and "beside-right" in text and "a cat" in text,
              text[:900])

    PAIR_STATE = """(() => {
      const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect();
        return {x: b.x, y: b.y, w: b.width, h: b.height, r: b.right, b: b.bottom}; };
      const ed = document.querySelector('.block.editing');
      const pair = ed && ed.querySelector('.pair');
      return JSON.stringify({
        cls: pair ? pair.className : null,
        media: r(pair && pair.querySelector('.pair-media')),
        ta: r(ed && ed.querySelector('.pair-text textarea')),
        imgs: ed ? ed.querySelectorAll('.pair-media img, .pair-media video').length : 0,
      });
    })()"""

    def pair_state():
        return json.loads(cdp.js(PAIR_STATE))

    def case_pair_open():
        load_media(cdp, base)
        before = tap_block(M_PAIR)
        after = place(cdp, M_PAIR)
        ps = pair_state()
        bar_basics("pair")
        check("pair: opens as a pair, picture beside the field",
              ps["media"] and ps["ta"] and ps["imgs"] == 1
              and (ps["media"]["x"] >= ps["ta"]["r"] - 1 or ps["ta"]["x"] >= ps["media"]["r"] - 1), ps)
        check("pair: block top and next block stay put (2px)",
              abs(after["block"]["y"] - before["block"]["y"]) <= 2
              and abs(after["next"]["y"] - before["next"]["y"]) <= 2,
              {"before": before, "after": after})
        if shots:
            png = cdp("Page.captureScreenshot", format="png")["data"]
            Path(shots, f"{prefix}-{w}-pair.png").write_bytes(base64.b64decode(png))
        cdp.tap_el(bar_button("Picture on the left"), 0.4)
        ps2 = pair_state()
        check("pair: flipping side flips it live",
              "pair-left" in ps2["cls"] and ps2["media"]["r"] <= ps2["ta"]["x"] + 1, ps2)
        cdp.tap_el(bar_button("Prose at the top"), 0.4)
        check("pair: prose position updates live", "justify-top" in pair_state()["cls"], pair_state())
        cdp.tap_el(bar_button("Cancel"), 1.0)
        check("pair: Cancel after changes writes nothing", POST.read_text() == MEDIA_BODY)

    def case_pair_done_unchanged():
        load_media(cdp, base)
        tap_block(M_PAIR)
        cdp.tap_el(DONE, 1.2)
        check("pair: Done with no changes leaves the file byte-identical",
              POST.read_text() == MEDIA_BODY and not bar(cdp)["shown"])

    def case_pair_photo():
        load_media(cdp, base)
        tap_block(M_PAIR)
        cdp.tap_el(bar_button("Photo: alt text and link preview"), 0.6)
        sheet = json.loads(cdp.js(
            "JSON.stringify({inputs: document.querySelectorAll('.pair-photo-sheet input').length,"
            " stars: document.querySelectorAll('.pair-photo-sheet .preview-pick').length})"))
        check("pair: Photo opens a sheet with an alt field and a star per photo",
              sheet == {"inputs": 1, "stars": 1}, sheet)
        if shots:
            png = cdp("Page.captureScreenshot", format="png")["data"]
            Path(shots, f"{prefix}-{w}-pair-photo.png").write_bytes(base64.b64decode(png))
        cdp.js("(() => { const i = document.querySelector('.pair-photo-sheet input');"
               " i.focus(); i.value = 'a black cat'; i.dispatchEvent(new Event('input')); })()")
        cdp.tap_el(DONE, 1.2)
        text = POST.read_text()
        check("pair: an alt edit is written into the pair's <img alt>",
              text == MEDIA_BODY.replace('alt="a cat"', 'alt="a black cat"'), text[:900])
        load_media(cdp, base)
        tap_block(M_PAIR)
        cdp.tap_el(bar_button("Picture on the left"), 0.4)
        cdp.tap_el(bar_button("Photo: alt text and link preview"), 0.6)
        cdp.js("(() => { const i = document.querySelector('.pair-photo-sheet input');"
               " i.value = 'nope'; i.dispatchEvent(new Event('input')); })()")
        cdp.tap_el(bar_button("Cancel"), 1.0)
        check("pair: Cancel after a side flip and an alt edit writes nothing",
              POST.read_text() == MEDIA_BODY and not cdp.js("!!document.querySelector('.pair-photo-sheet')"))

    def case_video_pair():
        load_media(cdp, base)
        tap_block(M_VPAIR)
        b = bar(cdp)
        check("video pair: opens, and has no Photo button",
              b["shown"] and "Photo: alt text and link preview" not in b["labels"]
              and pair_state()["imgs"] == 1, b)

    for case in (case_closed, case_row_open, case_row_side_done, case_row_cancel,
                 case_spacer, case_pair_unpair, case_pair_open, case_pair_done_unchanged,
                 case_pair_photo, case_video_pair):
        try:
            case()
        except Exception as exc:  # noqa: BLE001
            check(f"media case {case.__name__} ran", False, repr(exc))
        cdp.js("localStorage.clear()")


CARET_END = ("(() => { const t = document.querySelector('.block.editing textarea');"
             " t.focus(); t.setSelectionRange(t.value.length, t.value.length); })()")
DONE = "#edit-bar .edit-done"
PLUS = '#edit-bar .block-controls button[title="Insert a paragraph"]'


def flush_via_plus(cdp) -> None:
    """Tap + (which saves first) and then the menu's Cancel."""
    cdp.tap_el(PLUS, 1.0)
    cdp.tap_el(".insert-choice .insert-cancel", 0.6)


def run_review_cases(cdp, base, w, h, check):
    """Ways an independent review found to lose typed text."""

    def case_1():
        # 1a. Trailing whitespace: saved "Hello " comes back as "Hello".
        load(cdp, base)
        open_long(cdp)
        cdp.js(CARET_END)
        cdp("Input.insertText", text=" Hello ")
        flush_via_plus(cdp)
        s = state(cdp)
        check("review 1: trailing space survives a save, editor stays open",
              s["editing"] == LONG_IDX and (s["value"] or "").endswith("Hello "), s)
        cdp.js(CARET_END)
        cdp("Input.insertText", text="world")
        cdp.tap_el(DONE, 1.0)
        check("review 1: typing after it saves too", "Hello world" in POST.read_text())

    def case_2():
        # 1b. A save that splits the block ("# Heading" + a paragraph).
        load(cdp, base)
        cdp.tap_el(block_sel(FIRST), 0.6)
        cdp.js("(() => { const t = document.querySelector('.block.editing textarea'); t.select(); })()")
        cdp("Input.insertText", text="# Split heading\nSplit body.")
        flush_via_plus(cdp)
        s = state(cdp)
        check("review 1: a save that splits the block keeps editing its first piece",
              s["editing"] == FIRST and s["value"] == "# Split heading", s)
        cdp.tap_el(DONE, 1.0)
        text = POST.read_text()
        check("review 1: split text saved once, nothing duplicated",
              text.count("Split heading") == 1 and text.count("Split body.") == 1, text[:300])

    def case_3():
        # 2. Pair prose: saved through the pair route on a control tap and on
        # switching blocks, picture intact.
        load(cdp, base)
        cdp.tap_el(block_sel(PAIR_IDX), 0.6)
        cdp.js("(() => { const t = document.querySelector('.block.editing textarea'); t.focus();"
               " t.setSelectionRange(t.value.length, t.value.length); })()")
        cdp("Input.insertText", text=" Extra prose.")
        cdp.tap_el(block_sel(FIRST), 1.5)
        text = POST.read_text()
        s = state(cdp)
        check("review 2: switching blocks saves the pair's prose via the pair route",
              "Extra prose." in text and 'class="pair pair-right' in text and "a cat" in text,
              text[-400:])
        check("review 2: and opens the tapped block", s["editing"] == FIRST, s)

        load(cdp, base)
        cdp.tap_el(block_sel(PAIR_IDX), 0.6)
        cdp.js("(() => { const t = document.querySelector('.block.editing textarea'); t.focus();"
               " t.setSelectionRange(t.value.length, t.value.length); })()")
        cdp("Input.insertText", text=" Moved prose.")
        cdp.js(f"document.querySelector('#edit-bar .block-controls button[title=\"Move this block\"], "
               f"{block_sel(PAIR_IDX)} .block-controls button[title=\"Move this block\"]').click()")
        time.sleep(1.2)
        text = POST.read_text()
        check("review 2: a control tap saves the pair's prose, picture intact",
              "Moved prose." in text and 'class="pair pair-right' in text and "a cat" in text,
              text[-400:])

    def case_4():
        # 3. Insert Above next to an identical "New paragraph.": the editor must
        # follow its own block, not the new one with the same text.
        load(cdp, base)
        open_long(cdp)
        cdp.tap_el(PLUS, 1.0)
        cdp.tap_el(".insert-choice button:nth-of-type(2)", 1.2)  # ↓ Below
        cdp.tap_el(DONE, 1.0)
        cdp.tap_el(block_sel(LONG_IDX + 1), 0.6)  # the new "New paragraph."
        cdp.tap_el(PLUS, 1.0)
        cdp.tap_el(".insert-choice button", 1.2)  # ↑ Above
        s = state(cdp)
        check("review 3: Above keeps the editor on its own block",
              s["editing"] == LONG_IDX + 2, s)

    def case_5():
        # 4. A 409 then a reload: the typing comes back from localStorage.
        load(cdp, base)
        open_long(cdp)
        cdp.js(CARET_END)
        cdp("Input.insertText", text=" Draft text.")
        POST.write_text(POST.read_text() + "\nChanged on disk.\n")
        cdp.tap_el(DONE, 1.0)
        s = state(cdp)
        check("review 4: a 409 leaves the editor open with its text",
              s["editing"] == LONG_IDX and "Draft text." in (s["value"] or ""), s)
        cdp("Page.reload")
        time.sleep(2.0)
        offered = cdp.rect(".draft-offer")
        restored = cdp.tap_el(".draft-offer button", 1.0)  # Restore
        s = state(cdp)
        check("review 4: after reload the draft is offered and restores",
              offered and restored and s["editing"] == LONG_IDX
              and "Draft text." in (s["value"] or ""), s)
        cdp.tap_el(DONE, 1.0)
        check("review 4: and then saves", "Draft text." in POST.read_text())
        cdp.js("localStorage.clear()")

    def case_6():
        # 5. Typing after a save started must not be dropped by Done.
        load(cdp, base)
        open_long(cdp)
        cdp.js(CARET_END)
        cdp("Input.insertText", text=" First.")
        # A slow network holds the first save in flight while the typing
        # and the Done tap happen.
        cdp("Network.emulateNetworkConditions", offline=False, latency=1500,
            downloadThroughput=-1, uploadThroughput=-1)
        try:
            cdp.js("(() => { flushPendingEdit(); const t = document.querySelector('.block.editing textarea');"
                   " t.value += ' Late.'; t.dispatchEvent(new Event('input')); })()")
            cdp.tap_el(DONE, 8.0)
        finally:
            cdp("Network.emulateNetworkConditions", offline=False, latency=0,
                downloadThroughput=-1, uploadThroughput=-1)
        text = POST.read_text()
        check("review 5: text typed during an in-flight save is saved by Done",
              "First." in text and "Late." in text, text[:400])

    def case_7():
        # 7. Row mode: Done is on screen while the field is taller than the
        # window (keyboard up).
        if True:
            load(cdp, base)
            cdp("Emulation.setDeviceMetricsOverride", width=w, height=300,
                deviceScaleFactor=1, mobile=True)
            time.sleep(0.4)
            cdp.js(f"document.querySelector('{block_sel(LONG_IDX)}').scrollIntoView({{block: 'start'}});"
                   "scrollBy(0, -80)")
            time.sleep(0.3)
            b = cdp.rect(block_sel(LONG_IDX))
            cdp.tap(b["x"] + b["w"] / 2, b["y"] + 30)
            cdp.js(f"document.querySelector('{block_sel(LONG_IDX)}').scrollIntoView({{block: 'start'}})")
            time.sleep(0.3)
            r = cdp.rect(DONE)
            check("review 7: Done stays on screen under a tall field",
                  r and r["y"] + r["h"] <= 300 + 1 and r["y"] >= 0, r or state(cdp))
            cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
                deviceScaleFactor=1, mobile=True)

    # --- Re-review: never re-attach to (or restore onto) an unverified block.
    SET_TEXT = ("(text) => { const t = document.querySelector('.block.editing textarea');"
                " t.value = text; t.dispatchEvent(new Event('input')); }")

    def set_text(text):
        cdp.js(f"({SET_TEXT})({json.dumps(text)})")

    def done_if_open():
        if cdp.rect(DONE):
            cdp.tap_el(DONE, 1.0)

    def case_8():
        # NEW-1: a paragraph saved empty is removed; the editor must not
        # reopen on the block that moved into its index.
        load(cdp, base)
        cdp.tap_el(block_sel(FIRST), 0.6)
        set_text("")
        cdp.tap_el(PLUS, 1.0)
        done_if_open()
        text = POST.read_text()
        check("re-review 1: clearing a paragraph leaves the next block untouched",
              text.count("This paragraph is one long") == 6
              and "A short opening" not in text, text[:400])

    def case_9():
        # NEW-1: "- x" after a list merges into it; the next block survives.
        load(cdp, base)
        cdp.tap_el(block_sel(AFTER_LIST), 0.6)
        set_text("- x")
        cdp.tap_el(PLUS, 1.0)
        done_if_open()
        text = POST.read_text()
        check("re-review 1: a save that merges into a list overwrites nothing",
              "Final words." in text and "- x" in text and "- two" in text, text[-300:])

    def case_10():
        # NEW-2: a network error during Insert Above, then Undo.
        load(cdp, base)
        open_long(cdp)
        cdp.js(CARET_END)
        cdp("Input.insertText", text=" Undo me.")
        cdp.tap_el(PLUS, 1.0)  # saves
        cdp("Network.emulateNetworkConditions", offline=True, latency=0,
            downloadThroughput=-1, uploadThroughput=-1)
        try:
            cdp.tap_el(".insert-choice button", 1.0)  # Above, fails
        finally:
            cdp("Network.emulateNetworkConditions", offline=False, latency=0,
                downloadThroughput=-1, uploadThroughput=-1)
        cdp.js("document.getElementById('undo').click()")
        time.sleep(1.2)
        s = state(cdp)
        done_if_open()
        text = POST.read_text()
        check("re-review 2: after a failed insert, Undo doesn't move the editor",
              s["editing"] in (None, LONG_IDX)
              and "A closing paragraph that follows the long one." in text
              and text.count("This paragraph is one long") == 6, {"state": s, "text": text[:200]})

    def case_11():
        # NEW-3: a draft whose block changed is never restored onto another
        # block with the same text.
        POST.write_text(BODY + "\nNew paragraph.\n")
        cdp("Page.navigate", url=f"{base}/edit/{SLUG}")
        time.sleep(1.5)
        cdp.js("localStorage.setItem('editor-draft:%s:2:x:old', JSON.stringify({kind: 'text',"
               " index: 2, original: 'New paragraph.', text: 'Draft for a gone block.', at: Date.now()}))"
               % SLUG)
        cdp("Page.reload")
        time.sleep(2.0)
        copy_box = cdp.rect(".draft-offer textarea")
        restore = cdp.js("[...document.querySelectorAll('.draft-offer button')]"
                         ".some((b) => b.textContent.startsWith('Restore'))")
        cdp.tap_el(".draft-offer button", 1.0)  # whatever comes first
        done_if_open()
        text = POST.read_text()
        check("re-review 3: a draft for a changed block is shown to copy, not restored",
              copy_box and not restore and "Draft for a gone block." not in text
              and text.endswith("New paragraph.\n"), text[-200:])

    def case_12():
        # NEW-4: Delete on another block while the open one's save splits.
        load(cdp, base)
        cdp.tap_el(block_sel(FIRST), 0.6)
        set_text("# Head\nBody text.")
        cdp.js("window.confirm = () => true;"
               f"document.querySelector('{block_sel(CLOSING)} .block-controls "
               "button[title=\"Delete this block\"]').click()")
        time.sleep(1.5)
        done_if_open()
        text = POST.read_text()
        check("re-review 4: Delete during a split removes the block it was aimed at",
              "A closing paragraph" not in text and text.count("This paragraph is one long") == 6
              and "# Head" in text and "Body text." in text and PAIR in text, text[:300])


    # Each case reports a FAIL rather than crashing the run when the code
    # under test doesn't even get far enough to measure.
    for case in [case_1, case_2, case_3, case_4, case_5, case_6, case_7,
                 case_8, case_9, case_10, case_11, case_12]:
        try:
            case()
        except Exception as exc:  # noqa: BLE001
            check(f"review case {case.__name__} ran", False, repr(exc))
        cdp.js("localStorage.clear()")
        cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
            deviceScaleFactor=1, mobile=True)


# --- Left | Center and the link button --------------------------------------

CLOSING_TEXT = "A closing paragraph that follows the long one."


def centred(inner: str) -> str:
    return f'<div class="align-center">\n\n{inner}\n\n</div>'


FIELD = """(() => {
  const t = document.querySelector('.block.editing textarea');
  const bar = document.getElementById('edit-bar');
  const sheet = document.querySelector('#edit-bar .link-sheet');
  return JSON.stringify({
    value: t ? t.value : null,
    focused: !!t && document.activeElement === t,
    sel: t ? [t.selectionStart, t.selectionEnd] : null,
    centred: t ? getComputedStyle(t).textAlign : null,
    pressed: [...bar.querySelectorAll('button[aria-pressed="true"]')].map((b) => b.getAttribute('aria-label')),
    link: !!bar.querySelector('.link-button'),
    sheet: !!sheet,
    sheetFocus: !!sheet && document.activeElement === sheet.querySelector('input'),
  });
})()"""


def run_align_cases(cdp, base, w, h, check, shots, prefix):
    def field():
        return json.loads(cdp.js(FIELD))

    def load_body(body):
        POST.write_text(body)
        cdp("Page.navigate", url=f"{base}/edit/{SLUG}")
        for _ in range(80):
            time.sleep(0.25)
            try:
                if cdp.js(f"!!document.querySelector('{block_sel(FINAL)}')"):
                    time.sleep(0.3)
                    return
            except RuntimeError:
                pass
        raise RuntimeError("editor never rendered the scratch post")

    def open_block(i, settle=0.8):
        cdp.js(f"document.querySelector('{block_sel(i)}').scrollIntoView({{block: 'center'}})")
        time.sleep(0.3)
        b = cdp.rect(block_sel(i))
        cdp.tap(b["x"] + b["w"] / 2, b["y"] + b["h"] / 2, settle)
        return b

    def select(start, end):
        cdp.js("(() => { const t = document.querySelector('.block.editing textarea');"
               f" t.focus(); t.setSelectionRange({start}, {end}); }})()")

    def case_center_then_left():
        load(cdp, base)
        before = open_block(CLOSING)
        f = field()
        check("align: an open paragraph offers Left | Center, Left pressed, and 🔗",
              f["pressed"] == ["Align left"] and f["link"], f)
        cdp.tap_el(bar_button("Align center"), 0.4)
        f = field()
        check("align: Center centres the open field at once, focus kept",
              f["centred"] == "center" and f["focused"], f)
        cdp.tap_el(DONE, 1.2)
        text = POST.read_text()
        check("align: Center then Done writes the wrapper, nothing else",
              text == BODY.replace(CLOSING_TEXT, centred(CLOSING_TEXT)), text[:700])
        shown = cdp.js(f"(() => {{ const p = document.querySelector('{block_sel(CLOSING)} "
                       ".block-content .align-center p'); return p ? getComputedStyle(p).textAlign : null; })()")
        check("align: the closed block renders centred", shown == "center", shown)
        after = cdp.rect(block_sel(CLOSING))
        check("align: still one block, same height (2px)",
              after and abs(after["h"] - before["h"]) <= 2, {"before": before, "after": after})
        # Reopen: the field holds the words, not the wrapper.
        top = open_block(CLOSING)
        f = field()
        reopened = cdp.rect(block_sel(CLOSING))
        check("align: reopened, the field shows the inner text and Center is pressed",
              f["value"] == CLOSING_TEXT and f["pressed"] == ["Align center"]
              and f["centred"] == "center", f)
        check("align: a centred block opens in place (2px)",
              reopened and abs(reopened["y"] - top["y"]) <= 2, {"before": top, "after": reopened})
        if shots:
            png = cdp("Page.captureScreenshot", format="png")["data"]
            Path(shots, f"{prefix}-{w}-centred.png").write_bytes(base64.b64decode(png))
        cdp.tap_el(bar_button("Align left"), 0.4)
        cdp.tap_el(DONE, 1.2)
        text = POST.read_text()
        check("align: Left then Done removes the wrapper (byte-identical to before)",
              text == BODY, text[:700])

    def case_center_typing():
        # Typing into a centred block keeps the wrapper.
        load_body(BODY.replace(CLOSING_TEXT, centred(CLOSING_TEXT)))
        open_block(CLOSING)
        cdp.js(CARET_END)
        cdp("Input.insertText", text=" More.")
        time.sleep(0.2)
        flush_via_plus(cdp)
        f = field()
        check("align: a save mid-edit keeps the centred editor open on its block",
              f["value"] == CLOSING_TEXT + " More." and f["pressed"] == ["Align center"], f)
        cdp.tap_el(DONE, 1.2)
        text = POST.read_text()
        check("align: typing in a centred block keeps the wrapper",
              text == BODY.replace(CLOSING_TEXT, centred(CLOSING_TEXT + " More.")), text[:700])

    def case_url_link():
        url_text = "Final words at https://example.com/page here."
        body = BODY.replace("Final words.", url_text)
        load_body(body)
        open_block(FINAL)
        start = url_text.index("https://")
        end = start + len("https://example.com/page")
        select(start, end)
        cdp.tap_el("#edit-bar .link-button", 0.5)
        f = field()
        want = "Final words at [https://example.com/page](https://example.com/page) here."
        check("link: a selected URL becomes a link in one tap", f["value"] == want and not f["sheet"], f)
        caret = want.index(") here") + 1
        check("link: focus stays in the field, caret after the link",
              f["focused"] and f["sel"] == [caret, caret], f)
        cdp.tap_el(DONE, 1.2)
        text = POST.read_text()
        check("link: Done saves it", text == body.replace(url_text, want), text[-200:])

    def case_www_link():
        www = "See www.example.com for more."
        load_body(BODY.replace("Final words.", www))
        open_block(FINAL)
        select(4, 4 + len("www.example.com"))
        cdp.tap_el("#edit-bar .link-button", 0.5)
        f = field()
        check("link: a bare www. URL gets https:// in the target",
              f["value"] == "See [www.example.com](https://www.example.com) for more.", f)

    def case_words_link():
        load(cdp, base)
        open_block(AFTER_LIST)
        select(len("After "), len("After the list"))
        cdp.tap_el("#edit-bar .link-button", 0.6)
        f = field()
        check("link: selected words open the address sheet, focused",
              f["sheet"] and f["sheetFocus"], f)
        if shots:
            png = cdp("Page.captureScreenshot", format="png")["data"]
            Path(shots, f"{prefix}-{w}-link-sheet.png").write_bytes(base64.b64decode(png))
        sheet = cdp.rect("#edit-bar .link-sheet")
        barr = cdp.rect("#edit-bar")
        check("link: the sheet sits above the bar, on screen",
              sheet and barr and sheet["y"] + sheet["h"] <= barr["y"] + 0.5
              and sheet["x"] >= 0 and sheet["x"] + sheet["w"] <= w + 0.5, {"sheet": sheet, "bar": barr})
        small = cdp.js("[...document.querySelectorAll('#edit-bar .link-sheet button, #edit-bar .link-sheet input')]"
                       ".filter((b) => b.getBoundingClientRect().height < 43.5).length")
        check("link: the sheet's controls are 44px targets", small == 0, small)
        cdp("Input.insertText", text="example.org/x")
        time.sleep(0.2)
        cdp.tap_el("#edit-bar .link-sheet .link-add", 0.5)
        f = field()
        want = "After [the list](https://example.org/x)."
        check("link: Add link wraps the words, back in the field, caret after it",
              f["value"] == want and not f["sheet"] and f["focused"]
              and f["sel"] == [len(want) - 1, len(want) - 1], f)
        cdp.tap_el(DONE, 1.2)
        text = POST.read_text()
        check("link: Done saves the linked words", text == BODY.replace("After the list.", want), text[-300:])

    def case_cancel_and_caret():
        load(cdp, base)
        open_block(AFTER_LIST)
        select(len("After "), len("After the list"))
        cdp.tap_el("#edit-bar .link-button", 0.6)
        cdp.tap_el("#edit-bar .link-sheet .link-cancel", 0.5)
        f = field()
        check("link: Cancel changes nothing and gives the selection back",
              f["value"] == "After the list." and not f["sheet"] and f["focused"]
              and f["sel"] == [len("After "), len("After the list")], f)
        # No selection: [link text](url) at the caret, "link text" selected.
        cdp.js(CARET_END)
        cdp.tap_el("#edit-bar .link-button", 0.6)
        cdp("Input.insertText", text="https://example.net")
        cdp("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter",
            windowsVirtualKeyCode=13)
        cdp("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter",
            windowsVirtualKeyCode=13)
        time.sleep(0.4)
        f = field()
        at = len("After the list.") + 1
        check("link: no selection inserts [link text](url) with the words selected",
              f["value"] == "After the list.[link text](https://example.net)" and f["focused"]
              and f["sel"] == [at, at + len("link text")], f)
        # Saved, so leaving the page doesn't flush it into the next case.
        cdp.tap_el(DONE, 1.2)

    def case_pair_link():
        load(cdp, base)
        open_block(PAIR_IDX)
        has = cdp.js("!!document.querySelector('#edit-bar .link-button')")
        check("link: a pair's prose field has 🔗 too", has, has)
        cdp.js("(() => { const t = document.querySelector('.block.editing .pair-text textarea');"
               " t.focus(); t.setSelectionRange(0, 5); })()")
        cdp.tap_el("#edit-bar .link-button", 0.6)
        cdp("Input.insertText", text="https://example.com/w")
        cdp.tap_el("#edit-bar .link-sheet .link-add", 0.5)
        cdp.tap_el(DONE, 1.4)
        text = POST.read_text()
        check("link: a pair's prose link saves through the pair route, picture kept",
              text == BODY.replace("Words beside the cat.", "[Words](https://example.com/w) beside the cat."),
              text[text.index('<div class="pair-text">'):][:300])

    def case_heading_has_toggle_spacer_does_not():
        load_media(cdp, base)
        cdp.tap_el(block_sel(M_SPACER), 0.8)
        b = bar(cdp)
        check("align: a spacer has no Left | Center and no 🔗",
              "Align center" not in b["labels"] and "Link" not in b["labels"], b["labels"])

    for case in (case_center_then_left, case_center_typing, case_url_link, case_www_link,
                 case_words_link, case_cancel_and_caret, case_pair_link,
                 case_heading_has_toggle_spacer_does_not):
        try:
            case()
        except Exception as exc:  # noqa: BLE001
            check(f"align case {case.__name__} ran", False, repr(exc))
        cdp.js("localStorage.clear()")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots")
    ap.add_argument("--shot-prefix", default="edit-bar")
    ap.add_argument("--only", action="append", default=[],
                    help="tap / inplace / media / review / align; repeatable. Default: all")
    ap.add_argument("--viewport", action="append", default=[],
                    help="WxH; repeatable. Default: all three tablet viewports")
    args = ap.parse_args()
    viewports = [tuple(int(n) for n in v.split("x")) for v in args.viewport] or VIEWPORTS

    if POST.exists():
        sys.exit(f"{POST} already exists; refusing to overwrite it")
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="edit-tap-", dir=cache))
    procs: list[subprocess.Popen] = []
    results: list = []
    try:
        POST.write_text(BODY)
        py = venv_python()
        env = dict(os.environ, EDITOR_AUTH_DB=str(tmp / "auth.db"),
                   EDITOR_COOKIE_SECURE="false")
        sid = subprocess.run(
            [py, "-c",
             "from datetime import datetime, timedelta, timezone\n"
             "from editor.auth import security, store\n"
             "c = store.connect(); sid = security.new_session_id()\n"
             "n = datetime.now(timezone.utc)\n"
             "store.create_session(c, sid, 'ptr.vldz@gmail.com', n.isoformat(),"
             " (n + timedelta(days=1)).isoformat()); c.close(); print(sid)"],
            cwd=REPO, env=env, check=True, capture_output=True, text=True,
        ).stdout.strip()

        port = free_port()
        procs.append(subprocess.Popen(
            [py, "-m", "uvicorn", "editor.app:app", "--host", "127.0.0.1",
             "--port", str(port)],
            cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        ))
        base = f"http://127.0.0.1:{port}"
        wait_http(f"{base}/healthz")

        dport = free_port()
        procs.append(subprocess.Popen(
            ["/usr/bin/chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
             "--hide-scrollbars", "--remote-allow-origins=*",
             f"--user-data-dir={tmp / 'profile'}",
             f"--remote-debugging-port={dport}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        ))
        wait_http(f"http://127.0.0.1:{dport}/json/version")
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{dport}/json").read())
        page = next(t for t in targets if t["type"] == "page")
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp("Network.enable")
        cdp("Network.setCookie", name="editor_session", value=sid,
            domain="127.0.0.1", path="/")

        for w, h in viewports:
            run_viewport(cdp, base, w, h, results, args.shots, args.shot_prefix, args.only)
    finally:
        for p in reversed(procs):
            # Kill the whole process group by its own PID: Chromium's
            # renderer/GPU children survive a plain terminate() of the parent.
            try:
                os.killpg(p.pid, 15)
                p.wait(timeout=10)
            except Exception:
                pass
        POST.unlink(missing_ok=True)
        # Saves snapshot the post into the gitignored undo history.
        shutil.rmtree(REPO / "editor" / ".history" / SLUG, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)

    failed = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failed += 1
            if detail is not None:
                print(f"      {json.dumps(detail)[:600]}")
    print(f"{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed or not results else 0


if __name__ == "__main__":
    sys.exit(main())
