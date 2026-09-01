"""Regression tests for the live FantasyPros value board in the draft driver.

Key guarantee (regression for a real bug): a player whose FantasyPros feed
reports ADP=0 -- e.g. an undrafted rookie, or any player the API legitimately
scores 0 -- must NOT be dropped from the live board. The original parser used
`adp = p.get("adp") or p.get("rank_adp") or ...`; since `0 or ...` is falsy,
a 0 ADP was coerced to None and the player fell back to the static board.
We assert full coverage and that the 0 value is preserved.

Run with:  python -m pytest tests/test_draft_driver.py
"""

import re
import sys
import time as _realtime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import driver.draft_driver as dd  # noqa: E402

_ORIG_FP_GET = dd._fp_get
_ORIG_KEY = dd.FP_API_KEY


def _install_mock_fp(offsets):
    """Faithful mock of the FantasyPros consensus-rankings response for every
    position in BOARD. The 2nd player of each group gets adp=0 to exercise the
    previously-broken path."""
    positions = {}
    for (name, team, pos, adp) in dd.BOARD:
        positions.setdefault(pos, []).append((name, team, adp))

    def mock_fp_get(path):
        pos = re.search(r"position=(\w+)", path).group(1)
        lookup = "DEF" if pos == "DST" else pos   # feed codes defenses as DST
        out = []
        for i, (name, team, adp) in enumerate(positions.get(lookup, [])):
            out.append({
                "player_name": name, "player_team_id": team, "position": pos,
                "rank_ecr": i + 1,
                "adp": i + 1 + offsets[i % len(offsets)],
                "tier": 1,
            })
        return {"players": out}

    dd._fp_get = mock_fp_get


def teardown_module(module):
    dd._fp_get = _ORIG_FP_GET
    dd.FP_API_KEY = _ORIG_KEY


def test_fetch_fp_consensus_keeps_zero_adp():
    """adp=0 must be returned, not coerced to None by `or` coalescing."""
    dd._fp_get = lambda path: {"players": [
        {"player_name": "Zero Adp Guy", "player_team_id": "FA",
         "position": "RB", "rank_ecr": 3, "adp": 0, "tier": 1}]}
    rows = dd.fetch_fp_consensus("RB")
    assert len(rows) == 1
    assert rows[0]["adp"] == 0
    assert rows[0]["ecr"] == 3


def test_build_value_board_full_coverage_with_zero_adp():
    """All BOARD names survive build_value_board even when some have adp=0."""
    offsets = [4, -2, 6, -3, 2, -1, 5, -4, 3, -2,
               1, -5, 4, 3, -1, 2, 5, -3, 4, -2]
    _install_mock_fp(offsets)
    dd.FP_API_KEY = "MOCK"
    try:
        vb = dd.build_value_board()
    finally:
        dd.FP_API_KEY = None
    assert vb is not None, "expected a live board, got None"
    assert len(vb) == len(dd.BOARD), "lost players from the board"
    # every player must carry a real ecr (proves it took the live branch)
    for name, row in vb.items():
        assert "ecr" in row, f"{name} missing ecr (dropped from live board)"
        assert row["ecr"] is not None


def test_build_value_board_static_fallback_without_key():
    """Without a key we must fall back (return None), not crash."""
    dd.FP_API_KEY = None
    dd._fp_get = _ORIG_FP_GET
    vb = dd.build_value_board()
    assert vb is None


def test_build_value_board_ecr_only_when_adp_absent():
    """Free FantasyPros tier has ECR but no ADP: board must still be live and
    order by -ECR (best-player-available), not collapse to all-zero value."""
    def mock_ecr_only(path):
        # only ECR is present; adp is absent (matches the real free endpoint)
        pos = re.search(r"position=(\w+)", path).group(1)
        lookup = "DEF" if pos == "DST" else pos
        players = [b for b in dd.BOARD if b[2] == lookup]
        return {"players": [
            {"player_name": n, "player_team_id": t, "position": pos,
             "rank_ecr": i + 1, "tier": 1}
            for i, (n, t, pos2, adp) in enumerate(players)]}
    dd._fp_get = mock_ecr_only
    dd.FP_API_KEY = "MOCK"
    try:
        vb = dd.build_value_board()
    finally:
        dd.FP_API_KEY = None
    assert vb is not None
    assert len(vb) == len(dd.BOARD)
    # every matched player carries ecr and a non-zero, -ecr-based value
    matched = [row for row in vb.values() if "ecr" in row]
    assert matched, "no players took the live branch"
    for row in matched:
        assert row["value"] == -float(row["ecr"]), row
    # best available overall should be the #1 ECR player (Jahmyr Gibbs, RB)
    best = max(vb.values(), key=lambda r: r.get("value", 0.0))
    assert best["name"] == "Jahmyr Gibbs"


