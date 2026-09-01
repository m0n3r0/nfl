"""Tests for strict CDP transport and the mock-only Yahoo draft operator."""

from __future__ import annotations

import json

import pytest

from yahoo.cdp import CdpClient, CdpError, CdpJavaScriptError, CdpProtocolError, Target
from yahoo.mock_draft import (
    DraftState,
    MockDraftOperator,
    MockDraftPage,
    PlayerRow,
    _validate_mock_room,
)


class FakeSocket:
    """Minimal scripted websocket for transport tests."""

    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        return json.dumps(next(self.replies))

    def settimeout(self, _timeout):
        return None

    def close(self):
        self.closed = True


def target(url="https://football.fantasysports.yahoo.com/draftclient/f1/10401633/4"):
    """Build a test page target."""
    return Target("page", "page", "Yahoo", url, "ws://127.0.0.1/devtools/page/1")


def test_mock_room_rejects_real_league_and_non_mock_ids():
    with pytest.raises(ValueError):
        _validate_mock_room("1329011")
    with pytest.raises(ValueError):
        _validate_mock_room("not-a-room")
    _validate_mock_room("10401633")


def test_cdp_protocol_error_is_not_swallowed(monkeypatch):
    socket = FakeSocket([{"id": 1, "error": {"code": -1, "message": "broken"}}])
    monkeypatch.setattr("yahoo.cdp.websocket.create_connection", lambda *args, **kwargs: socket)
    client = CdpClient(target())
    with pytest.raises(CdpProtocolError, match="broken"):
        client.call("Runtime.enable")


def test_target_discovery_errors_use_cdp_recovery_contract(monkeypatch):
    monkeypatch.setattr(
        "yahoo.cdp.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("Chrome restarting")),
    )
    with pytest.raises(CdpError, match="target discovery failed"):
        from yahoo.cdp import list_targets

        list_targets()


