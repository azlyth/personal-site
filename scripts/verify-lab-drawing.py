#!/usr/bin/env python3
"""End-to-end check that a fast stroke on the drawing canvas is stored whole.

Drives real Chromium over the DevTools Protocol against the deployed page,
drags across the canvas as fast as the protocol will dispatch events, and
compares the number of pointer moves against the number of strokes Redis
gained. Before the queueing fix this reported a handful of strokes out of
dozens; now the two numbers match.

Usage: python3 scripts/verify-lab-drawing.py [base-url] [moves]
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time

import websocket

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://cloudy.nyc"
MOVES = int(sys.argv[2]) if len(sys.argv) > 2 else 60
PORT = 9222

# Both pages carry their own copy of the drawing client, so both get checked.
PAGES = [
    {
        "url": "/lab/experiment-3/?mobile=true",
        "canvas": "mobile-drawing-canvas",
        "ready": "(() => { const w = document.getElementById('mobile-canvas-wrapper');"
                 " return !!w && w.style.display === 'block'; })()",
    },
    {
        "url": "/lab/",
        "canvas": "drawing-canvas",
        "ready": "(() => { try { return !!document.getElementById('drawing-canvas')"
                 " && !!drawingSocket && drawingSocket.connected; } catch (e) { return false; } })()",
    },
]


def stored_strokes():
    raw = subprocess.run(
        ["docker", "compose", "exec", "-T", "redis", "redis-cli", "--raw",
         "GET", "drawing:global-drawing-canvas"],
        capture_output=True, text=True, check=True,
    ).stdout
    return len(json.loads(raw)["strokes"])


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
    profile = tempfile.mkdtemp(prefix="lab-verify-")
    chromium = subprocess.Popen([
        "/usr/bin/chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
        f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
        f"--user-data-dir={profile}", "--window-size=412,915", "about:blank",
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

        failures = 0
        for spec in PAGES:
            url = BASE + spec["url"]
            print(f"\n{url}")
            dev.send("Page.navigate", url=url)

            for _ in range(60):
                time.sleep(0.5)
                if dev.eval(spec["ready"]):
                    break
            else:
                print("FAIL: canvas never connected to the backend")
                failures += 1
                continue

            rect = json.loads(dev.eval(
                "(() => { const r = document.getElementById('" + spec["canvas"] + "')"
                ".getBoundingClientRect();"
                " return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height}); })()"))

            before = stored_strokes()

            x0 = rect["x"] + rect["w"] * 0.1
            x1 = rect["x"] + rect["w"] * 0.9
            y = rect["y"] + rect["h"] * 0.5
            step = (x1 - x0) / MOVES

            dev.send("Input.dispatchMouseEvent", type="mousePressed", x=x0, y=y,
                     button="left", clickCount=1, buttons=1)
            for i in range(1, MOVES + 1):
                dev.send("Input.dispatchMouseEvent", type="mouseMoved",
                         x=x0 + step * i, y=y, button="left", buttons=1)
            dev.send("Input.dispatchMouseEvent", type="mouseReleased", x=x1, y=y,
                     button="left", clickCount=1, buttons=0)

            time.sleep(2)
            after = stored_strokes()
            gained = after - before

            print(f"  pointer moves dispatched: {MOVES}")
            print(f"  strokes stored:           {gained} (canvas {before} -> {after})")
            if gained == MOVES:
                print("  PASS: the whole stroke was stored")
            else:
                print("  FAIL: strokes were dropped between the browser and Redis")
                failures += 1

        return 1 if failures else 0
    finally:
        chromium.terminate()
        chromium.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
