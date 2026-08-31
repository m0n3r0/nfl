"""
READ-ONLY live-DOM validation of the deployed draft driver against the REAL
Yahoo mock_lobby tab (league 1329011). Attaches to the existing mock_lobby page
target via CDP (REST /json/list + websocket) and runs the driver's own
read_available() / is_my_pick() / read_pick_number() against the live DOM.

This is SAFE: it only evaluates read-only JS in the already-open tab. It never
navigates, clicks, or drafts. Proof of concept for the user's correction that
the browser IS controllable from PowerShell/CDP and that the P0 #32 name-scan
fix works on the real Yahoo DOM.
"""
import sys, io, datetime, json, urllib.request, websocket

# Import the ACTUAL deployed driver (the code that will run on draft day).
DEPLOY = r"C:\edge-debug-profile"
sys.path.insert(0, DEPLOY)
import draft_driver as dd

LOG = r"C:\nfl-win\tools\_live_read.log"
def log(s):
    line = datetime.datetime.now().strftime("%H:%M:%S") + " " + str(s)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)

CDP = "http://127.0.0.1:9222"

def main():
    log("LIVE_READ_START deploy_sha=%s" % dd._driver_sha256())
    targets = json.loads(urllib.request.urlopen(CDP + "/json/list", timeout=8).read())
    pages = [t for t in targets if t.get("type") == "page"]
    log("page targets: %d" % len(pages))
    for t in pages:
        log("  page: %s" % t.get("url"))
    ml = next((t for t in pages if "mock_lobby" in (t.get("url") or "")), None)
    if not ml:
        log("NO mock_lobby page target -> cannot attach")
        return
    log("ATTACH -> %s" % ml["url"])
    ws = websocket.create_connection(ml["webSocketDebuggerUrl"], timeout=10,
                                     header={"Origin": "http://127.0.0.1:9222"})
    ws.send(json.dumps({"id":1,"method":"Runtime.enable","params":{}}))
    ws.recv()  # drain the Runtime.enable ack

    # P0 #32 fix validation: name-based scan on the real Yahoo DOM.
    raw = dd.read_available(ws)
    log("read_available() -> %d rows" % len(raw))
    for r in raw[:15]:
        log("  name=%-22s code=%-4s pos=%-3s" % (r[0], r[1], r[2]))

    my_turn = dd.is_my_pick(ws)
    log("is_my_pick() -> %s" % my_turn)
    pn = dd.read_pick_number(ws)
    log("read_pick_number() -> %s" % pn)

    # Normalize the first 15 (maps DEF codes -> board keys, parses Yahoo ADP).
    if raw:
        names, adp_map, pos_map = dd.normalize_available(raw, def_map={
            v["team"].upper(): v["name"] for v in dd.static_board().values()
            if v.get("pos") == "DEF"})
        log("normalized names (first 15): %s" % ", ".join(names[:15]))
        log("yahoo_adp parsed: %d" % len(adp_map))

    ws.close()
    log("LIVE_READ_DONE")

if __name__ == "__main__":
    main()
