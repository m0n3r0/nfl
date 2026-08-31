"""List CDP tabs and dump page info (diagnostic helper)."""
import json, urllib.request

p = json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=8).read())
for t in p:
    print(t.get('type'), '|', (t.get('title') or '')[:60], '|', (t.get('url') or '')[:100])
