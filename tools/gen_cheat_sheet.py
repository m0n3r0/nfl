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


def greedy_suggest(board, picks):
    """A simple best-value-per-need simulation for OUR 15 picks, used only as a
    guide. Opponents are ignored (this is a fallback, not the live bot). Mirrors
    the bot's bench caps so it doesn't hoard QBs/TEs."""
    taken = set()
    # starter needs
    need = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
    # hard totals (starter + bench) — mirrors driver BENCH_CAP discipline
    max_per = {"QB": 2, "TE": 2, "K": 1, "DEF": 1}
    have = {p: 0 for p in need}
    out = []
    for round_, overall in picks:
        avail = [r for r in board if id(r) not in taken]
        gaps, bench = [], []
        for r in avail:
            pos = r["pos"]
            if pos in need and have[pos] < need[pos] and gate(pos, round_):
                gaps.append(r)
            elif gate(pos, round_):
                # respect hard totals for capped positions
                if pos in max_per and have[pos] >= max_per[pos]:
                    continue
                bench.append(r)
        pool = gaps if gaps else bench
        if not pool:
            pool = avail  # desperate fallback: anything
        if gaps:
            best = max(pool, key=lambda x: x["value"])
        else:
            # balance RB/WR on bench picks so the guide looks like a real lineup
            rb_avail = any(r["pos"] == "RB" for r in pool)
            wr_avail = any(r["pos"] == "WR" for r in pool)
            if rb_avail and wr_avail:
                pref = "WR" if have["WR"] <= have["RB"] else "RB"
                sub = [r for r in pool if r["pos"] == pref]
                best = max(sub, key=lambda x: x["value"])
            else:
                best = max(pool, key=lambda x: x["value"])
        taken.add(id(best))
        pos = best["pos"]
        if pos in need and have[pos] < need[pos]:
            have[pos] += 1
        else:
            have[pos] = have.get(pos, 0) + 1
        out.append((round_, overall, best, "starter" if (gaps and best in gaps) else "bench/flex"))
    return out


def fmt_player(r):
    adp = r.get("adp")
    adp_s = f"ADP {adp:.0f}" if isinstance(adp, (int, float)) else "ADP -"
    return f"{r['name']} ({r['team']} - {r['pos']})  val {r['value']:.0f}  {adp_s}"


def main():
    write = "--write" in sys.argv
    board = load_board()
    by = rank_by_pos(board)
    picks = our_pick_numbers(OUR_TEAM, N_TEAMS, ROUNDS)
    suggested = greedy_suggest(board, picks)

    L = []
    L.append("# FD nation — Manual Draft Cheat Sheet (team #2 \"Doge\")")
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
        with open("docs/DRAFT_CHEAT_SHEET.md", "w") as f:
            f.write(text)
        print("wrote docs/DRAFT_CHEAT_SHEET.md")
    else:
        print(text)


if __name__ == "__main__":
    main()
