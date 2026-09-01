"""Safety and recovery tests for the FD nation real-draft operator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yahoo.cdp import CdpError, Target
from yahoo.mock_draft import DraftState, PlayerRow, RosterPick
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


def roster(count: int) -> tuple[RosterPick, ...]:
    return tuple(RosterPick(index, index, index, player(index)) for index in range(1, count + 1))


def state(count: int, *, my_turn: bool = True, current: PlayerRow | None = None) -> DraftState:
    round_number = min(count + 1, 15)
    return DraftState(
        f"YOUR TURN • ROUND {round_number}, PICK {round_number}",
        round_number,
        round_number,
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
        assert overall == self.count + 1
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
        "round": 5, "overall": 5, "player_id": "5",
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
        "round": 5, "overall": 5, "player_id": "5",
    }) + "\n")
    operator = operator_for(page, audit)
    operator._reconcile_pending(page.read_state())
    assert operator._pending_submission() is None
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
    assert searches == ["T. Player"]
