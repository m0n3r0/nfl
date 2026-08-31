---
name: fantasy-draft
description: "Live-draft driver for the user's Yahoo Fantasy Football league (FD nation, ID 1329011, team 2 'Doge'). Picks by a verified ADP board with automatic guardrails (QB late, K/DEF last, no doubled positions), executes picks with human-like Edge CDP clicks, logs every decision. Also schedules/launches the draft. Use at draft time or to set up the auto-draft safety net."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [Fantasy-Football, Yahoo, Draft, Automation, CDP]
    related_skills: [edge-cdp, fantasy-read]
---

# Fantasy Draft Driver — FD nation (team 2 "Doge")

Live snake draft automation for Yahoo league 1329011. Picks by a verified ADP
board with guardrails, clicks via human-like Edge CDP input, logs to a file.

## League parameters (verified)
- .5 PPR, H2H, 15 rounds, 1 min/pick, snake. 10 teams.
- Roster: 1QB/2WR/2RB/1TE/1WRT/1K/1DEF/6BN/2IR.
- Draft: Tue Sep 1 2026 5:00pm EDT (= 2026-09-02 06:00 JST on this machine).

## The driver script
Source of truth in the repo: `C:\nfl-win\driver\draft_driver.py` — it is the **only**
copy. Deployed to `C:\edge-debug-profile\draft_driver.py` (also
/home/eml/draft_driver.py), which is what actually runs.

> **A repo edit is not live until it is deployed.** Use `powershell -File
> tools/deploy.ps1` — it copies `driver/draft_driver.py` + `data/board/original_board.json`
> to the deploy dir, writes `DEPLOY_SHA.txt` (git SHA), and `Get-FileHash`-verifies both
> copies so a partial deploy fails loudly. The driver logs `DEPLOY_GIT_SHA` /
> `FILE_SHA256` at startup, so `draft_log.txt` proves which code ran.

It:
1. Connects to Edge 9222 (--remote-allow-origins=* required).
2. Opens the draft room, polls for "your pick" (team 2).
3. On your pick: reads available players, chooses highest board player passing
   guardrails:
   - 10-team RB anchor: soft scarcity premium (SCARCITY_FRACTION = 0.10 of the RB
     value spread) on RBs still needed, hard force 1st RB by R3 / 2nd RB by R5
     (ANCHOR_BY_ROUND schedule)
   - no QB before round 10
   - K/DEF only last 2 rounds
   - no doubling a filled position slot
   - ADP sanity window (no absurd reaches)
4. Clicks the player row + Draft/confirm with Bézier+jitter motion.
5. Logs every decision to `C:\edge-debug-profile\draft_log.txt`.

## Board (250 players, in `data/board/original_board.json` — NOT embedded in the script)

Built by `python cli.py original-board` from nflverse data only. 250 players:
QB 32, RB 60, WR 70, TE 32, K 28, DEF 28.

It is deliberately larger than the draft itself: a 10-team x 15-round snake consumes
150 players, and rivals take ~9 names between each of our picks. An earlier 121-player
board ran dry around round 12, at which point the driver stalled and Yahoo auto-drafted
the rest of our team — including the K and DEF slots. `src/draft_board.py` enforces
`MIN_BOARD_SIZE = 250` so that cannot regress.

The ~30-name static `BOARD` tuple inside the driver is **only** the fallback used when
the JSON is missing; it is not the draft board.

## Value metric (live board)
**Default: the original nflverse-derived board** — `python cli.py original-board`
builds `data/board/original_board.json` from our own projections (skill),
kicking columns (K), and derived team defense (DEF); `value = projected 2026
fantasy points`. The deployed driver reads that JSON and drafts
best-player-available by value + 10-team scarcity/anchor guardrails. **No
FantasyPros / Yahoo / third-party feed is used by default.**

FantasyPros (`VALUE = FantasyPros_RT_ADP − FantasyPros_ECR`) is now an **opt-in
legacy cross-check** used only when `DRAFT_ENGINE=fantasypros` is set (and a key is
present); Yahoo ADP is a
live per-turn patch used only in that legacy mode. Full detail in
`docs/DATA_SOURCES.md` (see "Original board engine").

## Run it manually (Windows)
```
py.exe C:\edge-debug-profile\draft_driver.py
```
Requires Edge open on 9222 with --remote-allow-origins=* at that moment.

