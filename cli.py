#!/usr/bin/env python3
"""Command-line interface for the fantasy football toolkit.

The "current" season is driven by src/config.py: SCHEDULE_SEASON (2026) for the
game schedule, STATS_SEASON (2025) for the most recent published player stats.

Examples
--------
  python cli.py ingest                 # download + cache nflverse data
  python cli.py schedule               # print the 2026 game schedule
  python cli.py rank --preset ppr --top 15
  python cli.py week 12 --preset half-ppr
  python cli.py lineup --preset ppr
  python cli.py validate              # compare our scoring vs nflverse
"""

from __future__ import annotations

import argparse
import sys

from src import ingest, scoring, lineup, corpus, projections, analysis, model
from src.config import FANTASY_POSITIONS, SCHEDULE_SEASON, STATS_SEASON


def _df(name: str, refresh: bool, stats_season: int = STATS_SEASON):
    return ingest.load(name, refresh=refresh, stats_season=stats_season)


def cmd_ingest(args) -> int:
    season = args.season or STATS_SEASON
    print(f"Downloading nflverse datasets (stats season {season}, "
          f"schedule season {SCHEDULE_SEASON}) into data/raw ...")
    ingest.load_all(refresh=args.refresh, stats_season=season)
    print("Done. Files cached in data/raw/.")
    return 0


def cmd_schedule(args) -> int:
    season = args.season or SCHEDULE_SEASON
    games = ingest.load_schedule(season=season, refresh=args.refresh)
    print(f"\n=== {season} schedule ({len(games)} games) ===")
    cols = ["week", "gameday", "away_team", "home_team", "game_type"]
    _print_table(games[cols].sort_values(["week", "gameday"]))
    return 0


def cmd_rank(args) -> int:
    season = args.season or STATS_SEASON
    df = _df("player_week_stats", args.refresh, stats_season=season)
    table = scoring.rank_players(
        df, preset=args.preset, positions=args.positions, top_n=args.top
    )
    print(f"\n=== {season} season rankings ({args.preset}) ===")
    _print_table(table)
    return 0


def cmd_week(args) -> int:
    season = args.season or STATS_SEASON
    df = _df("player_week_stats", args.refresh, stats_season=season)
    table = scoring.weekly_rankings(
        df, week=args.week, preset=args.preset, positions=args.positions, top_n=args.top
    )
    print(f"\n=== {season} Week {args.week} ({args.preset}) ===")
    _print_table(table)
    return 0


def cmd_lineup(args) -> int:
    season = args.season or STATS_SEASON
    df = _df("player_week_stats", args.refresh, stats_season=season)
    ranked = scoring.add_scores(df, preset=args.preset, copy=True)
    picks = lineup.optimize_lineup(ranked, preset=args.preset)
    total = lineup.lineup_total(picks)
    print(f"\n=== Optimized lineup ({args.preset}, stats {season}) | projected total: {total} ===")
    empty = []
    for slot, players in picks.items():
        label = f"{slot}"
        if players:
            names = ", ".join(f"{p['player']} ({p['position']}, {p['points']})" for p in players)
        else:
            names = "(no scorable players in dataset)"
            empty.append(slot)
        print(f"  {label:<5} {names}")
    if empty:
        print(f"\nNote: slots {', '.join(empty)} are empty because the nflverse player "
              f"stat table scores K/DEF as 0 (defense is team-level). Add those "
              f"datasets to fill them.")
    return 0


def cmd_validate(args) -> int:
    season = args.season or STATS_SEASON
    df = _df("player_week_stats", args.refresh, stats_season=season)
    sample = scoring.validate_against_nflverse(df, preset=args.preset)
    print(f"\n=== Scoring validation vs nflverse ({args.preset}, {season}) ===")
    print(f"max abs delta: {sample['delta'].abs().max():.2f}")
    print(f"mean abs delta: {sample['delta'].abs().mean():.4f}")
    _print_table(sample.head(15))
    return 0


def cmd_corpus(args) -> int:
    print("Collecting 2026 projection corpus (this downloads ~80MB of data)...")
    c = ingest.collect_corpus(refresh=args.refresh)
    print("Corpus ready. Tables in memory:")
    for k, v in c.items():
        if hasattr(v, "shape"):
            print(f"  {k}: {v.shape[0]} rows x {v.shape[1]} cols")
    return 0


def _build_corpus(preset: str):
    return corpus.build(preset=preset)


def cmd_projections(args) -> int:
    c = _build_corpus(args.preset)
    proj = projections.project_players(c, preset=args.preset)
    if args.positions:
        proj = proj[proj["position"].isin(args.positions)]
    print(f"\n=== 2026 projections ({args.preset}) ===")
    _print_table(proj.head(args.top))
    return 0


def cmd_consistency(args) -> int:
    c = _build_corpus(args.preset)
    cons = analysis.consistency(c, preset=args.preset)
    if args.positions:
        cons = cons[cons["position"].isin(args.positions)]
    print(f"\n=== Consistency (CV; lower = steadier) ({args.preset}) ===")
    _print_table(cons.head(args.top))
    return 0