def test_build_value_board_matches_def_by_team_id():
    """FantasyPros defenses come back as full team names ('Houston Texans')
    with a player_team_id ('HOU'); our BOARD stores the short team ('Hou').
    The board must match them by team id, not by name. Also: a SAME-TEAM
    kicker (Ka'imi Fairbairn / HOU) must NOT overwrite the Houston Texans DST
    ECR record, so fp_team is keyed ONLY from DEF rows (see build_value_board)."""
    def mock_mixed(path):
        pos = re.search(r"position=(\w+)", path).group(1)
        if pos == "DST":
            return {"players": [
                {"player_name": "Houston Texans", "player_team_id": "HOU",
                 "position": "DST", "rank_ecr": 1, "tier": 1},
                {"player_name": "Denver Broncos", "player_team_id": "DEN",
                 "position": "DST", "rank_ecr": 2, "tier": 1}]}
        players = [b for b in dd.BOARD if b[2] == pos]
        out = [{"player_name": n, "player_team_id": t, "position": pos,
                "rank_ecr": i + 1, "tier": 1}
               for i, (n, t, pos2, adp) in enumerate(players)]
        # Inject a same-team kicker: if fp_team were keyed from every row that
        # carries a team, this HOU kicker would clobber the Texans DST ECR below.
        if pos == "K":
            out.append({"player_name": "Ka'imi Fairbairn", "player_team_id": "HOU",
                        "position": "K", "rank_ecr": 99, "tier": 1})
        return {"players": out}
    dd._fp_get = mock_mixed
    dd.FP_API_KEY = "MOCK"
    try:
        vb = dd.build_value_board()
    finally:
        dd.FP_API_KEY = None
    assert vb is not None
    # DST matched by team_id with the expected ECR (NOT clobbered by the kicker).
    texans = vb["Texans"]
    assert "ecr" in texans and texans["ecr"] == 1, "Texans DST ECR overwritten by same-team kicker"
    broncos = vb["Broncos"]
    assert "ecr" in broncos and broncos["ecr"] == 2, "Broncos DST ECR missing"


def test_unmatched_players_deprioritized():
    """Players absent from the feed must sort BELOW every matched player
    (value ~ -(adp+1000)), never above them."""
    def mock_qb_only(path):
        return {"players": [
            {"player_name": "Josh Allen", "player_team_id": "BUF",
             "position": "QB", "rank_ecr": 1, "tier": 1}]}
    dd._fp_get = mock_qb_only
    dd.FP_API_KEY = "MOCK"
    try:
        vb = dd.build_value_board()
    finally:
        dd.FP_API_KEY = None
    matched = [r for r in vb.values() if "ecr" in r]
    unmatched = [r for r in vb.values() if "ecr" not in r]
    assert matched and unmatched
    assert max(r["value"] for r in unmatched) < min(r["value"] for r in matched)


def test_parse_adp():
    """Yahoo ADP is extracted from the draft-row text via its explicit label."""
    assert dd.parse_adp("Josh Allen BUF - QB ADP 12.3 extra") == 12.3
    assert dd.parse_adp("ADP: 5") == 5.0
    assert dd.parse_adp("ADP 7.5") == 7.5
    assert dd.parse_adp("no adp in this row 99") is None
    assert dd.parse_adp("") is None


def test_choose_pick_uses_yahoo_adp():
    """When a live Yahoo ADP is known, VALUE = Yahoo_ADP - FantasyPros_ECR must
    drive the pick (not the static ECR order)."""
    board = {
        "Shiny Guy":  {"name": "Shiny Guy",  "team": "X", "pos": "RB",
                       "adp": 2,  "value": -1.0, "ecr": 1},
        "Value Guy":  {"name": "Value Guy",  "team": "Y", "pos": "RB",
                       "adp": 30, "value": -5.0, "ecr": 5},
    }
    drafted, round_num = {}, 1
    # No ADP map -> picks the best ECR player (Shiny Guy).
    p_no = dd.choose_pick(["Shiny Guy", "Value Guy"], drafted, round_num, board)
    assert p_no[0] == "Shiny Guy"
    # With Yahoo ADP for Value Guy, he's +25 value vs Shiny's -1 -> Value Guy.
    p_yes = dd.choose_pick(["Shiny Guy", "Value Guy"], drafted, round_num,
                           board, adp_map={"value guy": 30})
    assert p_yes[0] == "Value Guy"


