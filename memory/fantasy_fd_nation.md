# Fantasy Football — League "FD nation" (Yahoo, ID 1329011)

Persistent context for the user's Yahoo Fantasy Football league. Load this whenever
the user mentions fantasy football, their league, the draft, lineup, waivers, or Edge/CDP.

## League facts (verified 2026-08-20 via live Edge CDP)
- Platform: Yahoo Fantasy Football, league ID **1329011**, name **"FD nation"**.
- Manager: user is **"Doge"**, team **#2** (URL team id = 2). Other teams: Goal Line Dwayne (commish), Game Plan buy, Take it in the Browns, Kwasi's Wins, QB Sneak Christopher, Otto-matic Win!, Neal Before Zod. All 10 spots filled (verified live 2026-08-28; was 7 of 10 on 2026-08-20).
- Format: Head-to-Head, **.5 PPR** (Receptions = 0.5), fractional points ON, negative points ON.
- Roster: 1 QB, 2 WR, 2 RB, 1 TE, 1 W/R/T (flex), 1 K, 1 DEF, 6 BN, 2 IR (15 total).
- Draft: **Live Standard snake**, 15 rounds, **1 minute per pick**, scheduled **Tue Sep 1 2026, 5:00pm EDT** (= 2026-09-02 06:00 JST on this machine). *Corrected 2026-08-28 from the live Yahoo tab — repo had Aug 28; actual draft is Sep 1.*
- Not a cash league. Playoffs top 4, Weeks 16-17.
- Waiver: 2-day rolling list; trade review by league vote; max acquisitions unlimited.

## Draft strategy (user-approved)
- Approach: draft by **value = expert rank − ADP** when a live FantasyPros feed is
  available (set `FP_API_KEY` for the free API); otherwise fall back to the
  pre-built ADP board (verified top-30). Automatic guardrails apply either way:
  - No QB before round 10.
  - K and DEF only in the last 2 rounds.
  - Don't double a position that's already filled to its slot count.
  - ADP sanity window (don't reach absurdly above ADP).
- Safety net: Yahoo DEFAULT pre-rank (ADP-based) is the auto-draft fallback. User accepted this (custom Edit-My-Rankings UI was too fragile to automate safely — Yahoo uses a JS drag widget with no stable controls).
- Do-not-draft list: **none** (user confirmed).

## Engineering setup (verified working)
- Edge launched by user on **port 9222** with `--remote-allow-origins=*` (and the original `--user-data-dir=C:\edge-debug-profile`). This is REQUIRED for CDP WebSocket control. Without the flag, Edge rejects WS with 403.
- Control from WSL is NOT possible directly (WSL2 separate netns). Driver runs on the **Windows side via `py.exe`** where `websocket-client` 1.9.0 is installed (pip into Windows Python 3.13).
- Windows Python launcher: `py.exe` = C:\Users\user\AppData\Local\Programs\Python\Python313-32\python.exe. `websocket-client` installed there.
- Output/artifacts dir on Windows: `C:\edge-debug-profile\`.
- Human-like input layer: quadratic Bézier mouse paths + per-step jitter + variable think delays, dispatched as real CDP Input.dispatchMouseEvent. navigator.webdriver=false on the page (no automation banner).

## Live draft driver (deployed)
- Script: `C:\edge-debug-profile\draft_driver.py` (also at /home/eml/draft_driver.py).
- Scheduled Windows task **"FDnationDraftDriver"**: fires **2026-09-01 17:00 EDT (= 2026-09-02 06:00 JST)**, runs `py.exe C:\edge-debug-profile\draft_driver.py`. Rescheduled 2026-08-28 after the live tab showed Sep 1 (was Aug 28).
- Decision log: `C:\edge-debug-profile\draft_log.txt` (created at first run).
- CRITICAL dependency: Edge must be OPEN on 9222 with --remote-allow-origins=* at draft time, or the driver errors and Yahoo default auto-draft takes over.

## Proven skills (see /home/eml/.hermes/skills/)
- `edge-cdp`: connect to Edge 9222, human-like input helpers.
- `fantasy-read`: read roster/standings/matchups/waivers from the live tab.
- `fantasy-draft`: the live draft driver + scheduler + board.

## Honest limitations
- The driver's PICK-CLICKING logic is UNTESTED against the live Yahoo draft room (room doesn't exist until draft day). Plan: mock-draft validation ~Aug 27.
- I cannot guarantee wins — real NFL games decide outcomes. The system maximizes expected value and avoids timer-expiry/panic mistakes.
- WSL↔Windows: /mnt/c is unreliable from this shell; use `py.exe -` (stdin) and PowerShell base64 round-trips to move data reliably.
