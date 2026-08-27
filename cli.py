#!/usr/bin/env python3
"""Command-line interface for the fantasy football toolkit.

Examples
--------
  python cli.py ingest                 # download + cache nflverse data
  python cli.py rank --preset ppr --top 15
  python cli.py week 12 --preset half-ppr
  python cli.py lineup --preset ppr
  python cli.py validate              # compare our scoring vs nflverse
"""

from __future__ import annotations

import argparse
import sys

from src import ingest, scoring, lineup
from src.config import FANTASY_POSITIONS


def _df(name: str, refresh: bool):
    return ingest.load(name, refresh=refresh)


def cmd_ingest(args) -> int:
    print("Downloading nflverse datasets into data/raw ...")
    ingest.load_all(refresh=args.refresh)
    print("Done. Files cached in data/raw/.")
    return 0


def cmd_rank(args) -> int:
    df = _df("player_week_stats", refresh=args.refresh)
    table = scoring.rank_players(
        df, preset=args.preset, positions=args.positions, top_n=args.top
    )
    _print_table(table)
    return 0


def cmd_week(args) -> int:
    df = _df("player_week_stats", refresh=args.refresh)
    table = scoring.weekly_rankings(
        df, week=args.week, preset=args.preset, positions=args.positions, top_n=args.top
    )
    print(f"\n=== Week {args.week} ({args.preset}) ===")
    _print_table(table)
    return 0


def cmd_lineup(args) -> int:
    df = _df("player_week_stats", refresh=args.refresh)
    ranked = scoring.add_scores(df, preset=args.preset, copy=True)
    picks = lineup.optimize_lineup(ranked, preset=args.preset)
    total = lineup.lineup_total(picks)
    print(f"\n=== Optimized lineup ({args.preset}) | projected total: {total} ===")
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
    df = _df("player_week_stats", refresh=args.refresh)
    sample = scoring.validate_against_nflverse(df, preset=args.preset)
    print(f"\n=== Scoring validation vs nflverse ({args.preset}) ===")
    print(f"max abs delta: {sample['delta'].abs().max():.2f}")
    print(f"mean abs delta: {sample['delta'].abs().mean():.4f}")
    _print_table(sample.head(15))
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fantasy football toolkit")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("ingest", help="download + cache nflverse data")
    pi.add_argument("--refresh", action="store_true", help="re-download even if cached")
    pi.set_defaults(func=cmd_ingest)

    pr = sub.add_parser("rank", help="season rankings by total fantasy points")
    pr.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pr.add_argument("--positions", type=_pos_type, default=None, help="QB,RB,WR,TE,K,DEF")
    pr.add_argument("--top", type=int, default=20)
    pr.add_argument("--refresh", action="store_true")
    pr.set_defaults(func=cmd_rank)

    pw = sub.add_parser("week", help="rankings for a specific week")
    pw.add_argument("week", type=int, help="week number")
    pw.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pw.add_argument("--positions", type=_pos_type, default=None)
    pw.add_argument("--top", type=int, default=20)
    pw.add_argument("--refresh", action="store_true")
    pw.set_defaults(func=cmd_week)

    pl = sub.add_parser("lineup", help="greedy optimized starting lineup")
    pl.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pl.add_argument("--refresh", action="store_true")
    pl.set_defaults(func=cmd_lineup)

    pv = sub.add_parser("validate", help="compare scoring vs nflverse shipped values")
    pv.add_argument("--preset", default="ppr", choices=["standard", "ppr", "half-ppr"])
    pv.add_argument("--refresh", action="store_true")
    pv.set_defaults(func=cmd_validate)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
