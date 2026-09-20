#!/usr/bin/env python3
"""Advisory Jev (TypeSafe) judgment for a proposed trade: --give vs --receive.

Read-only and manual. The factual base is our own season projection table;
Jev only judges the numbers it is handed (it has no live NFL knowledge), so
the verdict is a structured second opinion next to the raw projection delta —
not an authority. Usage:

    python tools/trade_check.py --give "Chase Brown" --receive "Justin Jefferson"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src import corpus as corpus_mod, jev, projections  # noqa: E402
from src.config import league_preset  # noqa: E402


def find_player(proj: pd.DataFrame, name: str) -> dict:
    """Case-insensitive substring lookup; fail loud on missing/ambiguous."""
    hits = proj[proj["player_display_name"].str.contains(name, case=False, na=False)]
    if len(hits) != 1:
        names = hits["player_display_name"].tolist() or ["<none>"]
        raise SystemExit(f"error: {name!r} matched {len(hits)} players: {names[:5]}")
    row = hits.iloc[0]
    return {"name": row["player_display_name"], "position": row["position"],
            "team": row["last_team"], "proj_ppg": round(float(row["proj_ppg"]), 2),
            "proj_total": round(float(row["proj_total"]), 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--give", action="append", required=True,
                        help="player we give up (repeatable)")
    parser.add_argument("--receive", action="append", required=True,
                        help="player we receive (repeatable)")
    args = parser.parse_args()

    corp = corpus_mod.build(preset=league_preset())
    proj = projections.project_players(corp)
    give = [find_player(proj, n) for n in args.give]
    receive = [find_player(proj, n) for n in args.receive]
    delta = (sum(p["proj_total"] for p in receive)
             - sum(p["proj_total"] for p in give))

    try:
        with jev.connect() as client:
            verdict = jev.judge_trade(give, receive, client=client)
    except jev.JevError as exc:
        print(f"error: Jev unavailable: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({"give": give, "receive": receive,
                      "proj_total_delta": round(delta, 1),
                      "jev": verdict}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
