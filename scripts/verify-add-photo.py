#!/usr/bin/env python3
"""Check the editor's Add photo button end to end in headless Chromium.

What it pins, at two tablet viewports:

1. The 📷 button is visible, 56px, labelled "Add photo", sits under the
   toolbar and stays put while the post scrolls.
2. Tapping it saves and closes an open text editor before the picker opens.
3. Picking shows the placement banner (thumbnails, "Tap where the photo
   goes", Cancel), one blue line per gap (N+1 for N blocks) on the block
   boundaries, hides the button, and reflows nothing.
4. A line tapped before the (deliberately slow) upload finishes is marked
   "Placing when the upload finishes"; the photo lands at that gap once the
   upload is back, and its photo editor opens.
5. Two photos make one row; the top and the end gaps both place.
6. Cancel and Escape insert nothing and revoke the thumbnails' object URLs.
7. A failed upload leaves placement with its reason and writes nothing.
8. A post changed on disk under a placement gets the stale message.
9. The button is hidden during a proofread run and its review, and in move
   mode.

Same harness as scripts/verify-edit-tap.py (whose CDP helper it imports): a
scratch draft in content/blog, a scratch uvicorn of THIS checkout on a free
port with its own auth db under ~/.cache. S3 is faked the way the pytest
suite fakes it -- `app.state.s3` set before the first upload -- by a small
launcher this script writes into its temp dir, so the app itself carries no
test hook; the fake's put_object sleeps for whatever the temp dir's `delay`
file says, which is how an upload is made slow. Proofread runs against a
fake claude (EDITOR_CLAUDE_BIN). The file picker is the real input: its
click() is captured and DOM.setFileInputFiles fills it, which fires the
same change event a person's pick does. Everything is removed afterwards;
processes are killed by their own PIDs.

Usage: python3 scripts/verify-add-photo.py [--shots DIR]
  Writes DIR/add-photo-<width>.png of placement mode (default ~/.cache),
  plus -button.png (scrolled, button showing) and -pending.png (a line
  tapped while the upload is still out).
Exits non-zero if any check fails.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("verify_edit_tap", REPO / "scripts" / "verify-edit-tap.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)
CDP, free_port, wait_http, venv_python = harness.CDP, harness.free_port, harness.wait_http, harness.venv_python

BLOG = REPO / "content" / "blog"
SLUG = "zz-add-photo-scratch"
POST = BLOG / f"{SLUG}.md"
HISTORY = REPO / "editor" / ".history" / SLUG

PARAS = [
    "I hope you get this before teh weekend starts.",
] + [
    f"Paragraph {n}. " + "A few sentences of filler so the post is long enough to scroll on a tablet. " * 8
    for n in range(2, 9)
]
BODY = (
    "+++\ntitle = \"Add photo scratch\"\ndate = 2026-10-04\ndraft = true\n+++\n\n"
    + "\n\n".join(PARAS) + "\n"
)
N_BLOCKS = len(PARAS)

LAUNCHER = r'''
import os, sys, time
sys.path.insert(0, REPO)
from editor.app import app
import uvicorn

class SlowFakeS3:
    """Stands in for boto3 exactly as the pytest suite's FakeS3 does."""
    def put_object(self, **kwargs):
        try:
            time.sleep(float(open(DELAY).read() or 0))
        except FileNotFoundError:
            pass

app.state.s3 = SlowFakeS3()
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
'''

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, re, sys, time
prompt = sys.stdin.read()
time.sleep(1.5)
out = []
for idx, body in re.findall(r'<block index="(\d+)">\n(.*?)\n</block>', prompt, re.S):
    if body.count("teh") == 1:
        out.append({"block": int(idx), "before": "teh", "after": "the", "kind": "spelling"})
print(json.dumps(out))
'''

VIEWPORTS = [(1024, 1366), (820, 1180)]

# Captures the file input the button creates instead of opening a picker.
CAPTURE_PICKER = """(() => {
  if (window.__pickerHooked) return;
  window.__pickerHooked = true;
  window.__pickers = [];
  const orig = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (this.type === 'file') { window.__pickers.push(this); return; }
    return orig.call(this);
  };
})()"""


