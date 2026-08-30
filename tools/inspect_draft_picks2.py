"""Verify post-draft data: 2026 class in draft_picks, players, depth charts."""
import pandas as pd

dp = pd.read_csv(r'C:\nfl-win\data\raw\draft_picks.csv', low_memory=False)
print('draft_picks seasons:', dp['season'].min(), '->', dp['season'].max(),
      '| cols:', list(dp.columns))
d26 = dp[dp['season'] == 2026]
print('2026 picks:', len(d26))
print(d26[d26['position'].isin(['QB', 'RB', 'WR', 'TE'])].head(25).to_string(index=False))

pl = pd.read_csv(r'C:\nfl-win\data\raw\players.csv', low_memory=False)
pl26 = pl[pl['draft_year'] == 2026]
print('\nplayers.csv: draft_year 2026 ->', len(pl26), 'players')
print(pl26[pl26['position'].isin(['QB', 'RB', 'WR', 'TE'])]
      [['gsis_id', 'display_name', 'position', 'draft_round', 'draft_pick',
        'draft_team']].head(25).to_string(index=False))

dc = pd.read_csv(r'C:\nfl-win\data\raw\depth_charts_2026.csv', low_memory=False)
print('\ndepth_charts_2026 rows:', len(dc), '| weeks:', sorted(dc['week'].unique())[-3:])
ids26 = set(pl26['gsis_id'].dropna())
dc26 = dc[dc['gsis_id'].isin(ids26)]
print('2026 rookies appearing in depth charts:', dc26['gsis_id'].nunique())
poscol = 'pos_abbv' if 'pos_abbv' in dc.columns else 'position'
sk = dc26[dc26[poscol].isin(['QB', 'RB', 'WR', 'TE'])]
print('skill rookies in depth charts:', sk['gsis_id'].nunique())
