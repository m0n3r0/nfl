"""Verify the Yahoo abbreviated-name -> full board-name resolution (P0 fix)."""
import sys
sys.path.insert(0, r"C:\nfl-win\driver")
import draft_driver as dd

print("ABBREV_TO_FULL size:", len(dd.ABBREV_TO_FULL))
print("NAME_TO_TEAM size:", len(dd.NAME_TO_TEAM))

# 1) Reverse map must resolve a Yahoo-style abbreviated key to the full board name.
key = dd._norm_name("Joe Burrow", "Cin")
print("key Joe Burrow/Cin ->", repr(key), "resolves ->", dd.ABBREV_TO_FULL.get(key))

# 2) normalize_available must turn an abbreviated Yahoo row into the full board name.
raw = [["J. Burrow", None, None, "J. Burrow CIN - QB ADP 5"]]
names, adp, pos = dd.normalize_available(raw, def_map={})
print("abbrev row -> name:", repr(names[0]), "| pos_map:", pos)

# 3) to_display must turn a full board name back into the abbreviated DOM form.
print("to_display('Joe Burrow','Cin') ->", repr(dd.to_display("Joe Burrow", "Cin")))

# 4) Collision case: A.J. Brown (NE) vs Amon-Ra St. Brown (DET) must NOT cross-resolve.
raw_ne = [["A. Brown", None, None, "A. Brown NE - WR ADP 20"]]
raw_det = [["A. Brown", None, None, "A. Brown DET - WR ADP 20"]]
n_ne, _, _ = dd.normalize_available(raw_ne, def_map={})
n_det, _, _ = dd.normalize_available(raw_det, def_map={})
print("A. Brown NE ->", repr(n_ne[0]))
print("A. Brown DET ->", repr(n_det[0]))

# 5) Full-name input must still pass through unchanged (backward compat with local mock).
raw_full = [["Joe Burrow", None, None, "Joe Burrow CIN - QB ADP 5"]]
nf, _, _ = dd.normalize_available(raw_full, def_map={})
print("full-name row -> name:", repr(nf[0]))

assert names[0] == "Joe Burrow", "abbrev failed to resolve"
assert n_ne[0] != n_det[0], "collision not disambiguated by team"
assert nf[0] == "Joe Burrow", "full-name broken"

# 6) read_available()'s name regex must NOT chop the initial ("J. Burrow" -> "Burrow")
#    nor drop the "Mc" in "McCaffrey". Replicates the in-browser JS regex in Python.
import re
JS_RE = re.compile(r"^(?:\d+\.?\s*)?(.*?)\s+([A-Za-z]{2,4})\s*-\s*(QB|RB|WR|TE|K|DEF|DST)")
checks = {
    "J. Burrow CIN - QB ADP 5": "J. Burrow",
    "A.J. Brown NE - WR ADP 12": "A.J. Brown",
    "Christian McCaffrey SF - RB ADP 2": "Christian McCaffrey",
    "Amon-Ra St. Brown DET - WR ADP 15": "Amon-Ra St. Brown",
    "Ja'Marr Chase Cin - WR ADP 8": "Ja'Marr Chase",
    "Ravens BAL - DEF ADP 180": "Ravens",
    "12. Breece Hall NYJ - RB ADP 20": "Breece Hall",
    "C. Little Jax - K ADP 200": "C. Little",
}
for txt, exp in checks.items():
    mm = JS_RE.search(txt)
    assert mm and mm.group(1) == exp, \
        "regex %r -> %r, expected %r" % (txt, mm.group(1) if mm else None, exp)
print("read_available regex keeps abbreviated+full names intact")

# 7) ACTIVE-board coverage. The module-level maps are built from the 67-player
#    static BOARD tuple, but the draft engine runs on the 250-player JSON board --
#    which left ~198 players unresolvable (they fell to the raw-ADP fallback).
#    rebuild_abbrev_maps() must make EVERY active board player resolvable.
from collections import defaultdict  # noqa: E402

board = dd.load_original_board()
before = sum(1 for v in board.values()
             if v.get("name") and dd._norm_name(v["name"], v.get("team")) in dd.ABBREV_TO_FULL)
n_indexed = dd.rebuild_abbrev_maps(board)
after = sum(1 for v in board.values()
            if v.get("name") and dd._norm_name(v["name"], v.get("team")) in dd.ABBREV_TO_FULL)
print("active board %d players | resolvable before rebuild=%d after=%d"
      % (len(board), before, after))
assert n_indexed >= len(board) - 1, "rebuild indexed only %d of %d" % (n_indexed, len(board))
assert after >= len(board) - 1, "%d board players still unresolvable" % (len(board) - after)
assert before < after, "rebuild was a no-op (expected strictly better coverage)"

# A player the static maps could NOT resolve must now resolve end to end.
target = next(v for v in board.values() if v.get("name") == "Drake Maye")
disp = dd.to_display(target["name"], target.get("team"))
row = [[disp, None, None, "%s %s - QB ADP 30" % (disp, target["team"])]]
nm, _, _ = dd.normalize_available(row, def_map={})
assert nm[0] == "Drake Maye", "active-board rebuild did not resolve %r (got %r)" % (disp, nm[0])
print("active-board rebuild resolves %r -> %r" % (disp, nm[0]))

# 8) Collision safety: when two active players abbreviate to the SAME key and no
#    team code is available, the key must be left unresolvable (None) rather than
#    guessing one of them -- a wrong guess would draft the wrong player.
groups = defaultdict(list)
for v in board.values():
    if v.get("name"):
        groups[dd._norm_name(v["name"], None)].append(v["name"])
amb = sorted(k for k, ns in groups.items() if len(set(ns)) > 1)
assert amb, "expected at least one ambiguous abbreviation on the active board"
for k in amb[:3]:
    got = dd.ABBREV_TO_FULL_NT.get(k, "MISSING")
    assert got is None, "ambiguous key %r must be None, got %r" % (k, got)
print("ambiguous abbrev keys left unmatched (no team code):", amb[:3])

print("\nALL ABBREV TESTS PASSED")
