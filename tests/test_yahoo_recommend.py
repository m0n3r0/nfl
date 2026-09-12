"""Hermetic tests for the weekly lineup recommender (yahoo/recommend.py)."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pandas as pd

from yahoo.recommend import apply_schedule_locks, propose_lineup
from yahoo.team import EXPECTED_ACTIVE_SLOTS, RosterPlayer, TeamSnapshot

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "BN", "BN", "BN", "BN", "BN", "BN", "K", "DEF"]
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "WR", "RB", "WR", "RB", "WR", "QB", "TE", "K", "DEF"]
NAMES = ["Qb One", "Rb One", "Rb Two", "Wr One", "Wr Two", "Te One", "Wr Three",
         "Rb Bench", "Wr Bench", "Rb Deep", "Wr Deep", "Qb Bench", "Te Bench", "K One", "Def One"]


def snapshot(locked=(), slots=None, positions=None):
    slots = slots or SLOTS
    positions = positions or POSITIONS
    roster = tuple(
        RosterPlayer(yahoo_id=str(i), name=name, team="KC", position=pos,
                     slot=slot, injury_status="", game="Sun 1:00 pm vs DEN",
                     locked=str(i) in locked)
        for i, (name, pos, slot) in enumerate(zip(NAMES, positions, slots), 1)
    )
    return TeamSnapshot(league_id="1329011", team_id="2", team_name="Shiba Innu",
                        record="0-0-0", week=1, opponent="Opponent", waiver_priority=4,
                        roster=roster)


def projections(values, on_bye=(), injuries=None, positions=None):
    positions = positions or POSITIONS
    injuries = injuries or {}
    rows = []
    for i, name in enumerate(NAMES[:-2], 1):  # K/DEF have no projection rows
        rows.append({
            "player_id": f"00-{i}", "player_display_name": name,
            "position": positions[i - 1], "last_team": "KC",
            "proj_week": values[name], "on_bye": name in on_bye,
            "injury_status": injuries.get(name, ""),
        })
    return pd.DataFrame(rows)


BASE = {name: 10.0 for name in NAMES[:-2]}


def moves_of(proposal):
    return {(m.yahoo_id, m.from_slot, m.to_slot) for m in proposal.moves}


def proposed_slot(proposal, yahoo_id):
    return next(p.proposed_slot for p in proposal.plan if p.yahoo_id == yahoo_id)


def test_bench_outranks_starter_triggers_swap():
    values = dict(BASE, **{"Wr Bench": 16.0, "Wr Two": 8.0})
    proposal = propose_lineup(snapshot(), projections(values), week=1)

    assert proposed_slot(proposal, "9") == "WR"   # Wr Bench up
    assert proposed_slot(proposal, "5") == "BN"   # Wr Two down
    assert ("9", "BN", "WR") in moves_of(proposal)
    assert ("5", "WR", "BN") in moves_of(proposal)
    slots = Counter(p.proposed_slot for p in proposal.plan)
    assert slots == EXPECTED_ACTIVE_SLOTS


def test_locked_starter_never_moves():
    values = dict(BASE, **{"Qb Bench": 20.0, "Qb One": 5.0})
    proposal = propose_lineup(snapshot(locked={"1"}), projections(values), week=1)

    assert proposed_slot(proposal, "1") == "QB"
    assert proposed_slot(proposal, "12") == "BN"  # Qb Bench has nowhere to go
    assert not any(m[0] in {"1", "12"} for m in moves_of(proposal))


def test_bye_starter_replaced_and_warned():
    values = dict(BASE, **{"Rb Two": 0.0, "Rb Bench": 9.0, "Rb Deep": 8.0})
    proposal = propose_lineup(snapshot(), projections(values, on_bye=("Rb Two",)), week=6)

    assert proposed_slot(proposal, "3") == "BN"   # bye starter out
    assert proposed_slot(proposal, "8") == "RB"   # Rb Bench is the best replacement
    assert any("BYE" in w for w in proposal.warnings)


def test_unmapped_starter_blocks_slot_no_swap():
    values = dict(BASE, **{"Qb Bench": 20.0, "Qb One": 1.0})
    proj = projections(values)
    proj = proj[proj["player_display_name"] != "Qb One"]  # starter unmapped
    proposal = propose_lineup(snapshot(), proj, week=1)

    assert proposed_slot(proposal, "1") == "QB"
    assert proposed_slot(proposal, "12") == "BN"
    assert not any(m[0] in {"1", "12"} for m in moves_of(proposal))
    assert any("unmapped" in w for w in proposal.warnings)


def test_questionable_starter_discounted_but_kept():
    values = {name: 9.0 for name in NAMES[:-2]}
    values["Wr One"] = 9.35
    proj = projections(values, injuries={"Wr One": "Questionable"})
    proposal = propose_lineup(snapshot(), proj, week=1)

    assert proposed_slot(proposal, "4") == "WR"  # discounted 9.35 still beats 9.0
    assert proposal.moves == ()
    notes = {p.name: p.note for p in proposal.plan}
    assert notes["Wr One"] == "injury: Questionable"


def test_already_optimal_produces_no_moves():
    proposal = propose_lineup(snapshot(), projections(BASE), week=1)

    assert proposal.moves == ()
    assert all(p.current_slot == p.proposed_slot for p in proposal.plan)


def test_kicker_and_defense_are_never_moved_or_warned():
    values = dict(BASE, **{"Wr Bench": 16.0, "Wr Two": 8.0})
    proposal = propose_lineup(snapshot(), projections(values), week=1)

    assert not any(m[0] in {"14", "15"} for m in moves_of(proposal))
    assert not any("K One" in w or "Def One" in w for w in proposal.warnings)
    notes = {p.name: p.note for p in proposal.plan}
    assert notes["K One"] == "no projection data; kept"


def test_best_surplus_players_fill_wr_then_flex():
    values = dict(BASE, **{"Wr One": 12.0, "Wr Two": 12.0, "Wr Bench": 11.0, "Wr Three": 7.0})
    proposal = propose_lineup(snapshot(), projections(values), week=1)

    assert proposed_slot(proposal, "4") == "WR"    # 12-point starters keep WR
    assert proposed_slot(proposal, "5") == "WR"
    assert proposed_slot(proposal, "9") == "W/R/T"  # 11-pointer is the best surplus
    assert proposed_slot(proposal, "7") == "BN"     # Wr Three displaced
    slots = Counter(p.proposed_slot for p in proposal.plan)
    assert slots == EXPECTED_ACTIVE_SLOTS


def test_missing_bye_injury_columns_warn_loudly():
    proj = projections(BASE).drop(columns=["on_bye", "injury_status"])
    proposal = propose_lineup(snapshot(), proj, week=1)

    assert any("no bye data" in w for w in proposal.warnings)
    assert any("no injury data" in w for w in proposal.warnings)
    assert proposal.moves == ()


def test_bye_bench_player_is_never_auto_started():
    values = dict(BASE, **{"Rb Bench": 16.0})  # bye bench out-projects everyone
    proposal = propose_lineup(snapshot(), projections(values, on_bye=("Rb Bench",)), week=6)

    assert proposed_slot(proposal, "8") == "BN"
    assert proposal.moves == ()


def test_bye_starter_benched_despite_full_projection():
    values = dict(BASE, **{"Rb Two": 16.0, "Rb Bench": 9.0})
    proposal = propose_lineup(snapshot(), projections(values, on_bye=("Rb Two",)), week=6)

    assert proposed_slot(proposal, "3") == "BN"
    assert ("3", "RB", "BN") in moves_of(proposal)
    assert any("BYE" in w for w in proposal.warnings)


def test_unbackfillable_slot_withholds_promotion():
    # The flex occupant is listed as a QB (position anomaly): once promoted out,
    # nobody left can take W/R/T with every bench RB/WR/TE unmapped. The proposal
    # must keep him instead of emitting a slot-unbalanced move set.
    positions = POSITIONS[:6] + ["QB"] + POSITIONS[7:]
    snap = snapshot(locked={"2"}, positions=positions)  # Rb One vacates an RB slot
    values = dict(BASE, **{"Wr Three": 14.0})
    proj = projections(values, positions=positions)
    bench = ["Rb One", "Rb Bench", "Wr Bench", "Rb Deep", "Wr Deep", "Te Bench"]
    proj = proj[~proj["player_display_name"].isin(bench)]
    proposal = propose_lineup(snap, proj, week=1)

    assert proposed_slot(proposal, "7") == "W/R/T"
    assert proposed_slot(proposal, "1") == "QB"
    assert proposal.moves == ()
    slots = Counter(p.proposed_slot for p in proposal.plan)
    assert slots == EXPECTED_ACTIVE_SLOTS
    assert any("no evaluated W/R/T replacement" in w for w in proposal.warnings)


def test_schedule_locked_team_counts_as_locked_and_warns():
    adjusted, warnings = apply_schedule_locks(snapshot(), {"KC"})

    assert all(p.locked for p in adjusted.roster)
    assert sum("has kicked off" in w for w in warnings) == len(adjusted.roster)


def test_dom_lock_agreeing_with_schedule_does_not_warn():
    adjusted, warnings = apply_schedule_locks(snapshot(locked={"1", "2"}), {"KC"})

    assert all(p.locked for p in adjusted.roster)
    assert not any(w.startswith(("Qb One", "Rb One")) for w in warnings)


def test_dom_locked_without_kickoff_warns_but_lock_holds():
    adjusted, warnings = apply_schedule_locks(snapshot(locked={"1", "8"}), set())

    assert {p.yahoo_id for p in adjusted.roster if p.locked} == {"1", "8"}
    assert sum("locked on the page" in w for w in warnings) == 2


def test_schedule_lock_normalizes_team_aliases():
    snap = snapshot()
    snap = replace(snap, roster=tuple(replace(p, team="LAR") for p in snap.roster))
    adjusted, _ = apply_schedule_locks(snap, {"LA"})

    assert all(p.locked for p in adjusted.roster)


def test_injured_reserve_rows_are_not_cross_checked():
    ir_player = RosterPlayer(yahoo_id="16", name="Rb Ir", team="KC", position="RB",
                             slot="IR", injury_status="IR", game="", locked=True)
    snap = replace(snapshot(), roster=snapshot().roster + (ir_player,))
    adjusted, warnings = apply_schedule_locks(snap, set())

    assert warnings == ()
    assert next(p for p in adjusted.roster if p.yahoo_id == "16").locked


def test_monitor_report_flags_attention_items():
    values = dict(BASE, **{"Rb Two": 0.0})
    proj = projections(values, on_bye=("Rb Two",), injuries={"Wr One": "Questionable"})
    proj = proj[proj["player_display_name"] != "Rb Bench"]  # one unmapped bench
    from yahoo.recommend import monitor_report

    report = monitor_report(snapshot(locked={"1"}), proj, week=6)

    assert report["locked_starters"] == ["Qb One"]
    assert report["bye_players"] == ["Rb Two (RB)"]
    assert report["injury_tags"] == ["Wr One (Questionable, WR)"]
    assert report["unevaluated"] == ["Rb Bench (unmapped)"]
    assert report["needs_attention"] is True
    assert report["starter_count"] == 9


def test_monitor_report_quiet_when_clean():
    from yahoo.recommend import monitor_report

    report = monitor_report(snapshot(), projections(BASE), week=1)

    assert report["locked_starters"] == []
    assert report["bye_players"] == []
    assert report["injury_tags"] == []
    assert report["unevaluated"] == []
    assert report["needs_attention"] is False


def test_monitor_report_uses_yahoo_only_injury_tag():
    snap = snapshot()
    tagged = replace(snap.roster[1], injury_status="Questionable")  # Rb One
    snap = replace(snap, roster=(snap.roster[0], tagged) + snap.roster[2:])
    from yahoo.recommend import monitor_report

    report = monitor_report(snap, projections(BASE), week=1)

    assert any(i.startswith("Rb One (Questionable") for i in report["injury_tags"])
    assert report["needs_attention"] is True
