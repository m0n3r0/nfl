"""Hermetic tests for the weekly lineup tool wrapper (tools/weekly_lineup.py)."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pandas as pd

import tools.weekly_lineup as wl
from yahoo.team import RosterPlayer, TeamSnapshot

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "BN", "BN", "BN", "BN", "BN", "BN", "K", "DEF"]
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "WR", "RB", "WR", "RB", "WR", "QB", "TE", "K", "DEF"]
NAMES = ["Qb One", "Rb One", "Rb Two", "Wr One", "Wr Two", "Te One", "Wr Three",
         "Rb Bench", "Wr Bench", "Rb Deep", "Wr Deep", "Qb Bench", "Te Bench", "K One", "Def One"]
SKILL = NAMES[:-2]  # K/DEF carry no projection rows


def snapshot(teams):
    roster = tuple(
        RosterPlayer(yahoo_id=str(i), name=name, team=teams[name], position=pos,
                     slot=slot, injury_status="", game="Sun 1:00 pm vs DEN", locked=False)
        for i, (name, pos, slot) in enumerate(zip(NAMES, POSITIONS, SLOTS), 1)
    )
    return TeamSnapshot(league_id="1329011", team_id="2", team_name="Shiba Innu",
                        record="0-0-0", week=6, opponent="Opponent", waiver_priority=4,
                        roster=roster)


def schedule(week, matchups, gameday="2099-10-18", gametime="13:00"):
    rows = []
    for home, away in matchups:
        for team, opponent, is_home in ((home, away, True), (away, home, False)):
            rows.append({"week": week, "team": team, "opponent": opponent, "home": is_home,
                         "game_id": f"2026_{week:02d}_{away}_{home}", "game_type": "REG",
                         "gameday": gameday, "gametime": gametime})
    return pd.DataFrame(rows)


def projection_frame(values, teams):
    """The exact shape project_for_week emits on this stack: no on_bye/injury_status."""
    rows = []
    for rank, (name, proj_week) in enumerate(values.items(), 1):
        rows.append({
            "rank": rank, "player_id": f"00-{rank:02d}", "player_display_name": name,
            "position": POSITIONS[NAMES.index(name)], "last_team": teams[name],
            "games": 16.0, "baseline_ppg": proj_week, "pos_mean": 8.0,
            "role_share": 0.6, "team_sos": 0.0, "expected_games": 16.0,
            "proj_ppg": proj_week, "proj_total": proj_week * 16,
            "draft_round": float("nan"), "is_rookie": False,
            "week_sos": 0.0, "proj_week": proj_week,
        })
    frame = pd.DataFrame(rows)
    assert "on_bye" not in frame.columns and "injury_status" not in frame.columns
    return frame


class FakeClient:
    def __init__(self, target, endpoint):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def run_tool(monkeypatch, tmp_path, snap, sched_df, proj_df):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(wl, "find_team_target", lambda endpoint: object())
    monkeypatch.setattr(wl, "CdpClient", FakeClient)
    monkeypatch.setattr(wl, "YahooTeamReader", lambda client: SimpleNamespace(snapshot=lambda: snap))
    monkeypatch.setattr(wl.corpus_mod, "build", lambda preset: {"schedule_2026": sched_df})
    monkeypatch.setattr(wl.projections, "project_for_week", lambda corp, week: proj_df)
    monkeypatch.setattr(wl, "AUDIT_LOG", audit)
    monkeypatch.setattr(sys, "argv", ["weekly_lineup.py", "--week", "6"])
    code = wl.main()
    return code, audit


def kc_teams(**overrides):
    teams = {name: "KC" for name in NAMES}
    teams.update(overrides)
    return teams


def test_byes_derived_from_schedule_bench_the_bye_starter(monkeypatch, tmp_path, capsys):
    teams = kc_teams(**{"Rb Two": "BUF"})  # BUF has no week-6 game -> on bye
    values = {name: 10.0 for name in SKILL}
    values["Rb Two"] = 16.0  # the bye starter out-projects everyone
    code, audit = run_tool(monkeypatch, tmp_path, snapshot(teams),
                           schedule(6, [("KC", "DEN")]), projection_frame(values, teams))

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "dry_run"
    plan = {p["name"]: p for p in report["plan"]}
    assert plan["Rb Two"]["proposed_slot"] == "BN"
    assert plan["Rb Two"]["note"] == "bye"
    moves = {(m["yahoo_id"], m["from_slot"], m["to_slot"]) for m in report["moves"]}
    assert ("3", "RB", "BN") in moves
    assert any("BYE" in w for w in report["warnings"])
    [record] = [json.loads(line) for line in audit.read_text().splitlines()]
    assert record["status"] == "dry_run"
    assert record["week"] == 6
    assert record["moves"] == report["moves"]


def test_dry_run_writes_audit_record_without_moves(monkeypatch, tmp_path, capsys):
    teams = kc_teams()
    values = {name: 10.0 for name in SKILL}
    code, audit = run_tool(monkeypatch, tmp_path, snapshot(teams),
                           schedule(6, [("KC", "DEN")]), projection_frame(values, teams))

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["moves"] == []
    [record] = [json.loads(line) for line in audit.read_text().splitlines()]
    assert record["status"] == "dry_run"
    assert record["week"] == 6
    assert record["moves"] == []
    assert "time" in record


def test_schedule_without_week_rows_fails_closed(monkeypatch, tmp_path, capsys):
    teams = kc_teams()
    values = {name: 10.0 for name in SKILL}
    code, _ = run_tool(monkeypatch, tmp_path, snapshot(teams),
                       schedule(7, [("KC", "DEN")]), projection_frame(values, teams))

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["moves"] == []
    assert any("no REG rows for week 6" in w for w in report["warnings"])


def test_schedule_locked_teams_block_moves_and_warn(monkeypatch, tmp_path, capsys):
    teams = kc_teams()
    values = {name: 10.0 for name in SKILL}
    values["Wr Bench"] = 16.0  # would force a swap if anyone were movable
    kicked_off = schedule(6, [("KC", "DEN")], gameday="2020-10-18", gametime="13:00")
    code, _ = run_tool(monkeypatch, tmp_path, snapshot(teams),
                       kicked_off, projection_frame(values, teams))

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["moves"] == []
    assert any("has kicked off per the schedule" in w for w in report["warnings"])
