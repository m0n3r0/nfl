"""Local web UI for the fantasy football + win-prediction toolkit.

Server-rendered (Jinja) so it runs with no build step:

    python web/app.py            # http://127.0.0.1:5000
    python cli.py web            # same, via the CLI

Pages:
  /            dashboard (2026 projections top + model backtest summary)
  /players     searchable player list with 2022-2025 stats + 2026 projection
  /player/<id> single player detail (history + projection)
  /predictions 2026 win probabilities by week
  /sos        2026 strength-of-schedule ranking
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, render_template, request, jsonify

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from src import corpus, projections, analysis, model, ingest  # noqa: E402
from src.config import SCHEDULE_SEASON, STATS_SEASON  # noqa: E402

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))


def _get_corpus(preset="ppr"):
    return corpus.build(preset=preset)


@app.route("/")
def dashboard():
    c = _get_corpus()
    proj = projections.project_players(c, preset="ppr").head(15)
    backtest = model.train_and_backtest()
    return render_template(
        "dashboard.html",
        season=SCHEDULE_SEASON, stats_season=STATS_SEASON,
        projections=proj.to_dict("records"),
        backtest={
            "model_accuracy": round(backtest["model_accuracy"], 4) if backtest["model_accuracy"] else None,
            "model_logloss": round(backtest["model_logloss"], 4) if backtest["model_logloss"] else None,
            "vegas": backtest["vegas_baseline_accuracy"],
            "n_test": backtest["n_test"],
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
    # per-season totals
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


@app.route("/api/predictions")
def api_predictions():
    week = request.args.get("week", type=int)
    return jsonify(model.predict_2026(week=week).to_dict("records"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=False)
