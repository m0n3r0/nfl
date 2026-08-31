#!/usr/bin/env python3
"""Generate a printable draft cheat sheet for team #2 ("Doge") in the FD nation
Yahoo league. This is the MANUAL FAILOVER artifact: if the auto-driver
(draft_driver.py via CDP) cannot run, a human drafts from this sheet.

It is reproducible: re-run after the morning-of ADP re-scrape / board rebuild to
refresh the numbers.

    py.exe tools/gen_cheat_sheet.py            # prints to stdout
    py.exe tools/gen_cheat_sheet.py --write    # also writes docs/DRAFT_CHEAT_SHEET.md

Strategy mirrors the bot's anchors (see memory/fantasy_fd_nation.md):
RB scarcest -> anchor RB early; WR early; TE by ~R7; QB not before R10;
K/DEF only R14-15. Value = projected points; ADP = league average pick.
"""
import json
import sys
import datetime

BOARD = "data/board/original_board.json"
N_TEAMS = 10
OUR_TEAM = 2          # 1-indexed team number in Yahoo
ROUNDS = 15
DRAFT_START = datetime.time(17, 0)   # 5:00pm EDT, Tue Sep 1 2026
PICK_SECONDS = 60     # 1 minute per pick


def our_pick_numbers(team, n, rounds):
    out = []
    for r in range(1, rounds + 1):
        overall = (r - 1) * n + team if r % 2 == 1 else r * n - team + 1
        out.append((r, overall))
    return out


def pick_clock(overall):
    # overall pick #1 starts at DRAFT_START; each pick is PICK_SECONDS later.
    secs = (overall - 1) * PICK_SECONDS
    base = datetime.datetime.combine(datetime.date(2026, 9, 1), DRAFT_START)
    t = base + datetime.timedelta(seconds=secs)
    return t.strftime("%H:%M EDT")


def load_board():
    with open(BOARD) as f:
        return json.load(f)


def rank_by_pos(board):
    by = {}
    for r in board:
        by.setdefault(r["pos"], []).append(r)
    for p in by:
        by[p].sort(key=lambda x: (-x["value"], x.get("adp") or 999))
    return by


def gate(pos, round_):
    """When is a position eligible to be drafted (starter or bench)?"""
    if pos in ("RB", "WR", "TE"):
        return True                      # flex/bench always OK
    if pos == "QB":
        return round_ >= 10
    if pos in ("K", "DEF"):
        return round_ >= 14
    return False


def snake_teams(n, rounds):
    """Return a list of team numbers in draft order (snake). Index i -> team of
    overall pick i+1."""
    order = []
    for r in range(1, rounds + 1):
        seq = list(range(1, n + 1)) if r % 2 == 1 else list(range(n, 0, -1))
        order.extend(seq)
    return order


def simulate(board, our_team, n, rounds):
    """Simulate the WHOLE draft (all teams) so the suggested picks reflect when
    players actually come off the board. Opponents draft for need by league ADP
    (like a typical league); WE draft by the bot's anchors + value, force-filling
    the single-copy slots (QB/K/DEF) at their anchor rounds. Returns our 15 picks."""
    order = snake_teams(n, rounds)
    taken = set()
    need = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
    max_per = {"QB": 2, "TE": 2, "K": 1, "DEF": 1}
    have = {p: 0 for p in need}
    opp_need = {t: dict(need) for t in range(1, n + 1)}
    # single-copy starters forced at their anchor round if still needed
    force = (("TE", 6), ("QB", 10), ("K", 14), ("DEF", 14))
    out = []
    for idx, team in enumerate(order):
        overall = idx + 1
        round_ = (overall - 1) // n + 1
        avail = [r for r in board if id(r) not in taken]
        if not avail:
            break
        if team == our_team:
            best = None
            role = "bench/flex"
            # force-fill single-slot starters at anchor round if still open
            for pos, gr in force:
                if have.get(pos, 0) < need.get(pos, 0) and round_ >= gr:
                    cands = [r for r in avail if r["pos"] == pos]
                    if cands:
                        best = max(cands, key=lambda x: x["value"])
                        role = "starter"
                        break
            if best is None:
                gaps, bench = [], []
                for r in avail:
                    pos = r["pos"]
                    if pos in need and have[pos] < need[pos] and gate(pos, round_):
                        gaps.append(r)
                    elif gate(pos, round_):
                        if pos in max_per and have[pos] >= max_per[pos]:
                            continue
                        bench.append(r)
                pool = gaps if gaps else bench
                if not pool:
                    pool = avail
                if gaps:
                    best = max(pool, key=lambda x: x["value"])
                    role = "starter"
                else:
                    rb = any(r["pos"] == "RB" for r in pool)
                    wr = any(r["pos"] == "WR" for r in pool)
                    if rb and wr:
                        pref = "WR" if have["WR"] <= have["RB"] else "RB"
                        best = max([r for r in pool if r["pos"] == pref],
                                   key=lambda x: x["value"])
                    else:
                        best = max(pool, key=lambda x: x["value"])
            pos = best["pos"]
            if pos in need and have[pos] < need[pos]:
                have[pos] += 1
            else:
                have[pos] = have.get(pos, 0) + 1
            out.append((round_, overall, best, role))
        else:
            # opponent: draft for need by league ADP (lowest ADP first)
            oneed = opp_need[team]
            need_avail = [r for r in avail
                          if r["pos"] in oneed and oneed[r["pos"]] > 0]
            pool_o = need_avail if need_avail else avail
            best = min(pool_o, key=lambda x: (
                x.get("adp") if isinstance(x.get("adp"), (int, float)) else 999,
                -x["value"]))
            pos = best["pos"]
            if pos in oneed:
                oneed[pos] -= 1
        taken.add(id(best))
    return out


