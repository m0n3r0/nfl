"""Local web UI for the fantasy football + win-prediction toolkit.

Server-rendered (Jinja) so it runs with no build step:

    python web/app.py            # http://127.0.0.1:5000
    python cli.py web            # same, via the CLI

Pages:
  /            dashboard (2026 projections + model card)
  /players     searchable player list with 2022-2025 stats + 2026 projection
  /player/<id> single player detail (history + projection)
  /predictions 2026 win probabilities by week
  /sos        2026 strength-of-schedule ranking
  /ratings     2025 team efficiency ratings (as-of season, per-play EPA etc.)
  /strategy     game-strategy situation splits for a team (3rd down, red zone, pass/run)
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, render_template, request, jsonify

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from src import corpus, projections, analysis, model, ingest, features  # noqa: E402
from src.config import SCHEDULE_SEASON, STATS_SEASON, PBP_SEASONS  # noqa: E402

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))


def _get_corpus(preset="ppr"):
    return corpus.build(preset=preset)


@app.route("/")
def dashboard():
    c = _get_corpus()
    proj = projections.project_players(c, preset="ppr").head(15)
    # Real, honest model evaluation (computed once per request; cached on disk by features).
    ev = model.train_and_evaluate((2022, 2023), (2024, 2025))
    cv = model.time_series_cv(PBP_SEASONS)
    return render_template(
        "dashboard.html",
        season=SCHEDULE_SEASON, stats_season=STATS_SEASON,
        projections=proj.to_dict("records"),
        backtest={
            "model_no_spread": ev["model_no_spread"],
            "model_with_spread": ev["model_with_spread"],
            "vegas": ev["vegas_baseline_accuracy"],
            "n_test": ev["n_test"],
            "cv_mean": cv["mean_accuracy"],
            "cv_folds": cv["folds"],
        },
    )


@app.route("/players")
def players():
    c = _get_corpus()
    proj = projections.project_players(c, preset="ppr")
    q = request.args.get("q", "").strip().upper()
    pos = request.args.get("pos", "").strip().upper()
    if q:
        proj = proj[proj["player_display_name"].str.upper().str.contains(q)]
    if pos:
        proj = proj[proj["position"] == pos]
    return render_template(
        "players.html", players=proj.head(200).to_dict("records"),
        q=q, pos=pos, positions=["QB", "RB", "WR", "TE"],
    )


@app.route("/player/<pid>")
def player_detail(pid):
    c = _get_corpus()
    hist = c["weekly_history"]
    ph = hist[hist["player_id"] == pid]
    if ph.empty:
        return "player not found", 404
    name = ph["player_display_name"].iloc[0]
    pos = ph["position"].iloc[0]
    season_agg = (
        ph.groupby("season")
        .agg(games=("week", "nunique"), ppg=("fantasy_points", "mean"))
        .round(2).reset_index()
    )
    proj = projections.project_players(c, preset="ppr")
    row = proj[proj["player_id"] == pid]
    proj_row = row.to_dict("records")[0] if len(row) else None
    return render_template(
        "player.html", name=name, pos=pos, pid=pid,
        history=season_agg.to_dict("records"), projection=proj_row,
    )


@app.route("/predictions")
def predictions():
    week = request.args.get("week", type=int)
    preds = model.predict_2026(week=week)
    weeks = list(range(1, 19))
    return render_template(
        "predictions.html", predictions=preds.to_dict("records"),
        week=week, weeks=weeks, season=SCHEDULE_SEASON,
    )


@app.route("/sos")
def sos():
    c = _get_corpus()
    s = analysis.sos_ranking(c)
    return render_template("sos.html", sos=s.to_dict("records"))


@app.route("/ratings")
def ratings():
    season = request.args.get("season", default=STATS_SEASON, type=int)
    week = request.args.get("week", default=1, type=int)
    # STATS_SEASON (2025) is already the last entry of PBP_SEASONS, so a plain
    # concatenation put 2025 in the dropdown twice. Dedupe + sort.
    seasons = sorted(set(list(PBP_SEASONS) + [STATS_SEASON]))
    rt = features.team_ratings_asof(season, week, refresh=False)
    if rt is None or rt.empty:
        # Week 1 of the earliest PBP season has no strictly-prior season to build
        # a prior from. team_ratings_asof() returns empty instead of reaching
        # forward into the future, so explain it rather than returning a 500.
        return render_template(
            "ratings.html", ratings=[], season=season, week=week, seasons=seasons,
            notice=(f"No ratings for {season} week {week}: week 1 needs play-by-play "
                    f"from a season before {season}, and {min(PBP_SEASONS)} is the "
                    f"earliest available."),
        )
    rt = rt.sort_values("off_epa_per_play", ascending=False)
    return render_template(
        "ratings.html",
        ratings=rt.fillna(0).round(3).to_dict("records"),
        season=season, week=week, seasons=seasons, notice=None,
    )


@app.route("/strategy")
def strategy():
    team = request.args.get("team", "BUF").upper()
    season = request.args.get("season", default=STATS_SEASON, type=int)
    pbp = ingest.load_pbp(season)
    bd = features.strategy_breakdown(pbp, team)
    return render_template("strategy.html", team=team, season=season, breakdown=bd)


@app.route("/api/predictions")
def api_predictions():
    week = request.args.get("week", type=int)
    return jsonify(model.predict_2026(week=week).to_dict("records"))


@app.route("/api/modelcard")
def api_modelcard():
    ev = model.train_and_evaluate((2022, 2023), (2024, 2025))
    cv = model.time_series_cv(PBP_SEASONS)
    return jsonify({"evaluation": ev, "cv": cv})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=False)
