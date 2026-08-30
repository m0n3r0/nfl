import json, urllib.request, websocket, random, time

def cdp(ws, method, params=None):
    wid = random.randint(100, 99999)
    ws.send(json.dumps({'id': wid, 'method': method, 'params': params or {}}))
    while True:
        o = json.loads(ws.recv())
        if o.get('id') == wid:
            return o

tabs = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()) if t.get('type') == 'page']
tab = next((t for t in tabs if 'fantasysports.yahoo.com' in t.get('url', '')), None)
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=30, header={'Origin': 'http://127.0.0.1:9222'})
time.sleep(3)
expr = r"""(function(){
  var b = document.body.innerText;
  var lines = b.split('\n');
  var keep = [];
  var keys = /order|round|pick|slot|position|draf|Doge|team/i;
  for (var i = 0; i < lines.length; i++) {
    var t = lines[i].trim();
    if (t && keys.test(t)) keep.push(i + ': ' + t.slice(0, 90));
  }
  return {total: lines.length, tail: b.slice(-1200), hits: keep.slice(0, 60)};
})()"""
o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
v = o['result']['result']['value']
print('=== ORDER/PICK LINES ===')
for h in v['hits']: print(h)
print('=== PAGE TAIL ===')
print(v['tail'])
ws.close()
