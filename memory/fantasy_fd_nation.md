# Fantasy Football — League "FD nation" (Yahoo, ID 1329011)

Persistent context for the user's Yahoo Fantasy Football league. Load this whenever
the user mentions fantasy football, their league, the draft, lineup, waivers, or Edge/CDP.

## League facts (verified 2026-08-20 via live Edge CDP)
- Platform: Yahoo Fantasy Football, league ID **1329011**, name **"FD nation"**.
- Manager: user is **"Doge"**, team **#2** (URL team id = 2). **10 teams** (verified 2026-08-28 via live Edge CDP — the FD nation Teams page listed exactly 10 teams; Yahoo Settings confirms "Max Teams: 10"; the earlier "12 teams" claim was incorrect). Known teams (10 total observed 08-28, 7 named): Goal Line Dwayne (commish), Game Plan buy, Take it in the Browns, Kwasi's Wins, QB Sneak Christopher, Otto-matic Win!, Neal Before Zod.
- Format: Head-to-Head, **.5 PPR** (Receptions = 0.5), fractional points ON, negative points ON.
- Roster: 1 QB, 2 WR, 2 RB, 1 TE, 1 W/R/T (flex), 1 K, 1 DEF, 6 BN, 2 IR (15 active + 2 IR).
- Draft: **Live Standard snake**, 15 rounds, **1 minute per pick**, scheduled **Tue Sep 1 2026, 5:00pm EDT** (= 2026-09-02 06:00 JST on this machine). *Corrected 2026-08-28 from the live Yahoo tab — repo had Aug 28; actual draft is Sep 1.*
- Not a cash league. Playoffs top 4, Weeks 16-17.
- Waiver: 2-day rolling list; trade review by league vote; max acquisitions unlimited.

## Draft strategy (user-approved)
- Format: **10-team** .5 PPR snake. Draft from the **original nflverse-derived
  board** (default; zero third-party feed) — `python cli.py original-board` builds
  `data/board/original_board.json` from our own projections (skill), kicking columns
  (K), and derived team defense (DEF); the deployed driver reads it and drafts
  best-player-available by projected value + 10-team scarcity/anchor guardrails.
  FantasyPros (ECR + Real-Time ADP) is now an **opt-in legacy cross-check** used
  only when `DRAFT_ENGINE=fantasypros` is set explicitly (and a key is present); the
  mere presence of `FP_API_KEY` does NOT switch engines. Yahoo ADP is a live per-turn
  patch used only in that legacy mode. Without a crowd signal we forfeit `VALUE = ADP − ECR`
  (crowd-arbitrage); the original engine maximizes our own expected points.
