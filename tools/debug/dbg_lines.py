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
expr = r"""(function(){
  var lines = document.body.innerText.split(/\r?\n/);
  var idx = [];
  for (var i = 0; i < lines.length; i++) if (/^[A-Za-z]{2,4} - (QB|WR|RB|TE|K|DEF)\s*$/.test(lines[i])) idx.push(i);
  var out = [];
  for (var k = 0; k < Math.min(2, idx.length); k++) {
    var i = idx[k];
    for (var j = Math.max(0, i - 2); j <= Math.min(lines.length - 1, i + 4); j++) out.push(j + ': ' + JSON.stringify(lines[j]));
    out.push('---');
  }
  return {url: location.href, n: idx.length, samples: out};
})()"""
o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
v = o['result']['result']['value']
print('URL:', v['url']); print('MATCHES:', v['n'])
for s in v['samples']: print(s)
ws.close()
