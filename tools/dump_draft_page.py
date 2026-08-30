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
cdp(ws, 'Page.navigate', {'url': 'https://football.fantasysports.yahoo.com/f1/1329011/draft'})
time.sleep(14)
expr = r"(function(){ var b=document.body.innerText; return {len: b.length, head: b.replace(/\n{2,}/g,'\n').slice(0, 3500)}; })()"
o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
v = o['result']['result']['value']
print('LEN:', v['len'])
print(v['head'].encode('utf-8', 'replace').decode('utf-8'))
ws.close()
