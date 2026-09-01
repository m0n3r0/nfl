"""Safety and recovery tests for the FD nation real-draft operator."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from yahoo.cdp import CdpError, Target
from yahoo.draft_report import render_draft_report
from yahoo.mock_draft import DraftState, Pick, PlayerRow, RosterPick
from yahoo.real_draft import (
    AUTHORIZATION,
    RealDraftOperator,
    RealDraftSafetyError,
    UncertainSubmission,
    find_real_draft_target,
    require_real_authorization,
)


def player(index: int, pos: str = "RB") -> PlayerRow:
    return PlayerRow(str(index), f"Player {index}", "NE", pos, "", float(index), float(index), "")


def pick_in_round(round_number: int) -> int:
    return 2 if round_number % 2 else 9


def overall_pick(round_number: int) -> int:
    return (round_number - 1) * 10 + pick_in_round(round_number)


def roster(count: int) -> tuple[RosterPick, ...]:
    return tuple(
        RosterPick(index, pick_in_round(index), overall_pick(index), player(index))
        for index in range(1, count + 1)
    )


def state(count: int, *, my_turn: bool = True, current: PlayerRow | None = None) -> DraftState:
    round_number = min(count + 1, 15)
    overall = overall_pick(round_number)
    return DraftState(
        f"YOUR TURN • ROUND {round_number}, PICK {overall}",
        round_number,
        overall,
        my_turn,
        count,
        15,
        count == 15,
        False,
        False,
        (current or player(round_number),),
        roster(count),
    )


def test_real_authorization_requires_cli_and_environment(monkeypatch):
    monkeypatch.delenv("FD_REAL_DRAFT_AUTHORIZATION", raising=False)
    with pytest.raises(RealDraftSafetyError):
        require_real_authorization(AUTHORIZATION)
    monkeypatch.setenv("FD_REAL_DRAFT_AUTHORIZATION", AUTHORIZATION)
    with pytest.raises(RealDraftSafetyError):
        require_real_authorization("wrong")
    require_real_authorization(AUTHORIZATION)


def test_real_target_selection_is_exact(monkeypatch):
    good = Target("1", "page", "FD", "https://football.fantasysports.yahoo.com/draftclient/f1/1329011/2?auth=x", "ws://127.0.0.1/1")
    mock = Target("2", "page", "mock", "https://football.fantasysports.yahoo.com/draftclient/f1/10401633/4?auth=x", "ws://127.0.0.1/2")
    monkeypatch.setattr("yahoo.cdp.list_targets", lambda endpoint: [good, mock])
    monkeypatch.setattr("yahoo.real_draft.select_target", lambda predicate, endpoint: next(t for t in [good, mock] if predicate(t)))
    assert find_real_draft_target().id == "1"


def test_state_validation_rejects_count_history_divergence():
    broken = state(2)
    broken = DraftState(*broken.__dict__.values())
    object.__setattr__(broken, "roster", roster(1))
    with pytest.raises(RealDraftSafetyError, match="parser returned"):
        RealDraftOperator._validate_state(broken)


class ResumePage:
    def __init__(self, start: int = 4):
        self.count = start
        self.current = player(start + 1)
        self.client = type("Client", (), {"bring_to_front": lambda _self: None})()
        self.submits = 0

    def verify_identity(self):
        return None

    def disable_autodraft(self):
        return None

    def read_state(self):
        return state(self.count, current=self.current)

    def submit(self, selected, overall):
        assert selected == self.current
        assert overall == overall_pick(self.count + 1)
        self.submits += 1
        self.count += 1

    def set_search(self, _query):
        return None


def operator_for(page, audit: Path) -> RealDraftOperator:
    operator = object.__new__(RealDraftOperator)
    operator.page = page
    operator.audit_path = audit
    operator.board = {}
    return operator


def test_real_operator_resumes_from_authoritative_roster(monkeypatch, tmp_path):
    page = ResumePage(start=4)
    operator = operator_for(page, tmp_path / "audit.jsonl")
    monkeypatch.setattr(operator, "_choose", lambda current: current.rows[0])
    original_read = page.read_state
    post_submit_reads = 0

    def read_until_complete():
        nonlocal post_submit_reads
        if page.count >= 5:
            post_submit_reads += 1
            return state(5) if post_submit_reads == 1 else state(15)
        return original_read()

    page.read_state = read_until_complete
    picks = operator.run(deadline_hours=0.01, poll_interval=0)
    assert page.submits == 1
    assert len(picks) == 15
    events = [json.loads(line)["event"] for line in operator.audit_path.read_text().splitlines()]
    assert events == ["decision", "submit_intent", "confirmed", "complete"]


def test_unresolved_submit_is_never_replayed(tmp_path):
    page = ResumePage(start=4)
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({
        "event": "submit_intent", "league": "1329011", "team": "2",
        "round": 5, "overall": overall_pick(5), "player_id": "5",
    }) + "\n")
    operator = operator_for(page, audit)
    with pytest.raises(UncertainSubmission, match="refusing to replay"):
        operator._reconcile_pending(page.read_state())
    assert page.submits == 0


def test_recovered_submit_is_confirmed_from_roster_without_click(tmp_path):
    page = ResumePage(start=5)
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({
        "event": "submit_intent", "league": "1329011", "team": "2",
        "round": 5, "overall": overall_pick(5), "player_id": "5",
    }) + "\n")
    operator = operator_for(page, audit)
    operator._reconcile_pending(page.read_state())
    assert operator._pending_submission() is None
    assert page.submits == 0


def test_unavailable_searches_are_scoped_to_the_current_round(tmp_path):
    page = ResumePage(start=4)
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({
        "event": "search_unavailable", "league": "1329011", "team": "2",
        "round": 5, "player": "Target Player",
    }) + "\n")
    operator = operator_for(page, audit)
    assert operator._known_unavailable_names(5) == {"target player"}
    assert operator._known_unavailable_names(6) == set()


def test_forced_autopick_mode_halts_without_click(tmp_path):
    page = ResumePage(start=4)
    page.read_state = lambda: replace(state(4), forced_autodraft=True)
    operator = operator_for(page, tmp_path / "audit.jsonl")
    with pytest.raises(RealDraftSafetyError, match="forced autopick"):
        operator.run(deadline_hours=0.01, poll_interval=0)
    assert page.submits == 0


def test_real_choice_searches_full_board_for_off_window_player(monkeypatch, tmp_path):
    from driver import draft_driver as driver

    target_player = PlayerRow("99", "T. Player", "NE", "RB", "", 1, 1, "")
    page = ResumePage(start=4)
    searches = []

    def set_search(query):
        searches.append(query)
        page.current = target_player

    monkeypatch.setattr(page, "set_search", set_search)
    operator = operator_for(page, tmp_path / "audit.jsonl")
    operator.board = {
        "Target Player": {"name": "Target Player", "team": "NE", "pos": "RB", "value": 200, "adp": 1}
    }
    driver.rebuild_abbrev_maps(operator.board)
    monkeypatch.setattr(
        driver,
        "choose_pick",
        lambda available, *_args, **_kwargs: ("Target Player", "NE", "RB", 1)
        if "Target Player" in available else None,
    )

    chosen = operator._choose(state(4, current=player(5)))

    assert chosen == target_player
    assert searches == ["Target Player"]


def test_decision_reason_records_pick_specific_roster_context(tmp_path):
    operator = operator_for(ResumePage(start=4), tmp_path / "audit.jsonl")
    reason = operator._decision_reason(state(4), player(5, "RB"))
    assert "starting RB/WR core" in reason
    assert "0 QB, 4 RB, 0 WR" in reason


def test_decision_reason_marks_a_late_first_te(tmp_path):
    operator = operator_for(ResumePage(start=8), tmp_path / "audit.jsonl")
    reason = operator._decision_reason(state(8), player(9, "TE"))
    assert "after missing the round-7 target deadline" in reason


def test_completed_report_uses_authoritative_picks_and_audit_reasoning(tmp_path):
    audit = tmp_path / "audit.jsonl"
    audit.write_text(json.dumps({
        "event": "decision", "league": "1329011", "team": "2",
        "round": 1, "overall": 2, "player_id": "1", "player": "Player 1",
        "board_player": "Canonical Player 1", "board_value": 299,
        "selection_path": "full_board_search",
        "yahoo_xrank": 2.0, "yahoo_adp": 2.3,
        "reason": "Build the starting RB/WR core.",
        "alternatives_unavailable": ["First Choice"],
    }) + "\n", encoding="utf-8")
    picks = [
        Pick(round_number, overall_pick(round_number), player(round_number))
        for round_number in range(1, 16)
    ]

    report = render_draft_report(picks, audit)

    assert "Round 1, overall 2: Canonical Player 1" in report
    assert "Build the starting RB/WR core." in report
    assert "Selection provenance: Internal FD nation board." in report
    assert "- Internal FD nation board: 1" in report
    assert "- Unknown or incomplete audit provenance: 14" in report
    assert "board value 299" in report
    assert "First Choice" in report
    assert "Round 15, overall 142: Player 15" in report
    assert report.count("### Round ") == 15


def test_completed_report_distinguishes_autopick_from_yahoo_rank_fallback(tmp_path):
    audit = tmp_path / "audit.jsonl"
    records = [
        {
            "event": "decision", "league": "1329011", "team": "2",
            "round": 1, "player_id": "1", "source": "yahoo_autopick",
        },
        {
            "event": "decision", "league": "1329011", "team": "2",
            "round": 2, "player_id": "2", "selection_path": "live_yahoo_rank",
        },
    ]
    audit.write_text("".join(json.dumps(record) + "\n" for record in records))
    picks = [
        Pick(round_number, overall_pick(round_number), player(round_number))
        for round_number in range(1, 16)
    ]

    report = render_draft_report(picks, audit)

    assert "- Yahoo autopick: 1" in report
    assert "- Yahoo XRank recovery fallback: 1" in report
    assert "Selection provenance: Yahoo autopick." in report
    assert "Selection provenance: Yahoo XRank recovery fallback." in report