## Scheduled task (already deployed)
Task "FDnationDraftDriver" fires 2026-09-01 17:00 EDT and runs the driver.
Recreate if needed (PowerShell, Windows side):
```powershell
$py = (Get-Command py).Source
$script = 'C:\edge-debug-profile\draft_driver.py'
$off = [TimeSpan]::FromHours(-4)
$dto = [DateTimeOffset]::New(2026,9,1,17,0,0,$off)
$trigger = New-ScheduledTaskTrigger -Once -At $dto.LocalDateTime
$trigger.StartBoundary = $dto.ToString("yyyy-MM-ddTHH:mm:sszzz")
$action = New-ScheduledTaskAction -Execute $py -Argument $script -WorkingDirectory 'C:\edge-debug-profile'
Register-ScheduledTask -TaskName "FDnationDraftDriver" -Action $action -Trigger $trigger -Force
```
NOTE: this machine is JST (UTC+9); the stored trigger shows +09:00 and next-run
2026-09-02 06:00 local, which IS 5pm EDT Sep 1. Correct.

## Safety net
Yahoo DEFAULT pre-rank is the auto-draft fallback if the driver errors (e.g. Edge
closed). User accepted this; custom Edit-My-Rankings UI was too fragile to automate.

## VALIDATION

### 2026-08-31 — simulated full draft on the real pick logic (current)
`tools/simulate_draft.py` replays all 15 rounds offline against the actual
`choose_pick()`, with opponents modelled as filling starter needs and avoiding K/DEF
until late. This is the regression gate for board/driver changes — run it after
touching either file.

Result: **15/15 picks made**, K at R14, DEF (Ravens) at R15, legal lineup.

Three bugs were found and fixed in this pass (issues #9/#10/#11):

1. **Board too small** — 121 players for a 150-pick draft; ran dry at round 12 and
   Yahoo auto-drafted the rest. Board is now 250, with a `MIN_BOARD_SIZE` guard.
2. **DEF map rebuild was dead code** — `run_draft()` assigned `DEF_CODE_TO_NAME`
   without a `global`, so it bound a local nothing read, and 5 defenses (BAL/CHI/KC/
   LAC/TB, including the top-rated Ravens) could never be drafted. Now threaded
   explicitly and layered over the static map.
3. **No fallback when the board is exhausted** — `choose_pick()` returned `None` and
   stalled. Added `_fallback_pick()`, which drafts a player Yahoo is showing.

Resolved (issues #19/#20): the sim previously drafted **4 TEs and 0 QBs** because board
`value` mixed season points with a per-game DEF rating and raw points are QB-inflated.
Fixed by putting DEF on a season-points footing and applying VOR (value over replacement)
inside `choose_pick()`, with the scarcity premium rescaled to a fraction of the RB value
spread and a bench cap (`BENCH_CAP`). A full 15-round replay now yields a balanced roster
(RB 3, WR 6, TE 2, QB 2, K 1, DEF 1) with no `NO_VALID_PICK`. Regression: `tests/test_simulation.py`.

### 2026-08-21 — mock draft (superseded)
Historical: the original hand-built `BOARD` had **no K and no DEF**, so the driver would
have drafted 15 skill players and left K/DEF empty (illegal lineup). Fixed at the time
by adding K/DEF tiers to the static tuple and rewriting `choose_pick` to be
position-target-aware (forces required slots by `ANCHOR_BY_ROUND` deadlines, fills bench
with best available). Superseded by the nflverse board above.

2. CLICK SELECTOR BUG: Yahoo player ROWS hold the name in a cell, NOT inside the
   `/nfl/players/` anchor (that anchor only wraps an icon, empty text). Original
   `read_available`/`click_player` matched anchor TEXT and would have failed/mis-clicked.
   FIX: name-based row finder — scan `tr,li` rows for "Name TEAM - POS" pattern; climb
   to nearest TR/LI; scrollIntoView; click center. VALIDATED on live draftanalysis page:
   extracted real names (Puka Nacua, Brock Bowers, etc.) and click coordinate landed
   exactly on Jahmyr Gibbs's row (elementFromPoint confirmed the row's TD). CDP mouse
   events dispatch without error.

3. MOCK ROOM ITSELF: Yahoo's Instant Mock Draft is paywalled ("Subscribe to Unlock");
   free "Join" mock rooms exist (`/mock_join?...`) but direct-URL join bounced to
   homepage (needs in-page JS click + a room that actually starts). So the live
   pick→Draft-button flow could NOT be exercised end-to-end pre-draft. The click
   MECHANISM is validated; the draft-room-specific "Draft" button text is the only
   unverified bit (handled generically via /draft|select|confirm/ regex).

## RISKS (honest, remaining)
- The pick→confirm flow is validated at the mechanism level but NOT end-to-end in a
  live draft room (gated). Review draft_log.txt after the real draft.
- Cannot guarantee wins — real NFL games decide outcomes. System maximizes expected
  value and avoids timer-expiry/panic mistakes.
- If live room DOM differs, `read_available`/`click_player` may need a nudge; the driver
  logs every decision.
