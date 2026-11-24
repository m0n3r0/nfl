#!/usr/bin/env python3
"""Precompute the prediction-engine web artifacts — the FD nation method.

The Python engine (src/) does the thinking OFFLINE; nfl-webd serves the
analytics pages natively from these JSON files, exactly like the fantasy
pages read logs/*.json. Nothing is computed in the request path, and the
Flask web backend is gone.

Artifacts (data/web/, git-ignored):
  dashboard.json      top projections + honest model evaluation
  players.json        full projection board (nfl-webd filters q/pos)
  players/<pid>.json  per-player season history + projection
  predictions.json    2026 win probabilities (all computable weeks)
  ratings.json        as-of team ratings for every (season, week) combo
  strategy.json       per-team situation splits for every PBP season
  sos.json            2026 strength-of-schedule ranking
  modelcard.json      evaluation + time-series CV (/api/modelcard payload)

Refresh: the com.fdnation.predreport launchd agent (daily 06:12 JST and
Wed 21:05 after the waiver run's --refresh-data), or manually:

    python tools/predictions_report.py [--out DIR]

Fail-soft per section: one broken section never blocks the others; the
summary lists errors and the exit code is 1 when any section failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src import analysis, corpus, features, ingest, model, projections  # noqa: E402
from src.config import (  # noqa: E402
    PBP_SEASONS,
    SCHEDULE_SEASON,
    STATS_SEASON,
    league_preset,
)


# The two most recent completed seasons are the honest holdout: training on
# everything strictly earlier, testing on the latest data. PBP_SEASONS already
# carries the available seasons, so this never goes stale when a new season
# publishes (the old hardcoded (2022,2023)/(2024,2025) ignored 2026 entirely).
EVAL_TEST_SEASONS = tuple(PBP_SEASONS[-2:])
EVAL_TRAIN_SEASONS = tuple(PBP_SEASONS[:-2])


def records(df: pd.DataFrame) -> list:
    """DataFrame -> JSON-safe records (numpy scalars + NaN handled by pandas)."""
    return json.loads(df.to_json(orient="records"))


def _jsonable(obj):
    """Best-effort numpy-scalar coercion for plain dict payloads."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)


def seasons_all() -> list:
    return sorted(set(list(PBP_SEASONS) + [STATS_SEASON]))


def build_all(out: Path = ROOT / "data" / "web") -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    summary: dict = {"generated_at": now, "sections": [], "errors": {}}

    def section(name: str, fn):
        try:
            fn()
            summary["sections"].append(name)
            print(f"  ok  {name}", flush=True)
        except Exception as exc:  # fail-soft: one section never blocks the rest
            summary["errors"][name] = f"{type(exc).__name__}: {exc}"
            print(f"FAIL  {name}: {exc}", file=sys.stderr, flush=True)

    # Shared inputs, computed ONCE (this is the ~3s the Flask routes paid
    # per request).
    try:
        c = corpus.build(preset=league_preset())
        proj = projections.project_players(c)
    except Exception as exc:
        summary["errors"]["corpus"] = f"{type(exc).__name__}: {exc}"
        print(f"FAIL corpus: {exc}", file=sys.stderr)
        return summary

    evaluation: dict = {}

    def _dashboard():
        nonlocal evaluation
        ev = model.train_and_evaluate(EVAL_TRAIN_SEASONS, EVAL_TEST_SEASONS)
        cv = model.time_series_cv(PBP_SEASONS)
        evaluation = {"evaluation": ev, "cv": cv}
        write_json(out / "dashboard.json", {
            "generated_at": now,
            "season": SCHEDULE_SEASON,
            "stats_season": STATS_SEASON,
            "projections": records(proj.head(15)),
            "backtest": {
                "model_no_spread": ev["model_no_spread"],
                "model_with_spread": ev["model_with_spread"],
                "vegas": ev["vegas_baseline_accuracy"],
                "n_test": ev["n_test"],
                "cv_mean": cv["mean_accuracy"],
                "cv_folds": cv["folds"],
            },
        })

    def _modelcard():
        if not evaluation:
            raise RuntimeError("dashboard section did not produce the evaluation")
        write_json(out / "modelcard.json", {"generated_at": now, **_jsonable(evaluation)})

    def _players():
        write_json(out / "players.json", {
            "generated_at": now,
            "players": records(proj),
            "positions": ["QB", "RB", "WR", "TE"],
        })
        hist = c["weekly_history"]
        proj_by_id = {r["player_id"]: r for r in records(proj)}
        pdir = out / "players"
        pdir.mkdir(parents=True, exist_ok=True)
        for pid, ph in hist.groupby("player_id"):
            agg = (
                ph.groupby("season")
                .agg(games=("week", "nunique"), ppg=("fantasy_points", "mean"))
                .round(2).reset_index()
            )
            write_json(pdir / f"{pid}.json", {
                "generated_at": now,
                "pid": pid,
                "name": ph["player_display_name"].iloc[0],
                "pos": ph["position"].iloc[0],
                "history": records(agg),
                "projection": proj_by_id.get(pid),
            })

    def _predictions():
        # The served model must reflect the latest published data. The nightly
        # producer is the ONLY place that trains offline; the web never trains.
        # Re-fitting is ~1s over 1,231 rows, so do it on every artifact build
        # rather than trusting an artifact whose data may be a week old.
        model.train_and_persist()
        preds = model.predict_2026(week=None)
        write_json(out / "predictions.json", {
            "generated_at": now,
            "season": SCHEDULE_SEASON,
            "weeks": list(range(1, 19)),
            "predictions": records(preds),
        })

    def _ratings():
        table: dict = {}
        for season in seasons_all():
            for week in range(1, 19):
                rt = features.team_ratings_asof(season, week, refresh=False)
                if rt is None or rt.empty:
                    table[f"{season}-{week}"] = []
                else:
                    rt = rt.sort_values("off_epa_per_play", ascending=False)
                    table[f"{season}-{week}"] = records(rt.fillna(0).round(3))
        write_json(out / "ratings.json", {
            "generated_at": now, "seasons": seasons_all(), "ratings": table,
        })

    def _strategy():
        table: dict = {}
        for season in seasons_all():
            pbp = ingest.load_pbp(season)
            teams = sorted(pbp["posteam"].dropna().unique())
            table[str(season)] = {t: features.strategy_breakdown(pbp, t) for t in teams}
        write_json(out / "strategy.json", {
            "generated_at": now, "seasons": seasons_all(), "strategy": table,
        })

    def _sos():
        write_json(out / "sos.json", {
            "generated_at": now, "sos": records(analysis.sos_ranking(c)),
        })

    section("dashboard", _dashboard)
    section("modelcard", _modelcard)
    section("players", _players)
    section("predictions", _predictions)
    section("ratings", _ratings)
    section("strategy", _strategy)
    section("sos", _sos)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "data" / "web"),
                        help="artifact directory (default: data/web)")
    args = parser.parse_args()
    print(f"building prediction-engine artifacts -> {args.out}", flush=True)
    summary = build_all(Path(args.out))
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())