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
