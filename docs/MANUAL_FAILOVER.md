# Manual failover plan — FD nation auto-draft

**Draft:** Tue Sep 1 2026, 5:00pm EDT · 10-team .5 PPR · 15-round snake · 1 min/pick ·
team #2 "Doge".

The auto-driver (`C:\edge-debug-profile\draft_driver.py`, scheduled task
`FDnationDraftDriver`) is the primary path. This document is the **fallback** if it
cannot run or clearly fails. Work down the tiers in order.

> **Rule of thumb:** if the bot is drafting, *leave it alone.* Only switch to manual
> failover when the bot is (a) not running, (b) missing picks, or (c) making obviously
> wrong picks. The companion `docs/DRAFT_CHEAT_SHEET.md` is your pick list for Tier 3.

---

## Tier 0 — Primary: the auto-driver (hands off)

- Scheduled task `FDnationDraftDriver` fires **2026-09-01 17:00 EDT** and runs
  `py.exe C:\edge-debug-profile\draft_driver.py`.
- **Hard requirement:** Edge must be OPEN on `127.0.0.1:9222` with
  `--remote-allow-origins=*` at draft time, or the driver errors and **Yahoo's default
  auto-draft takes over** (which is itself a failover — see Tier 2).
- `run_draft()` logs `DEPLOY_GIT_SHA=<sha> FILE_SHA256=<12-char hash>` at startup into
  `C:\edge-debug-profile\draft_log.txt`. The first lines prove which code actually ran.
- On any pick it cannot make, it logs `NO_VALID_PICK` and **yields to Yahoo auto-draft**
  rather than stalling — so a partial failure degrades gracefully instead of freezing.

---

## Tier 1 — Manual re-trigger of the driver

Use if the scheduled task didn't fire, or the driver errored at launch (e.g. Edge
wasn't up yet).

1. Confirm Edge is open with remote debugging: browse
   `http://127.0.0.1:9222/json/version` — you should get a JSON blob, not an error.
   If not, relaunch Edge with
   `--remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir=C:\edge-debug-profile`.
2. Run the driver manually:
   `py.exe C:\edge-debug-profile\draft_driver.py`
3. Watch `draft_log.txt`; the first pick should appear within ~50s of your turn.

This requires Windows-side Python with `websocket-client` (the repo's `.venv` or the
system `py.exe`). It will not work from WSL.

---

## Tier 2 — Yahoo native auto-draft (pre-ranked)

If CDP/Edge can't be fixed in time, let Yahoo draft for you using the order you set in
**Edit My Rankings / Pre-Draft Rankings**. This is the accepted safety net — but it is
only as good as the order you pre-set.

**This must be prepared BEFORE the draft (see checklist).** Seed it from the positional
menus in `docs/DRAFT_CHEAT_SHEET.md` (drag your top RBs/WRs/TEs/QB/K/DEF to the top, in
roughly that priority). Yahoo's own default order is ADP-based and acceptable, but a
board-aligned order beats it.

To hand control to Yahoo: do nothing — if the bot never connects, Yahoo auto-drafts on
its default timer. To *force* it mid-draft after stopping a broken bot, just stop the
bot (Tier 1 process / close Edge) and let the clock run out on your pick.

---

## Tier 3 — Full manual drafting (human at the keyboard)

Use the cheat sheet. You are already logged into Yahoo in Edge, so you can draft directly
in the room.

1. Open `docs/DRAFT_CHEAT_SHEET.md`. Your 15 picks and their approx. clock times are
   listed (e.g. pick 2 ≈ 17:01, pick 19 ≈ 17:18, … pick 142 ≈ 19:21 EDT).
2. On each of your turns, draft the **best available player that fits your needs**,
   following the anchor rules:
   - Rounds 1–5: RB/WR. Anchor **2nd RB by R5**, **WR by R5/R9**.
   - **TE by ~R7.** **No QB before R10.** **K/DEF only R14–15.**
   - If a stud falls way past his ADP, take him even if it bends the timeline.
   - Fill the 6 bench spots with best remaining value (usually WR/RB).
3. Use the per-position menus as your "who's left" list; the Suggested table is a *guide*,
   not a script — opponents won't draft the same way.

You have **1 minute per pick**. That is plenty for "best player on the sheet that fits."

---

## How to detect failure (during the draft)

- **Before your first pick (≈17:01):** if nothing has been drafted for team "Doge" and
  the clock is ticking, the bot isn't connected. Jump to Tier 1, then Tier 2/3.
- **Mid-draft:** if your turn comes and goes with no pick (Yahoo auto-picks a random
  player, or the timer expires), the bot missed it. Check `draft_log.txt` tail.
- **Wrong players:** if the bot drafts a K in round 3 or ignores a top WR, something is
  off — consider stopping it (Tier 1 process / close Edge) and taking over manually
  (Tier 3) for the rest.
- **First sanity check always:** read the top of `draft_log.txt`. If `DEPLOY_GIT_SHA`
  doesn't match the latest (currently `d1a027c…`) or `FILE_SHA256` looks stale, the
  running code is not the fixed version — re-run `tools/deploy.ps1` and Tier 1.

---

## Pre-draft checklist (do this before Sep 1)

- [ ] Print or save `docs/DRAFT_CHEAT_SHEET.md` to your phone (you'll want it away from
      the drafting PC).
- [ ] Set Yahoo **Edit My Rankings / Pre-Draft Order** from the cheat-sheet menus (powers
      Tier 2). Do it now, not at draft time.
- [ ] Verify Edge launches on 9222: `py.exe tools/edge_alive.py` (or hit
      `http://127.0.0.1:9222/json/version`). Fix the launch shortcut if it fails.
- [ ] Confirm scheduled task `FDnationDraftDriver` is **Enabled** and next run =
      2026-09-02 06:00 JST ( = Sep 1 5:00pm EDT).
- [ ] Confirm `C:\edge-debug-profile\draft_driver.py` + `original_board.json` are present
      and `DEPLOY_SHA.txt` = current HEAD.
- [ ] You're logged into Yahoo in Edge (already true per last check).
- [ ] Have a secondary device ready in case the PC browser is the problem.
- [ ] **Morning of Sep 1:** re-scrape ADP, rebuild the board, re-deploy
      (`tools/deploy.ps1`), then refresh the sheet:
      `py.exe tools/gen_cheat_sheet.py --write`.

---

## Post-failover (bot drafted some, then died)

- Check the roster / `draft_log.txt` to see which slots are already filled.
- Resume manually (Tier 3) drafting only for the **remaining needs** — the cheat sheet's
  anchor rules still apply; just skip positions you already have.
- Don't panic: 1 min/pick gives you time to read the sheet each turn.

---

## Files

- `docs/MANUAL_FAILOVER.md` — this runbook.
- `docs/DRAFT_CHEAT_SHEET.md` — printable pick list (your 15 picks, suggested picks,
  anchor rules, per-position menus). Regenerate morning-of.
- `tools/gen_cheat_sheet.py` — produces the sheet from `data/board/original_board.json`.
- `tools/deploy.ps1` — copies driver + board to `C:\edge-debug-profile` and writes
  `DEPLOY_SHA.txt` (run after any driver/board change).
- `memory/fantasy_fd_nation.md` — full league/driver context.
