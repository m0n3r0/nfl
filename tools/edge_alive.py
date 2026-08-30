import json, urllib.request
try:
    tabs = json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=6).read())
    pages = [t for t in tabs if t.get('type') == 'page']
    print('EDGE OK, tabs:', len(pages))
    for t in pages[:6]: print(' ', t['title'][:45], '|', t['url'][:70])
except Exception as e:
    print('EDGE NOT REACHABLE:', repr(e))
