import sys
sys.path.insert(0, r'C:\nfl-win')
from src import corpus, ingest

roles = corpus.build_depth_roles()
print('roles rows:', len(roles), '| unique players:', roles['gsis_id'].nunique())
print('starters:', int(roles['starter'].sum()))
# do 2026 rookies appear with meaningful roles?
pl = ingest.load('players')
rookie_ids = set(pl[pl['draft_year'] == 2026]['gsis_id'].dropna())
rk = roles[roles['gsis_id'].isin(rookie_ids)]
print('rookies with roles:', rk['gsis_id'].nunique(), '| rookie starters:', int(rk['starter'].sum()))
print(rk[rk['starter']].head(12).to_string(index=False))
