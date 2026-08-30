import json, urllib.request, websocket, random

tabs = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5).read()) if t.get('type') == 'page']
print('TABS:')
for i, t in enumerate(tabs):
    print(f'  [{i}] {t["title"][:60]} | {t["url"][:90]}')

tab = next((t for t in tabs if 'fantasysports.yahoo.com' in t.get('url', '')), None)
if not tab:
    print('NO YAHOO TAB OPEN'); raise SystemExit
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=15, header={'Origin': 'http://127.0.0.1:9222'})
expr = r"""(function(){
  var b = document.body.innerText;
  return {
    url: location.href,
    signed_in: /sign out|profile/i.test(b) && !/sign in to yahoo/i.test(b),
    doge_mentions: (b.match(/Doge/g) || []).length,
    draft_mentioned: /draft/i.test(b),
    draft_snippets: (b.match(/[^\n]*draft[^\n]*/gi) || []).slice(0, 8),
    team_links: (function(){
      var a = document.querySelectorAll('a[href*="/f1/1329011/"]');
      var out = [];
      for (var i = 0; i < a.length && out.length < 15; i++) {
        var txt = (a[i].innerText || '').trim();
        if (txt) out.push(txt.slice(0, 40));
      }
      return out;
    })()
  };
})()"""
wid = random.randint(100, 99999)
ws.send(json.dumps({'id': wid, 'method': 'Runtime.evaluate', 'params': {'expression': expr, 'returnByValue': True}}))
while True:
    o = json.loads(ws.recv())
    if o.get('id') == wid:
        print(json.dumps(o['result']['result']['value'], indent=1)); break
ws.close()