def cmd_matchups(args) -> int:
    c = _build_corpus(args.preset)
    board = analysis.weekly_matchups(c, week=args.week, preset=args.preset, top_n=args.top)
    print(f"\n=== 2026 Week {args.week} matchups ({args.preset}) ===")
    _print_table(board)
    return 0


def cmd_sos(args) -> int:
    c = corpus.build()  # SOS is schedule/defense based; preset-independent
    sos = analysis.sos_ranking(c)
    print("\n=== 2026 Strength-of-Schedule (easier = higher sos) ===")
    _print_table(sos)
    return 0


def cmd_predict(args) -> int:
    preds = model.predict_2026(week=args.week)
    title = f"2026" + (f" Week {args.week}" if args.week else " (all weeks)")
    print(f"\n=== {title} win probabilities ===")
    _print_table(preds)
    return 0


def cmd_web(args) -> int:
    import os
    from web import app
    port = args.port
    print(f"Starting web UI at http://127.0.0.1:{port}  (Ctrl-C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False)
    return 0


def _print_table(df):
    if df is None or len(df) == 0:
        print("(no rows)")
        return
    with pd_option_context():
        print(df.to_string(index=False))


def pd_option_context():
    import pandas as pd
    return pd.option_context("display.max_columns", None, "display.width", 200)


def _pos_type(value: str):
    items = [v.strip().upper() for v in value.split(",") if v.strip()]
    bad = [v for v in items if v not in FANTASY_POSITIONS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown position(s): {bad}")
    return items


def _add_season(p):
    p.add_argument("--season", type=int, default=None,
                   help=f"stats season (default {STATS_SEASON}); schedule uses "
                        f"{SCHEDULE_SEASON}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fantasy football toolkit")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("ingest", help="download + cache nflverse data")
    _add_season(pi)
    pi.add_argument("--refresh", action="store_true", help="re-download even if cached")
    pi.set_defaults(func=cmd_ingest)

    ps = sub.add_parser("schedule", help=f"print the {SCHEDULE_SEASON} game schedule")
    ps.add_argument("--season", type=int, default=None, help=f"schedule season (default {SCHEDULE_SEASON})")
    ps.add_argument("--refresh", action="store_true")
    ps.set_defaults(func=cmd_schedule)

    pr = sub.add_parser("rank", help="season rankings by total fantasy points")
    _add_season(pr)
    pr.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pr.add_argument("--positions", type=_pos_type, default=None, help="QB,RB,WR,TE,K,DEF")
    pr.add_argument("--top", type=int, default=20)
    pr.add_argument("--refresh", action="store_true")
    pr.set_defaults(func=cmd_rank)

    pw = sub.add_parser("week", help="rankings for a specific week")
    _add_season(pw)
    pw.add_argument("week", type=int, help="week number")
    pw.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pw.add_argument("--positions", type=_pos_type, default=None)
    pw.add_argument("--top", type=int, default=20)
    pw.add_argument("--refresh", action="store_true")
    pw.set_defaults(func=cmd_week)

    pl = sub.add_parser("lineup", help="greedy optimized starting lineup")
    _add_season(pl)
    pl.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pl.add_argument("--refresh", action="store_true")
    pl.set_defaults(func=cmd_lineup)

    pv = sub.add_parser("validate", help="compare scoring vs nflverse shipped values")
    _add_season(pv)
    pv.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pv.add_argument("--refresh", action="store_true")
    pv.set_defaults(func=cmd_validate)

    pc = sub.add_parser("corpus", help="download + assemble the 2026 projection corpus")
    pc.add_argument("--refresh", action="store_true")
    pc.set_defaults(func=cmd_corpus)

    pj = sub.add_parser("projections", help="2026 projections (multi-year + role + SOS)")
    pj.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pj.add_argument("--positions", type=_pos_type, default=None)
    pj.add_argument("--top", type=int, default=30)
    pj.set_defaults(func=cmd_projections)

    pcons = sub.add_parser("consistency", help="weekly consistency / boom-bust by player")
    pcons.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pcons.add_argument("--positions", type=_pos_type, default=None)
    pcons.add_argument("--top", type=int, default=30)
    pcons.set_defaults(func=cmd_consistency)

    pm = sub.add_parser("matchups", help="2026 weekly start/sit board")
    pm.add_argument("week", type=int, help="2026 week number")
    pm.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pm.add_argument("--top", type=int, default=25)
    pm.set_defaults(func=cmd_matchups)

    pso = sub.add_parser("sos", help="2026 team strength-of-schedule ranking")
    pso.add_argument("--top", type=int, default=32)
    pso.set_defaults(func=cmd_sos)

    ppred = sub.add_parser("predict", help="2026 win probabilities")
    ppred.add_argument("week", type=int, nargs="?", default=None, help="2026 week (omit for all)")
    ppred.set_defaults(func=cmd_predict)

    pw = sub.add_parser("web", help="launch the local web UI")
    pw.add_argument("--port", type=int, default=5000)
    pw.set_defaults(func=cmd_web)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
