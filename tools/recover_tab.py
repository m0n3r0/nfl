import json, urllib.request, websocket, random, time
tabs = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()) if t.get('type') == 'page']
tab = next((t for t in tabs if 'fantasysports.yahoo.com' in t.get('url', '')), None)
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=20, header={'Origin': 'http://127.0.0.1:9222'})
wid = random.randint(100, 99999)
ws.send(json.dumps({'id': wid, 'method': 'Page.navigate', 'params': {'url': 'https://football.fantasysports.yahoo.com/f1/1329011'}}))
ws.recv(); time.sleep(8)
wid2 = random.randint(100, 99999)
expr = r"""(function(){
  var b = document.body.innerText;
  return {url: location.href, title: document.title.slice(0,60),
    signed_in: /sign out/i.test(b), doge: (b.match(/[^\n]*Doge[^\n]*/gi)||[]).slice(0,4),
    draft_lines: (b.match(/[^\n]*[Dd]raft[^\n]*/gi)||[]).slice(0,10)};
})()"""
ws.send(json.dumps({'id': wid2, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
while True:
    o = json.loads(ws.recv())
    if o.get('id') == wid2:
        print(json.dumps(o['result']['result']['value'], indent=1)); break
ws.close()
