"""Mock draft validation for the FD-nation live draft driver.

Goal: prove the previously-untested CDP PICK-CLICK path works end to end
(read_available -> choose_pick -> click_player -> _confirm_pick) BEFORE the
real Yahoo draft room opens on Sep 1. It also asserts the draft CONTRACT:
K/DEF only in the last two rounds, QB not before round 10, every required
slot filled by its anchor deadline, and every chosen player actually clicked
and confirmed.

How it works (all against the LIVE Edge on 127.0.0.1:9222):
  - opens the Yahoo-style mock room (tools/mock_draft_room.html) in a NEW tab
    via CDP Target.createTarget + attachToTarget (sessionId model, so your real
    Yahoo tab is never touched and we don't depend on /json/list);
  - injects the REAL original board (250 players) and uses its available pool
    10-team league has enough bodies for 150 picks;
  - runs a full 15-round snake for team #2, calling the DEPLOYED driver's real
    functions on every turn (no reimplementation);
  - between the bot's turns it simulates the other 9 teams drafting skill
    players only (opponents leave K/DEF for the bot's late rounds), so the
    scarcity/anchor guardrails and the K/DEF-last contract are exercised;
  - verifies the final roster is legal AND the contract held, then closes tab.

This is validation only -- it performs real CDP mouse clicks inside the mock
page but never touches Yahoo, your league, or a real draft.
"""
import importlib.util
import json
import os
import random
import sys
import threading
import time
import urllib.request
import websocket
import http.server
import socketserver

CDP = "http://127.0.0.1:9222"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _pick(env, win, posix):
    """Env override wins; otherwise the Windows default or a portable path."""
    if os.environ.get(env):
        return os.environ[env]
    return win if sys.platform.startswith("win") else posix

# Deployed driver: test the exact copy the live draft will use. Override with
# DRAFT_DRIVER on non-standard installs (e.g. the headless-Mac copy).
DEPLOYED = _pick("DRAFT_DRIVER", r"C:\edge-debug-profile\draft_driver.py",
                 os.path.join(REPO, "driver", "draft_driver.py"))
HTML = _pick("MOCK_HTML", r"C:\nfl-win\tools\mock_draft_room.html",
             os.path.join(REPO, "tools", "mock_draft_room.html"))
LOG = _pick("MOCK_LOG", r"C:\edge-debug-profile\mock_draft_log.txt",
            os.path.join(REPO, "logs", "mock_draft_log.txt"))
os.makedirs(os.path.dirname(LOG), exist_ok=True)
# Let the imported deployed driver log to the same writable place too.
os.environ.setdefault("FD_DRAFT_LOG", LOG)
MOCK_PORT = 8765

TEAM_ID = "2"
N_TEAMS = 10
TOTAL_ROUNDS = 15
REQUIRED = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}

# Anchor deadline mirror of driver/draft_driver.py ANCHOR_BY_ROUND: the latest
# round by which the REQUIRED count for a position must be met. K and DEF share
# the last-two-rounds window (14-15); the driver fills K at R14 and DEF at R15,
# so their effective deadline is the final round (15). Used by the contract
# assertions below -- if the driver regresses, the run fails loudly.
ANCHOR_DEADLINE = {"RB": 5, "WR": 9, "TE": 7, "QB": 10, "K": 15, "DEF": 15}
K_DEF_FIRST_ROUND = TOTAL_ROUNDS - 2 + 1   # K/DEF only from this round on (=14)
QB_FIRST_ROUND = 10                         # QB not before this round

# Filler name pools: 1-2 alphabetic words, NO digits, so the deployed
# read_available() regex parses every filler row. Skills enough combos for ~160
# unique fillers (47 first x 35 last).
_FILLER_FIRST = ["Ace", "Bay", "Cole", "Dane", "Eli", "Finn", "Gage", "Hugo", "Ike",
                 "Jax", "Kai", "Lane", "Max", "Nash", "Owen", "Pace", "Quinn",
                 "Reed", "Slade", "Tate", "Vance", "Wade", "Xan", "York", "Zane",
                 "Beck", "Cruz", "Drew", "Ezra", "Fox", "Grey", "Hale", "Ivo",
                 "Jude", "Knox", "Luca", "Milo", "Nate", "Otis", "Pax", "Rhett",
                 "Sawyer", "Theo", "Vik", "Wren", "Xer", "Yael", "Zed"]
