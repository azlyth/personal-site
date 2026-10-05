#!/usr/bin/env python3
"""Check the editor's Proofread flow end to end in headless Chromium.

What it pins, at two tablet viewports:

1. Tapping ✨ shows the progress strip; it counts up to "Proofreading 7 of
   7 paragraphs" and its fill grows between the two batches.
2. The red/green marks render, the bottom bar says "1 of N", ↓ steps on with
   the current mark scrolled into view above the bar, ↑ wraps from 1 to N.
3. Tapping a block during review opens no editor and says why.
4. Accept writes the fix to the post on disk and enables Undo.
5. Reject leaves the source alone and takes the mark away.
6. Accept all writes every remaining fix and ends the review.
7. Close mid-review drops the marks and writes nothing.
8. A batch whose claude call fails is reported; the other batch still shows.
9. Every review-bar button is a 44px touch target.
Plus: starting a proofread saves a text editor that was open.

Same harness as scripts/verify-edit-tap.py (whose CDP helper it imports): a
scratch draft in content/blog, a scratch uvicorn of THIS checkout on a free
port with its own auth db under ~/.cache, and EDITOR_CLAUDE_BIN pointed at a
fake claude that "finds" three planted typos. Everything is removed
afterwards; processes are killed by their own PIDs.

Usage: python3 scripts/verify-proofread.py [--shots DIR]
  Writes DIR/proofread-<width>.png of the review state (default ~/.cache).
Exits non-zero if any check fails.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("verify_edit_tap", REPO / "scripts" / "verify-edit-tap.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)
CDP, free_port, wait_http, venv_python = harness.CDP, harness.free_port, harness.wait_http, harness.venv_python

BLOG = REPO / "content" / "blog"
SLUG = "zz-proofread-scratch"
POST = BLOG / f"{SLUG}.md"
HISTORY = REPO / "editor" / ".history" / SLUG

# Seven paragraphs, so two batches (5 + 2). Five planted typos across
# paragraphs 1, 2 and 6; paragraph 4 is clean on purpose.
PARAS = [
    "I hope you recieve this before teh weekend starts.",
    "We leave tomorow morning, early.",
    "A third paragraph with nothing wrong in it at all.",
    "The fourth one is clean as well.",
    "Fifth paragraph, still fine.",
    "Did you recieve the tickets for tomorow?",
    "And the seventh closes it out.",
]
BODY = (
    "+++\ntitle = \"Proofread scratch\"\ndate = 2026-10-04\ndraft = true\n+++\n\n"
    + "\n\n".join(PARAS) + "\n"
)
N_SUGGESTIONS = 5

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, re, sys, time
prompt = sys.argv[sys.argv.index("-p") + 1]
time.sleep(0.6)
# Case 8: with the marker present, the batch holding block 5 fails.
if os.path.exists(MARKER) and '<block index="5">' in prompt:
    sys.exit(3)
out = []
for idx, body in re.findall(r'<block index="(\d+)">\n(.*?)\n</block>', prompt, re.S):
    for wrong, right in (("recieve", "receive"), ("teh", "the"), ("tomorow", "tomorrow")):
        if body.count(wrong) == 1:
            out.append({"block": int(idx), "before": wrong, "after": right, "kind": "spelling"})
print(json.dumps(out))
'''

VIEWPORTS = [(1024, 1366), (820, 1180)]

# Records every value the progress strip shows, so a check can see the
# intermediate "5 of 7" even though the strip hides as soon as it's done.
WATCH_PROGRESS = """(() => {
  window.__proof = [];
  const p = document.getElementById('proof-progress');
  const rec = () => window.__proof.push({
    shown: !p.hidden,
    text: p.querySelector('.proof-text').textContent,
    fill: parseFloat(p.querySelector('.proof-fill').style.width) || 0,
  });
  new MutationObserver(rec).observe(p, {attributes: true, childList: true, subtree: true,
    characterData: true});
})()"""


def load(cdp: CDP, base: str) -> None:
    POST.write_text(BODY)
    shutil.rmtree(HISTORY, ignore_errors=True)
    cdp("Page.navigate", url=f"{base}/edit/{SLUG}")
    for _ in range(80):
        time.sleep(0.25)
        try:
            if cdp.js("!!document.querySelector('.block[data-index=\"6\"]')"):
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


def text(cdp, selector) -> str:
    return cdp.js(f"(document.querySelector({json.dumps(selector)}) || {{}}).textContent || ''")


def status(cdp) -> str:
    return text(cdp, "#status")


def count_text(cdp) -> str:
    return text(cdp, ".review-bar .review-count")


BAR_VISIBLE = "!document.getElementById('review-bar').hidden"
RUN_DONE = "document.getElementById('proof-progress').hidden"
NEXT = '.review-bar button[title="Next suggestion"]'
PREV = '.review-bar button[title="Previous suggestion"]'


def start_proofread(cdp) -> bool:
    cdp.js(WATCH_PROGRESS)
    cdp.js("scrollTo(0, 0)")
    tapped = cdp.tap_el("#proofread", 0.2)
    return tapped and wait_for(cdp, RUN_DONE + " && window.__proof.length > 0", 20)


def run_viewport(cdp, base, w, h, results, shots):
    cdp("Emulation.setDeviceMetricsOverride", width=w, height=h,
        deviceScaleFactor=1, mobile=True)
    cdp("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

    def check(name, ok, detail=None):
        results.append((f"{w}x{h} {name}", bool(ok), detail))

    # --- 0. an open text editor is saved before the proofread starts ----------
    load(cdp, base)
    cdp.tap_el('.block[data-index="2"]', 0.6)
    cdp.js("(() => { const t = document.querySelector('.block.editing textarea');"
           " t.value = t.value + ' Saved first.'; t.dispatchEvent(new Event('input')); })()")
    started = start_proofread(cdp)
    check("0: ✨ saves the open editor first and closes it",
          started and "Saved first." in POST.read_text()
          and not cdp.js("!!document.querySelector('.block.editing')"),
          {"started": started, "status": status(cdp)})

    # --- 1. progress -----------------------------------------------------------
    load(cdp, base)
    ok = start_proofread(cdp)
    log = cdp.js("JSON.stringify(window.__proof)")
    log = json.loads(log) if log else []
    texts = [e["text"] for e in log if e["shown"]]
    fills = [e["fill"] for e in log if e["shown"]]
    check("1: progress shows and reaches 'Proofreading 7 of 7 paragraphs'",
          ok and "Proofreading 7 of 7 paragraphs" in texts, texts)
    check("1: the fill grows between batches",
          "Proofreading 5 of 7 paragraphs" in texts and fills and max(fills) == 100
          and any(0 < f < 100 for f in fills), fills)

    # --- 2. marks, bar, stepping -----------------------------------------------
    marks = cdp.js("[document.querySelectorAll('del.pr-old[data-sid]').length,"
                   " document.querySelectorAll('ins.pr-new[data-sid]').length]")
    check("2: red/green pairs render for every suggestion",
          marks == [N_SUGGESTIONS, N_SUGGESTIONS], marks)
    check("2: the bar says 1 of N", wait_for(cdp, BAR_VISIBLE, 2)
          and count_text(cdp) == f"1 of {N_SUGGESTIONS}", count_text(cdp))
    check("2: no block controls while reviewing",
          cdp.js("document.querySelectorAll('.block-controls').length") == 0)
    # 9. touch targets
    sizes = json.loads(cdp.js("JSON.stringify([...document.querySelectorAll('.review-bar button')]"
                              ".map((b) => { const r = b.getBoundingClientRect();"
                              " return [b.textContent, r.width, r.height]; }))"))
    check("9: every review-bar button is >= 44px tall",
          sizes and all(s[2] >= 43.5 and s[1] >= 43.5 for s in sizes), sizes)
    bar_one_row = cdp.rect("#review-bar")
    check("9: the review bar fits the width", bar_one_row and bar_one_row["w"] <= w, bar_one_row)

    cdp.tap_el(NEXT, 1.0)
    in_view = json.loads(cdp.js(
        "(() => { const m = document.querySelector('del.pr-current');"
        " const bar = document.getElementById('review-bar').getBoundingClientRect();"
        " if (!m) return 'null'; const r = m.getBoundingClientRect();"
        " return JSON.stringify({top: r.top, bottom: r.bottom, barTop: bar.top,"
        " toolbar: document.querySelector('.bar').getBoundingClientRect().bottom}); })()"))
    check("2: ↓ moves to 2", count_text(cdp) == f"2 of {N_SUGGESTIONS}", count_text(cdp))
    check("2: the current mark is on screen, above the bar and below the toolbar",
          in_view and in_view["bottom"] <= in_view["barTop"] and in_view["top"] >= in_view["toolbar"],
          in_view)
    if shots:
        png = cdp("Page.captureScreenshot", format="png")["data"]
        Path(shots, f"proofread-{w}.png").write_bytes(base64.b64decode(png))
    cdp.tap_el(PREV, 0.4)
    cdp.tap_el(PREV, 0.4)
    check("2: ↑ wraps from 1 to N", count_text(cdp) == f"{N_SUGGESTIONS} of {N_SUGGESTIONS}",
          count_text(cdp))
    cdp.tap_el(NEXT, 0.6)  # back to 1

    # --- 3. a block tap during review -----------------------------------------
    cdp.tap_el('.block[data-index="3"]', 0.6)
    check("3: tapping a block opens no editor and says why",
          not cdp.js("!!document.querySelector('.block.editing')")
          and status(cdp) == "Close proofreading to edit.", status(cdp))

    # --- 4. Accept -------------------------------------------------------------
    undo_before = cdp.js("document.getElementById('undo').disabled")
    cdp.tap_el(".review-bar .review-accept", 1.2)
    src = POST.read_text()
    check("4: Accept writes the fix to the post",
          "I hope you receive this" in src and "recieve this" not in src, src[-400:])
    check("4: the count drops", count_text(cdp) == f"1 of {N_SUGGESTIONS - 1}", count_text(cdp))
    check("4: Undo is enabled", undo_before and not cdp.js("document.getElementById('undo').disabled"),
          {"before": undo_before})

    # --- 5. Reject -------------------------------------------------------------
    sid = cdp.js("(document.querySelector('del.pr-current') || {dataset: {}}).dataset.sid")
    before = POST.read_text()
    cdp.tap_el(".review-bar .review-reject", 0.8)
    check("5: Reject leaves the source alone", POST.read_text() == before and "teh weekend" in before)
    check("5: and its mark is gone",
          sid and cdp.js(f"document.querySelectorAll('[data-sid=\"{sid}\"]').length") == 0
          and count_text(cdp) == f"1 of {N_SUGGESTIONS - 2}", {"sid": sid, "count": count_text(cdp)})

    # --- 6. Accept all ---------------------------------------------------------
    cdp.tap_el(".review-bar .review-all", 0.2)
    wait_for(cdp, "document.getElementById('review-bar').hidden", 10)
    src = POST.read_text()
    check("6: Accept all writes every remaining fix",
          "We leave tomorrow morning" in src
          and "Did you receive the tickets for tomorrow?" in src
          and "teh weekend" in src, src[-400:])
    check("6: the bar hides and says so",
          cdp.js("document.getElementById('review-bar').hidden")
          and status(cdp) == "All suggestions reviewed."
          and cdp.js("document.querySelectorAll('del.pr-old, ins.pr-new').length") == 0,
          status(cdp))
    check("6: blocks are editable again",
          cdp.js("document.querySelectorAll('.block-controls').length") == 7)

    # --- 7. Close mid-review ---------------------------------------------------
    load(cdp, base)
    start_proofread(cdp)
    wait_for(cdp, BAR_VISIBLE, 5)
    cdp.tap_el(".review-bar .review-close", 0.6)
    check("7: Close hides the bar, drops the marks, writes nothing",
          cdp.js("document.getElementById('review-bar').hidden")
          and cdp.js("document.querySelectorAll('del.pr-old, ins.pr-new').length") == 0
          and POST.read_text() == BODY)
    cdp.tap_el('.block[data-index="3"]', 0.6)
    check("7: and a block opens for editing again",
          cdp.js("!!document.querySelector('.block.editing')"))

    # --- 8. one batch fails ----------------------------------------------------
    load(cdp, base)
    MARKER.write_text("fail")
    try:
        start_proofread(cdp)
    finally:
        MARKER.unlink(missing_ok=True)
    st = status(cdp)
    check("8: a failed batch is reported", st.startswith("Couldn't check paragraphs"), st)
    check("8: the other batch's suggestions still show",
          cdp.js("document.querySelectorAll('del.pr-old').length") == 3
          and count_text(cdp) == "1 of 3", count_text(cdp))
    cdp.tap_el(".review-bar .review-close", 0.4)
    check("8: nothing was written", POST.read_text() == BODY)


MARKER: Path  # set in main()


def main() -> int:
    global MARKER
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(Path.home() / ".cache"))
    args = ap.parse_args()

    if POST.exists():
        sys.exit(f"{POST} already exists; refusing to overwrite it")
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="proofread-", dir=cache))
    MARKER = tmp / "fail-batch"
    fake = tmp / "fake-claude"
    fake.write_text(FAKE_CLAUDE.replace("MARKER", repr(str(MARKER)), 1))
    fake.chmod(0o755)
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
            try:
                run_viewport(cdp, base, w, h, results, args.shots)
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
