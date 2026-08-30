import json, urllib.request, websocket, random

tabs = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()) if t.get('type') == 'page']
tab = [t for t in tabs if 'fantasysports.yahoo.com' in t.get('url', '')][0]
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=15, header={'Origin': 'http://127.0.0.1:9222'})
expr = r"""(function(){
  var b = document.body.innerText;
  var markers = {
    my_team: /my team/i.test(b),
    standings: /standings/i.test(b),
    matchups: /matchup/i.test(b),
    doge_count: (b.match(/Doge/g) || []).length
  };
  // Definitive: same-origin fetch of a login-protected team page.
  return fetch('/f1/1329011/team/002', {credentials: 'same-origin'})
    .then(function(r){
      markers.team_page_status = r.status;                 // 200 = authed, 4xx/redirect-to-login = not
      return r.text();
    })
    .then(function(html){
      markers.team_page_has_doge = /Doge/i.test(html);
      return markers;
    })
    .catch(function(e){ markers.fetch_error = String(e); return markers; });
})()"""
wid = random.randint(100, 99999)
ws.send(json.dumps({'id': wid, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True, 'awaitPromise': True}}))
while True:
    o = json.loads(ws.recv())
    if o.get('id') == wid:
        print(json.dumps(o['result']['result']['value'], indent=1)); break
ws.close()