def png(path: Path, rgb: tuple[int, int, int], w: int = 120, h: int = 90) -> Path:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def load(cdp: CDP, base: str) -> None:
    POST.write_text(BODY)
    shutil.rmtree(HISTORY, ignore_errors=True)
    cdp("Page.navigate", url=f"{base}/edit/{SLUG}")
    for _ in range(80):
        time.sleep(0.25)
        try:
            if cdp.js(f"!!document.querySelector('.block[data-index=\"{N_BLOCKS - 1}\"]')"):
                cdp.js(CAPTURE_PICKER)
                time.sleep(0.3)
                return
        except RuntimeError:
            pass
    raise RuntimeError("editor never rendered the scratch post")


def wait_for(cdp: CDP, expr: str, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if cdp.js(expr):
                return True
        except RuntimeError:
            pass
        time.sleep(0.1)
    return False


def status(cdp) -> str:
    return cdp.js("document.getElementById('status').textContent")


def button_shown(cdp) -> bool:
    return cdp.js("(() => { const b = document.getElementById('add-photo');"
                  " return !b.hidden && getComputedStyle(b).display !== 'none'"
                  " && b.getBoundingClientRect().width > 0; })()")


def pick(cdp, files: list[Path]) -> bool:
    """Tap 📷, then fill the input it opened, as the OS picker would."""
    before = cdp.js("window.__pickers.length")
    cdp.js("scrollTo(0, 0)")
    time.sleep(0.1)
    r = cdp.rect("#add-photo")
    if not r:
        return False
    cdp.tap(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2, 0.3)
    if not wait_for(cdp, f"window.__pickers.length > {before}", 5):
        return False
    obj = cdp("Runtime.evaluate", expression="window.__pickers[window.__pickers.length - 1]")
    cdp("DOM.setFileInputFiles", files=[str(f) for f in files], objectId=obj["result"]["objectId"])
    return wait_for(cdp, "!!document.querySelector('.place-banner')", 5)


def tap_gap(cdp, gap: int, settle: float = 0.3) -> bool:
    sel = f'.move-target[data-gap="{gap}"]'
    cdp.js(f"document.querySelector('{sel}').scrollIntoView({{block: 'center'}})")
    time.sleep(0.2)
    r = json.loads(cdp.js(
        f"JSON.stringify(document.querySelector('{sel}').getBoundingClientRect())"))
    if not r or not r["width"]:
        return False
    # The bar itself: it's thin, and its ::after extends the hit area.
    cdp.tap(r["x"] + r["width"] * 0.3, r["y"] + r["height"] / 2, settle)
    return True


def source_blocks() -> list[str]:
    body = POST.read_text().split("+++", 2)[2]
    return [b.strip() for b in body.strip().split("\n\n")]


LAYOUT = """JSON.stringify({
  height: document.documentElement.scrollHeight,
  tops: [...document.querySelectorAll('#blocks > .block')].map((b) => b.offsetTop),
})"""


def run_viewport(cdp, base, w, h, results, shots, files, delay_file):
    cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
        deviceScaleFactor=1, mobile=True)
    cdp("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
    red, green, blue, bogus = files

    def check(name, ok, detail=None):
        results.append((f"{w}x{h} {name}", bool(ok), detail))

    def delay(seconds):
        delay_file.write_text(str(seconds))

    # --- 1. the button -----------------------------------------------------
    load(cdp, base)
    delay(0)
    r = cdp.rect("#add-photo")
    bar = cdp.rect(".bar")
    label = cdp.js("document.getElementById('add-photo').getAttribute('aria-label')")
    check("1: button visible, 56px round, labelled 'Add photo', under the toolbar, at the right",
          button_shown(cdp) and r and r["w"] >= 56 and r["h"] >= 56 and label == "Add photo"
          and bar and r["y"] >= bar["y"] + bar["h"] and r["y"] < bar["y"] + bar["h"] + 40
          and r["x"] + r["w"] > w - 40,
          {"rect": r, "bar": bar, "label": label})
    cdp.js("scrollTo(0, 900)")
    time.sleep(0.3)
    scrolled = cdp.rect("#add-photo")
    check("1: stays put while the post scrolls",
          cdp.js("scrollY") > 300 and scrolled and abs(scrolled["y"] - r["y"]) < 1,
          {"scrollY": cdp.js("scrollY"), "before": r, "after": scrolled})
    if shots:
        shot = cdp("Page.captureScreenshot", format="png")["data"]
        Path(shots, f"add-photo-{w}-button.png").write_bytes(base64.b64decode(shot))
    cdp.js("scrollTo(0, 0)")

    # --- 2. an open text editor is saved and closed first ------------------
    cdp.tap_el('.block[data-index="1"]', 0.6)
    cdp.js("(() => { const t = document.querySelector('.block.editing textarea');"
           " t.value = t.value + ' Saved first.'; t.dispatchEvent(new Event('input')); })()")
    cdp.js("scrollTo(0, 0)")
    picked = pick(cdp, [red])
    check("2: 📷 saves the open editor, closes it, then picks",
          picked and "Saved first." in POST.read_text()
          and not cdp.js("!!document.querySelector('.block.editing')"),
          {"picked": picked, "status": status(cdp)})
    cdp.tap_el(".place-banner .move-cancel", 0.4)

    # --- 3/4. placement mode, a tap that beats a slow upload ---------------
    load(cdp, base)
    before_layout = json.loads(cdp.js(LAYOUT))
    delay(2.5)
    t0 = time.time()
    picked = pick(cdp, [red])
    zones = json.loads(cdp.js("""JSON.stringify((() => {
      const blocks = [...document.querySelectorAll('#blocks > .block')];
      const zones = [...document.querySelectorAll('.move-layer .move-target')];
      const last = blocks[blocks.length - 1];
      const want = blocks.map((b) => b.offsetTop).concat(last.offsetTop + last.offsetHeight);
      return {n: zones.length, blocks: blocks.length,
              off: zones.map((z, i) => Math.abs(z.offsetTop - want[i]))};
    })())"""))
    after_layout = json.loads(cdp.js(LAYOUT))
    banner = cdp.js("document.querySelector('.place-banner').innerText")
    thumbs = cdp.js("[...document.querySelectorAll('.place-banner .place-thumbs img')]"
                    ".map((i) => i.src.startsWith('blob:') && i.naturalWidth > 0)")
    check("3: picking shows the banner with the thumbnail, text and Cancel",
          picked and "Tap where the photo goes" in banner and "Cancel" in banner
          and thumbs == [True], {"banner": banner, "thumbs": thumbs})
    check("3: a blue line at every gap, on the block boundaries (N+1)",
          zones["n"] == N_BLOCKS + 1 and zones["blocks"] == N_BLOCKS and max(zones["off"]) <= 1,
          zones)
    check("3: nothing reflows", before_layout == after_layout,
          {"before": before_layout, "after": after_layout})
    check("3: the button hides while placing", not button_shown(cdp))

    tap_gap(cdp, 2)
    pending = cdp.js("(() => { const t = document.querySelector('.move-target.pending');"
                     " return t ? t.dataset.gap + '|' + t.innerText : ''; })()")
    early = time.time() - t0 < 2.5
    if shots:
        shot = cdp("Page.captureScreenshot", format="png")["data"]
        Path(shots, f"add-photo-{w}-pending.png").write_bytes(base64.b64decode(shot))
    unchanged = "img.cloudy.nyc" not in POST.read_text()
    check("4: a line tapped before the upload is marked 'Placing when the upload finishes'",
          early and pending == "2|Placing when the upload finishes" and unchanged,
          {"pending": pending, "early": early,
           "banner": cdp.js("document.querySelector('.place-banner')?.innerText")})
    landed = wait_for(cdp, "!document.querySelector('.place-banner')"
                           " && !!document.querySelector('.block.editing')", 10)
    blocks = source_blocks()
    check("4: the photo lands at that gap once the upload is back",
          landed and len(blocks) == N_BLOCKS + 1 and blocks[2].startswith("![](https://img.cloudy.nyc/")
          and blocks[1].startswith("Paragraph 2") and blocks[3].startswith("Paragraph 3"),
          blocks[:4])
    editor = cdp.js("(() => { const e = document.querySelector('.block.editing');"
                    " return e ? e.dataset.index + '|' + !!e.querySelector('.image-strip')"
                    " + '|' + !!e.querySelector('.image-alt-input') : ''; })()")
    check("4: the new block's photo editor opens, for the alt text",
          editor == "2|true|true" and button_shown(cdp), {"editor": editor, "status": status(cdp)})
    check("4: Undo is offered", cdp.js("!document.getElementById('undo').disabled"))
    cdp.tap_el(".block.editing .image-cancel", 0.4)

    # --- 5. two photos make one row, at the end ---------------------------
    load(cdp, base)
    delay(0)
    pick(cdp, [green, blue])
    wait_for(cdp, "document.querySelector('.place-banner').innerText.includes('Uploaded')", 10)
    banner = cdp.js("document.querySelector('.place-banner').innerText")
    n_thumbs = cdp.js("document.querySelectorAll('.place-banner .place-thumbs img').length")
    check("5: two photos: plural text, two thumbnails",
          "Tap where the 2 photos go" in banner and n_thumbs == 2, banner)
    if shots:
        cdp.js("scrollTo(0, 0)")
        time.sleep(0.3)
        shot = cdp("Page.captureScreenshot", format="png")["data"]
        Path(shots, f"add-photo-{w}.png").write_bytes(base64.b64decode(shot))
    tap_gap(cdp, N_BLOCKS, 0.2)
    wait_for(cdp, "!document.querySelector('.place-banner') && !!document.querySelector('.block.editing')", 10)
    blocks = source_blocks()
    last = blocks[-1]
    check("5: two photos place as one img-row, appended at the end gap",
          len(blocks) == N_BLOCKS + 1 and last.startswith('<div class="img-row">')
          and last.count("<img ") == 2 and blocks[-2].startswith("Paragraph 8"), last)
    check("5: its photo editor opens with both photos",
          cdp.js("document.querySelectorAll('.block.editing .image-thumb').length") == 2
          and cdp.js(f"document.querySelector('.block.editing').dataset.index") == str(N_BLOCKS))
    cdp.tap_el(".block.editing .image-cancel", 0.4)

    # --- 5b. the top gap ---------------------------------------------------
    load(cdp, base)
    pick(cdp, [red])
    wait_for(cdp, "document.querySelector('.place-banner').innerText.includes('Uploaded')", 10)
    tap_gap(cdp, 0, 0.2)
    wait_for(cdp, "!document.querySelector('.place-banner')", 10)
    blocks = source_blocks()
    check("5: the top gap places above the first block",
          blocks[0].startswith("![](https://img.cloudy.nyc/") and blocks[1].startswith("I hope"),
          blocks[:2])
    cdp.js("document.querySelector('.block.editing .image-cancel')?.click()")

    # --- 6. Cancel and Escape ----------------------------------------------
    load(cdp, base)
    delay(1.5)
    pick(cdp, [red, green])
    srcs = cdp.js("[...document.querySelectorAll('.place-thumbs img')].map((i) => i.src)")
    tap_gap(cdp, 3)
    cdp.tap_el(".place-banner .move-cancel", 0.3)
    time.sleep(2)  # past the upload, which must not place anything
    revoked = cdp.js(f"""Promise.all({json.dumps(srcs)}.map((u) =>
      fetch(u).then(() => 'live', () => 'revoked')))""")
    check("6: Cancel (even after a line was tapped) inserts nothing",
          POST.read_text() == BODY and not cdp.js("!!document.querySelector('.place-banner')")
          and not cdp.js("!!document.querySelector('.move-target')") and button_shown(cdp),
          {"status": status(cdp)})
    check("6: Cancel revokes the thumbnails' object URLs", revoked == ["revoked", "revoked"], revoked)
    delay(0)
    pick(cdp, [red])
    cdp("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape",
        windowsVirtualKeyCode=27)
    cdp("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape",
        windowsVirtualKeyCode=27)
    time.sleep(0.5)
    check("6: Escape cancels", POST.read_text() == BODY
          and not cdp.js("!!document.querySelector('.place-banner')") and button_shown(cdp))

    # --- 7. a failed upload --------------------------------------------------
    load(cdp, base)
    pick(cdp, [red, bogus])
    gone = wait_for(cdp, "!document.querySelector('.place-banner')", 10)
    st = status(cdp)
    check("7: a failed upload leaves placement, says why, writes nothing",
          gone and st.startswith("upload failed") and "not a valid image" in st
          and POST.read_text() == BODY and button_shown(cdp), st)

    # --- 8. the post changed on disk under the placement --------------------
    load(cdp, base)
    pick(cdp, [red])
    wait_for(cdp, "document.querySelector('.place-banner').innerText.includes('Uploaded')", 10)
    changed = BODY + "\nWritten from a terminal.\n"
    POST.write_text(changed)
    tap_gap(cdp, 1, 0.8)
    check("8: a stale post gets the usual message, leaves placement, writes nothing",
          status(cdp) == "changed on disk — reload" and POST.read_text() == changed
          and not cdp.js("!!document.querySelector('.place-banner')"), status(cdp))

    # --- 9. hidden during proofread and move mode --------------------------
    load(cdp, base)
    cdp.tap_el("#proofread", 0.4)
    during_run = cdp.js("!document.getElementById('proof-progress').hidden") and not button_shown(cdp)
    in_review = wait_for(cdp, "!document.getElementById('review-bar').hidden", 15)
    hidden_review = in_review and not button_shown(cdp)
    cdp.tap_el(".review-bar .review-close", 0.4)
    check("9: hidden during a proofread run and its review, back after Close",
          during_run and hidden_review and button_shown(cdp),
          {"run": during_run, "review": hidden_review})
    cdp.js("document.querySelector('.block[data-index=\"1\"]').dispatchEvent(new MouseEvent('mouseover'))")
    cdp.js("[...document.querySelectorAll('.block[data-index=\"1\"] .block-controls button')]"
           ".find((b) => b.textContent === '⇅').click()")
    time.sleep(0.4)
    in_move = cdp.js("!!document.querySelector('.move-banner')")
    check("9: hidden in move mode", in_move and not button_shown(cdp))
    cdp.tap_el(".move-banner .move-cancel", 0.4)
    check("9: back after move mode", button_shown(cdp))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(Path.home() / ".cache"))
    args = ap.parse_args()

    if POST.exists():
        sys.exit(f"{POST} already exists; refusing to overwrite it")
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="add-photo-", dir=cache))
    delay_file = tmp / "delay"
    launcher = tmp / "launch.py"
    launcher.write_text(LAUNCHER.replace("REPO", repr(str(REPO))).replace("DELAY", repr(str(delay_file))))
    fake = tmp / "fake-claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(0o755)
    files = [png(tmp / "red.png", (200, 40, 40)), png(tmp / "green.png", (40, 160, 70)),
             png(tmp / "blue.png", (40, 90, 200))]
    bogus = tmp / "not-a-photo.jpg"
    bogus.write_text("this is not an image")
    files.append(bogus)
    procs: list[subprocess.Popen] = []
    results: list = []
    try:
        POST.write_text(BODY)
        py = venv_python()
        env = dict(os.environ, EDITOR_AUTH_DB=str(tmp / "auth.db"),
                   EDITOR_COOKIE_SECURE="false", EDITOR_CLAUDE_BIN=str(fake))
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
            [py, str(launcher), str(port)],
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
            try:
                run_viewport(cdp, base, w, h, results, args.shots, files, delay_file)
            except Exception as exc:  # noqa: BLE001
                results.append((f"{w}x{h} ran to the end", False, repr(exc)))
            cdp.js("localStorage.clear()")
    finally:
        for p in reversed(procs):
            # The whole process group, by its own PID: Chromium's renderer/GPU
            # children survive a plain terminate() of the parent.
            try:
                os.killpg(p.pid, 15)
                p.wait(timeout=10)
            except Exception:
                pass
        POST.unlink(missing_ok=True)
        shutil.rmtree(HISTORY, ignore_errors=True)
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
