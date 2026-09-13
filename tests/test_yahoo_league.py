"""Hermetic tests for league-level reads (yahoo/league.py)."""

from __future__ import annotations

import pytest

from yahoo.league import (
    LeagueReadError,
    LeagueWafBlocked,
    MatchupScore,
    ScoreboardEntry,
    StandingsRow,
    matchup,
    opponent_roster,
    opponent_team_id,
    scoreboard,
    standings,
)


class Client:
    def __init__(self, payloads, denied=False):
        self.payloads = payloads
        self.denied = denied
        self.navigated = []

    def navigate(self, url, expected, timeout=20):
        assert expected(url)
        self.navigated.append(url)
        return url

    def evaluate(self, expression):
        if "yahoo-waf-denied" in expression:
            return self.denied
        for marker, payload in self.payloads.items():
            if marker in expression:
                return payload
        raise AssertionError(f"unexpected expression: {expression[:80]}")


STANDINGS_HEADER = ["Rank", "Team", "W-L-T", "PF", "PA", "Streak", "Waiver Bdgt", "Waiver", "Moves"]
STANDINGS_ROWS = [
    ["1", "Team Alpha", "1-0-0", "120.5", "95.2", "W1", "-", "4", "3"],
    ["2", "Team Beta", "0-1-0", "95.2", "120.5", "L1", "-", "7", "1"],
]


def test_standings_parses_columns_by_header_name():
    client = Client({"yahoo-league-standings": {
        "path": "/f1/1329011",
        "header": STANDINGS_HEADER,
        "rows": STANDINGS_ROWS,
    }})

    rows = standings(client)

    assert rows == (
        StandingsRow(rank=1, team="Team Alpha", record="1-0-0", points_for=120.5,
                     points_against=95.2, waiver=4),
        StandingsRow(rank=2, team="Team Beta", record="0-1-0", points_for=95.2,
                     points_against=120.5, waiver=7),
    )


def test_standings_fails_closed_on_missing_table():
    client = Client({"yahoo-league-standings": {"path": "/f1/1329011", "header": STANDINGS_HEADER, "rows": []}})

    with pytest.raises(LeagueReadError, match="no parseable standings rows"):
        standings(client)


def test_standings_fails_closed_on_missing_columns():
    client = Client({"yahoo-league-standings": {
        "path": "/f1/1329011", "header": ["Team", "Score"], "rows": STANDINGS_ROWS}})

    with pytest.raises(LeagueReadError, match="missing columns"):
        standings(client)


def test_matchup_parses_score_and_projection():
    client = Client({"yahoo-league-matchup": {
        "week": "1", "names": ["Shiba Innu", "Team Alpha"],
        "score": [35.6, 0.0], "live": [100.54, 112.74],
    }})

    score = matchup(client)

    assert score == MatchupScore(week=1, team="Shiba Innu", score=35.6,
                                 opponent="Team Alpha", opponent_score=0.0,
                                 team_proj=100.54, opponent_proj=112.74)


def test_matchup_requires_scores():
    client = Client({"yahoo-league-matchup": {"week": "1", "names": [], "score": None}})

    with pytest.raises(LeagueReadError, match="scores are missing"):
        matchup(client)


def test_opponent_roster_reads_rows_and_blocks_own_team():
    client = Client({"yahoo-league-opponent-roster": {
        "path": "/f1/1329011/7",
        "rows": [{"name": "Some Player", "team": "KC", "position": "RB",
                  "slot": "RB", "injury_status": ""}],
    }})

    rows = opponent_roster(client, "7")

    assert rows == ({"name": "Some Player", "team": "KC", "position": "RB",
                     "slot": "RB", "injury_status": ""},)
    with pytest.raises(LeagueReadError, match="authorized team"):
        opponent_roster(client, "2")


def test_opponent_team_id_excludes_authorized_team():
    client = Client({"yahoo-league-opponent-id": ["2", "7"]})
    assert opponent_team_id(client) == "7"

    ambiguous = Client({"yahoo-league-opponent-id": ["2", "7", "9"]})
    with pytest.raises(LeagueReadError, match="could not isolate"):
        opponent_team_id(ambiguous)


def test_league_reads_fail_fast_on_waf_denial_page():
    # Empty payload maps: the denial check must fire before any payload read.
    with pytest.raises(LeagueWafBlocked, match="Request denied"):
        standings(Client({}, denied=True))
    with pytest.raises(LeagueWafBlocked, match="Request denied"):
        matchup(Client({}, denied=True))
    with pytest.raises(LeagueWafBlocked, match="Request denied"):
        opponent_roster(Client({}, denied=True), "7")
    with pytest.raises(LeagueWafBlocked, match="Request denied"):
        opponent_team_id(Client({}, denied=True))


