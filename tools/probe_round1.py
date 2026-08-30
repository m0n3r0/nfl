"""Dump round-1 table cells from the draft results page (format probe)."""
import json, random, urllib.request, websocket

p = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=8).read())
     if t.get('type') == 'page' and 'fantasysports.yahoo.com' in (t.get('url') or '')][0]
ws = websocket.create_connection(p['webSocketDebuggerUrl'], timeout=20,
                                 header={'Origin': 'http://127.0.0.1:9222'})
wid = random.randint(1000, 99999)
expr = r"""(function(){
  var t = document.querySelectorAll('table')[0];
  var rows = [];
  for (var r = 0; r < Math.min(t.rows.length, 3); r++) {
    var cells = [];
    for (var c = 0; c < t.rows[r].cells.length; c++) {
      cells.push(t.rows[r].cells[c].innerText.replace(/\n/g, ' || '));
    }
    rows.push(cells);
  }
  return rows;
})()"""
ws.send(json.dumps({'id': wid, 'method': 'Runtime.evaluate',
                    'params': {'expression': expr, 'returnByValue': True}}))
while True:
    o = json.loads(ws.recv())
    if o.get('id') == wid:
        print(json.dumps(o['result']['result']['value'], indent=1)); break
ws.close()
