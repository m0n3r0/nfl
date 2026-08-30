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
cdp(ws, 'Page.navigate', {'url': 'https://football.fantasysports.yahoo.com/f1/1329011/draftanalysis'})
time.sleep(12)
# NO clicks -- parse the rendered table. Header: Player/Rank/PosRank/CER/%Drafted/Preseason/AllDrafts/Last7Days
expr = r"""(function(){
  var L = document.body.innerText.split(/\r?\n/).map(function(s){return s.trim();});
  var TP = /^[A-Za-z]{2,4} - (QB|WR|RB|TE|K|DEF)$/;
  var rows = [];
  var i = 0;
  while (i < L.length) {
    if (TP.test(L[i])) {
      var team = L[i].split(' - ')[0], pos = L[i].split(' - ')[1];
      var name = (L[i-1] || '').replace(/Video.*$|Player Note.*$|No new player Notes/g, '').trim();
      var injury = '';
      var vals = [];
      var j = i + 1;
      while (j < L.length && !TP.test(L[j]) && vals.length < 10) {
        var t = L[j];
        if (/^(Q|O|IR|IR-R|SUSP|NA|DTD)$/.test(t) && !injury && vals.length === 0) injury = t;
        else if (/^\d+$/.test(t)) vals.push(parseInt(t));
        else if (/^\d+\.\d+$/.test(t)) vals.push(parseFloat(t));
        else if (/^\d+%$/.test(t)) vals.push(parseInt(t));
        else if (/[a-z]/i.test(t) && t.length > 3) break; // next player section
        j++;
      }
      // vals order = [rank(int), pct_drafted(int<=100), adp floats...]
      var rank = null, pct = null, adps = [];
      for (var k = 0; k < vals.length; k++) {
        if (rank === null) rank = vals[k];
        else if (pct === null) pct = vals[k];
        else if (typeof vals[k] === 'number' && vals[k] <= 30) adps.push(vals[k]);
      }
      if (name && rank !== null) rows.push({name: name, team: team, pos: pos, injury: injury, rank: rank, pct_drafted: pct, adp_all_drafts: adps[0] || null, adp_last_7d: adps[1] || null});
      i = j;
    } else i++;
  }
  return {url: location.href, n: rows.length, rows: rows};
})()"""
o = cdp(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True})
v = o['result']['result']['value']
print('URL:', v['url'])
print('PARSED:', v['n'])
rows = v['rows']
if rows:
    out = {'scraped_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'league': 1329011,
           'source': 'yahoo draft analysis (league-adjusted ADP)', 'players': rows}
    with open(r'C:\nfl-win\data\scrapes\yahoo_league_adp.json', 'w') as f:
        json.dump(out, f, indent=1)
    print('SAVED', len(rows), 'players to data/scrapes/yahoo_league_adp.json')
    for r in rows[:12]: print(r)
else:
    # debug: show lines near a TP match
    dbg = r"""(function(){ var L=document.body.innerText.split(/\r?\n/); var o=[]; for (var i=0;i<L.length;i++){ if(/ - (QB|WR|RB|TE|K|DEF)/.test(L[i])){ for(var j=Math.max(0,i-1);j<=Math.min(L.length-1,i+3);j++) o.push(j+': '+JSON.stringify(L[j].trim())); o.push('---'); if(o.length>28) break; } } return {n_lines: L.length, samples: o}; })()"""
    o2 = cdp(ws, 'Runtime.evaluate', {'expression': dbg, 'returnByValue': True})
    d = o2['result']['result']['value']
    print('LINES:', d['n_lines'])
    for s in d['samples']: print(s)
ws.close()
