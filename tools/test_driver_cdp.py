"""CDP (remote-control Edge) regression test for the live-draft driver fixes.

Drives a REAL Edge browser on ws://127.0.0.1:9222 (launched with
--remote-debugging-port=9222 --remote-allow-origins=*) against an isolated
LOCAL mock draft room. It opens a NEW tab (never the user's Yahoo session tab)
and exercises the actual CDP DOM code paths for:

  #23  off-window target: read_available() only sees ~40 virtualized rows, so a
       deep target must be reached via search_player() before click_player().
  #26  read_pick_number() parses the overall pick number; the guard must not
       re-trigger on a repeated number.

Run:  .venv/Scripts/python.exe tools/test_driver_cdp.py
"""
import json
import os
import sys
import time
import random
import urllib.request
import websocket
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import driver.draft_driver as dd  # noqa: E402

CDP = dd.CDP
# Proper Windows file:// URL (needs the drive colon: file:///C:/...), otherwise
# Edge rejects it with chrome-error://chromewebdata/.
MOCK_URL = Path(ROOT, "tools", "mock_draft_room_40.html").as_uri()

FIRST = ["Aaron", "Bryce", "Cole", "Dane", "Eli", "Finn", "Gage", "Hugh", "Ivan",
         "Josh", "Kyle", "Liam", "Mason", "Noah", "Owen", "Parker", "Quinn",
         "Reed", "Seth", "Theo", "Umar", "Vince", "Wade", "Xander", "York",
         "Zane", "Beau", "Cruz", "Drew", "Ezra", "Fox", "Gus", "Hank", "Ira",
         "Jude", "Knox", "Lane", "Milo", "Nash", "Otis", "Pax", "Rory", "Sawyer",
         "Tate", "Wes", "Ace", "Bo", "Cade", "Dax", "Elias", "Ford", "Holt",
         "Ike", "Jax", "Koa", "Luca", "Micah", "Nico", "Otto", "Pete"]
LAST = ["Adams", "Brooks", "Cole", "Diaz", "Evans", "Ford", "Green", "Hayes",
        "Ivey", "Jones", "Knight", "Lopez", "Moore", "Nash", "Owens", "Price",
        "Quill", "Reed", "Stein", "Tate", "Unger", "Vance", "Wells", "Xu",
        "Young", "Zorn", "Bell", "Cruz", "Dunn", "Ellis", "Frost", "Grant",
        "Hale", "Irons", "Jett", "Kerr", "Lamb", "Moss", "Ortega", "Pace",
        "Quay", "Rhodes", "Stone", "Troy", "Voss", "Wolfe", "Yale", "Zimmer",
        "Ash", "Banks", "Cobb", "Dane", "Earl", "Frye", "Gould", "Hart",
        "Imes", "Jay", "Kemp", "Lowe"]
TEAMS = ["NE", "BUF", "MIA", "NYJ", "PIT", "BAL", "CIN", "CLE", "HOU", "IND",
         "JAX", "TEN", "DEN", "KC", "LV", "LAC", "CHI", "DET", "GB", "MIN"]
POS = ["RB", "WR", "QB", "TE", "K", "DEF"]

# 60 players; the deep target sits at index 55, beyond the 40-row window.
DEEP_NAME = "Zach Zenith"
DEEP_IDX = 55


def build_players():
    out = []
    for i in range(60):
        out.append({
            "name": "%s %s" % (FIRST[i], LAST[i]),
            "team": TEAMS[i % len(TEAMS)],
            "pos": POS[i % len(POS)],
        })
    out[DEEP_IDX] = {"name": DEEP_NAME, "team": "ZEN", "pos": "WR"}
    return out


def connect_mock_tab():
    """Open a fresh tab on the mock room; return (ws, target_id, browser_ws)."""
    targets = json.loads(urllib.request.urlopen(CDP + "/json/list", timeout=8).read())
    page = next((t for t in targets if t.get("type") == "page"), None)
    if not page:
        raise SystemExit("no page target in /json/list (is Edge on 9222?)")
    pws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10,
                                      header={"Origin": CDP})
    pws.send(json.dumps({"id": 1, "method": "Target.enable", "params": {}}))
    wid = random.randint(100, 99999)
    pws.send(json.dumps({"id": wid, "method": "Target.createTarget",
                         "params": {"url": MOCK_URL}}))
    new_id = None
    while True:
        o = json.loads(pws.recv())
        if o.get("id") == wid:
            new_id = o.get("result", {}).get("targetId")
            break
    time.sleep(2)  # let the mock's script define window.MockDraft
    targets = json.loads(urllib.request.urlopen(CDP + "/json/list", timeout=8).read())
    ntab = next((t for t in targets if t.get("id") == new_id), None)
    if not ntab:
        raise SystemExit("mock tab not found in /json/list")
    ws = websocket.create_connection(ntab["webSocketDebuggerUrl"], timeout=10,
                                     header={"Origin": CDP})
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))
    ws.send(json.dumps({"id": 2, "method": "Page.enable", "params": {}}))
    ws.send(json.dumps({"id": 3, "method": "Input.enable", "params": {}}))
    return ws, new_id, pws