def fmt_player(r):
    adp = r.get("adp")
    adp_s = f"ADP {adp:.0f}" if isinstance(adp, (int, float)) else "ADP -"
    return f"{r['name']} ({r['team']} - {r['pos']})  val {r['value']:.0f}  {adp_s}"


def main():
    write = "--write" in sys.argv
    team = OUR_TEAM
    if "--team" in sys.argv:
        team = int(sys.argv[sys.argv.index("--team") + 1])
    out = "docs/DRAFT_CHEAT_SHEET.md"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    board = load_board()
    by = rank_by_pos(board)
    picks = our_pick_numbers(team, N_TEAMS, ROUNDS)
    suggested = simulate(board, team, N_TEAMS, ROUNDS)

    L = []
    L.append(f"# FD nation — Manual Draft Cheat Sheet (team #{team} \"Doge\")")
    L.append("")
    L.append(f"_Generated {datetime.datetime.now():%Y-%m-%d %H:%M} from "
             f"`data/board/original_board.json` ({len(board)} players). "
             "Re-run `tools/gen_cheat_sheet.py --write` after the morning-of "
             "ADP re-scrape to refresh._")
    L.append("")
    L.append("## Your 15 picks (snake, 10-team, 1 min/pick)")
    L.append("")
    L.append("| Round | Overall pick | Approx. clock |")
    L.append("|---|---|---|")
    for r, o in picks:
        L.append(f"| {r} | {o} | {pick_clock(o)} |")
    L.append("")
    L.append("## Suggested pick by round (GUIDE — draft best available that fits your needs)")
    L.append("")
    L.append("| R | Overall | Player | Role |")
    L.append("|---|---|---|---|")
    for r, o, p, role in suggested:
        L.append(f"| {r} | {o} | {p['name']} ({p['team']} - {p['pos']}) val {p['value']:.0f} | {role} |")
    L.append("")
    L.append("## Anchor rules (same as the bot)")
    L.append("- Rounds 1-5: take RB/WR. Anchor **2nd RB by R5**, **WR by R5/R9**.")
    L.append("- **TE by R7** (target the TE on your list around R6-R8).")
    L.append("- **No QB before R10.** Take your QB in R10-R12.")
    L.append("- **K and DEF only in R14-R15.**")
    L.append("- If a stud falls way past ADP, take him even if it bends the timeline.")
    L.append("- Fill the 6 bench spots with best remaining value (usually WR/RB).")
    L.append("")
    L.append("## Position menus (top of board by projected value)")
    L.append("")
    for pos in ("RB", "WR", "TE", "QB", "DEF", "K"):
        L.append(f"### {pos}")
        for i, r in enumerate(by.get(pos, [])[:18], 1):
            L.append(f"{i:>2}. {fmt_player(r)}")
        L.append("")
    L.append("---")
    L.append("_This sheet is the failover for the CDP auto-driver. If the bot is "
             "running, IGNORE this sheet and let it draft. Only use it if the bot "
             "cannot start or has clearly failed._")

    text = "\n".join(L) + "\n"
    if write:
        with open(out, "w") as f:
            f.write(text)
        print(f"wrote {out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
