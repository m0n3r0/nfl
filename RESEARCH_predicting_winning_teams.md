# Deep dive: data to predict a WINNING team (game-outcome modeling)

Goal: move beyond fantasy points (who scores) to team-win prediction (who wins).
This is a different modeling problem. The signals that predict fantasy points are
NOT the same as the signals that predict wins. Below is what is actually collectable
from public sources (verified against live nflverse endpoints), ranked by how well
the literature shows they predict outcomes.

## Tier 1 — strongest predictors (collect these first)

1. Vegas lines (point spread, moneyline, total)
   - Source: nflverse `schedules/games.csv` (columns: `spread_line`,
     `home_moneyline`, `away_moneyline`, `total_line`, `away_spread_odds`,
     `home_spread_odds`).
   - Why: the closing spread is historically the single best predictor of game
     outcomes — it already aggregates all public information. A model that just
     "believes the spread" is the hard-to-beat baseline. Use as a feature AND as
     the evaluation baseline.

2. EPA / success-rate efficiency (offense & defense)
   - Source: nflverse `stats_team` (`stats_team_reg_2025.csv`). Columns include
     `passing_epa`, `rushing_epa`, `receiving_epa` (offense) and the `def_*` family
     (`def_pass_defended`, `def_sacks`, `def_interceptions`, `def_tds`, ...).
   - Verified: BUF 2025 passing_epa = 97.06, rushing_epa = 41.29.
   - Why: EPA (Expected Points Added) is the gold-standard efficiency metric.
     Yards/TDs are volume stats inflated by garbage time; EPA measures per-play
     contribution to winning. Team pass EPA differential is one of the best
     single win-correlation stats.

3. Turnover differential
   - Source: team stats — `passing_interceptions`, fumbles (`rushing_fumbles_lost`,
     `receiving_fumbles_lost`), `def_interceptions`, `def_fumbles_forced`.
   - Why: turnover margin is one of the most consistent year-to-year win
     correlates (though turnovers are themselves noisy / low-predictability week to week).

## Tier 2 — useful context / matchup features

4. Schedule & rest
   - Source: `games.csv` — `away_rest`, `home_rest` (days rest), `roof`, `temp`,
     `wind`, `week`, `away_team`, `home_team`, `away_score`/`home_score` (targets).
   - Why: short-week / rest advantage and indoor-vs-outdoor (wind) are real edges.

5. Next Gen Stats (player tracking)
   - Source: nflverse `nextgen_stats/*` (e.g. `ngs_passing.csv`). Verified columns:
     `avg_time_to_throw`, `avg_intended_air_yards`, `avg_air_yards_to_sticks`,
     `completion_percentage_above_expectation`, `avg_completed_air_yards`.
   - Why: QB decision quality (air yards to sticks, completion above expectation)
     is more stable/predictive than raw completions. Aggregate to team level.

6. Injuries / availability
   - Source: nflverse `injuries` (latest = 2025; 2026 not published preseason).
     For in-season 2026 use weekly injury reports / depth charts (`depth_charts_2026`).
   - Why: missing key players (QB, top WR/edge) shifts win prob materially.

7. Draft capital / roster strength
   - Source: `players.csv` has `draft_year`, `draft_round`, `draft_pick`; PFR/ESPN ids.
   - Why: roster quality (esp. trench + QB) is a season-level strength signal.

## Tier 3 — use with caution

8. Raw volume stats (yards, TDs, receptions) — good for fantasy, weak for wins
   (correlated with trailing/garbage time). Use only as inputs to EPA, not directly.
9. Historical win% / streaks — weak predictive value (Games Behind, hot-hand fallacy).

## Target variable
- `home_win` (1/0) derived from `home_score > away_score` in `games.csv`.
- Or point-spread outcome: did the favorite cover? (needs `spread_line`.)

## Suggested model (transparent, not a black box)
- Features: home/away team EPA differentials (offense+defense, last N games or
  season-to-date), Vegas spread, rest differential, turnovers, weather.
- Approach: logistic regression or gradient-boosted trees on historical games
  (2022-2025) with a strict train/test split by time (never leak future games).
- Baseline to beat: "pick the spread favorite" (≈% accuracy to match).
- Evaluate: log-loss + accuracy on a held-out future season.

## What we already have vs what to add
Already in the corpus: games.csv (scores + vegas + weather + rest), stats_team
(team EPA), players (draft capital), depth_charts_2026, injuries.
Still to add for win-prediction: aggregate stats_team to per-team efficiency,
join nextgen_stats to team level, engineer EPA differentials + rolling form,
build the labeled `home_win` target, and a model module.

## Ethical/ractical note
This predicts outcomes for analysis/fun, not gambling. Treat vegas lines as a
baseline, not a guarantee.
