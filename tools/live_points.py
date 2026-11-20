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
  --loop          daemon: ~10s cadence during games, sleeps between windows

Politeness (free API — don't spam):
  * one scoreboard request per cycle (ESPN caches it ~8s)
  * a game's summary is re-fetched ONLY when its scoreboard signature
    changed (period, clock, scores, situation.lastPlay.id) — a new play is
    the only thing that can change a boxscore; stopped clocks cost nothing
  * a forced full sweep every 6th cycle (~60s) catches stat corrections
  * >= 0.25s between requests, +/-10% jitter on the cycle sleep
  * final games are fetched once, then served from cache
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
POLL_SECONDS = 10.0      # cycle during live games (ESPN UI polls similarly)
MIN_POLL_SECONDS = 5.0   # floor: faster than this is spam, not freshness
REQUEST_GAP = 0.25       # min seconds between any two HTTP requests
SWEEP_EVERY = 6          # force-refresh all games every N cycles (~60s)


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
            "home": side.get("homeAway") == "home",
        }
    last_play = (comp.get("situation") or {}).get("lastPlay") or {}
    return {"id": event.get("id"), "name": event.get("name"),
            "date": event.get("date"),
            "state": status.get("type", {}).get("state", "pre"),
            "detail": status.get("type", {}).get("shortDetail", ""),
            "period": status.get("period", 0),
            "clock": status.get("displayClock", ""),
            "clock_seconds": status.get("clock"),
            "last_play_id": last_play.get("id"),
            "teams": teams}


def game_signature(meta: dict) -> tuple:
    """Everything that can signal a boxscore change, from the scoreboard.

    A new play (lastPlay.id), a scoring change, or the clock/period moving
    are the only ways stats change; identical signature -> identical
    boxscore (modulo rare corrections, covered by the periodic sweep).
    """
    scores = tuple(sorted((a, t.get("score")) for a, t in meta["teams"].items()))
    return (meta.get("period"), meta.get("clock_seconds"), scores,
            meta.get("last_play_id"))


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


def compute_week(week: int | None = None, cache: dict | None = None,
                 force: bool = False) -> dict:
    board = scoreboard(week)
    events = [event_meta(e) for e in board.get("events", [])]
    wk = (board.get("week") or {}).get("number") or week
    scoring = load_scoring()
    cache = cache if cache is not None else {}
    sigs = cache.setdefault("sigs", {})
    gdata = cache.setdefault("gdata", {})
    players: dict[str, dict] = {}
    defs: dict[str, float] = {}
    game_teams: dict[str, dict] = {}
    games: dict[str, dict] = {}
    fresh = cached = 0
    for meta in events:
        eid = meta["id"]
        games[eid] = meta
        if meta["state"] not in ("in", "post"):
            continue  # scheduled: no stats yet
        sig = game_signature(meta)
        entry = gdata.get(eid)
        if not force and entry is not None and sigs.get(eid) == sig:
            cached += 1
            meta["fetch"] = "cached"
        else:
            try:
                summary = fetch_json(f"{ESPN}/summary?event={eid}")
                parsed = parse_game(summary)
                entry = {"points": compute_game(summary, scoring),
                         "players": parsed["players"], "teams": parsed["teams"]}
                gdata[eid] = entry
                sigs[eid] = sig
                fresh += 1
                meta["fetch"] = "fresh"
                time.sleep(REQUEST_GAP)  # stagger; never burst the free API
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                print(f"warning: summary {eid} failed: {exc}", file=sys.stderr)
                meta["error"] = str(exc)
                if entry is None:
                    continue
                cached += 1
                meta["fetch"] = "stale"  # serve the last good data
        game_teams[eid] = entry["teams"]
        for key, pts in entry["points"].items():
            if key.startswith("DEF:"):
                defs[key] = pts
            else:
                p = entry["players"].get(key, {})
                players[key] = {"display": p.get("display", key),
                                "team": p.get("team", ""),
                                "points": pts, "game_id": eid,
                                "state": meta["state"]}
    # prune caches for games no longer on the board (week rollover)
    live_ids = set(games)
    for store in (sigs, gdata):
        for eid in list(store):
            if eid not in live_ids:
                del store[eid]
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
        "fetch_stats": {"fresh": fresh, "cached": cached},
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


def archive_if_final(artifact: dict, dirpath: Path = ROOT / "logs") -> Path | None:
    """Persist a completed week's points to logs/live-points-week-<N>.json.

    live-points.json itself is overwritten every cycle; this archive is the
    permanent per-player record once every game of the week is final.
    Re-written only when the stable content changes (late stat corrections).
    """
    games = artifact.get("games") or {}
    week = artifact.get("week")
    if not games or not week:
        return None
    if not all(g.get("state") == "post" for g in games.values()):
        return None
    path = dirpath / f"live-points-week-{week}.json"
    payload = {k: artifact.get(k) for k in
               ("week", "players", "def", "def_named", "totals", "games",
                "scoring_sha")}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if all(existing.get(k) == v for k, v in payload.items()):
            return path  # unchanged — don't touch the archive
    except (OSError, ValueError):
        pass
    payload["archived_at"] = datetime.now(timezone.utc).isoformat()
    dirpath.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    print(f"archived week {week} finals -> {path.name}", flush=True)
    return path


def clamp_interval(seconds: float) -> float:
    """Freshness floor: faster than MIN_POLL_SECONDS is spam, not signal."""
    return max(MIN_POLL_SECONDS, float(seconds))


def loop(interval: float = POLL_SECONDS) -> int:
    import random
    interval = clamp_interval(interval)
    cache: dict = {}
    cycle = 0
    print(f"live-points loop started (ESPN -> Yahoo-weighted points, "
          f"{interval:.0f}s cadence, change-gated fetches)", flush=True)
    while True:
        try:
            force = cycle % SWEEP_EVERY == 0  # periodic correction sweep
            artifact = compute_week(cache=cache, force=force)
            write_artifact(artifact)
            archive_if_final(artifact)
            live = [g for g in artifact["games"].values() if g["state"] == "in"]
            cycle += 1
            if live:
                fs = artifact["fetch_stats"]
                print(f"{artifact['captured_at']} live={len(live)} "
                      f"fresh={fs['fresh']} cached={fs['cached']} "
                      f"drift={artifact['reconciliation']['drift']}", flush=True)
                time.sleep(interval * random.uniform(0.9, 1.1))
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
    parser.add_argument("--interval", type=float, default=POLL_SECONDS,
                        help=f"live-game cycle seconds (floor {MIN_POLL_SECONDS:.0f})")
    parser.add_argument("--out", default=str(ARTIFACT))
    args = parser.parse_args()
    if args.loop:
        return loop(args.interval)
    artifact = compute_week(args.week)
    write_artifact(artifact, Path(args.out))
    archive_if_final(artifact)
    print(json.dumps({k: artifact[k] for k in
                      ("captured_at", "week", "scoring_sha")}, indent=2))
    print(f"players={len(artifact['players'])} teams={len(artifact['totals'])} "
          f"drift={artifact['reconciliation']['drift']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
