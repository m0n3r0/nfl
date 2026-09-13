"""Tests for the read-only Yahoo team snapshot."""

from __future__ import annotations

import pytest

from yahoo.cdp import Target
from yahoo.team import TeamReadError, YahooTeamReader, _parse_payload, is_team_target


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "W/R/T", "BN", "BN", "BN", "BN", "BN", "BN", "K", "DEF"]
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "RB", "WR", "WR", "RB", "WR", "RB", "WR", "K", "DEF"]


def payload():
    return {
        "identity": {"signedIn": True, "league": True, "team": True, "path": True},
        "summary": {
            "team_name": "Shiba Innu", "record": "0-0-0",
            "matchup": "Week 1 vs QB Sack Corey", "waiver": "Waiver Priority: 4th",
        },
        "roster": [
            {
                "yahoo_id": str(index), "name": f"Player {index}", "team": "NE",
                "position": position, "slot": slot,
                "injury_status": "Q" if index == 1 else "", "game": "Sun 1:00 pm vs NYJ",
            }
            for index, (slot, position) in enumerate(zip(SLOTS, POSITIONS), 1)
        ],
    }


def test_parse_authoritative_team_snapshot():
    snapshot = _parse_payload(payload())

    assert snapshot.league_id == "1329011"
    assert snapshot.team_id == "2"
    assert snapshot.week == 1
    assert snapshot.opponent == "QB Sack Corey"
    assert snapshot.waiver_priority == 4
    assert len(snapshot.roster) == 15
    assert snapshot.roster[0].injury_status == "Q"


def test_rejects_identity_failure():
    current = payload()
    current["identity"]["team"] = False
    with pytest.raises(TeamReadError, match="identity check"):
        _parse_payload(current)


def test_rejects_duplicate_yahoo_player_ids():
    current = payload()
    current["roster"][1]["yahoo_id"] = current["roster"][0]["yahoo_id"]
    with pytest.raises(TeamReadError, match="duplicate Yahoo player IDs"):
        _parse_payload(current)


def test_rejects_unexpected_lineup_slots():
    current = payload()
    current["roster"][6]["slot"] = "BN"
    with pytest.raises(TeamReadError, match="unexpected lineup slots"):
        _parse_payload(current)


def test_accepts_two_injured_reserve_players_in_addition_to_active_roster():
    current = payload()
    current["roster"].extend([
        {
            "yahoo_id": "16", "name": "Player 16", "team": "NE",
            "position": "RB", "slot": "IR", "injury_status": "IR", "game": "",
        },
        {
            "yahoo_id": "17", "name": "Player 17", "team": "NE",
            "position": "WR", "slot": "IR", "injury_status": "IR", "game": "",
        },
    ])

    snapshot = _parse_payload(current)

    assert len(snapshot.roster) == 17


def test_reader_only_evaluates_page():
    class Client:
        def __init__(self):
            self.expression = ""

        def evaluate(self, expression):
            self.expression = expression
            return payload()

    client = Client()
    snapshot = YahooTeamReader(client).snapshot()

    assert len(snapshot.roster) == 15
    assert "tr.editable" not in client.expression
    assert "ysf-rosterswap-manager" in client.expression
    assert "SLOT_RE" in client.expression
    assert not hasattr(client, "navigate")


def test_locked_rows_are_kept_and_flagged():
    current = payload()
    for row in current["roster"][:3]:
        row["locked"] = True

    snapshot = _parse_payload(current)

    assert len(snapshot.roster) == 15
    assert [player.locked for player in snapshot.roster] == [True] * 3 + [False] * 12


def test_team_target_requires_exact_yahoo_https_origin():
    def target(url):
        return Target("id", "page", "", url, "ws://127.0.0.1:9222/devtools/page/id")

    assert is_team_target(target("https://football.fantasysports.yahoo.com/f1/1329011/2"))
    assert not is_team_target(target("https://example.com/f1/1329011/2"))
    assert not is_team_target(target("http://football.fantasysports.yahoo.com/f1/1329011/2"))


def test_is_team_url_requires_exact_authorized_route():
    from yahoo.team import is_team_url

    assert is_team_url("https://football.fantasysports.yahoo.com/f1/1329011/2")
    assert is_team_url("https://football.fantasysports.yahoo.com/f1/1329011/2/")
    assert not is_team_url("https://example.com/f1/1329011/2")
    assert not is_team_url("http://football.fantasysports.yahoo.com/f1/1329011/2")
    assert not is_team_url("https://football.fantasysports.yahoo.com/f1/1329011/2/editroster")
    assert not is_team_url("about:blank")
    assert not is_team_url("")


