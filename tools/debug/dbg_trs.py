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
  var out = [];
  var trs = document.querySelectorAll('tr');
  for (var i = 0; i < trs.length && out.length < 4; i++) {
    var t = trs[i].innerText || '';
    if (t.indexOf('- ') >= 0 || /RB|WR|QB/.test(t)) out.push(JSON.stringify(t).slice(0, 400));
  }
  return {n_trs: trs.length, samples: out};
})()"""
o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
v = o['result']['result']['value']
print('N TRS:', v['n_trs'])
for s in v['samples']: print(s)
ws.close()
