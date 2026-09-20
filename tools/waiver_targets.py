#!/usr/bin/env python3
"""Rank available free agents/waiver players by our weekly projection.

Read-only: paginates the Yahoo players pages (never clicks), reconciles every
available player against the projection model, and prints the best available
per week. Use before deciding a waiver claim; the claim itself goes through
tools/yahoo_waiver.py with exact IDs.

``--jev N`` adds an advisory Jev (TypeSafe System One) judgment for the top N
targets: the projection stays the ranking source of truth, Jev only attaches
a typed second opinion (profile / claim priority / injury-risk) per player.
Missing API key or API errors degrade to the plain projection ranking with a
warning on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import corpus as corpus_mod, jev, projections  # noqa: E402
from src.config import league_preset  # noqa: E402
from yahoo.cdp import CdpClient  # noqa: E402
from yahoo.team import TEAM_PATH, YahooTeamReader, find_team_target  # noqa: E402
from yahoo.wire import rank_targets, scan_available  # noqa: E402

BASE = "https://football.fantasysports.yahoo.com"


def jev_state(target: dict, week: int) -> dict:
    """Compact per-player state; Jev can only judge facts we hand it."""
    return {
        "task": "Assess an available free agent for a fantasy football waiver claim.",
        "league": "12-team half-PPR Yahoo league; weekly lineup QB/2RB/2WR/TE/W-R-T/K/DEF.",
        "week": week,
        "player": {k: target[k] for k in
                   ("name", "position", "team", "availability", "injury_status")},
        "proj_points_this_week": target["proj_week"],
    }


def jev_questions() -> dict:
    return {
        "profile": jev.choice(
            "Which profile best fits `player` as a waiver target right now?",
            {"steady_starter": "Reliable weekly starter talent.",
             "breakout": "Emerging role with sustainable upside.",
             "injury_fillin": "Value depends on a teammate's injury.",
             "one_week_spike": "Recent hype driven by a fluke game.",
             "depth_piece": "Bench depth or handcuff only."}),
        "claim": jev.score(
            "Recommended waiver action for `player` this week.",
            ["ignore", "watchlist", "stream if needed", "claim now"]),
        "risk": jev.noul(
            "Does `player` carry injury or role risk the projection may not capture?"),
    }


def review_targets(targets: list[dict], week: int) -> int:
    """Attach a 'jev' block to each target in place; returns failures."""
    failures = 0
    for target in targets:
        try:
            resp = jev.ask(jev_state(target, week), jev_questions())
            answers = resp.answers
            target["jev"] = {
                "profile": answers["profile"].choice,
                "claim_score": answers["claim"].score,
                "claim_legend": answers["claim"].legend,
                "risk_noul": answers["risk"].noul,
            }
        except jev.JevError as exc:
            failures += 1
            print(f"warning: Jev skipped {target['name']}: {exc}",
                  file=sys.stderr)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, default=None,
                        help="projection week (default: the roster page's current week)")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--jev", type=int, default=0, metavar="N",
                        help="advisory Jev (TypeSafe) review of the top N targets")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be >= 0")
    if args.jev < 0:
        parser.error("--jev must be >= 0")

    with CdpClient(find_team_target(args.endpoint), endpoint=args.endpoint, timeout=25) as client:
        snapshot = YahooTeamReader(client).snapshot()
        week = args.week or snapshot.week
        try:
            available = scan_available(client, week)
        finally:
            client.navigate(f"{BASE}{TEAM_PATH}",
                            lambda url: urlparse(url).path.rstrip("/") == TEAM_PATH, 30)

    corp = corpus_mod.build(preset=league_preset())
    proj = projections.project_for_week(corp, week)
    ranked, skipped = rank_targets(available, proj)

    top = ranked[: args.top]
    if args.jev:
        review_targets(top[: args.jev], week)

    print(json.dumps({
        "week": week,
        "available_scanned": len(available),
        "skipped": skipped,
        "targets": top,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