def test_build_value_board_uses_realtime_adp():
    """The FREE Real-Time ADP scrape (RT_ADP_URL) combined with the free ECR feed
    must yield VALUE = RT_ADP - ECR for covered players. The join key is the
    team-suffixed normalized name ('F. Last|TEAM') so two players who abbreviate
    to the same 'Initial. Last' -- A.J. Brown and Amon-Ra St. Brown both render
    as 'A. Brown' -- resolve to DISTINCT adps instead of colliding. This is the
    path that makes the paid ADP tier unnecessary."""
    def mock_ecr(path):
        pos = re.search(r"position=(\w+)", path).group(1)
        lookup = "DEF" if pos == "DST" else pos
        players = [b for b in dd.BOARD if b[2] == lookup]
        return {"players": [
            {"player_name": n, "player_team_id": t, "position": pos,
             "rank_ecr": i + 1, "tier": 1}
            for i, (n, t, pos2, adp) in enumerate(players)]}
    dd._fp_get = mock_ecr
    dd.FP_API_KEY = "MOCK"
    # Team-suffixed normalized names (initial+last|TEAM) the RT page renders.
    # A.J. Brown (NE) and Amon-Ra St. Brown (DET) both abbreviate to 'A. Brown',
    # so they MUST be keyed distinctly or the collision makes one overwrite the
    # other.
    adp_map = {"J. Gibbs|DET": 1.2, "B. Robinson|ATL": 2.2,
               "J. Chase|CIN": 3.8, "C. McCaffrey|SF": 6.0,
               "A. Brown|NE": 7.8, "A. Brown|DET": 18.6}
    try:
        vb = dd.build_value_board(adp_map=adp_map)
    finally:
        dd.FP_API_KEY = None
    assert vb is not None, "expected a live board"
    # Jahmyr Gibbs is BOARD[0] (1st RB) -> mock ECR=1; RT adp 1.2 -> value 0.2
    row = vb["Jahmyr Gibbs"]
    assert row["adp"] == 1.2
    assert row["value"] == 1.2 - float(row["ecr"])
    # Bijan Robinson is BOARD[1] (2nd RB) -> mock ECR=2; RT adp 2.2 -> value 0.2
    row2 = vb["Bijan Robinson"]
    assert row2["adp"] == 2.2
    assert row2["value"] == 2.2 - float(row2["ecr"])
    # Collision check: the two 'A. Brown' players resolve to DISTINCT adps and
    # values (proves the team suffix kept them separate).
    aj = vb["A.J. Brown"]            # NE -> 7.8
    amsr = vb["Amon-Ra St. Brown"]   # DET -> 18.6
    assert aj["adp"] == 7.8
    assert amsr["adp"] == 18.6
    assert aj["value"] == 7.8 - float(aj["ecr"])
    assert amsr["value"] == 18.6 - float(amsr["ecr"])
    # A player without an RT entry keeps its ECR-only value (-ECR).
    ceedee = vb["CeeDee Lamb"]
    assert ceedee["adp"] is None
    assert ceedee["value"] == -float(ceedee["ecr"])


def _board(*rows):
    """rows: (name, pos, value) -> board dict the driver understands."""
    return {n: {"name": n, "team": "T", "pos": p, "adp": None, "value": v}
            for (n, p, v) in rows}


