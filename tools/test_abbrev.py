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

print("\nALL ABBREV TESTS PASSED")
