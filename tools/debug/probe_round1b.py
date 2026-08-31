"""Deeper probe: full round-1 table text + cell HTML + a later round."""
import json, random, urllib.request, websocket

p = [t for t in json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=8).read())
     if t.get('type') == 'page' and 'fantasysports.yahoo.com' in (t.get('url') or '')][0]
ws = websocket.create_connection(p['webSocketDebuggerUrl'], timeout=20,
                                 header={'Origin': 'http://127.0.0.1:9222'})
wid = random.randint(1000, 99999)
expr = r"""(function(){
  var t = document.querySelectorAll('table')[0];
  var t5 = document.querySelectorAll('table')[5];
  return {
    t0_text: t.innerText,
    t0_row2_html: t.rows[1] ? t.rows[1].innerHTML.slice(0, 1200) : null,
    t5_row2_text: t5 && t5.rows[1] ? t5.rows[1].innerText : null
  };
})()"""
ws.send(json.dumps({'id': wid, 'method': 'Runtime.evaluate',
                    'params': {'expression': expr, 'returnByValue': True}}))
while True:
    o = json.loads(ws.recv())
    if o.get('id') == wid:
        print(json.dumps(o['result']['result']['value'], indent=1)); break
ws.close()