- 10-team scarcity anchoring: RB is the scarcest position, so the bot (a) adds a
  soft +8 value premium to RBs we still need (anchors them early despite the
  crowd's RB inflation) and (b) hard-forces slots by `ANCHOR_BY_ROUND`: 1st RB by
  R3, 2nd RB by R5, WR by R5/R9, TE by R7, QB by R10, K/DEF by R14.
- BOARD depth for 10-team: ~67 players (10 QBs, 10 TEs, 10 Ks, 10 DEFs) so a required
  slot is never stranded if the crowd snipes the top names before our anchor turn.
- Other guardrails: no QB before round 10; K/DEF only last 2 rounds; don't double
  a position past its slot count; ADP sanity window (don't reach absurdly above ADP).
- Safety net: Yahoo DEFAULT pre-rank (ADP-based) is the auto-draft fallback. User accepted this (custom Edit-My-Rankings UI was too fragile to automate safely — Yahoo uses a JS drag widget with no stable controls).
- Do-not-draft list: **none** (user confirmed).

## Engineering setup (verified working)
- Edge launched by user on **port 9222** with `--remote-allow-origins=*` (and the original `--user-data-dir=C:\edge-debug-profile`). This is REQUIRED for CDP WebSocket control. Without the flag, Edge rejects WS with 403.
- **Security:** the CDP debug port (9222) is a full browser-control interface. Bind Edge to loopback only (`--remote-debugging-address=127.0.0.1`) and ensure no firewall/port-forward exposes 9222 to the network — anyone who reaches it can drive the browser and read the logged-in Yahoo session. Close Edge when not drafting.
- Control from WSL is NOT possible directly (WSL2 separate netns). Driver runs on the **Windows side via `py.exe`** where `websocket-client` 1.9.0 is installed (pip into Windows Python 3.13).
- Windows Python launcher: `py.exe` = C:\Users\user\AppData\Local\Programs\Python\Python313-32\python.exe. `websocket-client` installed there.
- Output/artifacts dir on Windows: `C:\edge-debug-profile\`.
- Human-like input layer: quadratic Bézier mouse paths + per-step jitter + variable think delays, dispatched as real CDP Input.dispatchMouseEvent. navigator.webdriver=false on the page (no automation banner).

## Live draft driver (deployed)
- Script: `C:\edge-debug-profile\draft_driver.py` (also at /home/eml/draft_driver.py).
- Scheduled Windows task **"FDnationDraftDriver"**: fires **2026-09-01 17:00 EDT (= 2026-09-02 06:00 JST)**, runs `py.exe C:\edge-debug-profile\draft_driver.py`. Rescheduled 2026-08-28 after the live tab showed Sep 1 (was Aug 28).
- Decision log: `C:\edge-debug-profile\draft_log.txt` (created at first run).
- CRITICAL dependency: Edge must be OPEN on 9222 with --remote-allow-origins=* at draft time, or the driver errors and Yahoo default auto-draft takes over.

## Mock draft validation — 2026-08-28 (CLOSES the "pick-clicking untested" gap)
Goal: prove the previously-untested CDP PICK-CLICK path (`read_available` →
`choose_pick` → `click_player` → `_confirm_pick`) works end to end BEFORE the
real Yahoo room opens on Sep 1. Driven through the **live Edge on 127.0.0.1:9222**
in a NEW CDP tab (user's Yahoo tab untouched) against a Yahoo-style mock room
(`tools/mock_draft_room.html`) that exposes a `window.MockDraft` API.

Method: `tools/mock_draft_run.py` injects the REAL 119-player original board +
filler, runs a full 15-round snake for team #2, and calls the DEPLOYED driver's
REAL functions on every turn (no reimplementation). Opponents are simulated
(biased to snipe board players) so scarcity/anchor guardrails are exercised.

**Result: 15/15 picks clicked + confirmed via CDP; final roster LEGAL
(QB=4 RB=6 WR=2 TE=1 K=1 DEF=1); `NO_FAILURES`.**

Bugs the mock caught and were fixed in `driver/draft_driver.py` (all real, would
have broken the live draft):
1. **`click_player` clicked the first enabled "Draft" button on the page, not the
   chosen player's row button.** The displayed list is Yahoo-sorted (ADP/board
   order), so our value pick is rarely the top row → the bot drafted the WRONG
   players. Fixed: scope the button search to the chosen player's own row.
2. **`read_available` regex required a two-word name, so single-word team-defense
   names ("Ravens BAL - DEF") never parsed** → the bot could NEVER draft a defense
   → illegal lineup. Fixed: allow 1-3 word names.
3. **`choose_pick` had no bench phase** (returned `None` once REQUIRED slots were
   filled) → bot made only 7 of 15 picks. Fixed: fallback now drafts best-available
   for bench (still respecting K/DEF-last + QB-round timing guards).
4. (mock-only) drafted players were rendered as `<li>`, so `read_available`'s
   `tr,li` scan re-scanned them as available and the bot tried to re-draft them.
   Fixed in the mock: drafted list uses `<div>`.

Honest remaining gap: the mock validates the driver's click/confirm *mechanics*
using the real deployed functions against a Yahoo-style DOM. The REAL Yahoo room's
exact markup (draft-button label/position, live ADP parsing) can only be confirmed
on Sep 1 — but the logic that finds, clicks, and confirms a pick is now proven.

## Proven skills (see /home/eml/.hermes/skills/)
- `edge-cdp`: connect to Edge 9222, human-like input helpers.
- `fantasy-read`: read roster/standings/matchups/waivers from the live tab.
- `fantasy-draft`: the live draft driver + scheduler + board.

## Honest limitations
- The driver's PICK-CLICKING logic was UNTESTED against the live Yahoo room →
  **MOCK-VALIDATED 2026-08-28** (see above). Remaining gap: the REAL Yahoo room's
  exact DOM (draft-button label/position, ADP parsing) is only confirmable on Sep 1;
  the mock proves the click/confirm *mechanics* via the real deployed functions.
- I cannot guarantee wins — real NFL games decide outcomes. The system maximizes expected value and avoids timer-expiry/panic mistakes.
- WSL↔Windows: /mnt/c is unreliable from this shell; use `py.exe -` (stdin) and PowerShell base64 round-trips to move data reliably.