def test_cdp_rejects_non_loopback_websocket_before_connect(monkeypatch):
    called = False

    def connect(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("yahoo.cdp.websocket.create_connection", connect)
    remote = Target("page", "page", "bad", "https://example.test", "ws://example.test/devtools/page/1")
    with pytest.raises(ValueError, match="loopback"):
        CdpClient(remote)
    assert called is False


def test_cdp_javascript_exception_is_not_swallowed(monkeypatch):
    socket = FakeSocket([
        {
            "id": 1,
            "result": {
                "exceptionDetails": {
                    "text": "Uncaught",
                    "exception": {"description": "ReferenceError: missing"},
                }
            },
        }
    ])
    monkeypatch.setattr("yahoo.cdp.websocket.create_connection", lambda *args, **kwargs: socket)
    client = CdpClient(target())
    with pytest.raises(CdpJavaScriptError, match="ReferenceError"):
        client.evaluate("missing")


def test_cdp_context_entry_closes_socket_on_partial_initialization(monkeypatch):
    socket = FakeSocket([{"id": 1, "error": {"code": -1, "message": "enable failed"}}])
    monkeypatch.setattr("yahoo.cdp.websocket.create_connection", lambda *args, **kwargs: socket)
    with pytest.raises(CdpProtocolError, match="enable failed"):
        with CdpClient(target()):
            pass
    assert socket.closed is True


class StateClient:
    """Client returning one Yahoo-shaped draft state."""

    def __init__(self, payload):
        self.target = target()
        self.payload = payload

    def evaluate(self, _expression):
        return self.payload


def test_current_yahoo_state_parser_reads_rows_and_authoritative_count():
    client = StateClient(
        {
            "status": "YOUR TURN • ROUND 7, PICK 64",
            "teamCount": 6,
            "totalRoster": 15,
            "complete": False,
            "forcedAutodraft": False,
            "autodraftChecked": False,
            "rows": [
                {
                    "id": "40102",
                    "name": "T. Kraft",
                    "team": "GB",
                    "pos": "TE",
                    "injury": "Q",
                    "xrank": 67,
                    "adp": 60.5,
                    "text": "T. Kraft Q TE GB Bye 5 67 60.5",
                }
            ],
        }
    )
    state = MockDraftPage(client, "10401633").read_state()
    assert state.my_turn is True
    assert (state.round, state.pick, state.team_count, state.total_roster) == (7, 64, 6, 15)
    assert state.rows[0] == PlayerRow("40102", "T. Kraft", "GB", "TE", "Q", 67.0, 60.5, "T. Kraft Q TE GB Bye 5 67 60.5")


class FullDraftPage:
    """Deterministic page model that advances only after submit."""

    def __init__(self):
        self.count = 0
        self.submit_calls = 0
        self.players = [
            PlayerRow(str(index), f"Player {index}", "NE", "RB", "", float(index), float(index), f"Player {index} RB NE Bye 1 {index} {index}")
            for index in range(1, 16)
        ]
        self.client = type("Client", (), {"bring_to_front": lambda _self: None})()

    def disable_autodraft(self):
        return None

    def read_state(self):
        current = min(self.count + 1, 15)
        return DraftState(
            status=f"YOUR TURN • ROUND {current}, PICK {current}",
            round=current,
            pick=current,
            my_turn=True,
            team_count=self.count,
            total_roster=15,
            complete=self.count == 15,
            forced_autodraft=False,
            autodraft_checked=False,
            rows=tuple(self.players[self.count :]),
        )

    def submit(self, player, pick):
        assert player == self.players[self.count]
        assert pick == self.count + 1
        self.submit_calls += 1
        self.count += 1


def test_full_mock_requires_and_confirms_all_15_roster_transitions(monkeypatch):
    page = FullDraftPage()
    operator = object.__new__(MockDraftOperator)
    operator.page = page
    operator.room = "10401633"
    operator.log_path = None
    operator.board = {}
    monkeypatch.setattr(operator, "_choose", lambda state, roster: state.rows[0])
    monkeypatch.setattr(operator, "_log", lambda *args, **kwargs: None)

    picks = operator.run(poll_interval=0)

    assert len(picks) == 15
    assert page.submit_calls == 15
    assert page.read_state().complete is True


def test_current_row_is_rendered_for_legacy_identity_and_adp_parser():
    from driver import draft_driver as driver

    driver.rebuild_abbrev_maps(driver.static_board())
    row = PlayerRow("1", "T. Kraft", "GB", "TE", "", 67, 60.5, "current Yahoo layout")
    text = MockDraftOperator._driver_row_text(row)
    names, adp, positions = driver.normalize_available([[row.name, row.team, row.pos, text]])
    assert names == ["Tucker Kraft"]
    assert adp["tucker kraft"] == 60.5
    assert positions["tucker kraft"] == "TE"


def test_off_board_choice_without_team_or_position_is_identity_safe(monkeypatch):
    from collections import Counter
    from driver import draft_driver as driver

    board = driver.static_board()
    driver.rebuild_abbrev_maps(board)
    operator = object.__new__(MockDraftOperator)
    operator.board = board
    row = PlayerRow("1", "T. Kraft", "GB", "TE", "", 67, 60.5, "current Yahoo layout")
    state = DraftState("YOUR TURN • ROUND 7, PICK 64", 7, 64, True, 6, 15, False, False, False, (row,))
    monkeypatch.setattr(driver, "choose_pick", lambda *args, **kwargs: ("Tucker Kraft", None, None, 60.5))
    assert operator._choose(state, Counter()) == row


def test_operator_refuses_mid_draft_without_guessing(monkeypatch):
    page = FullDraftPage()
    page.count = 4
    operator = object.__new__(MockDraftOperator)
    operator.page = page
    operator.room = "10401633"
    operator.log_path = None
    operator.board = {}
    monkeypatch.setattr(operator, "_log", lambda *args, **kwargs: None)
    with pytest.raises(CdpError, match="fresh room"):
        operator.run(poll_interval=0)
    assert page.submit_calls == 0
