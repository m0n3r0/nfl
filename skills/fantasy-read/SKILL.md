---
name: fantasy-read
description: "Read-only operations on a user's Yahoo Fantasy Football league/tab via Edge CDP: roster, standings, matchups, waivers, draft board/ADP. No changes made. Use to report league state, build a draft board, or prep lineup decisions."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [Fantasy-Football, Yahoo, Read-Only, Scraping, CDP]
    related_skills: [edge-cdp, fantasy-draft]
---

# Fantasy Read (Yahoo) — read-only

Read state from the user's open Yahoo Fantasy tab (league 1329011, team 2 "Doge").
All operations are READ-ONLY. Drives Edge via the `edge-cdp` skill.

## Quick start
- Edge must be open on 9222 with --remote-allow-origins=*.
- Run scripts on Windows via `py.exe` (stdin). Output base64 to round-trip to WSL.

## Endpoints that work
- League home:  https://football.fantasysports.yahoo.com/f1/1329011
- Your team:    https://football.fantasysports.yahoo.com/f1/1329011/2   (team id 2 = Doge)
- Settings:     .../1329011/settings   (scoring format, roster, draft time)
- Draft board:  .../1329011/draftanalysis  (ADP per player; top ~30 reliable,
  deeper rows virtualized — scroll to load more)
- Draft Central:.../1329011/draft

## Reading the roster/standings (pattern)
```python
import json, urllib.request, websocket
CDP="http://127.0.0.1:9222"
def http_get(p):
    with urllib.request.urlopen(CDP+p,timeout=8) as r: return json.loads(r.read().decode())
def connect():
    t=next(x for x in http_get("/json/list") if x.get("type")=="page")
    ws=websocket.create_connection(t["webSocketDebuggerUrl"],timeout=10,header={"Origin":"http://127.0.0.1:9222"})
    ws.send(json.dumps({"id":1,"method":"Runtime.enable","params":{}}))
    ws.send(json.dumps({"id":2,"method":"Page.enable","params":{}}))
    return ws
def ev(ws,expr):
    ws.send(json.dumps({"id":99,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
    while True:
        o=json.loads(ws.recv())
        if o.get("id")==99: return o.get("result",{}).get("result",{}).get("value")
ws=connect()
ws.send(json.dumps({"id":5,"method":"Page.navigate","params":{"url":"https://football.fantasysports.yahoo.com/f1/1329011/2"}}))
import time; time.sleep(4)
print(ev(ws,"document.body.innerText.slice(0,2500)"))
```

## Extracting the draft board (verified)
The board is a single `<table>`; rows are `<tbody><tr>` with cells:
name (player link), team-pos ("Det - RB"), and a numeric ADP cell. Parse with:
```python
rows = ev(ws, """(function(){
  var tb=document.querySelector('tbody'); if(!tb) return 'NO_TBODY';
  var out=[];
  for(var i=0;i<tb.querySelectorAll('tr').length;i++){
    var r=tb.querySelectorAll('tr')[i];
    out.push(r.innerText.replace(/\\n+/g,' | ').trim());
  }
  return out.join('\\n---\\n');
})()""")
```
Top ~30 players (verified ADP, .5 PPR): Gibbs(1.5), Bijan(1.9), Chase(3.3),
Puka(4.7), CMC(5.5), Amon-Ra(8.0), JSN(6.7), Taylor(7.1), CeeDee(10.2),
Cook(9.9), Saquon(12.4), Jefferson(12.4), Jeanty(14.1), Achane(15.7),
ChaseBrown(16.6), K.Walker(17.0), Henry(18.2), London(18.6), Hampton(18.7),
Allen QB(19.6), Bowers TE(21.1), Nico(22.2), Pickens(22.4), A.J.Brown(25.0),
McBride TE(25.4), Love(27.2), DeVonta(29.4), Kyren(29.6), Jacobs(32.8),
Olave(34.0).

## Gotchas
- Reading player links: `a[href*="/nfl/players/"]`. On the edit-rank page only 1
  link appears (JS widget) — don't rely on it there.
- The Edit-My-Rankings page (.../2/editprerank) is a fragile JS drag widget with no
  stable automatable controls. Prefer leaving Yahoo default pre-rank as the safety net.
- Output via UTF-8 file + base64 round-trip (cp932 console mangles Unicode).
