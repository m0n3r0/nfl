import json, urllib.request, websocket, random
tabs = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()) if t.get('type') == 'page']
tab = next((t for t in tabs if 'fantasysports.yahoo.com' in t.get('url', '')), None)
if tab['url'] != 'https://football.fantasysports.yahoo.com/f1/1329011':
    ws0 = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=15, header={'Origin': 'http://127.0.0.1:9222'})
    wid = random.randint(100, 99999)
    ws0.send(json.dumps({'id': wid, 'method': 'Page.navigate', 'params': {'url': 'https://football.fantasysports.yahoo.com/f1/1329011'}}))
    ws0.recv(); import time; time.sleep(7); ws0.close()
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=20, header={'Origin': 'http://127.0.0.1:9222'})
expr = r"""(function(){
  var out = [];
  var a = document.querySelectorAll('a[href]');
  for (var i = 0; i < a.length; i++) {
    var h = a[i].href;
    if (/draft|order/i.test(h) && out.indexOf(h) < 0) out.push(h.slice(0,110) + ' :: ' + (a[i].innerText||'').replace(/\s+/g,' ').trim().slice(0,40));
  }
  return out.slice(0, 25);
})()"""
wid2 = random.randint(100, 99999)
ws.send(json.dumps({'id': wid2, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
while True:
    o = json.loads(ws.recv())
    if o.get('id') == wid2:
        for x in o['result']['result']['value']: print(x)
        break
ws.close()