def test_scoreboard_parses_all_matchups():
    client = Client({"yahoo-league-scoreboard": {
        "path": "/f1/1329011",
        "entries": [
            {"week": "1", "ids": ["2", "10"], "names": ["Shiba Innu", "Team Alpha"],
             "nums": [134.7, 150.89, 86.2, 134.63]},
            {"week": "1", "ids": ["1", "6"], "names": ["Team Beta", "Team Gamma"],
             "nums": [89.46, 113.82, 75.86, 97.49]},
        ],
    }})

    entries = scoreboard(client)

    assert entries == (
        ScoreboardEntry(week=1, team1="Shiba Innu", team1_id="2", score1=134.7,
                        proj1=150.89, team2="Team Alpha", team2_id="10",
                        score2=86.2, proj2=134.63),
        ScoreboardEntry(week=1, team1="Team Beta", team1_id="1", score1=89.46,
                        proj1=113.82, team2="Team Gamma", team2_id="6",
                        score2=75.86, proj2=97.49),
    )
    assert client.navigated == []  # rides on the standings page: no navigation


def test_scoreboard_degrades_to_zeros_without_numbers():
    # Pre-game pages can render matchup cards without the score/proj floats.
    client = Client({"yahoo-league-scoreboard": {
        "path": "/f1/1329011",
        "entries": [{"week": "1", "ids": ["2", "10"],
                     "names": ["Shiba Innu", "Team Alpha"], "nums": None}],
    }})

    (entry,) = scoreboard(client)

    assert (entry.score1, entry.proj1, entry.score2, entry.proj2) == (0.0, 0.0, 0.0, 0.0)
    assert entry.team1 == "Shiba Innu" and entry.team2_id == "10"


def test_scoreboard_fails_closed_on_wrong_page_and_empty_payload():
    wrong_page = Client({"yahoo-league-scoreboard": {"path": "/f1/1329011/2", "entries": []}})
    with pytest.raises(LeagueReadError, match="not on the league home page"):
        scoreboard(wrong_page)

    no_entries = Client({"yahoo-league-scoreboard": {"path": "/f1/1329011", "entries": [
        {"week": "1", "ids": ["2"], "names": ["Shiba Innu"], "nums": None},  # malformed
    ]}})
    with pytest.raises(LeagueReadError, match="no parseable scoreboard entries"):
        scoreboard(no_entries)


def test_scoreboard_skips_mangled_entries_keeps_good_ones():
    entries = (
        {"week": "abc", "ids": ["2", "10"], "names": ["Shiba Innu", "Team Alpha"],
         "nums": [1.0, 2.0, 3.0, 4.0]},          # bad week
        {"week": "1", "ids": ["1", "6"], "names": ["Team Beta", "Team Gamma"],
         "nums": ["x", 113.82, 75.86, 97.49]},   # bad float
        {"week": "1", "ids": ["3", "4"], "names": ["Team Delta", "Team Epsilon"],
         "nums": [10.5, 100.1, 20.5, 90.2]},     # clean
    )

    (survivor,) = scoreboard(Client({"yahoo-league-scoreboard": {
        "path": "/f1/1329011", "entries": list(entries)}}))

    assert survivor.team1 == "Team Delta" and survivor.score1 == 10.5


def test_wire_rank_targets_orders_and_skips():
    import pandas as pd

    from yahoo.identity import YahooPlayerIdentity, reconcile_identities
    from yahoo.players import AvailablePlayer
    from yahoo.wire import rank_targets

    available = {
        "1": AvailablePlayer("1", "Wire One", "KC", "WR", "FA", "", "Sun"),
        "2": AvailablePlayer("2", "Wire Two", "KC", "RB", "W (Sep 16)", "Q", "Sun"),
        "3": AvailablePlayer("3", "Ghost Player", "KC", "RB", "FA", "", "Sun"),
    }
    proj = pd.DataFrame([
        {"player_id": "00-1", "player_display_name": "Wire One", "position": "WR",
         "last_team": "KC", "proj_week": 9.0},
        {"player_id": "00-2", "player_display_name": "Wire Two", "position": "RB",
         "last_team": "KC", "proj_week": 12.5},
    ])

    ranked, skipped = rank_targets(available, proj)

    assert [r["name"] for r in ranked] == ["Wire Two", "Wire One"]
    assert ranked[0]["proj_week"] == 12.5
    assert skipped == {"unmapped": 1}