_FILLER_LAST = ["Ash", "Birch", "Crest", "Dale", "East", "Frost", "Grove", "Hale",
                "Isle", "Jade", "Knoll", "Lyn", "Marsh", "North", "Oak", "Pike",
                "Quay", "Reef", "Stone", "Vale", "West", "Yew", "Zorn", "Brook",
                "Cove", "Dune", "Field", "Glass", "Heath", "Lake", "Moor", "Park",
                "Ridge", "Shore", "Wood"]


def log(s):
    """Append a timestamped line to the mock log and echo it to stdout."""
    line = time.strftime("%H:%M:%S") + " " + str(s)
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_deployed():
    """Import the DEPLOYED driver module (C:\\edge-debug-profile\\draft_driver.py)
    by absolute path so the harness tests the real file, not a copy."""
    spec = importlib.util.spec_from_file_location("dd", DEPLOYED)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def http_get(p):
    """GET a JSON endpoint from the local CDP HTTP interface."""
    with urllib.request.urlopen(CDP + p, timeout=8) as r:
        return json.loads(r.read().decode())


def ws_connect(url):
    """Open a websocket to a CDP endpoint with the localhost Origin header."""
    return websocket.create_connection(url, timeout=15, header={"Origin": CDP})


def send(ws, method, params=None, session_id=None, rid=None):
    """Send a CDP command; returns the id used (so the caller can match the
    response). Injects sessionId when given."""
    rid = rid or random.randint(100000, 999999)
    msg = {"id": rid, "method": method, "params": params or {}}
    if session_id is not None:
        msg["sessionId"] = session_id
    ws.send(json.dumps(msg))
    return rid


