"""Shared opponent (rival) pick model for the draft tools.

Both tools/simulate_draft.py and tools/gen_cheat_sheet.py simulate the other
nine managers, and they must agree on how rivals behave: fill starting slots
first, then take best available for the bench -- but never hoard. One starter,
occasionally a backup, never a pile, and no K/DEF before the final two rounds
or QB before round 5.

History: the uncapped bench path let every rival stack the highest-raw-value
position on every pick -- all 32 QBs in simulate_draft (issue #20), all 28
kickers by round 13 in gen_cheat_sheet, which made the cheat sheet's own
force-fill K step no-op and prescribed a roster with zero kickers (issue #52).
"""

# Realistic per-team totals: past these a rival stops reaching for the
# position even if its projection is high, exactly as a human would.
RIVAL_CAP = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 1, "DEF": 1}


def legal(pos, rnd, total_rounds):
    """Position timing gates: no K/DEF before the last two rounds, no QB early."""
    if pos in ("K", "DEF") and rnd < total_rounds - 1:
        return False
    if pos == "QB" and rnd < 5:
        return False
    return True


def room_for(pos, roster):
    return roster.get(pos, 0) < RIVAL_CAP.get(pos, 99)


def opponent_pick(cands, roster, rnd, required, total_rounds, key):
    """Pick one player for a rival.

    cands: list of available board dicts (must have "pos"; ranking is via key).
    roster: position -> count mapping for this rival (Counter or dict).
    required: position -> starters needed (e.g. driver.REQUIRED).
    key: ranking function; the rival takes the max by this key.
    Returns the chosen board dict, or None if nothing is draftable.
    """
    if not cands:
        return None

    # 1) Fill a required starting slot we still need (and have room for).
    for pos, need in required.items():
        if roster.get(pos, 0) < need and room_for(pos, roster):
            best = max((v for v in cands
                        if v["pos"] == pos and legal(pos, rnd, total_rounds)),
                       key=key, default=None)
            if best is not None:
                return best
    # 2) Best available we still have room for (bench), rounding out the
    #    roster instead of stacking one position.
    best = max((v for v in cands
                if legal(v["pos"], rnd, total_rounds) and room_for(v["pos"], roster)),
               key=key, default=None)
    if best is not None:
        return best
    # 3) Last resort: anything legal (a deep board makes this unreachable).
    return max((v for v in cands if legal(v["pos"], rnd, total_rounds)),
               key=key, default=None)