def test_scarcity_premium_anchors_rb_over_higher_value_wr():
    """10-team overlay: while we still NEED an RB, the scarcity premium lifts a
    lower-raw-value RB above a higher-value WR, so we anchor RB early instead of
    letting the crowd's RB inflation (negative VALUE) price us out of the slot.

    The premium is a FRACTION of the position's value spread (issue #20), so the
    board must carry more than one RB for the spread -- and therefore the premium
    -- to be non-zero; a single-RB board has no spread to scale. Use two RBs with
    a real spread and a WR whose value sits just above the top RB, so only the
    premium tips the decision to RB.
    """
    # RB spread 10.0 vs 8.0 -> premium = 0.10 * 2.0 = 0.2 on the top RB.
    # WR at 10.1: without the premium RB(10.0) < WR(10.1); with it RB(10.2) > WR.
    board = _board(("RB Stud", "RB", 10.0), ("RB Other", "RB", 8.0),
                   ("WR Stud", "WR", 10.1))
    pick = dd.choose_pick(["RB Stud", "RB Other", "WR Stud"], {}, 1, board)
    assert pick[0] == "RB Stud"
    # Sanity: once the RB need is met, the higher-value WR wins again.
    pick2 = dd.choose_pick(["RB Stud", "RB Other", "WR Stud"], {"RB": 2}, 1, board)
    assert pick2[0] == "WR Stud"


def test_anchor_forces_rb_on_schedule():
    """ANCHOR_BY_ROUND must force the 1st RB by R3 and the 2nd by R5, but NOT
    before those rounds (so we still grab a falling stud early)."""
    board = _board(("RB A", "RB", 1.0), ("WR A", "WR", 20.0))
    # 1st RB: not forced at R2 (WR taken), forced at R3 (RB taken).
    assert dd.choose_pick(["RB A", "WR A"], {}, 2, board)[0] == "WR A"
    assert dd.choose_pick(["RB A", "WR A"], {}, 3, board)[0] == "RB A"
    # 2nd RB: with 1 already, not forced at R4 (WR taken), forced at R5 (RB taken).
    assert dd.choose_pick(["RB A", "WR A"], {"RB": 1}, 4, board)[0] == "WR A"
    assert dd.choose_pick(["RB A", "WR A"], {"RB": 1}, 5, board)[0] == "RB A"


def test_normalize_available_maps_def_code_to_board_name():
    """read_available returns [name, code, pos, text]; DEF rows must resolve to
    the BOARD's short DEF key (e.g. 'LAR' -> 'Rams') so choose_pick can match
    them, and Yahoo ADP must key off the normalized name."""
    raw = [
        ["Los Angeles Rams", "LAR", "DEF", "Los Angeles Rams LAR - DEF ADP 12.5 extra"],
        ["Jahmyr Gibbs", "DET", "RB", "Jahmyr Gibbs DET - RB ADP 1.5"],
        ["A.J. Brown", "NE", "WR", "A.J. Brown NE - WR ADP 25.0"],
    ]
    names, adp_map, pos_map = dd.normalize_available(raw)
    assert names == ["Rams", "Jahmyr Gibbs", "A.J. Brown"], names
    assert adp_map["rams"] == 12.5
    assert adp_map["jahmyr gibbs"] == 1.5
    assert adp_map["a.j. brown"] == 25.0
    # pos_map drives the off-board fallback's slot awareness
    assert pos_map["rams"] == "DEF"
    assert pos_map["jahmyr gibbs"] == "RB"


def test_normalize_available_uses_supplied_def_map():
    """Issue #10: the DEF map must come from the ACTIVE board, not the static
    BOARD tuple -- otherwise defenses that only exist on the original nflverse
    board (BAL/CHI/KC/LAC/TB) can never be drafted."""
    raw = [["Baltimore Ravens", "BAL", "DEF", "Baltimore Ravens BAL - DEF ADP 90.0"]]
    # Static BOARD has no BAL entry, so the default map leaves it unresolved.
    names, _, _ = dd.normalize_available(raw)
    assert names == ["Baltimore Ravens"], names
    # Passing the active board's map resolves it.
    active = {"BAL": "Ravens", "CHI": "Bears"}
    names, _, _ = dd.normalize_available(raw, def_map=active)
    assert names == ["Ravens"], names


def test_normalize_available_empty_def_map_falls_back_to_static():
    """An empty def_map must NOT defeat the static fallback.

    run_draft() builds the map from the active board with a comprehension, so a
    board with no DEF rows yields {} -- falsy but not None. Treating that as
    "caller supplied a map" would leave every defense unresolved, which is worse
    than the bug this replaced. The supplied map is layered over the static one.
    """
    # LAR is on the static BOARD, so an empty active map must still resolve it.
    raw = [["Los Angeles Rams", "LAR", "DEF", "Los Angeles Rams LAR - DEF"]]
    names, _, _ = dd.normalize_available(raw, def_map={})
    assert names == ["Rams"], names
    # ...and a code the static tuple knows, via an active map that lacks it.
    names, _, _ = dd.normalize_available(raw, def_map={"BAL": "Ravens"})
    assert names == ["Rams"], names