"""Drift recovery in find_team_target (self-healing team-tab anchor)."""

import yahoo.cdp as cdp_mod
import yahoo.team as team_mod
from yahoo.cdp import CdpError, CdpTimeout
from yahoo.team import TEAM_PATH, TEAM_URL, find_team_target

HOST = "https://football.fantasysports.yahoo.com"


def _target(url, tid):
    return Target(tid, "page", "", url, f"ws://127.0.0.1:9222/devtools/page/{tid}")


@pytest.fixture
def browser(monkeypatch):
    """A fake Chrome: mutable tabs + a CdpClient that 'navigates' them."""
    class TabList(list):
        pass
    tabs = TabList()

    def list_targets(endpoint, timeout=8):
        return [_target(t["url"], t["id"]) for t in tabs]

    class FakeClient:
        navigated = []

        def __init__(self, target, endpoint, timeout=12):
            self.tab = next(t for t in tabs if t["id"] == target.id)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def navigate(self, url, expected, timeout=20):
            assert expected(url)
            self.tab["url"] = url
            FakeClient.navigated.append((self.tab["id"], url))
            return url

    # select_target resolves list_targets inside yahoo.cdp; find_team_target
    # uses its own binding — patch both to the same fake browser.
    monkeypatch.setattr(cdp_mod, "list_targets", list_targets)
    monkeypatch.setattr(team_mod, "list_targets", list_targets)
    monkeypatch.setattr(team_mod, "CdpClient", FakeClient)
    tabs.FakeClient = FakeClient
    return tabs


def test_exact_anchor_match_returns_without_navigation(browser):
    browser.append({"id": "A", "url": f"{HOST}{TEAM_PATH}"})
    browser.append({"id": "B", "url": "https://sports.yahoo.com/nfl/scoreboard/"})

    target = find_team_target()

    assert target.url == f"{HOST}{TEAM_PATH}"
    assert browser.FakeClient.navigated == []  # already anchored: zero requests


def test_drifted_league_tab_is_navigated_back(browser, capsys):
    browser.append({"id": "A", "url": f"{HOST}/f1/1329011/6"})  # other team's page
    browser.append({"id": "B", "url": "https://sports.yahoo.com/nfl/scoreboard/"})

    target = find_team_target()

    assert target.url == f"{HOST}{TEAM_PATH}"
    assert browser.FakeClient.navigated == [("A", TEAM_URL)]
    assert browser[0]["url"] == f"{HOST}{TEAM_PATH}"
    assert "drifted" in capsys.readouterr().err


def test_first_fantasy_tab_wins_when_several_drifted(browser):
    browser.append({"id": "A", "url": f"{HOST}/f1/1329011"})      # league home
    browser.append({"id": "B", "url": f"{HOST}/f1/1329011/6"})    # another team

    find_team_target()

    assert browser.FakeClient.navigated == [("A", TEAM_URL)]  # first only
    assert browser[1]["url"] == f"{HOST}/f1/1329011/6"        # untouched


def test_no_fantasy_tab_keeps_the_original_error(browser):
    browser.append({"id": "A", "url": "https://sports.yahoo.com/nfl/scoreboard/"})

    with pytest.raises(CdpError, match="found 0"):
        find_team_target()
    assert browser.FakeClient.navigated == []  # articles are never hijacked


def test_two_exact_matches_stay_fatal(browser):
    browser.append({"id": "A", "url": f"{HOST}{TEAM_PATH}"})
    browser.append({"id": "B", "url": f"{HOST}{TEAM_PATH}"})

    with pytest.raises(CdpError, match="found 2"):
        find_team_target()
    assert browser.FakeClient.navigated == []  # anchor ambiguity never heals


def test_navigation_failure_propagates(browser, monkeypatch):
    browser.append({"id": "A", "url": f"{HOST}/f1/1329011/6"})

    def stuck(self, url, expected, timeout=20):
        raise CdpTimeout("navigation did not reach the expected page")
    monkeypatch.setattr(browser.FakeClient, "navigate", stuck)

    with pytest.raises(CdpTimeout):
        find_team_target()
