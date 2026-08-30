import json, urllib.request, websocket, random, time

def cdp(ws, method, params=None):
    wid = random.randint(100, 99999)
    ws.send(json.dumps({'id': wid, 'method': method, 'params': params or {}}))
    while True:
        o = json.loads(ws.recv())
        if o.get('id') == wid:
            return o

tabs = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()) if t.get('type') == 'page']
tab = next((t for t in tabs if 'yahoo' in t.get('url', '')), None)
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=30, header={'Origin': 'http://127.0.0.1:9222'})
cdp(ws, 'Page.navigate', {'url': 'https://football.fantasysports.yahoo.com/f1/1329011'})
time.sleep(10)
expr = r"(function(){ var b=document.body.innerText; return {url: location.href, doge: (b.match(/[^\n]*Doge[^\n]*/gi)||[]).slice(0,3), countdown: (b.match(/Live League Draft[^\n]*/i)||[''])[0]}; })()"
o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
print(json.dumps(o['result']['result']['value'], indent=1))
ws.close()
