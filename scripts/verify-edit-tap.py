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

Usage: python3 scripts/verify-edit-tap.py [--shots DIR] [--shot-prefix NAME]
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
    f"{PAIR}\n"
)
# Block indices in BODY.
FIRST, LONG_IDX, CLOSING, PAIR_IDX = 0, 1, 2, 3

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
  const rail = ed && ed.querySelector('.edit-rail');
  const menu = document.querySelector('.insert-choice');
  const buttons = rail ? [...rail.querySelectorAll('button')].map((b) => r(b)) : [];
  return JSON.stringify({
    editing: ed ? Number(ed.dataset.index) : null,
    focused: !!ta && document.activeElement === ta,
    value: ta ? ta.value : null,
    ta: ta && {...r(ta), client: ta.clientHeight, scroll: ta.scrollHeight},
    block: r(ed),
    rail: r(rail),
    menu: r(menu),
    buttons,
    vw: innerWidth,
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


def run_viewport(cdp, base, w, h, results, shots, prefix):
    cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
        deviceScaleFactor=1, mobile=True)
    cdp("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

    def check(name, ok, detail=None):
        results.append((f"{w}x{h} {name}", bool(ok), detail))

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
        check("open: Done/controls never overlap the text",
              s["rail"] and not overlaps(s["rail"], s["ta"]), s)
        check("open: every rail button is a 44px target",
              s["buttons"] and all(b["w"] >= 43.5 and b["h"] >= 43.5 for b in s["buttons"]),
              s["buttons"])
        if w >= 1000:
            check("open: controls are a rail to the right of the block",
                  s["rail"] and s["rail"]["x"] >= s["block"]["r"] and s["rail"]["r"] <= w, s)
        else:
            check("open: controls sit in a row under the textarea",
                  s["rail"] and s["rail"]["y"] >= s["ta"]["b"] - 1, s)
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
    tapped = cdp.tap_el('.block.editing .block-controls button[title="Insert a paragraph"]', 1.0)
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
        cdp.tap_el('.block.editing .block-controls button[title="Insert a paragraph"]', 1.0)
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
    done = cdp.tap_el(".block.editing .edit-done", 1.0)
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

    # --- a control tapped with the PAIR editor open must not eat the pair ---
    load(cdp, base)
    cdp.tap_el(block_sel(PAIR_IDX), 0.6)
    cdp.js(f"document.querySelector('{block_sel(PAIR_IDX)}').dispatchEvent("
           "new MouseEvent('mouseover', {bubbles: true}))")
    # The bar is hover-only outside the text editor, so press it directly.
    cdp.js(f"document.querySelector('{block_sel(PAIR_IDX)} .block-controls "
           "button[title=\"Move this block\"]').click()")
    time.sleep(1.0)
    check("pair: a control tap keeps the pair's picture",
          'class="pair pair-right' in POST.read_text() and "a cat" in POST.read_text(),
          POST.read_text()[-400:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots")
    ap.add_argument("--shot-prefix", default="edit-rail")
    args = ap.parse_args()

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

        for w, h in VIEWPORTS:
            run_viewport(cdp, base, w, h, results, args.shots, args.shot_prefix)
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
