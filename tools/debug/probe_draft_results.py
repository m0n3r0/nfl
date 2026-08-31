"""Probe the Yahoo draft-results page structure via CDP (diagnostic)."""
import json, time, random, urllib.request, websocket

CDP = 'http://127.0.0.1:9222'
LEAGUE = '1329011'

tabs = [t for t in json.loads(urllib.request.urlopen(CDP + '/json', timeout=8).read())
        if t.get('type') == 'page' and 'fantasysports.yahoo.com' in (t.get('url') or '')]
tab = tabs[0]
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=25,
                                 header={'Origin': 'http://127.0.0.1:9222'})
wid = random.randint(1000, 99999)


def send(expr, await_promise=False):
    global wid
    wid += 1
    my_id = wid
    ws.send(json.dumps({'id': my_id, 'method': 'Runtime.evaluate',
                        'params': {'expression': expr, 'returnByValue': True,
                                   'awaitPromise': await_promise}}))
    while True:
        o = json.loads(ws.recv())
        if o.get('id') == my_id:
            return o['result']['result'].get('value')


send("location.href='https://football.fantasysports.yahoo.com/f1/%s/draftresults'" % LEAGUE)
time.sleep(8)
print('URL:', send('location.href'))
print('TITLE:', send('document.title'))
info = send(r"""(function(){
  var tables = document.querySelectorAll('table');
  var out = [];
  tables.forEach(function(t, i){
    out.push({i: i, rows: t.rows.length, head: t.rows[0] ? t.rows[0].innerText.slice(0,150) : ''});
  });
  return {n_tables: tables.length, tables: out.slice(0, 20),
          body_head: document.body.innerText.slice(0, 800)};
})()""")
print(json.dumps(info, indent=1)[:2500])
ws.close()
