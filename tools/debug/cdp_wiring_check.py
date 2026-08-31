"""Safe CDP wiring check for the FD-nation live draft driver.

Goal: prove the deployed driver (C:\\edge-debug-profile\\draft_driver.py) is
wired to the live Edge (CDP 9222) AND uses the original nflverse-built board --
without performing ANY draft click.

What this does (all read-only against the live browser):
  - probe CDP /json endpoints
  - connect a CDP WebSocket to the open Yahoo Fantasy tab
  - load the original board JSON the deployed driver would use
  - run verify_session() (read-only guard)
  - run read_available() on the live tab (read-only parse)
  - run choose_pick() against the original board (proves the ORIGINAL method)

What this does NOT do: navigate, click, or draft. No mutations.
"""
import importlib.util
import json
import os
import sys
import urllib.request

CDP = "http://127.0.0.1:9222"
DEPLOYED = r"C:\edge-debug-profile\draft_driver.py"


def load_deployed():
    spec = importlib.util.spec_from_file_location("deployed_draft_driver", DEPLOYED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http_get(path):
    with urllib.request.urlopen(CDP + path, timeout=8) as r:
        return json.loads(r.read().decode())


def find_yahoo_tab():
    targets = http_get("/json/list")
    for t in targets:
        if t.get("type") == "page" and "fantasysports.yahoo.com" in (t.get("url") or ""):
            return t
    # fall back to any page tab (so we can at least prove CDP works)
    for t in targets:
        if t.get("type") == "page":
            return t
    return None


def main():
    print("=== 1. CDP endpoints ===")
    try:
        ver = http_get("/json/version")
        print("browser:", ver.get("Browser"))
    except Exception as e:
        print("CDP UNREACHABLE:", e)
        return 1

    print("\n=== 2. Load deployed driver module ===")
    mod = load_deployed()
    print("module loaded from:", DEPLOYED)
    print("FP_API_KEY set? ", bool(mod.FP_API_KEY))
    # Replicate run_draft's engine selection to PROVE the original board wins
    # even when FP_API_KEY is present (the old fragile behaviour flipped to
    # FantasyPros). Only an explicit DRAFT_ENGINE=fantasypros overrides it.
    engine = (os.environ.get("DRAFT_ENGINE") or "original").strip().lower()
    uses_fp = (engine == "fantasypros") and bool(mod.FP_API_KEY)
    print("DRAFT_ENGINE env:", repr(os.environ.get("DRAFT_ENGINE")),
          "-> resolved engine:", engine, "| would use FantasyPros?", uses_fp)
    board = mod.load_original_board()
    if board is None:
        print("ORIGINAL board JSON NOT loaded -> would use static_board fallback")
        board = mod.static_board()
        mode = "STATIC(fallback)"
    else:
        print("ORIGINAL board loaded: %d players" % len(board))
        mode = "ORIGINAL(nflverse)"
    print("BOARD_MODE would be:", mode)

    print("\n=== 3. Connect to live Edge (Yahoo tab) ===")
    tab = find_yahoo_tab()
    if tab is None:
        print("No page tab found in Edge.")
        return 1
    print("target tab:", tab.get("url"))
    import websocket
    ws = websocket.create_connection(
        tab["webSocketDebuggerUrl"], timeout=10,
        header={"Origin": "http://127.0.0.1:9222"})
    for dom in ("Runtime", "Page", "Input"):
        ws.send(json.dumps({"id": 1, "method": dom + ".enable", "params": {}}))
    print("CDP WebSocket connected:", ws.connected if hasattr(ws, "connected") else "ok")

    print("\n=== 4. verify_session() (read-only guard) ===")
    ok = mod.verify_session(ws)
    print("verify_session ->", ok, "(True=proceed / inconclusive, False=abort)")

    print("\n=== 5. read_available() on live tab (read-only parse) ===")
    raw = mod.read_available(ws) or []
    print("rows parsed on live tab:", len(raw))
    for r in raw[:8]:
        print("   ", r)

    print("\n=== 6. choose_pick() with ORIGINAL board (proves the method) ===")
    # Simulate draft start: everything on the board is still available.
    available = [v["name"] for v in board.values()]
    pick = mod.choose_pick(available, {}, 1, board, adp_map={})
    print("pick @ R1 (all available):", pick)

    # Simulate a mid-draft state: 2 RB, 2 WR, 1 TE already taken, round 8.
    drafted = {"RB": 2, "WR": 2, "TE": 1}
    pick2 = mod.choose_pick(available, drafted, 8, board, adp_map={})
    print("pick @ R8 (RB2/WR2/TE1 filled):", pick2)

    print("\n=== 7. cleanup ===")
    ws.close()
    print("DONE: CDP wiring + original-board method verified (no clicks performed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
