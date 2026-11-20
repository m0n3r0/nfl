#!/usr/bin/env python3
"""Live fantasy points poller — ESPN raw stats under exact Yahoo weights.

Architecture (zero Yahoo live calls — WAF-safe):
  ESPN scoreboard (free, no auth) -> live game ids -> per-game summary
  -> src/live_scoring.compute_game with data/league-scoring.json (the
  authoritative Yahoo settings) -> logs/live-points.json (atomic write).
  nfl-webd watches that file and pushes updates to browsers over WebSocket.

Accuracy contract: points must match Yahoo. The engine is validated 15/15
against Yahoo's week-10 finals (tests/test_live_scoring.py). At runtime we
reconcile against the Yahoo light-cron snapshot: when that snapshot is
fresh (<= 3 min old) and a team total differs by > 0.5, the artifact gets
drift=true and the web falls back to Yahoo's verified numbers.

Modes:
  --once          one pass over the current week (live + recent finals)
  --week N        compute a finished week (backtest / re-verification)
  --loop          daemon: ~30s cadence during games, sleeps between windows
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from src.live_scoring import (  # noqa: E402
    SCORING_PATH, compute_game, def_key_for, load_scoring, norm_name,
    parse_game,
)

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
ARTIFACT = ROOT / "logs" / "live-points.json"
AUDIT = ROOT / "logs" / "live-points-audit.jsonl"
LEAGUE_REPORT = ROOT / "logs" / "league-report.json"
UA = {"User-Agent": "Mozilla/5.0 (nfl-live-points; personal fantasy tracker)"}
DRIFT_TOLERANCE = 0.5
FRESH_SNAPSHOT_SECONDS = 180


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def scoreboard(week: int | None = None) -> dict:
    url = f"{ESPN}/scoreboard" + (f"?week={week}" if week else "")
    return fetch_json(url)


def event_meta(event: dict) -> dict:
    comp = event.get("competitions", [{}])[0]
    status = comp.get("status", {})
    teams = {}
    for side in comp.get("competitors", []):
        t = side.get("team", {})
        teams[t.get("abbreviation", "")] = {
            "display": t.get("displayName", ""),
            "score": side.get("score", "0"),
        }
    return {"id": event.get("id"), "name": event.get("name"),
            "date": event.get("date"),
            "state": status.get("type", {}).get("state", "pre"),
            "detail": status.get("type", {}).get("shortDetail", ""),
            "period": status.get("period", 0),
            "clock": status.get("displayClock", ""),
            "teams": teams}


def load_rosters() -> tuple[dict, str | None]:
    """Latest Yahoo-captured rosters (local artifact only, never live)."""
    try:
        report = json.loads(LEAGUE_REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    rosters = report.get("rosters") or {}
    my_name = (report.get("matchup") or {}).get("team")
    return rosters, my_name


def team_totals(rosters: dict, players: dict, defs: dict,
                game_teams: dict) -> tuple[dict, list, dict]:
    """Sum each fantasy team's STARTERS under the computed live points.

    Also resolves DEF entries to Yahoo roster names (def_named) so the
    browser can badge them without knowing ESPN team abbreviations.
    """
    totals, unmatched, def_named = {}, [], {}
    for team, roster in rosters.items():
        total = 0.0
        for p in roster:
            slot = str(p.get("slot", "")).upper()
            if slot in ("BN", "IR"):
                continue
            if str(p.get("position", "")).upper() == "DEF":
                key = None
                for teams in game_teams.values():
                    key = def_key_for(p.get("name", ""), p.get("team", ""), teams)
                    if key and key in defs:
                        break
                if key and key in defs:
                    total += defs[key]
                    def_named[p.get("name", "")] = defs[key]
                else:
                    unmatched.append({"team": team, "name": p.get("name"),
                                      "reason": "DEF game not found"})
                continue
            entry = players.get(norm_name(p.get("name", "")))
            if entry:
                total += entry["points"]
            else:
                unmatched.append({"team": team, "name": p.get("name"),
                                  "reason": "no ESPN match (bye/DNP/name?)"})
        totals[team] = round(total, 2)
    return totals, unmatched, def_named


def reconcile(totals: dict) -> dict:
    """Compare against Yahoo's own live totals from the light-cron snapshot.

    Only a FRESH snapshot can prove drift — an old one legitimately trails
    live scoring. Final-state accuracy is additionally frozen by the
    week-10 golden test (15/15 exact).
    """
    out = {"yahoo_captured_at": None, "age_seconds": None,
           "comparisons": [], "drift": False, "note": "no Yahoo snapshot"}
    try:
        report = json.loads(LEAGUE_REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    captured = report.get("captured_at")
    board = report.get("scoreboard") or []
    if not captured or not board:
        return out
    try:
        ts = datetime.fromisoformat(str(captured).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
    except ValueError:
        age = None
    out["yahoo_captured_at"] = captured
    out["age_seconds"] = round(age) if age is not None else None
    fresh = age is not None and age <= FRESH_SNAPSHOT_SECONDS
    for e in board:
        for side, score in (("team1", "score1"), ("team2", "score2")):
            name = e.get(side)
            if not name or name not in totals:
                continue
            try:
                yahoo = float(e.get(score))
            except (TypeError, ValueError):
                continue
            ours = totals[name]
            delta = round(ours - yahoo, 2)
            out["comparisons"].append(
                {"team": name, "yahoo": yahoo, "ours": ours, "delta": delta})
            if fresh and abs(delta) > DRIFT_TOLERANCE:
                out["drift"] = True
    out["note"] = ("fresh snapshot — drift check active" if fresh
                   else "snapshot stale — deltas informational only")
    return out


def compute_week(week: int | None = None) -> dict:
    board = scoreboard(week)
    events = [event_meta(e) for e in board.get("events", [])]
    wk = (board.get("week") or {}).get("number") or week
    scoring = load_scoring()
    players: dict[str, dict] = {}
    defs: dict[str, float] = {}
    game_teams: dict[str, dict] = {}
    games: dict[str, dict] = {}
    for meta in events:
        games[meta["id"]] = meta
        if meta["state"] not in ("in", "post"):
            continue  # scheduled: no stats yet
        try:
            summary = fetch_json(f"{ESPN}/summary?event={meta['id']}")
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"warning: summary {meta['id']} failed: {exc}", file=sys.stderr)
            meta["error"] = str(exc)
            continue
        parsed = parse_game(summary)
        game_teams[meta["id"]] = parsed["teams"]
        for key, pts in compute_game(summary, scoring).items():
            if key.startswith("DEF:"):
                defs[key] = pts
            else:
                p = parsed["players"].get(key, {})
                players[key] = {"display": p.get("display", key),
                                "team": p.get("team", ""),
                                "points": pts, "game_id": meta["id"],
                                "state": meta["state"]}
        time.sleep(0.3)  # be a polite client even on a public API
    rosters, my_name = load_rosters()
    totals, unmatched, def_named = team_totals(rosters, players, defs, game_teams)
    recon = reconcile(totals)
    artifact = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "week": wk, "source": "espn",
        "scoring_sha": hashlib.sha256(
            SCORING_PATH.read_bytes()).hexdigest()[:16],
        "my_team": my_name,
        "games": games, "players": players, "def": defs,
        "def_named": def_named,
        "totals": totals, "unmatched": unmatched,
        "reconciliation": recon,
    }
    return artifact


def write_artifact(artifact: dict, path: Path = ARTIFACT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(artifact, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    if artifact["reconciliation"]["comparisons"]:
        with AUDIT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "time": artifact["captured_at"],
                "drift": artifact["reconciliation"]["drift"],
                "comparisons": artifact["reconciliation"]["comparisons"],
            }) + "\n")


def _next_window(events: list[dict]) -> float:
    """Seconds until the next scheduled kickoff (capped for safety)."""
    now = datetime.now(timezone.utc)
    starts = []
    for e in events:
        try:
            ts = datetime.fromisoformat(str(e["date"]).replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if ts > now and e["state"] == "pre":
            starts.append((ts - now).total_seconds())
    if not starts:
        return 900.0
    return max(60.0, min(min(starts) - 120.0, 900.0))


def loop() -> int:
    print("live-points loop started (ESPN -> Yahoo-weighted points)", flush=True)
    while True:
        try:
            artifact = compute_week()
            write_artifact(artifact)
            live = [g for g in artifact["games"].values() if g["state"] == "in"]
            if live:
                print(f"{artifact['captured_at']} live={len(live)} "
                      f"drift={artifact['reconciliation']['drift']}", flush=True)
                time.sleep(30)
            else:
                delay = _next_window(list(artifact["games"].values()))
                print(f"{artifact['captured_at']} no live games; "
                      f"sleep {delay:.0f}s", flush=True)
                time.sleep(delay)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001 - daemon must survive
            print(f"warning: cycle failed: {exc}", file=sys.stderr, flush=True)
            time.sleep(60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--week", type=int)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--out", default=str(ARTIFACT))
    args = parser.parse_args()
    if args.loop:
        return loop()
    artifact = compute_week(args.week)
    write_artifact(artifact, Path(args.out))
    print(json.dumps({k: artifact[k] for k in
                      ("captured_at", "week", "scoring_sha")}, indent=2))
    print(f"players={len(artifact['players'])} teams={len(artifact['totals'])} "
          f"drift={artifact['reconciliation']['drift']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
