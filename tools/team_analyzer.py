#!/usr/bin/env python3
"""Manual team analyzer: is my team doing well, and what needs doing?

Read-only. Pulls every league roster live, maps them to the model's
projections, compares optimal-lineup strength across the league, flags
alerts (locks, injuries, bye concentration, dead spots), and prints a
ranked recommendation list. Run it anytime:

    python tools/team_analyzer.py            # human-readable report
    python tools/team_analyzer.py --json     # machine-readable
    python tools/team_analyzer.py --no-wire  # skip the (slow) wire scan
    python tools/team_analyzer.py --light    # gentle: my roster + standings +
                                             # matchup only (no league pulls)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from src import corpus as corpus_mod, projections  # noqa: E402
from src.config import league_preset  # noqa: E402
from yahoo import league_strength as ls  # noqa: E402
from yahoo.browser import BrowserError  # noqa: E402
from yahoo.cdp import CdpClient, CdpError, list_targets  # noqa: E402
from yahoo.identity import TEAM_ALIASES  # noqa: E402
from yahoo.league import LeagueWafBlocked, matchup, opponent_roster, standings  # noqa: E402
from yahoo.recommend import monitor_report, propose_lineup  # noqa: E402
from yahoo.team import TEAM_PATH, YahooTeamReader  # noqa: E402
from yahoo.wire import WireScanBlocked, rank_targets, scan_available  # noqa: E402

import preflight as preflight_mod  # noqa: E402  # tools/preflight.py

BASE = "https://football.fantasysports.yahoo.com"
MY_TEAM_ID = "2"
LEAGUE_TEAM_IDS = [str(i) for i in range(1, 11)]


def _league_tab(endpoint: str):
    tabs = [t for t in list_targets(endpoint)
            if t.type == "page" and "/f1/" in (t.url or "")
            and "draftanalysis" not in (t.url or "")]
    if not tabs:
        raise RuntimeError("no Yahoo fantasy tab found; open the league page first")
    return tabs[0]


def _wait_render(client, marker: str, attempts: int = 20) -> None:
    for _ in range(attempts):
        if client.evaluate(
                f"document.body && document.body.innerText.includes({json.dumps(marker)})"):
            return
        time.sleep(1)
    raise RuntimeError(f"page never rendered marker {marker!r}")


def analyze(endpoint: str, with_wire: bool, light: bool = False) -> dict:
    try:
        health = preflight_mod.preflight(endpoint=endpoint)
    except (BrowserError, CdpError) as exc:
        return {"status": "preflight_failed", "error": str(exc)}
    if health.get("waf_blocked"):
        return {"status": "waf_blocked", "preflight": health}
    if not (health.get("cdp") and health.get("team_tab") and health.get("auth")):
        return {"status": "preflight_failed", "preflight": health}

    corp = corpus_mod.build(preset=league_preset())

    with CdpClient(_league_tab(endpoint), endpoint, timeout=30) as client:
        waf_blocked_run = False
        wire_targets = []
        wire_blocked = False
        try:
            client.navigate(f"{BASE}{TEAM_PATH}",
                            lambda u: u.rstrip("/").endswith(TEAM_PATH), 25)
            _wait_render(client, "Shiba Innu")
            snapshot = YahooTeamReader(client).snapshot()  # must precede any navigation
            week = snapshot.week  # Yahoo's week, not the schedule's (they diverge Mon-Tue)
            weekly = projections.project_for_week(corp, week)
            rows = standings(client)
            rosters = {MY_TEAM_ID: [{"name": p.name, "team": p.team, "position": p.position,
                                     "slot": p.slot, "injury_status": p.injury_status}
                                    for p in snapshot.roster]}
            if not light:
                for tid in LEAGUE_TEAM_IDS:
                    if tid == MY_TEAM_ID:
                        continue
                    try:
                        rosters[tid] = list(opponent_roster(client, tid))
                    except LeagueWafBlocked:
                        raise  # abort the run; never keep pulling into a WAF block
                    except Exception as exc:  # one unreadable team must not kill the report
                        rosters[tid] = []
                        print(f"warning: team {tid} roster read failed: {exc}", file=sys.stderr)
                    time.sleep(1.0)  # stay polite with Yahoo's WAF
            my_matchup = matchup(client)
            if with_wire and not light:
                try:
                    available = scan_available(client, week)
                    wire_targets, _ = rank_targets(available, weekly)
                except WireScanBlocked as exc:
                    wire_blocked = True
                    print(f"warning: {exc}; continuing without wire targets", file=sys.stderr)
        except LeagueWafBlocked as exc:
            waf_blocked_run = True
            return {"status": "waf_blocked", "error": str(exc)}
        finally:
            # After a WAF block even one navigation can extend the throttle;
            # the tab is restored by the next green run instead.
            if not (waf_blocked_run or wire_blocked):
                try:  # best-effort restore; never mask an earlier failure
                    client.navigate(f"{BASE}{TEAM_PATH}",
                                    lambda u: u.rstrip("/").endswith(TEAM_PATH), 25)
                except CdpError as exc:
                    print(f"warning: tab restore failed: {exc}", file=sys.stderr)

    season = projections.project_players(corp)

    if light:  # no league pulls happened; league-wide sections stay empty
        teams_missing = []
        strength = None
        ranks = []
        my_season = ls.evaluate_roster(rosters[MY_TEAM_ID], season, "proj_total", 2000)
    else:
        teams_missing = [tid for tid, roster in rosters.items() if not roster]
        league_eval = {tid: ls.evaluate_roster(roster, season, "proj_total", 1000 * int(tid))
                       for tid, roster in rosters.items() if roster}
        scores = {tid: ls.optimal_score(players) for tid, players in league_eval.items()}
        ordered = sorted(scores.values(), reverse=True)
        my_rank = sorted(scores, key=lambda t: -scores[t]).index(MY_TEAM_ID) + 1
        strength = {"rank": my_rank, "of": len(scores), "score": scores[MY_TEAM_ID],
                    "leader": ordered[0] if ordered else None,
                    "playoff_line": ordered[3] if len(ordered) >= 4 else None}
        my_season = league_eval[MY_TEAM_ID]
        ranks = ls.position_ranks(league_eval, MY_TEAM_ID)
    my_week = ls.evaluate_roster(rosters[MY_TEAM_ID], weekly, "proj_week", 500000)
    byes = ls.bye_weeks(corp["schedule_2026"])
    concentration = ls.bye_concentration(my_season, byes, TEAM_ALIASES)

    proposal = propose_lineup(snapshot, weekly, week)
    moves = tuple(f"{p.name}: {p.current_slot} -> {p.proposed_slot}"
                  for p in proposal.plan if p.current_slot != p.proposed_slot)
    monitor = monitor_report(snapshot, weekly, week)

    alerts = []
    if wire_blocked:
        alerts.append("Yahoo served 'Request denied' during the wire scan — "
                      "waiver recommendations skipped this run; retry later")
    if monitor["locked_starters"]:
        alerts.append("locked starters: " + ", ".join(monitor["locked_starters"]))
    alerts += [f"injury: {tag}" for tag in monitor["injury_tags"]]
    alerts += [f"unevaluated: {name}" for name in monitor["unevaluated"]]
    if proposal.warnings:
        alerts += list(proposal.warnings)

    recs = ls.recommendations(
        my_eval=my_season, week_eval=my_week, lineup_moves=moves,
        wire_targets=wire_targets[:10], ranks=ranks,
        concentration=concentration,
        season_strength=(strength["rank"], strength["of"], strength["score"])
        if strength else (0, 0, 0.0))
    if light:  # league-wide rules have no input data in light mode
        recs = [r for r in recs if r["kind"] not in {"weak_slot", "waiver", "standing"}]

    return {
        "status": "ok", "mode": "light" if light else "full",
        "date": date.today().isoformat(), "week": week,
        "matchup": my_matchup.as_dict(),
        "standings": [{"rank": r.rank, "team": r.team, "record": r.record} for r in rows],
        "teams_missing": teams_missing,
        "season_strength": strength,
        "position_ranks": ranks,
        "bye_concentration": {str(k): v for k, v in concentration.items()},
        "alerts": alerts,
        "recommendations": recs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    parser.add_argument("--no-wire", action="store_true",
                        help="skip the wire scan (faster, no waiver recommendations)")
    parser.add_argument("--light", action="store_true",
                        help="gentle mode: my roster + standings + matchup only "
                             "(no league roster pulls, no wire scan)")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9222")
    args = parser.parse_args()

    report = analyze(args.endpoint, with_wire=not args.no_wire, light=args.light)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report.get("status") == "ok":
        print(ls.render_report(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