def recv_id(ws, rid, timeout=20):
    """Block until a CDP response with the given id arrives; raise on error."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        o = json.loads(ws.recv())
        if o.get("id") == rid:
            if "error" in o:
                raise RuntimeError(o["error"])
            return o.get("result")
    raise TimeoutError("no CDP response for id %s" % rid)


def browser_ws():
    """Open a websocket to the browser-level CDP target."""
    return ws_connect(http_get("/json/version")["webSocketDebuggerUrl"])


def peval(ws, expr, session_id=None, timeout=20):
    """Evaluate a JS expression in the given CDP session; return its value."""
    rid = send(ws, "Runtime.evaluate",
               {"expression": expr, "returnByValue": True, "awaitPromise": True},
               session_id=session_id)
    return recv_id(ws, rid, timeout).get("result", {}).get("value")


def wait_for(ws, expr, session_id=None, tries=40, delay=0.3):
    """Poll a JS predicate until true or tries exhausted; return bool."""
    for _ in range(tries):
        try:
            if peval(ws, expr, session_id):
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def open_mock_tab(url):
    """Open url in a NEW Edge tab via CDP, attach, force a real viewport, and
    bring it to the foreground. Returns (targetId, browser_ws, sessionId)."""
    bws = browser_ws()
    rid = send(bws, "Target.createTarget", {"url": url})
    tid = recv_id(bws, rid)["targetId"]
    rid = send(bws, "Target.attachToTarget", {"targetId": tid, "flatten": True})
    sess = recv_id(bws, rid)["sessionId"]
    for dom in ("Runtime", "Page", "Input"):
        send(bws, dom + ".enable", {}, session_id=sess)
    # Force a concrete layout viewport. A freshly-created debug tab has no real
    # window (0/off-screen), so getBoundingClientRect coords don't map to a
    # hit-testable region and synthetic mouse clicks silently miss -- making
    # every pick "click" (ok=True) yet never register (confirmed=False).
    send(bws, "Emulation.setDeviceMetricsOverride",
         {"width": 1280, "height": 900, "deviceScaleFactor": 1,
          "mobile": False, "screenWidth": 1280, "screenHeight": 900},
         session_id=sess)
    # Bring the tab to the foreground. Synthetic CDP mouse input is silently
    # ignored on a background tab, which would make every pick "click" but never
    # register -- exactly the bug this harness exists to catch.
    send(bws, "Target.activateTarget", {"targetId": tid}, session_id=sess)
    # Navigate (createTarget may not have loaded the url yet) and wait for load.
    send(bws, "Page.navigate", {"url": url}, session_id=sess)
    return tid, bws, sess


def close_tab(bws, tid):
    """Close a target, swallowing any CDP error."""
    try:
        send(bws, "Target.closeTarget", {"targetId": tid})
    except Exception as e:
        log("close_tab warn: %s" % e)


class SessionWS:
    """Proxy a WebSocket so every outgoing CDP command gets the attached
    target's sessionId injected. The deployed driver sends Runtime/Input/Page
    commands WITHOUT a sessionId (correct for a page-level socket); when we
    instead drive the attached target through the browser socket, each command
    needs the sessionId or it is ignored. Wrapping the socket lets the driver's
    real functions run unchanged."""

    def __init__(self, ws, session_id):
        self._ws = ws
        self._sid = session_id

    def send(self, data):
        msg = json.loads(data)
        if "sessionId" not in msg:
            msg["sessionId"] = self._sid
        self._ws.send(json.dumps(msg))

    def recv(self):
        return self._ws.recv()


def start_server():
    """Serve tools/ over loopback so the mock room loads via http://."""
    class _H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=os.path.dirname(HTML), **k)

        def log_message(self, *a):
            pass
    srv = socketserver.TCPServer(("127.0.0.1", MOCK_PORT), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def build_players(mod):
    """Build the injected player list: the REAL original board plus parser
    -compatible filler to reach ~210 bodies. Defenses are relabeled to their
    CITY-PREFIXED form so the read_available team-code capture is exercised."""
    board = mod.load_original_board()
    rows = sorted(board.values(), key=lambda v: v["value"], reverse=True)
    players = [{"name": b["name"], "team": b["team"], "pos": b["pos"]}
               for b in rows]
    board_names = set(b["name"] for b in rows)
    teams = ["BUF", "MIA", "NE", "NYJ", "BAL", "CIN", "CLE", "PIT", "HOU", "IND",
             "JAX", "TEN", "DEN", "KC", "LV", "LAC", "CHI", "DET", "GB", "MIN",
             "ATL", "CAR", "NO", "TB", "DAL", "NYG", "PHI", "WAS", "ARI", "LAR",
             "SF", "SEA"]
    positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
    i = 0
    while len(players) < 210:           # ~150 draft slots + buffer
        t = teams[i % len(teams)]
        p = positions[(i // len(teams)) % len(positions)]
        # 1-2 alphabetic words, NO digits -> read_available() accepts every row.
        name = "%s %s" % (_FILLER_FIRST[i % len(_FILLER_FIRST)],
                          _FILLER_LAST[(i // len(_FILLER_FIRST)) % len(_FILLER_LAST)])
        players.append({"name": name, "team": t, "pos": p})
        i += 1
    return players, board_names


def simulate_opponents(ws, n, board_names):
    """Simulate n opponent picks, taking SKILL players only (opponents leave
    K/DEF for the bot's late rounds). Filters on each available player's real
    pos (from window.MockDraft.availablePlayers), not a guessed position."""
    objs = peval(ws, "window.MockDraft.availablePlayers()") or []
    skill = [o["name"] for o in objs if o.get("pos") not in ("K", "DEF")]
    board_side = [x for x in skill if x in board_names]
    other = [x for x in skill if x not in board_names]
    for _ in range(n):
        pool = board_side if (board_side and random.random() < 0.6) else (other or board_side)
        if not pool:
            break
        pick = random.choice(pool)
        peval(ws, "window.MockDraft.removePlayer(%s)" % json.dumps(pick))
        (board_side if pick in board_names else other).remove(pick)


def check_contract(pick_log, fails):
    """Assert the draft CONTRACT against the recorded pick log. Appends human
    -readable violations to `fails`. Returns True when the contract holds."""
    ok = True
    for rnd, name, pos in pick_log:
        if pos in ("K", "DEF") and rnd < K_DEF_FIRST_ROUND:
            fails.append("CONTRACT: %s drafted round %d (must be >= %d)"
                         % (pos, rnd, K_DEF_FIRST_ROUND))
            ok = False
        if pos == "QB" and rnd < QB_FIRST_ROUND:
            fails.append("CONTRACT: QB drafted round %d (must be >= %d)"
                         % (rnd, QB_FIRST_ROUND))
            ok = False
    return ok


def main():
    open(LOG, "w", encoding="utf-8").close()
    mod = load_deployed()
    players, board_names = build_players(mod)
    srv = start_server()
    log("MOCK_DRAFT_START team=%s teams=%d rounds=%d pool=%d"
        % (TEAM_ID, N_TEAMS, TOTAL_ROUNDS, len(players)))

    tid, bws, sess = open_mock_tab(
        "http://127.0.0.1:%d/mock_draft_room.html" % MOCK_PORT)
    wsw = SessionWS(bws, sess)   # inject sessionId into every driver command
    try:
        if not wait_for(wsw, "typeof window.MockDraft==='object'", tries=80, delay=0.4):
            diag = peval(wsw,
                "({ready:document.readyState, href:location.href, "
                "hasMD: typeof window.MockDraft, body:(document.body?document.body.innerText.slice(0,120):'')})")
            log("MOCK_DRAFT_ABORT: MockDraft API not found; diag=%s" % diag)
            return 1
        peval(wsw, "window.MockDraft.load(%s)" % json.dumps(players))
        board = mod.load_original_board()
        active_def_map = {
            v["team"].upper(): v["name"]
            for v in board.values() if v["pos"] == "DEF" and v.get("team")
        }

        drafted = {}
        picks, fails = [], []
        pick_log = []          # (round, name, pos) for contract assertions
        filled_round = {}      # pos -> round its REQUIRED count was reached
        for rnd in range(1, TOTAL_ROUNDS + 1):
            peval(wsw, "window.MockDraft.setTurn(true)")
            raw = mod.read_available(wsw)
            # Match run_draft(): defenses on the nflverse board are normalized
            # by the active board's team map, not only the legacy static map.
            available, adp_map, pos_map = mod.normalize_available(
                raw, def_map=active_def_map)
            anchor_row = mod.search_forced_anchor(
                wsw, board, drafted, rnd, available)
            if anchor_row:
                raw.append(anchor_row)
                available, adp_map, pos_map = mod.normalize_available(
                    raw, def_map=active_def_map)
            pick = mod.choose_pick(available, drafted, rnd, board,
                                   adp_map=adp_map, pos_map=pos_map)
            if not pick:
                fails.append("R%d: NO_PICK (parsed=%d)" % (rnd, len(available)))
                log("R%-2d NO_PICK parsed=%d" % (rnd, len(available)))
                peval(wsw, "window.MockDraft.setTurn(false)")
                continue
            name, team, pos, adp = pick
            log("R%-2d CHOOSE %-22s pos=%s avail_top=%s"
                % (rnd, name, pos, ",".join(available[:3])))
            ok = mod.click_player(wsw, name, team, pos)
            # Immediate post-click check: is the name still on the page?
            after = mod.read_available(wsw)
            after_names = [r[0] for r in after]
            still = name in after_names
            log("R%-2d CLICK ok=%s post_click_still_present=%s" % (rnd, ok, still))
            confirmed = (mod._confirm_pick(wsw, name) if ok else False)
            if ok and confirmed:
                drafted[pos] = drafted.get(pos, 0) + 1
                picks.append((rnd, name, pos))
                pick_log.append((rnd, name, pos))
                if pos in REQUIRED and pos not in filled_round \
                        and drafted[pos] >= REQUIRED[pos]:
                    filled_round[pos] = rnd
                log("R%-2d PICKED %-22s %s" % (rnd, name, pos))
            else:
                fails.append("R%d: CLICK_FAIL %s (ok=%s confirmed=%s)"
                             % (rnd, name, ok, confirmed))
                log("R%-2d CLICK_FAIL %s ok=%s confirmed=%s" % (rnd, name, ok, confirmed))
            simulate_opponents(wsw, N_TEAMS - 1, board_names)

        # Count ONLY team #2's own picks (the final page list includes every
        # team's picks, so we must not score opponents' selections here).
        counts = {}
        for _, _, pos in picks:
            counts[pos] = counts.get(pos, 0) + 1
        final = peval(wsw, "window.MockDraft.drafted()") or []
        log("MOCK_DRAFT_DONE picks=%d drafted_total=%d" % (len(picks), len(final)))
        log("FINAL_ROSTER(team2) " + " ".join("%s=%d" % (k, counts.get(k, 0))
                                       for k in ("QB", "RB", "WR", "TE", "K", "DEF")))
        legal = all(counts.get(k, 0) >= v for k, v in REQUIRED.items())
        log("ROSTER_LEGAL=%s" % legal)

        # Contract: every required slot met by its anchor deadline.
        for pos, need in REQUIRED.items():
            if counts.get(pos, 0) < need:
                continue
            met = filled_round.get(pos)
            if met is None:
                continue
            if met > ANCHOR_DEADLINE[pos]:
                fails.append("CONTRACT: %s filled round %d (deadline R%d)"
                             % (pos, met, ANCHOR_DEADLINE[pos]))
        check_contract(pick_log, fails)

        if fails:
            log("FAILURES: %s" % " | ".join(fails))
        else:
            log("NO_FAILURES: all 15 picks clicked + confirmed via CDP; contract held")
        return 0 if (legal and not fails) else 1
    finally:
        close_tab(bws, tid)
        try:
            srv.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
