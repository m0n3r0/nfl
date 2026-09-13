"""Local web UI for the fantasy football + win-prediction toolkit.

Server-rendered (Jinja) so it runs with no build step:

    python web/app.py            # http://127.0.0.1:5000
    python cli.py web            # same, via the CLI

Pages:
  /            dashboard (2026 projections + model card)
  /team        my FD nation team (latest operator report: matchup, lineup, flags)
  /league      league standings + matchup (how the other teams are doing)
  /league/team/<name>  one team's standing, trajectory, and roster when captured
  /cron        operator/cron status (run history + schedule)
  /players     searchable player list with 2022-2026 stats + 2026 projection
  /player/<id> single player detail (history + projection)
  /predictions 2026 win probabilities by week
  /sos        2026 strength-of-schedule ranking
  /ratings     2026 team efficiency ratings (as-of season, per-play EPA etc.)
  /strategy     game-strategy situation splits for a team (3rd down, red zone, pass/run)

The fantasy pages read LOCAL artifacts only (logs/team-operator.jsonl,
logs/league-report.json, logs/league-report.jsonl — written by the cron
operators). The web process never touches Yahoo live — live reads belong to
the gentle, WAF-aware cron jobs.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from flask import Flask, render_template, request, jsonify

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from src import corpus, projections, analysis, model, ingest, features  # noqa: E402
from src.config import SCHEDULE_SEASON, STATS_SEASON, PBP_SEASONS, league_preset  # noqa: E402

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))

OPERATOR_AUDIT = ROOT / "logs" / "team-operator.jsonl"
LEAGUE_REPORT = ROOT / "logs" / "league-report.json"
LEAGUE_AUDIT = ROOT / "logs" / "league-report.jsonl"

# The host crontab (docs/TEAM_OPERATOR.md is the authoritative runbook).
CRON_SCHEDULE = [
    ("24 8,20 * * *", "twice daily 08:24 / 20:24", "team_operator.py — monitor + report"),
    ("47 23 * * 0", "Sun 23:47", "team_operator.py --apply — lineup safety net"),
    ("23 1 * * 1", "Mon 01:23", "team_operator.py --apply — final pre-kickoff set"),
    ("11 20 * * 3", "Wed 20:11", "team_operator.py --waiver-scan --refresh-data"),
    ("19 21 * * *", "nightly 21:19", "league_report.py --opponent-roster --out --audit — league snapshot"),
    ("37 9 * * 0", "Sun 09:37", "profile_backup.py — browser-profile backup"),
]


def _read_operator_runs(limit: int = 30, path: Path | None = None) -> list[dict]:
    """Parse the operator audit log, newest first; non-dict/broken lines skipped."""
    path = path or OPERATOR_AUDIT
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    runs = []
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        proposal = record.get("proposal")
        if isinstance(proposal, dict):
            # Normalize at the artifact boundary so templates never see a
            # non-list moves/plan (a corrupted record must not 500 the page).
            if not isinstance(proposal.get("moves"), list):
                proposal["moves"] = []
            if not isinstance(proposal.get("plan"), (list, type(None))):
                proposal["plan"] = None
        runs.append(record)
        if len(runs) >= limit:
            break
    return runs


def _read_league_report(path: Path | None = None) -> dict | None:
    """Return the latest persisted league snapshot, or None when absent/invalid."""
    path = path or LEAGUE_REPORT
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def _read_league_history(path: Path | None = None) -> list[dict]:
    """Return the season's nightly league snapshots, oldest first."""
    path = path or LEAGUE_AUDIT
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    snaps = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            snaps.append(record)
    return snaps


def _team_row(standings, team_name: str) -> dict | None:
    """Find one team's row in a standings list (exact name match).

    Numeric fields are coerced to floats at this boundary so templates can
    do arithmetic without trusting the artifact's types.
    """
    if not isinstance(standings, list):
        return None
    row = next((r for r in standings
                if isinstance(r, dict) and r.get("team") == team_name), None)
    if row is None:
        return None

    def num(key: str) -> float:
        try:
            value = float(row.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    return {**row, "points_for": num("points_for"),
            "points_against": num("points_against")}


def _record_games(record: str) -> int:
    """Games played from a 'W-L-T' record string (0 when unparseable)."""
    try:
        return sum(int(part) for part in str(record).split("-")[:3])
    except ValueError:
        return 0


def _get_corpus(preset=None):
    return corpus.build(preset=preset or league_preset())


@app.route("/")
def dashboard():
    c = _get_corpus()
    proj = projections.project_players(c).head(15)
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


@app.route("/team")
def my_team():
    """My FD nation team, from the newest operator audit record."""
    runs = _read_operator_runs(limit=200)  # deep window: the ok-fallback spans outages
    latest = runs[0] if runs else None
    latest_ok = next((r for r in runs if r.get("status") == "ok"), None)
    return render_template("team.html", latest=latest, report=latest_ok)


@app.route("/league")
def league():
    """League standings + current matchup (how the other teams are doing)."""
    report = _read_league_report()
    standings = report.get("standings") if report else None
    if not isinstance(standings, list):
        standings = None
    matchup = report.get("matchup") if report else None
    my_name = matchup.get("team") if isinstance(matchup, dict) else None
    return render_template("league.html", report=report, standings=standings,
                           my_name=my_name)


@app.route("/league/team/<path:team_name>")
def league_team(team_name):
    """Detail page for one league team: standing, trend, roster when captured."""
    latest = _read_league_report()
    row = _team_row(latest.get("standings") if latest else None, team_name)
    trend = []
    for snap in _read_league_history():
        mine = _team_row(snap.get("standings"), team_name)
        if mine:
            trend.append({**mine, "captured_at": str(snap.get("captured_at", ""))})
    matchup = latest.get("matchup") if latest else None
    is_opponent = isinstance(matchup, dict) and matchup.get("opponent") == team_name
    roster = latest.get("opponent_roster") if (latest and is_opponent) else None
    if row is None and not trend:
        return render_template("league_team.html", name=team_name, row=None,
                               trend=[], games=0, matchup=None, roster=None,
                               captured_at=None), 404
    games = _record_games(row.get("record", "")) if row else 0
    return render_template("league_team.html", name=team_name, row=row,
                           trend=trend, games=games,
                           matchup=matchup if is_opponent else None,
                           roster=roster if isinstance(roster, list) else None,
                           captured_at=latest.get("captured_at") if latest else None)


@app.route("/cron")
def cron_status():
    """Operator run history + the cron schedule that produces it."""
    return render_template("cron.html", runs=_read_operator_runs(limit=14),
                           schedule=CRON_SCHEDULE)


@app.route("/players")
def players():
    c = _get_corpus()
    proj = projections.project_players(c)
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
    proj = projections.project_players(c)
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
    # STATS_SEASON (2026) is already the last entry of PBP_SEASONS, so a plain
    # concatenation put 2026 in the dropdown twice. Dedupe + sort.
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
