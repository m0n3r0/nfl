#!/usr/bin/env python3
"""Backtest returning-player fantasy PPG projections against a realized season."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import backtest, corpus
from src.config import HISTORY_SEASONS, league_preset


def _table(metrics):
    lines = ["| Scope | Players | Spearman | MAE PPG | Top-N recall |", "|---|---:|---:|---:|---:|"]
    for metric in metrics:
        recall = "—" if metric.top_n_recall is None else f"{metric.top_n_recall:.3f} (top {metric.top_n})"
        lines.append(f"| {metric.scope} | {metric.players} | {metric.spearman:.3f} | {metric.mae_ppg:.3f} | {recall} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-season", type=int, default=max(HISTORY_SEASONS))
    parser.add_argument("--write-doc", type=Path)
    args = parser.parse_args()
    target = args.target_season
    seasons = [season for season in HISTORY_SEASONS if season < target]
    if not seasons:
        parser.error("target season must follow at least one configured history season")
    recency = {season: 1.0 + 0.5 * index for index, season in enumerate(seasons)}
    equal = {season: 1.0 for season in seasons}

    weekly = corpus._weekly_history(preset=league_preset())
    frame = backtest.project_historical_season(weekly, target, recency)
    equal_frame = backtest.project_historical_season(weekly, target, equal)
    results = {
        "target_season": target,
        "training_seasons": seasons,
        "model": [metric.as_dict() for metric in backtest.backtest_metrics(frame, "model_ppg")],
        "equal_weight": [metric.as_dict() for metric in backtest.backtest_metrics(equal_frame, "model_ppg")],
        "prior_year": [metric.as_dict() for metric in backtest.backtest_metrics(frame, "prior_year_ppg")],
    }
    print(json.dumps(results, indent=2, sort_keys=True))

    if args.write_doc:
        text = f"""# Projection backtest

This leakage-controlled returning-player backtest trains on {seasons[0]}–{seasons[-1]} regular-season weekly rows and predicts {target} half-PPR points per game. Players need at least four realized target-season games. It reports rank correlation, PPG error, and positional top-N recall.

## Production recency weights plus games/20 shrinkage

{_table(backtest.backtest_metrics(frame, "model_ppg"))}

## Equal-season-weight comparison

{_table(backtest.backtest_metrics(equal_frame, "model_ppg"))}

## Prior-year PPG baseline

{_table(backtest.backtest_metrics(frame, "prior_year_ppg"))}

## Interpretation and limits

This validates the historical baseline, recency weighting, and games/20 shrinkage for returning players. It does not validate rookie priors because rookies have no prior NFL rows, and it intentionally excludes current depth-chart role and future schedule/SOS adjustments because using end-of-season target-year data would leak future information. Those components must remain separately labeled heuristics.

The model should not be described as a proven advantage merely because it beats or trails one baseline on one season. Re-run this report after every completed season and compare multiple target years when enough cached history exists.
"""
        args.write_doc.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
