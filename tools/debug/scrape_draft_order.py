import json, urllib.request, websocket, random, time, sys

TABS_URL = 'http://127.0.0.1:9222/json'
LEAGUE = '1329011'
DRAFT_PAGE = f'https://football.fantasysports.yahoo.com/f1/{LEAGUE}/draft'

def cdp(ws, method, params=None):
    wid = random.randint(100, 99999)
    ws.send(json.dumps({'id': wid, 'method': method, 'params': params or {}}))
    while True:
        o = json.loads(ws.recv())
        if o.get('id') == wid:
            return o

def main():
    tabs = [t for t in json.loads(urllib.request.urlopen(TABS_URL, timeout=5).read()) if t.get('type') == 'page']
    tab = next((t for t in tabs if 'fantasysports.yahoo.com' in t.get('url', '')), None)
    if not tab:
        print('NO YAHOO TAB OPEN'); sys.exit(1)
    ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=25, header={'Origin': 'http://127.0.0.1:9222'})
    cdp(ws, 'Page.navigate', {'url': DRAFT_PAGE})
    time.sleep(8)
    expr = r"""(function(){
      var b = document.body.innerText;
      var rows = [];
      var els = document.querySelectorAll('li, tr');
      for (var i = 0; i < els.length; i++) {
        var t = (els[i].innerText || '').replace(/\s+/g, ' ').trim();
        if (/^\s*\d{1,2}[.)]\s*\S/.test(t) && t.length < 120 && rows.indexOf(t) < 0) rows.push(t);
      }
      return {url: location.href, title: document.title.slice(0,60),
              scheduled: (b.match(/scheduled for[^\n]*/i) || [''])[0],
              countdown: (b.match(/(Live League Draft|draft)[^\n]*in \d[^\n]*/i) || [''])[0],
              order_header: (b.match(/[^\n]*[Dd]raft [Oo]rder[^\n]*/g) || []).slice(0,5),
              doge: (b.match(/[^\n]*Doge[^\n]*/gi) || []).slice(0,4),
              rows: rows.slice(0, 30)};
    })()"""
    o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    print(json.dumps(o['result']['result']['value'], indent=1, ensure_ascii=True))
    ws.close()

main()
