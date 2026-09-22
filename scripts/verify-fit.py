#!/usr/bin/env python3
"""Check that the pages meant to be one screenful still fit in one screenful.

The root font size scales up on big displays (see the `html` rule in
templates/base.html), capped by `--fit-cap: calc(100vh / 63)` so a page never
grows taller than the window. That 63 is the home page's height in rem -- a
MEASUREMENT of today's content, not a constant of nature. Add a project to the
home page list, or enough posts to the blog index, and the real number climbs
past 63, the cap stops binding early enough, and the footer slides back off
the bottom of the screen.

Nothing else would tell you. The page still renders, still looks right at a
laptop size, and only misbehaves on a display you may not be sitting at. So
this drives real Chromium at several window heights and fails if any capped
page overflows.

Blog posts are deliberately NOT checked: they set `html.page-scrolls`, opt out
of the cap, and are ~370 rem tall. They are supposed to scroll.

Usage: python3 scripts/verify-fit.py [base-url]
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time

import websocket

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://cloudy.nyc"
PORT = 9223

# Every page that carries the default --fit-cap. A post is excluded on
# purpose; so are the /lab/#<game> hashes, where an open board is taller than
# the menu and scrolling is expected.
PAGES = ["/", "/blog/", "/timeline/", "/lab/"]

# The cap only binds on a tall window -- below ~1070px the clamp floor wins
# and nothing scales. These span from just inside that threshold up past the
# point where the width term takes over, so a bad constant cannot hide in a
# gap between two sizes.
VIEWPORTS = [(2560, 1100), (2560, 1330), (2560, 1440), (3840, 1600), (3840, 2000)]


# Scrolling to the bottom and seeing whether we actually moved IS the
# complaint, stated exactly: "the footer is cut off, you have to scroll down a
# bit". It is also the only reliable measure -- documentElement.scrollHeight is
# clamped UP to the viewport height, so the obvious height-vs-window comparison
# silently passes for every page at every size.
MEASURE = """(() => {
  const before = window.scrollY;
  window.scrollTo(0, 1e6);
  const over = Math.round(window.scrollY);
  window.scrollTo(0, before);
  return JSON.stringify({
    root: parseFloat(getComputedStyle(document.documentElement).fontSize),
    vh: innerHeight,
    over,
  });
})()"""

# A page that MUST overflow. If this one reports a fit, the measurement above
# has stopped working and every "ok" in this run is meaningless -- which is
# exactly the failure the first version of this script shipped with.
CANARY = "/blog/guerilla-gardening/"


class Devtools:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True)
        self.id = 0

    def send(self, method, **params):
        self.id += 1
        self.ws.send(json.dumps({"id": self.id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def eval(self, expression):
        result = self.send("Runtime.evaluate", expression=expression, returnByValue=True)
        return result.get("result", {}).get("value")


def main():
    profile = tempfile.mkdtemp(prefix="fit-verify-")
    chromium = subprocess.Popen([
        "/usr/bin/chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
        f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "--window-size=1200,900", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        targets = None
        for _ in range(60):
            try:
                targets = json.loads(subprocess.run(
                    ["curl", "-s", f"http://127.0.0.1:{PORT}/json"],
                    capture_output=True, text=True, check=True).stdout)
                if targets:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not targets:
            raise RuntimeError("chromium devtools endpoint never came up")

        page = next(t for t in targets if t["type"] == "page")
        dev = Devtools(page["webSocketDebuggerUrl"])
        dev.send("Page.enable")
        dev.send("Runtime.enable")

        failures = []

        dev.send("Emulation.setDeviceMetricsOverride",
                 width=2560, height=1330, deviceScaleFactor=1, mobile=False)
        dev.send("Page.navigate", url=BASE + CANARY)
        for _ in range(40):
            if dev.eval("document.readyState === 'complete'"):
                break
            time.sleep(0.25)
        if json.loads(dev.eval(MEASURE))["over"] <= 0:
            print("FAIL: the canary page %s reports that it fits in a 1330px"
                  % CANARY)
            print("window. It is ~370 rem tall, so it cannot. The overflow")
            print("measurement is broken and this check proves nothing.")
            return 1
        print("canary ok: %s correctly reports an overflow" % CANARY)

        for width, height in VIEWPORTS:
            dev.send("Emulation.setDeviceMetricsOverride",
                     width=width, height=height, deviceScaleFactor=1, mobile=False)
            print(f"\n{width}x{height}")
            for path in PAGES:
                dev.send("Page.navigate", url=BASE + path)
                # Fonts land after first paint and they change the height, so
                # wait on the font loader rather than on a fixed sleep.
                for _ in range(40):
                    if dev.eval("document.readyState === 'complete' && document.fonts.status === 'loaded'"):
                        break
                    time.sleep(0.25)
                measured = json.loads(dev.eval(MEASURE))
                over = measured["over"]
                ok = over <= 0
                print("  %-12s root %5.1fpx  window %5dpx  %s"
                      % (path, measured["root"], measured["vh"],
                         "fits" if ok else "SCROLLS %dpx past the bottom" % over))
                if not ok:
                    failures.append((width, height, path, over))

        if failures:
            print("\nFAIL: %d page/size combination(s) overflow." % len(failures))
            print("The --fit-cap divisor in templates/base.html is too small for")
            print("today's content. Re-measure the tallest capped page with:")
            print("  document.documentElement.scrollHeight /"
                  " parseFloat(getComputedStyle(document.documentElement).fontSize)")
            print("and raise the divisor in the `html` rule to match.")
            return 1

        print("\nOK: every capped page fits its window at all %d sizes." % len(VIEWPORTS))
        return 0
    finally:
        chromium.terminate()
        try:
            chromium.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chromium.kill()
        # terminate() leaves the renderer and GPU children behind; they hold
        # the profile dir open and pile up in /tmp across runs.
        subprocess.run(["pkill", "-f", profile], check=False)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
