"""Scrape the completed FD nation (1329011) draft from Yahoo via CDP.

Primary source: /draftresults round tables (round-by-round picks).
Fallback/supplement: each team's roster page /f1/1329011/{team_id}.

Output (repo data store):
  data/scrapes/draft_results_2026.json   -- structured picks + per-team rosters
  data/scrapes/draft_results_2026.md     -- human-readable summary

Run:  .venv/Scripts/python.exe tools/scrape_draft_results.py
"""

import io
import json
import os
import random
import re
import sys
import time
import urllib.request
import websocket

CDP = 'http://127.0.0.1:9222'
LEAGUE = '1329011'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, 'data', 'scrapes')

tabs = [t for t in json.loads(urllib.request.urlopen(CDP + '/json', timeout=8).read())
        if t.get('type') == 'page' and 'fantasysports.yahoo.com' in (t.get('url') or '')]
tab = tabs[0]
ws = websocket.create_connection(tab['webSocketDebuggerUrl'], timeout=30,
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


def navigate(url, wait=8):
    send("location.href=%s" % json.dumps(url))
    time.sleep(wait)


# ---- 1. draft results page ---------------------------------------------------
navigate('https://football.fantasysports.yahoo.com/f1/%s/draftresults' % LEAGUE, wait=10)
rounds = send(r"""(function(){
  var out = [];
  document.querySelectorAll('table').forEach(function(t){
    var head = t.rows[0] ? t.rows[0].innerText.trim() : '';
    var m = head.match(/Round\s+(\d+)/i);
    if (!m) return;
    var picks = [];
    for (var r = 1; r < t.rows.length; r++) {
      var cells = t.rows[r].cells;
      picks.push({
        pick_in_round: cells[0] ? cells[0].innerText.trim().replace('.', '') : '',
        player: cells[1] ? cells[1].innerText.trim() : '',
        team_name: cells[2] ? cells[2].innerText.trim() : ''
      });
    }
    out.push({round: parseInt(m[1], 10), picks: picks});
  });
  return out;
})()""") or []

rounds = [r for r in rounds if r.get('picks')]
has_players = any(p['player'] and p['player'] != '\u00a0' for r in rounds for p in r['picks'])
print('draftresults tables: %d rounds, players_present=%s'
      % (len(rounds), has_players))

# ---- 2. team roster pages (always scraped: authoritative rosters) ------------
TEAM_IDS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']
teams = {}
for tid in TEAM_IDS:
    navigate('https://football.fantasysports.yahoo.com/f1/%s/%s' % (LEAGUE, tid), wait=6)
    info = send(r"""(function(){
      var name = (document.querySelector('h1') || {}).innerText || document.title;
      // roster rows: player links inside the roster table
      var rows = [];
      document.querySelectorAll('table').forEach(function(t){
        t.querySelectorAll('tr').forEach(function(tr){
          var a = tr.querySelector('a[href*="nfl.fantasysports.yahoo.com"], a[href*="/f1/"][href*="&p="], a.playerlink, a[href*="playerreport"]')
                  || (tr.querySelector('.Nowrap a') || null);
          var txt = tr.innerText.replace(/\s+/g, ' ').trim();
          if (a && / - (QB|RB|WR|TE|K|DEF)/.test(a.innerText)) {
            rows.push({cell: a.innerText.trim(), row: txt.slice(0, 120)});
          }
        });
      });
      return {name: name.trim(), rows: rows.slice(0, 40)};
    })()""")
    teams[tid] = info
    print('team %s: %s (%d player rows)' % (tid, info['name'], len(info['rows'])))

ws.close()

# ---- 3. persist --------------------------------------------------------------
os.makedirs(OUT_DIR, exist_ok=True)
data = {
    'league': LEAGUE,
    'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    'rounds': rounds,
    'teams': teams,
}
jpath = os.path.join(OUT_DIR, 'draft_results_2026.json')
with io.open(jpath, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=1, ensure_ascii=False)
print('wrote', jpath)

# markdown summary of my team (team 2 = Doge) roster
my = teams.get('2', {})
lines = ['# FD nation draft results (league %s)' % LEAGUE, '',
         'Scraped: %s' % data['scraped_at'], '',
         '## My roster (team 2, Doge)', '']
for row in my.get('rows', []):
    lines.append('- %s' % row['cell'])
mpath = os.path.join(OUT_DIR, 'draft_results_2026.md')
with io.open(mpath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print('wrote', mpath)
