import json, urllib.request, websocket, random

def cdp(ws, method, params=None):
    wid = random.randint(100, 99999)
    ws.send(json.dumps({'id': wid, 'method': method, 'params': params or {}}))
    while True:
        o = json.loads(ws.recv())
        if o.get('id') == wid:
            return o

tabs = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()) if t.get('type') == 'page']
tab = next((t for t in tabs if 'draftanalysis' in t.get('url', '')), None)
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=30, header={'Origin': 'http://127.0.0.1:9222'})
expr = r"(function(){ var L=document.body.innerText.split(/\r?\n/); return L.slice(15, 135).map(function(s,i){return (i+15)+': '+JSON.stringify(s.trim());}); })()"
o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
for s in o['result']['result']['value']: print(s)
ws.close()
