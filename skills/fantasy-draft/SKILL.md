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
- .5 PPR, H2H, 15 rounds, 1 min/pick, snake. 7 teams.
- Roster: 1QB/2WR/2RB/1TE/1WRT/1K/1DEF/6BN/2IR.
- Draft: Fri Aug 28 2026 6:00pm EDT (= 2026-08-29 07:00 JST on this machine).

## The driver script
Full implementation: `C:\edge-debug-profile\draft_driver.py` (also
/home/eml/draft_driver.py). It:
1. Connects to Edge 9222 (--remote-allow-origins=* required).
2. Opens the draft room, polls for "your pick" (team 2).
3. On your pick: reads available players, chooses highest board player passing
   guardrails:
   - no QB before round 10
   - K/DEF only last 2 rounds
   - no doubling a filled position slot
   - ADP sanity window (no absurd reaches)
4. Clicks the player row + Draft/confirm with Bézier+jitter motion.
5. Logs every decision to `C:\edge-debug-profile\draft_log.txt`.

## Board (verified top-30 ADP, embedded in script)
Gibbs, Bijan, Chase, Puka, McCaffrey, Amon-Ra, JSN, Taylor, CeeDee, Cook,
Saquon, Jefferson, Jeanty, Achane, ChaseBrown, K.Walker, Henry, London, Hampton,
Allen(QB), Bowers(TE), Nico, Pickens, A.J.Brown, McBride(TE), Love, DeVonta,
Kyren, Jacobs, Olave.

## Run it manually (Windows)
```
py.exe C:\edge-debug-profile\draft_driver.py
```
Requires Edge open on 9222 with --remote-allow-origins=* at that moment.

## Scheduled task (already deployed)
Task "FDnationDraftDriver" fires 2026-08-28 18:00 EDT and runs the driver.
Recreate if needed (PowerShell, Windows side):
```powershell
$py = (Get-Command py).Source
$script = 'C:\edge-debug-profile\draft_driver.py'
$off = [TimeSpan]::FromHours(-4)
$dto = [DateTimeOffset]::New(2026,8,28,18,0,0,$off)
$trigger = New-ScheduledTaskTrigger -Once -At $dto.LocalDateTime
$trigger.StartBoundary = $dto.ToString("yyyy-MM-ddTHH:mm:sszzz")
$action = New-ScheduledTaskAction -Execute $py -Argument $script -WorkingDirectory 'C:\edge-debug-profile'
Register-ScheduledTask -TaskName "FDnationDraftDriver" -Action $action -Trigger $trigger -Force
```
NOTE: this machine is JST (UTC+9); the stored trigger shows +09:00 and next-run
2026-08-29 07:00 local, which IS 6pm EDT Aug 28. Correct.

## Safety net
Yahoo DEFAULT pre-rank is the auto-draft fallback if the driver errors (e.g. Edge
closed). User accepted this; custom Edit-My-Rankings UI was too fragile to automate.

## VALIDATION (done 2026-08-21 — mock draft)
Ran mock-draft validation. Findings + fixes applied to the driver:

1. LOGIC TEST (simulated full 15-round draft): FIRST run FAILED — original BOARD had
   NO K and NO DEF players, so the driver would draft 15 skill players and leave K/DEF
   EMPTY (illegal lineup). FIX: added K tier (Aubrey/Fairbairn/Dicker/Myers/Little) and
   DEF tier (Rams/Texans/Broncos/Seahawks/Eagles/Patriots) with real Yahoo ADP; rewrote
   `choose_pick` to be position-target-aware (forces required slots by FORCE_BY_ROUND
   deadlines, fills bench with best available). RE-TEST: LEGAL_LINEUP_CHECK PASS —
   exactly QB,TE,K,DEF=1 and RB,WR>=2, K/DEF in last 2 rounds, QB at round 10.

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
