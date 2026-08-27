---
name: edge-cdp
description: "Connect to a locally running Microsoft Edge exposed via Chrome DevTools Protocol (CDP) on a given port, and drive it with human-like input (Bézier mouse motion, jitter, variable delays). Use for controlling a user-launched Edge (e.g. fantasy sports, web automation) from this machine."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [Browser-Automation, CDP, Edge, WebSocket, Web-Scraping]
    related_skills: [fantasy-read, fantasy-draft]
---

# Edge CDP Driver (human-like)

Drive a running Microsoft Edge via the Chrome DevTools Protocol. Proven for
controlling a user's Yahoo Fantasy Football tab from this Windows machine.

## Critical requirements (learned the hard way)
- Edge MUST be launched with `--remote-debugging-port=PORT --remote-allow-origins=*`.
  Without `--remote-allow-origins=*`, the WebSocket control channel is rejected
  with HTTP 403 even though the `/json` HTTP endpoints work.
- From WSL2 you CANNOT reach Edge directly (separate network namespace). Run the
  driver on the WINDOWS side via `py.exe` (where `websocket-client` is installed).
- `pip install websocket-client` into the Windows Python (py.exe), NOT WSL python3.
- Page sees `navigator.webdriver === false` and no automation banner (raw CDP, no
  `--enable-automation`). Good for stealth.

## Connection (Python, Windows side)
```python
import json, urllib.request, websocket

CDP = "http://127.0.0.1:9222"   # or whatever port Edge uses

def http_get(path):
    with urllib.request.urlopen(CDP + path, timeout=8) as r:
        return json.loads(r.read().decode())

def connect():
    targets = http_get("/json/list")
    page = next(t for t in targets if t.get("type") == "page")
    ws = websocket.create_connection(
        page["webSocketDebuggerUrl"], timeout=10,
        header={"Origin": "http://127.0.0.1:9222"})
    # enable domains
    for dom in ("Runtime", "Page", "Input"):
        ws.send(json.dumps({"id": 1, "method": dom + ".enable", "params": {}}))
    return ws

def ev(ws, expr):
    wid = 12345
    ws.send(json.dumps({"id": wid, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True}}))
    while True:
        o = json.loads(ws.recv())
        if o.get("id") == wid:
            return o.get("result", {}).get("result", {}).get("value")
```

## Human-like input (avoid teleporting / bot detection)
```python
import random, math

def move_to(ws, x, y, steps=None, jitter=3):
    cur = getattr(move_to, "cur", (x, y))
    sx, sy = cur
    if steps is None:
        steps = max(8, int(math.hypot(x - sx, y - sy) / 12))
    mx = (sx + x) / 2 + random.uniform(-25, 25)
    my = (sy + y) / 2 + random.uniform(-25, 25)
    for i in range(1, steps + 1):
        t = i / steps
        bx = (1-t)**2*sx + 2*(1-t)*t*mx + t**2*x
        by = (1-t)**2*sy + 2*(1-t)*t*my + t**2*y
        jx = bx + random.uniform(-jitter, jitter)
        jy = by + random.uniform(-jitter, jitter)
        ws.send(json.dumps({"id": 0, "method": "Input.dispatchMouseEvent",
                            "params": {"type": "mouseMoved", "x": round(jx), "y": round(jy)}}))
        time.sleep(random.uniform(0.004, 0.016))
    move_to.cur = (x, y)

def click_at(ws, x, y, button="left"):
    move_to(ws, x, y)
    time.sleep(random.uniform(0.05, 0.2))
    ws.send(json.dumps({"id": 0, "method": "Input.dispatchMouseEvent",
                        "params": {"type": "mousePressed", "x": x, "y": y,
                                   "button": button, "clickCount": 1}}))
    time.sleep(random.uniform(0.04, 0.12))
    ws.send(json.dumps({"id": 0, "method": "Input.dispatchMouseEvent",
                        "params": {"type": "mouseReleased", "x": x, "y": y,
                                   "button": button, "clickCount": 1}}))
    time.sleep(random.uniform(0.1, 0.4))
```

## Reliable WSL->Windows data round-trip
`/mnt/c` is unreliable from this shell. To move text/results:
1. Run Python via `cat script.py | py.exe -` (stdin).
2. From Windows Python, base64-encode output and print `B64START...B64END`.
3. Decode in WSL with python3. (See readdump pattern in fantasy-draft.)

## Tips
- Read text/state via `Runtime.evaluate` returning `innerText` (not full HTML; large
  HTML blows past buffers). Encode logs as UTF-8 files, never print to cp932 console.
- Screenshot: `Page.captureScreenshot` -> base64 -> write PNG to C:\edge-debug-profile\.