def test_choose_pick_falls_back_off_board_instead_of_none():
    """Issue #11: a board with no available candidate must still yield a pick,
    preferring a slot we still need, rather than returning None (which stalls
    run_draft until Yahoo auto-drafts our slot)."""
    board = {"Rams": {"name": "Rams", "team": "LAR", "pos": "DEF",
                      "adp": None, "ecr": None, "value": 6.0}}
    # Nothing on our board is available; Yahoo is showing assorted players.
    available = ["Some Kicker", "Some RB", "Another WR"]
    pos_map = {"some kicker": "K", "some rb": "RB", "another wr": "WR"}
    adp_map = {"some kicker": 150.0, "some rb": 40.0, "another wr": 60.0}

    # Every slot filled except K, round 14 (K/DEF window open): take the kicker
    # even though the RB has a better (lower) ADP, because we NEED the slot.
    need_k = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "DEF": 1}
    pick = dd.choose_pick(available, need_k, 14, board,
                          adp_map=adp_map, pos_map=pos_map)
    assert pick is not None, "must fall back, not return None"
    assert pick[0] == "Some Kicker", pick

    # Mid-draft with every slot filled: take the best (lowest) ADP available.
    drafted = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
    pick = dd.choose_pick(available, drafted, 5, board,
                          adp_map=adp_map, pos_map=pos_map)
    assert pick is not None
    assert pick[0] == "Some RB", pick   # lowest ADP among timing-legal names

    # Timing guards still hold in the fallback: a K is not draftable in round 5.
    pick = dd.choose_pick(["Some Kicker"], {"QB": 1, "RB": 2, "WR": 2, "TE": 1},
                          5, board, adp_map={"some kicker": 150.0},
                          pos_map={"some kicker": "K"})
    assert pick is None, "K must not be drafted before its window even in fallback"

    # Genuinely nothing available -> None (nothing we can do).
    assert dd.choose_pick([], {}, 5, board, adp_map={}, pos_map={}) is None


def test_board_has_enough_candidates_per_required_position():
    """10-team draft: each forced one-slot position (QB, TE, K, DEF) must have
    exactly 10 BOARD candidates so the anchor-driven forced pick can always fill
    the slot even if rivals snipe the top names before our anchor round."""
    from collections import Counter
    counts = Counter(pos for (_, _, pos, _) in dd.BOARD)
    for pos in ("QB", "TE", "K", "DEF"):
        assert counts[pos] == 10, "%s has %d candidates (expected 10)" % (pos, counts[pos])
    assert len(dd.BOARD) == 67, "BOARD has %d players (expected 67)" % len(dd.BOARD)


def _run_draft_controlled(off_window_name, on_window_names):
    """Drive run_draft() end-to-end with every external dependency faked, so we
    can assert the issue #23 off-window search wiring without a live browser.

    `choose_pick` always returns `off_window_name`; `read_available` only ever
    surfaces `on_window_names`. Returns call counters for search_player/click.
    """
    calls = {"search": 0, "click": 0}
    saved = {}

    def patch(attr, val):
        saved[attr] = getattr(dd, attr)
        setattr(dd, attr, val)

    # Make the draft loop exit after the first pick by leaping the clock forward
    # on every time.time() call so the ~3h deadline is exceeded immediately.
    clock = [_realtime.time()]

    def fake_time():
        clock[0] += 10_000
        return clock[0]

    patch("connect", lambda: "WS")
    patch("navigate", lambda ws, url: None)
    patch("verify_session", lambda ws: True)
    patch("log_deploy_identity", lambda: None)
    patch("load_original_board", lambda: {})
    patch("read_available",
          lambda ws: [[n, "c", "RB", "ADP 9"] for n in on_window_names])
    patch("normalize_available",
          lambda raw, def_map=None: ([r[0] for r in raw], {}, {}))
    patch("choose_pick", lambda *a, **k: (off_window_name, "Tm", "RB", 99))
    patch("search_player",
          lambda ws, name, team=None, pos=None: (calls.__setitem__("search", calls["search"] + 1)
                            or [name, "c9", "RB", "ADP 99"]))
    patch("click_player",
          lambda ws, name, team=None, pos=None: (calls.__setitem__("click", calls["click"] + 1)
                            or True))
    patch("is_my_pick", lambda ws: True)
    patch("_confirm_pick", lambda ws, name, timeout=8: True)
    patch("log", lambda *a, **k: None)
    patch("ev", lambda ws, js: "")
    patch("time", type("T", (), {
        "time": staticmethod(fake_time),
        "sleep": staticmethod(lambda *a, **k: None),
    })())
    patch("random", type("R", (), {
        "uniform": staticmethod(lambda a, b: 1.0),
    })())
    try:
        dd.run_draft()
    finally:
        for attr, val in saved.items():
            setattr(dd, attr, val)
    return calls


