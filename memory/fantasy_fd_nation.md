# Fantasy Football — League "FD nation" (Yahoo, ID 1329011)

Persistent context for the user's Yahoo Fantasy Football league. Load this whenever
the user mentions fantasy football, their league, the draft, lineup, waivers, or Edge/CDP.

## League facts (verified 2026-08-20 via live Edge CDP)
- Platform: Yahoo Fantasy Football, league ID **1329011**, name **"FD nation"**.
- Manager: user is **"Doge"**, team **#2** (URL team id = 2). **10 teams** (verified 2026-08-28 via live Edge CDP — the FD nation Teams page listed exactly 10 teams; Yahoo Settings confirms "Max Teams: 10"; the earlier "12 teams" claim was incorrect).
- Known opposing team names (10 observed 08-28, 7 named): "Goal Line D. (commish)", "Game Plan buy", "Take it in the Browns", "K.'s Wins", "QB Sneak C.", "Otto-matic Win!", "N. Before Zod".
  *Manager first names are deliberately REDUCED TO INITIALS here. This repo is public
  (it was made public on 2026-08-31), and these are other people's real names — don't
  restore them. The bot picks best-player-available and is slot-agnostic, so it never
  needs to know who runs which team.*
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
  soft scarcity premium (`SCARCITY_FRACTION = {"RB": 0.10}` of the RB value spread)
  to RBs we still need (anchors them early despite the crowd's RB inflation) and
  (b) hard-forces slots by `ANCHOR_BY_ROUND`: 1st RB by R3, 2nd RB by R5, WR by
  R5/R9, TE by R7, QB by R10, K/DEF by R14.
- BOARD depth: **250 players** (QB 32, RB 60, WR 70, TE 32, K 28, DEF 28) in
  `data/board/original_board.json`, built by `python cli.py original-board`. The board
  must outlast the WHOLE draft, not just the early rounds — 10 teams x 15 rounds = 150
  picks. *(Was ~67, then 121; 121 ran dry at round 12 and Yahoo auto-drafted the rest of
  our team. Corrected 2026-08-31; `MIN_BOARD_SIZE = 250` in `src/draft_board.py` now
  guards against regression.)*
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

Method: `tools/mock_draft_run.py` injects the REAL original board + filler, runs a
full 15-round snake for team #2, and calls the DEPLOYED driver's REAL functions on
every turn (no reimplementation). Opponents are simulated (skill players only, so
K/DEF are left for the bot's late rounds) so scarcity/anchor guardrails AND the
K/DEF-last / QB-round contract are exercised. The harness also asserts the draft
CONTRACT: K/DEF only in rounds 14-15, QB not before R10, every required slot filled
by its anchor deadline.

### Round 1 validation (PR #5, 3b7786a) — 3 real bugs found & fixed
1. **`click_player` clicked the first enabled "Draft" button on the page, not the
   chosen player's row button.** Yahoo-sorts the list, so our value pick is rarely
   the top row → the bot drafted the WRONG players. Fixed: scope the button search
   to the chosen player's own row.
2. **`choose_pick` had no bench phase** (returned `None` once REQUIRED slots were
   filled) → bot made only 7 of 15 picks. Fixed: fallback now drafts best-available
   for bench (still respecting K/DEF-last + QB-round timing guards).
3. (mock-only) drafted players were rendered as `<li>`, so `read_available`'s
   `tr,li` scan re-scanned them as available and the bot tried to re-draft them.
   Fixed in the mock: drafted list uses `<div>`.

**Result (R1): 15/15 picks clicked + confirmed via CDP; roster LEGAL; NO_FAILURES.**
(Correction of an earlier doc claim: "single-word defense names never parsed" was
wrong — the original regex already allowed 1-3 word names and the deployed board
uses all-caps team codes, so defenses parsed fine. The real DEF gap was the
team-CODE capture, fixed below.)

### CodeRabbit review on PR #5 — regex / harness hardening (this session)
CodeRabbit flagged 3 Major issues; fixing them surfaced a 4th (critical) bug:
- **Stray `)` in the `read_available` regex** introduced while adding the team-code
  capture group → the whole regex was a JS syntax error → `read_available` threw
  inside the CDP eval and returned `None`. Fixed (removed the extra paren).
- **Team-code not captured** (CodeRabbit): the regex captured only name + position,
  not the team code, so `normalize_available` couldn't map a defense label like
  `"Los Angeles Rams LAR - DEF"` to the board key `"Rams"`. Fixed: capture the team
  code as its own group; `normalize_available` maps `LAR → Rams`.
- **Filler names unparseable** (CodeRabbit): `"Fantasy Stash 0 BUF ..."` contains a
  digit, which the name regex rejects → the mock couldn't supply 150 bodies.
  Fixed: filler names are now 1-2 alphabetic words, no digits.
- **Opponent K/DEF filtering guessed position** (CodeRabbit): `simulate_opponents`
  called `_pos_of()` on a bare name (always `""`), so K/DEF were eligible for
  opponent snipes → nondeterministic roster. Fixed: the mock now exposes
  `availablePlayers()` (name + pos); opponents filter on real `pos` and never take
  K/DEF.
- Hardening found while fixing: the team-code class is now `[A-Za-z]{2,4}` (Yahoo
  team codes can be mixed-case, e.g. `Det`), and the name pattern now consumes an
  optional generational suffix (`III`, `Jr.`) and up to 4 tokens
  (e.g. `Amon-Ra St. Brown`). Verified: **119/119 board rows parse**, including
  `Ja'Marr Chase`, `James Cook III`, `Amon-Ra St. Brown`, `Brian Thomas Jr.`.

**Result (rerun, this session): 15/15 picks clicked + confirmed via CDP; roster
LEGAL (QB=3 RB=5 WR=4 TE=1 K=1 DEF=1); contract held; NO_FAILURES.**

Honest remaining gap: the mock validates the driver's click/confirm *mechanics*
using the real deployed functions against a Yahoo-style DOM. The REAL Yahoo room's
exact markup (draft-button label/position, live ADP parsing) can only be confirmed
on Sep 1 — but the logic that finds, clicks, and confirms a pick is now proven, and
the parser handles every board name format we know of.

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

## Session recovery + pre-draft intel (2026-08-30, ~2 days before draft)
- WSL crashed; recovery verified: Windows driver intact (`C:\edge-debug-profile\draft_driver.py`), scheduled task `FDnationDraftDriver` confirmed next run **2026/09/02 06:00 JST**. WSL `.venv` is a WINDOWS venv (Scripts/Lib) — run tools via `py.exe C:\nfl-win\tools\<x>.py`, NOT the WSL venv (WSL system python has no websocket-client).
- Live check: session alive (Doge visible), countdown "Live League Draft in 2 days", draft time confirmed **Tue Sep 1 5:00pm EDT**.
- **Draft order: commissioner generated RANDOM order** — order/slot NOT visible pre-draft anywhere on Yahoo (Draft Central/Draft pages don't show it). Bot is BPA + anchors, so slot-agnostic; order reveals when room opens Sep 1.
- **League ADP captured** (previously forfeited crowd signal): `data/scrapes/yahoo_league_adp.json` — 30 players from Yahoo Draft Analysis (`/f1/1329011/draftanalysis`, no clicks needed). Top: Gibbs 1.4, Bijan 2.0, Chase 3.5 (tagged Q), Nacua 4.9 (Q), CMC 5.7 (Q), Taylor 6.7, JSN 7.1, St. Brown 7.9, Cook 9.6, Lamb 10.8, Saquon 11.7, Jefferson 13.1. Injury tags (Q/O/IR) captured per player. Default page shows ~30 rows; depth limited without pagination (risky clicks — see below).
- ⚠️ Yahoo trap: clicking "View All" on Draft Central navigated the tab to login.yahoo.com (transient logout scare; navigating back restored session). NEVER click UI elements on these pages via CDP — navigate + parse text only.
- The `/f1/<id>/draftorder` URL is a 404 (dead URL guess). Real pages: `/draft` (Draft Central, needs ~14s JS wait), `/draftanalysis` (ADP table, ~12s wait).
- Console is cp932 (Japanese Windows): run probes with `set PYTHONIOENCODING=utf-8&&`; Windows python can't write /mnt/c paths — use `C:\nfl-win\...`.
- Tool scripts added: `tools/scrape_league_adp.py` (league ADP), `tools/check_draft_state.py`, `tools/dump_draft_page*.py`, `tools/back_to_league.py`.

## ADP merged into the original board + reach guard wired (2026-08-30)
- **ADP now flows into the DEFAULT original engine.** `cli.py original-board` merges
  `data/scrapes/yahoo_league_adp.json` into every board row via
  `src/draft_board.load_league_adp` (team-code alias LAR->LA etc) + `merge_league_adp`
  (name-only fallback when the name uniquely matches but the team changed).
- **Live-verified trades caught by the merge:** `A.J. Brown PHI->NE` and `Kenneth
  Walker III SEA->KC` (verified on Yahoo Draft Analysis 2026-08-30; both flagged
  `adp_team_changed=True` in the board JSON so the row keeps its board team but
  inherits the crowd ADP). Board rebuild -> 28/30 active players carry league ADP.
- **Driver reach guard live** (`driver/draft_driver.py`): `_crowd_reach(c, round_num)`
  skips a board pick whose league ADP is > ADP_WINDOW (40) picks past the current
  round window unless an anchor forces it or nothing else is available (step-4
  bypass + anchor bypass logged). Deprecates the previously dead ADP_WINDOW constant.
- **Validation:** `tools/mock_draft_run.py` full 15-round run through the DEPLOYED
  driver (`C:\edge-debug-profile\draft_driver.py`, loaded new board) ->
  `15/15 picks clicked + confirmed; ROSTER_LEGAL=True; NO_FAILURES` (R1-9 skill,
  R10-13 QB per contract, R14 K, R15 DEF). `pytest tests/test_original_board.py
  tests/test_draft_driver.py` -> **24 passed**. Both driver copies + board deployed
  to `C:\edge-debug-profile\`.
- Reach guard did NOT fire in the mock (expected): by R10 every known-ADP player is
  far past the crowd window so `adp - window < 40`. It exists for post-scrape ADP
  crashes (injury news) — only confirmable against the live room.
- Mock roster artifact (QB=4/RB=6) is an artifact of simulated opponents never
  drafting QBs; real-room opponents take QBs so the board won't dump 4 QBs on us.
- Remaining pre-draft steps: re-scrape ADP + rebuild board the morning of Sep 1
  (new injuries/cuts), and ensure Edge is open on 9222 at 5pm EDT.

## GAME_PLAN.md completed + tree cleaned (2026-08-30, post-crash)
- `docs/GAME_PLAN.md` (beginner game plan) finished: Parts 0-6 (60-sec, what-is
  fantasy, three phases, draft bot + draft-day checklist, waivers, weekly lineup,
  command cheat-sheet with exact `cli.py` half-ppr commands).
- Committed session leftovers: `tools/edge_alive.py` (Edge 9222 health check),
  `tools/back_to_league.py`, `tools/recover_tab.py` (tab recovery), plus ADP-page
  debug probes (`dbg_headers/lines/trs.py`, `dump_draft_page*.py`,
  `find_draft_links.py`). All small read-only CDP probes; safe to keep.
- WSL crashed again at ~20:30; verified: repo intact at ae09196, tests 24 passed
  (draft suite), deployed driver/board MD5-match, Edge still alive on 9222.

## Headless login + cross-platform tooling (2026-08-30)
- `tools/login_yahoo.py`: CDP-driven Yahoo login for a fresh headless browser
  (email → password → 2FA prompt → verify via same-origin team-page fetch).
  Reads YAHOO_USER/YAHOO_PASSWORD (env or .env) or stdin. Prints
  ALREADY_LOGGED_IN / LOGGED_IN_OK / CAPTCHA_BLOCKED. **Tested live** against
  the logged-in Edge: `ALREADY_LOGGED_IN` detected correctly, zero page
  interaction. Credential prompt is skipped when already logged in.
- Caveat: Yahoo occasionally serves an interactive captcha to headless mode →
  then fall back to MAC_SETUP option A (cookie-copy the Windows profile) or C
  (one-time headful login via Screen Sharing). Option A is preferred because
  Yahoo auth is cookie-based and the profile transfers directly.
- `signed_in()` reuses the proven marker (team page fetch 200 + /Doge/i) from
  tools/check_login.py — plain "sign out" body-text is NOT reliable on Yahoo.
