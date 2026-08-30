"""Check rookie coverage in the refreshed depth_charts_2026."""
import pandas as pd

dc = pd.read_csv(r'C:\nfl-win\data\raw\depth_charts_2026.csv', low_memory=False)
print('snapshot date(s):', dc['dt'].min(), '->', dc['dt'].max())
pl = pd.read_csv(r'C:\nfl-win\data\raw\players.csv', low_memory=False)
pl26 = pl[pl['draft_year'] == 2026]
ids26 = set(pl26['gsis_id'].dropna())
dc26 = dc[dc['gsis_id'].isin(ids26)]
print('rookies in depth charts:', dc26['gsis_id'].nunique(), 'of', len(ids26))
sk = dc26[dc26['pos_abb'].isin(['QB', 'RB', 'WR', 'TE'])]
print('skill rookies in depth charts:', sk['gsis_id'].nunique())
mer = sk.merge(pl26[['gsis_id', 'display_name']], on='gsis_id')
cols = ['display_name', 'pos_abb', 'team', 'pos_slot', 'pos_rank']
print(mer[cols].sort_values(['pos_abb', 'pos_rank']).head(30).to_string(index=False))