def test_off_window_target_triggers_search_player():
    """Issue #23: a chosen player absent from read_available()'s virtualized
    40-row window must be searched (filtering Yahoo's DOM to that player)
    before the click, so a deep target (e.g. row 60) is still selectable."""
    calls = _run_draft_controlled("Deep Sleeper", ["Vis A", "Vis B"])
    assert calls["search"] == 1, calls
    assert calls["click"] == 1, calls


def test_on_window_target_skips_search_player():
    """Negative control: a target already in the visible 40-row window is
    clicked directly, with no extra Yahoo search round-trip."""
    calls = _run_draft_controlled("Vis A", ["Vis A", "Vis B"])
    assert calls["search"] == 0, calls
    assert calls["click"] == 1, calls


def test_search_player_rejects_wrong_identity_and_clears_search(monkeypatch):
    queries = []
    monkeypatch.setattr(dd, "_set_player_search",
                        lambda ws, query: queries.append(query) or True)
    monkeypatch.setattr(dd, "read_available", lambda ws: [
        ["A. Brown", "DET", "WR", "A. Brown DET - WR"],
    ])
    monkeypatch.setattr(dd.time, "sleep", lambda seconds: None)

    assert dd.search_player("WS", "A.J. Brown", "PHI", "WR") is None
    assert queries == ["A.J. Brown", ""]


def test_search_player_matches_abbreviation_team_and_position(monkeypatch):
    monkeypatch.setattr(dd, "_set_player_search", lambda ws, query: True)
    row = ["A. Brown", "PHI", "WR", "A. Brown PHI - WR"]
    monkeypatch.setattr(dd, "read_available", lambda ws: [row])
    monkeypatch.setattr(dd.time, "sleep", lambda seconds: None)

    assert dd.search_player("WS", "A.J. Brown", "PHI", "WR") == row


def test_forced_anchor_searches_hidden_required_position(monkeypatch):
    board = {
        "Ravens": {"name": "Ravens", "team": "BAL", "pos": "DEF", "value": 10},
        "Steelers": {"name": "Steelers", "team": "PIT", "pos": "DEF", "value": 9},
    }
    calls = []

    def fake_search(ws, name, team, pos):
        calls.append((name, team, pos))
        if name == "Steelers":
            return [name, team, pos, "%s %s - %s" % (name, team, pos)]
        return None

    monkeypatch.setattr(dd, "search_player", fake_search)
    drafted = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1}
    row = dd.search_forced_anchor(
        "WS", board, drafted, dd.TOTAL_ROUNDS, ["Skill Player"])

    assert row is not None
    assert row[:3] == ["Steelers", "PIT", "DEF"]
    assert calls == [("Ravens", "BAL", "DEF"), ("Steelers", "PIT", "DEF")]


if __name__ == "__main__":
    test_fetch_fp_consensus_keeps_zero_adp()
    test_build_value_board_full_coverage_with_zero_adp()
    test_build_value_board_ecr_only_when_adp_absent()
    test_build_value_board_matches_def_by_team_id()
    test_unmatched_players_deprioritized()
    test_parse_adp()
    test_choose_pick_uses_yahoo_adp()
    test_scarcity_premium_anchors_rb_over_higher_value_wr()
    test_anchor_forces_rb_on_schedule()
    test_build_value_board_static_fallback_without_key()
    test_build_value_board_uses_realtime_adp()
    test_normalize_available_maps_def_code_to_board_name()
    test_board_has_enough_candidates_per_required_position()
    print("All draft-driver tests passed.")