def load_players(ws, players):
    dd.ev(ws, "MockDraft.load(%s)" % json.dumps(players))
    dd.ev(ws, "MockDraft.setTurn(true)")
    time.sleep(0.3)


def main():
    ws = new_id = pws = None
    try:
        ws, new_id, pws = connect_mock_tab()
        for _ in range(40):
            if dd.ev(ws, "typeof window.MockDraft"):
                break
            time.sleep(0.2)
        players = build_players()
        load_players(ws, players)

        # --- #23a: virtualization — deep target is off-window ---
        avail = dd.read_available(ws)
        names = [r[0] for r in avail]
        assert len(avail) <= 40, "read_available returned %d rows (>40)" % len(avail)
        assert DEEP_NAME not in names, "deep target should be OFF-window but was visible"
        print("PASS #23a virtualization: read_available=%d rows, deep target off-window"
              % len(avail))

        # --- #23b: search surfaces the deep target ---
        row = dd.search_player(ws, DEEP_NAME)
        assert row is not None and DEEP_NAME.lower() in (row[0] or "").lower(), \
            "search_player did not surface %s (got %r)" % (DEEP_NAME, row)
        print("PASS #23b search_player surfaced deep target: %r" % (row,))

        # --- #23c: clicking the now-visible target drafts it ---
        ok = dd.click_player(ws, DEEP_NAME)
        assert ok is True, "click_player returned %r for off-window target" % ok
        drafted = dd.ev(ws, "MockDraft.drafted()")
        drafted_names = [p["name"] for p in (drafted or [])]
        assert DEEP_NAME in drafted_names, \
            "click did not register; drafted=%r" % drafted_names
        print("PASS #23c click_player drafted deep target via search; drafted=%s"
              % drafted_names)

        # --- #26: pick-number read + guard ---
        dd.ev(ws, "document.getElementById('pickno').textContent='Overall Pick 5 of 150'")
        pn = dd.read_pick_number(ws)
        assert pn == 5, "read_pick_number returned %r (expected 5)" % pn
        assert dd._pick_number_changed(5, 5) is False, "repeated number must not re-trigger"
        assert dd._pick_number_changed(6, 5) is True, "advanced number must trigger"
        print("PASS #26 pick-number read + guard: pn=%s" % pn)

        # --- #32: Yahoo abbreviation resolution (end-to-end, the P0 bug) ---
        # Real break on 2026-08-31: Yahoo shows "J. Burrow" but the board key is
        # "Joe Burrow"; read_available() previously chopped the initial ("Burrow")
        # and normalize_available() could never re-resolve, so choose_pick treated
        # every available player as off-board and fell to raw-ADP fallback. Load
        # REAL board players (so ABBREV_TO_FULL can resolve) rendered in Yahoo's
        # abbreviated form, then verify read -> normalize -> click all work.
        real = [{"name": n, "team": t, "pos": p}
                for (n, t, p, a) in dd.BOARD
                if n in ("Joe Burrow", "Christian McCaffrey", "A.J. Brown",
                         "Amon-Ra St. Brown", "Ja'Marr Chase", "CeeDee Lamb",
                         "Justin Jefferson")]
        load_players(ws, real)
        dd.ev(ws, "MockDraft.setAbbrev(true)")
        avail = dd.read_available(ws)
        raw_names = [r[0] for r in avail]
        assert "J. Burrow" in raw_names, \
            "read_available chopped initial; got %r" % raw_names
        assert "Burrow" not in raw_names, \
            "read_available leaked last-name-only: %r" % raw_names
        names, adp_map, pos_map = dd.normalize_available(avail, def_map={})
        assert "Joe Burrow" in names, \
            "normalize failed to resolve abbrev; names=%r" % names
        assert "Christian McCaffrey" in names, \
            "normalize failed McCaffrey; names=%r" % names
        assert "CeeDee Lamb" in names, \
            "normalize failed CeeDee Lamb; names=%r" % names
        assert "Justin Jefferson" in names, \
            "normalize failed Justin Jefferson; names=%r" % names
        ok = dd.click_player(ws, "Joe Burrow")
        assert ok is True, "click_player returned %r for abbreviated row" % ok
        drafted = dd.ev(ws, "MockDraft.drafted()")
        drafted_names = [p["name"] for p in (drafted or [])]
        assert "Joe Burrow" in drafted_names, \
            "abbrev click did not register; drafted=%r" % drafted_names
        print("PASS #32 abbreviation resolution: read=%r normalize ok click drafted=%s"
              % (raw_names, drafted_names))

        print("\nALL CDP BROWSER TESTS PASSED")
        return 0
    except AssertionError as e:
        print("FAIL: %s" % e)
        return 1
    except Exception as e:
        import traceback as _tb
        print("ERROR: %s" % repr(e))
        _tb.print_exc()
        return 2
    finally:
        for s in (ws, pws):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        if new_id:
            try:
                urllib.request.urlopen(CDP + "/json/close/" + new_id,
                                       timeout=5).read()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
