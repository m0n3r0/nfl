"""Hermetic tests for yahoo/league.py parsing (standings rows)."""

from yahoo.league import _parse_standings_rows

HEADER = ["Team", "W-L-T", "PF", "PA", "Waiver"]


def test_standings_rows_parse_plain_numbers():
    rows = [["Team Alpha", "1-0-0", "140.5", "90.1", "3"],
            ["Team Beta", "0-1-0", "95.4", "130.2", "7"]]
    parsed = _parse_standings_rows(HEADER, rows)
    assert [r.team for r in parsed] == ["Team Alpha", "Team Beta"]
    assert parsed[0].points_for == 140.5
    assert parsed[1].waiver == 7


def test_standings_rows_parse_comma_thousands():
    # Late season Yahoo renders PF/PA with comma separators; rows must not drop.
    rows = [["Team Alpha", "6-1-0", "1,023.4", "812.0", "2"],
            ["Team Beta", "3-4-0", "987.6", "1,001.3", "5"]]
    parsed = _parse_standings_rows(HEADER, rows)
    assert len(parsed) == 2
    assert parsed[0].points_for == 1023.4
    assert parsed[1].points_against == 1001.3


def test_team_ids_reads_mapping():
    from yahoo.league import LEAGUE_HOME, team_ids

    class Stub:
        def evaluate(self, expr):
            return {"path": LEAGUE_HOME, "ids": {"Team Alpha": "3", "Shiba Innu": "2"}}

    assert team_ids(Stub()) == {"Team Alpha": "3", "Shiba Innu": "2"}


def test_team_ids_empty_raises():
    import pytest
    from yahoo.league import LEAGUE_HOME, LeagueReadError, team_ids

    class Stub:
        def evaluate(self, expr):
            return {"path": LEAGUE_HOME, "ids": {}}

    with pytest.raises(LeagueReadError):
        team_ids(Stub())


def test_team_ids_wrong_page_raises():
    import pytest
    from yahoo.league import LeagueReadError, team_ids

    class Stub:
        def evaluate(self, expr):
            return {"path": "/f1/1329011/matchup", "ids": {"Team Alpha": "3"}}

    with pytest.raises(LeagueReadError, match="not on the league home page"):
        team_ids(Stub())


def test_matchup_score_prefers_live_proj_pair():
    from yahoo.league import _build_matchup_score
    payload = {"week": "1", "names": ["Mine", "Theirs"],
               "score": [45.6, 0.0], "live": [100.7, 112.7],
               "orig": [112.7, 100.7]}
    m = _build_matchup_score(payload)
    assert (m.team, m.opponent) == ("Mine", "Theirs")
    assert (m.score, m.opponent_score) == (45.6, 0.0)
    assert (m.team_proj, m.opponent_proj) == (100.7, 112.7)  # live pair wins


def test_matchup_score_orig_proj_fallback_order():
    from yahoo.league import _build_matchup_score
    # Live-game layout: Orig Proj pair is (opponent, team)
    payload = {"week": "1", "names": ["Mine", "Theirs"],
               "score": [45.6, 0.0], "live": None, "orig": [112.7, 100.7]}
    m = _build_matchup_score(payload)
    assert (m.team_proj, m.opponent_proj) == (100.7, 112.7)


def test_matchup_score_requires_scores():
    import pytest
    from yahoo.league import LeagueReadError, _build_matchup_score
    with pytest.raises(LeagueReadError, match="scores are missing"):
        _build_matchup_score({"week": "1", "names": ["Mine", "Theirs"], "score": None})
    with pytest.raises(LeagueReadError, match="did not parse"):
        _build_matchup_score({"names": [], "score": [1.0, 2.0]})
