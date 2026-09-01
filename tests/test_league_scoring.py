"""Fast checks for the live-verified FD nation scoring profile."""

import pandas as pd

import cli
from src import config, scoring


def test_fd_nation_profile_matches_live_yahoo_differences():
    assert config.FD_NATION_SCORING["receptions"] == 0.5
    assert config.FD_NATION_SCORING["passing_tds"] == 4.0
    assert config.FD_NATION_SCORING["passing_interceptions"] == -1.0
    assert config.FD_NATION_SCORING["rushing_fumbles_lost"] == -2.0

    stats = pd.Series({"passing_interceptions": 2, "receptions": 4})
    generic = scoring.score_row(stats, config.HALF_PPR_SCORING)
    league = scoring.score_row(stats, config.FD_NATION_SCORING)
    assert league == generic + 2.0


def test_half_env_selects_live_league_profile(monkeypatch):
    monkeypatch.setattr(config, "_env_var", lambda name: "HALF")
    assert config.league_preset() == "fd-nation"


def test_cli_uses_league_profile_but_validation_stays_nflverse(monkeypatch):
    monkeypatch.setattr(cli, "league_preset", lambda: "fd-nation")
    parser = cli.build_parser()

    assert parser.parse_args(["rank"]).preset == "fd-nation"
    assert parser.parse_args(["projections"]).preset == "fd-nation"
    assert parser.parse_args(["original-board"]).preset == "fd-nation"
    assert parser.parse_args(["validate"]).preset == "half-ppr"
    assert parser.parse_args(["rank", "--preset", "fd-nation"]).preset == "fd-nation"
