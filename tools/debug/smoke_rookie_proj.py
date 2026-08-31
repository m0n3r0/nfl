"""Smoke test: do 2026 draft-class rookies now get projections?"""
import sys
sys.path.insert(0, r'C:\nfl-win')
from src import corpus, projections

c = corpus.build(preset='half-ppr')
proj = projections.project_players(c, preset='half-ppr')
print('projected players:', len(proj))
rk = proj[proj['player_id'].astype(str).str.startswith('00-0041') |
          proj['player_id'].astype(str).str.startswith('00-0040')]
names = ['Jeremiyah Love', 'Carnell Tate', 'Kenyon Sadiq', 'Jordyn Tyson',
         'Fernando Mendoza', 'Makai Lemon', 'KC Concepcion', 'Omar Cooper Jr.']
hits = proj[proj['player_display_name'].isin(names)]
print(hits[['rank', 'player_display_name', 'position', 'last_team',
            'proj_ppg', 'proj_total']].to_string(index=False))
print('rookie starters expected high: Love (ARI RB1), Tate (TEN WR1)')
