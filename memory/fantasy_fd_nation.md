# Fantasy Football — League "FD nation" (Yahoo, ID 1329011)

Persistent context for the user's Yahoo Fantasy Football league. Load this whenever
the user mentions fantasy football, their league, the draft, lineup, waivers, or Edge/CDP.

> **How to read this file:** dated journal entries, newest at the bottom. Entries
> before "Post-draft + in-season pivot (2026-09-12)" are the DRAFT-ERA record —
> the Windows box, WSL, the draft driver, mock harness, ADP pipeline and most
> commands/paths in them are RETIRED (removed in #82; the draft completed Sep 1-2,
> 15/15). They are kept as history explaining why current rules exist, not as
> guidance. For current operations start at "Post-draft + in-season pivot" and
> read downward.

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

## Draft strategy (user-approved; draft COMPLETED Sep 1-2)
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

## Engineering setup (draft-era, RETIRED — Windows/WSL)
- Edge launched by user on **port 9222** with `--remote-allow-origins=*` (and the original `--user-data-dir=C:\edge-debug-profile`). This is REQUIRED for CDP WebSocket control. Without the flag, Edge rejects WS with 403.
- **Security:** the CDP debug port (9222) is a full browser-control interface. Bind Edge to loopback only (`--remote-debugging-address=127.0.0.1`) and ensure no firewall/port-forward exposes 9222 to the network — anyone who reaches it can drive the browser and read the logged-in Yahoo session. Close Edge when not drafting.
- Control from WSL is NOT possible directly (WSL2 separate netns). Driver runs on the **Windows side via `py.exe`** where `websocket-client` 1.9.0 is installed (pip into Windows Python 3.13).
- Windows Python launcher: `py.exe` = C:\Users\user\AppData\Local\Programs\Python\Python313-32\python.exe. `websocket-client` installed there.
- Output/artifacts dir on Windows: `C:\edge-debug-profile\`.
- Human-like input layer: quadratic Bézier mouse paths + per-step jitter + variable think delays, dispatched as real CDP Input.dispatchMouseEvent. navigator.webdriver=false on the page (no automation banner).

## Live draft driver (draft-era, RETIRED — Windows task)
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

## Proven skills (draft-era; skills removed in #82)
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
  use the re-login paths in docs/TEAM_OPERATOR.md (one manual headful login
  via Screen Sharing when captcha/2FA blocks automation). (Pre-Mac era this
  was cookie-copy the Windows profile; that box is retired.)
- `signed_in()` reuses the proven marker (team page fetch 200 + /Doge/i) from
  tools/check_login.py — plain "sign out" body-text is NOT reliable on Yahoo.

## Phase 2 complete (2026-08-31) — deploy drift fixed (#21)
- All Phase-2 issues (#17 leakage, #18 predict, #19/#20 VOR+scale, #21 deploy drift)
  are now committed, pushed (github main = c899774), and the driver/board are
  deployed to `C:\edge-debug-profile\`.
- **Deploy workflow is now one command:** `powershell -File tools/deploy.ps1`
  (default DeployDir `C:\edge-debug-profile`). It copies `driver/draft_driver.py` +
  `data/board/original_board.json`, writes `DEPLOY_SHA.txt` (git SHA), and
  `Get-FileHash`-verifies both copies so a partial deploy fails loudly.
- **Drift detection at runtime:** `run_draft()` logs
  `DEPLOY_GIT_SHA=<sha> FILE_SHA256=<12-char content hash>` at startup, so
  `draft_log.txt` proves which code actually ran. A stale deploy shows a SHA/SHA256
  mismatch even when `DEPLOY_SHA.txt` is missing.
- Reminder: a repo edit is NOT live until `tools/deploy.ps1` has been run and the
  `OK:` / `DEPLOY_SHA=` lines confirm. Validate before Sep 1 5pm EDT.
- Fast regression gate: `pytest tests/test_draft_driver.py tests/test_original_board.py
  tests/test_simulation.py` → 29 passed. Full suite was 47 passed earlier this cycle.

## All issues closed (2026-08-31) — tracker empty
- Remaining P2/P3 issues (#22-#31) all addressed per the rule "fix if not addressed,
  then track on merge": #22 mitigated (never committed, gitignored), #23 off-window
  search wired (236e35d), #24 ratings cache (7796fa0), #25 pytest/CI (0e689d2),
  #26 pick-number guard (236e35d), #27 raw-JS strings (7796fa0), #28 drop ties
  (7796fa0), #29 tools/debug split (31d94bf), #30 board-size invariant (7796fa0),
  #31 README de-stale (6fc6d40). `gh issue list --state open` → 0.
- Final commits this cycle: 236e35d (#26/#23 + 2 run_draft regression tests, pushed,
  deployed), 4dbbbed (REMEDIATION.md Phases 3-4 marked done). Remote HEAD = 4dbbbed.
- Driver re-deployed to `C:\edge-debug-profile\` after 236e35d; `DEPLOY_SHA.txt`
  236e35db0af0904399882542b5ae86b15e4e3abc. Fast gate now 31 passed.
- Live draft Tue Sep 1 2026 5pm EDT, team #2 "Doge", 10-team .5PPR 15-round snake.
  Nothing blocking remains in the repo before draft time.

## P0 #32 found & fixed via live Edge test (2026-08-31, post-close)
- After closing #9-#31, a live Edge CDP harness (NEW isolated `file://` tab; the user's
  logged-in Yahoo tab was never touched) drove the REAL `read_available` /
  `search_player` / `click_player` / `read_pick_number`. It surfaced **P0 #32**:
  `read_available()` returned `[]` on every page because #27's raw-string conversion
  (`r"""..."""`) left the regex escapes doubled — `\\s` in a raw string is two literal
  backslashes → CDP delivered `\\s` → JS matched literal `\s`, not whitespace. The driver
  could not see ANY available player → total draft failure on Sep 1. Fixed by
  single-backslashing the 7 escapes (commit `d1a027c`). Created + closed issue #32 with
  the fix reference.
- New harness (the only test that actually runs the parser; unit suite mocks
  `read_available` away): `tools/test_driver_cdp.py` + `tools/mock_draft_room_40.html`
  (40-row virtualized DOM window + real search box). Asserts #23a virtualization, #23b
  off-window search, #23c click-draft, #26 pick-number read + guard. `pytest` fast gate
  still 31 passed.
- **Deploy SHA is now `d1a027c461be65d37a0fb6580eb4d28058c6ee02`** (supersedes the
  236e35d noted above; confirmed via `DEPLOY_SHA.txt` + `Get-FileHash`).
- `gh issue list --state open` → 0. Repo is fully ready for the Tue Sep 1 2026 5pm EDT
  draft.

## Manual failover plan (2026-08-31)
- If the auto-driver (CDP) can't run on draft day, there's a documented human fallback:
  `docs/MANUAL_FAILOVER.md` (Tier 0 scheduled driver → Tier 1 manual re-trigger →
  Tier 2 Yahoo pre-rank auto-draft → Tier 3 full manual drafting).
- Printable pick list: `docs/DRAFT_CHEAT_SHEET.md` (our 15 picks + clock times, suggested
  round-by-round, anchor rules, per-position menus), generated by the reproducible
  `tools/gen_cheat_sheet.py` (run `--write`; re-run morning-of after ADP re-scrape).
- **Critical pre-draft action:** set Yahoo **Edit My Rankings / Pre-Draft Order** from the
  cheat-sheet menus NOW — this powers the Tier-2 native auto-draft safety net. Without it,
  a Yahoo auto-draft fallback is only as good as Yahoo's default order.
- Cheat sheet mirrors the bot's anchors: 2nd RB by R5, WR by R5/R9, TE ~R7, no QB before
  R10, K/DEF R14-15; our 15 overall picks are 2,19,22,39,42,59,62,79,82,99,102,119,122,
  139,142 (snake, team #2).
- **Important correction:** the cheat sheet's "suggested" column simulates ALL 10 teams
  drafting by league ADP (need-based), so early studs are correctly shown as gone before
  our picks. Josh Allen (board `adp: 20.0` ≈ round 2) will NOT be available at our R10 —
  our realistic QB is a later-tier player taken at R10, not Allen. The earlier naive greedy
  mistakenly listed Allen at R10 because it ignored opponent drafts. Don't promise Allen.
- **RESOLVED (2026-08-31): confirmed 1-QB league.** User pasted the live Settings → Roster
  Positions: `QB, WR, WR, RB, RB, TE, W/R/T, K, DEF, BN×6, IR×2` — exactly **one** QB slot.
  Matches the recorded roster (verified 2026-08-20 live CDP) and confirms the wait-on-QB-
  until-R10 strategy and all bot anchors are correct. **No change needed.** (CORRECTION 2026-08-31
  evening: the earlier 'sandbox blocks CDP-to-Yahoo' note is OVERTURNED — a read-only CDP attach
  to the live Yahoo tab succeeded, proving the live session is controllable from PowerShell/CDP.
  Only `Target.createTarget`-to-external-URL and `/json/new` are blocked; the driver's
  `connect()` attaches to an existing tab, so it's unaffected.)

## P0 Yahoo name-abbreviation bug — fixed 2026-08-31 (pre-draft)
Yahoo's draft room/roster render names abbreviated ("J. Burrow", "C. McCaffrey", "A.J. Brown")
while our board keys are full ("Joe Burrow"). Two-part fix in `driver/draft_driver.py`:
1. `read_available()`'s name regex was corrupting abbreviated names BEFORE normalize ran
   ("J. Burrow"->"Burrow", "McCaffrey"->"Caffrey"), so the resolution maps never triggered.
   Replaced with `^(?:\d+\.?\s*)?(.*?)\s+([A-Za-z]{2,4})\s*-\s*(POS)` — captures the name up
   to the "TEAM - POS" code (optionally skipping a leading rank "12. "), so BOTH abbreviated
   and full forms survive intact.
2. `to_display()` + `ABBREV_TO_FULL`/`ABBREV_TO_FULL_NT`/`NAME_TO_TEAM` reverse maps added;
   `normalize_available()` resolves abbreviated -> full (team-code disambiguated);
   `click_player()` and `_confirm_pick()` try BOTH full + display names.
Verified: `tools/_test_abbrev.py` (regex + map asserts) and a new `tools/test_driver_cdp.py`
#32 case drive the REAL driver against a Yahoo-style mock in abbreviated mode — read ->
normalize -> click all succeed. Deployed to `C:\edge-debug-profile\` (DEPLOY_SHA == HEAD).
This was the bug that would have made the bot fall back to raw-ADP on Sep 1.

## Post-draft + in-season pivot (2026-09-12)
- Draft COMPLETED Sep 1-2 (JST): 15/15 via the Mac real-draft operator. Roster:
  McCaffrey, C. Brown, Olave, Rice, Kittle, Tuten, B. Robinson, Watson, Tate,
  Purdy, Downs, Croskey-Merritt, Pierce, Loop (K), Steelers DEF. Report:
  docs/drafts/2026-09-02-fd-nation.md; audit: logs/real-draft-audit.jsonl.
- Week 1 vs "QB Sack Corey"; waiver priority 4th. Purdy/McCaffrey/Kittle played
  Thu (SF W 27-7 @ LAR) and are locked for the week.
- Platform: this Mac (JST) is now the ONLY machine. Chrome for Testing from
  /tmp/cft (shared with ~/games; /tmp clears on reboot — see #81) on CDP 9222,
  profile ~/edge-draft-profile; login verified (team_page_has_doge: true).
  The Windows setup (py.exe, C:\edge-debug-profile, FDnationDraftDriver,
  deploy.ps1) is RETIRED.
- #79 FIXED: yahoo/team.py parses game-locked roster rows (the tr.editable-only
  selector broke every Thu-Mon; locked players now flagged `locked: true`).
- #89 FIXED repo-side: images/human_demo.png exposed the live league invite URL
  (key/ikey tokens) — file purged from git history + force-pushed. League
  invite ROTATION declined by the user (2026-09-12): casual league, accepted
  risk, #89 closed. Revisit only if the league ever opens a slot or expands.
- Repo pivot to in-season maintenance: epic #80 (operator, manual+cron);
  data gaps #83 (week/kickoff), #84 (byes), #85 (injuries), #86 (2026 stats);
  lineup recommender #87; live read/write gaps #88; keepalive #81; cleanup #82.
  Full review: CODEBASE_REVIEW_INSEASON.md.
- Draft-era code REMOVED in the 2026-09-12 cleanup: driver/, yahoo/real_draft +
  mock_draft + draft_report, 14 draft-only tools (incl. deploy.ps1, mock
  harnesses, gen_cheat_sheet, simulate_draft), tools/debug/, validation/, 8
  draft-only tests, skills/fantasy-draft + skills/edge-cdp, src/draft_board.py
  and cli.py original-board/draft-class. All recoverable from git history
  (pre-cleanup commit cd16d8c).

## In-season epic #80 COMPLETE (2026-09-12)
- All issues closed: #81/#82 (PR #90), #83 (PR #91), #84 (PR #92), #85 (PR #93),
  #86 (PR #94), #87 (PR #95), #88 (PR #97), #80 (PR #99). Main at 7c3a502.
- Review path: CodeRabbit rate-limits (~1 review/hour, OSS manual trigger), so
  independent k3 reviewer subagents gated PRs #91-#95 (user-approved flow);
  CodeRabbit gated #97 and #99. Notable catches: stale injury statuses carried
  forever (recency-bound now: latest 2 report weeks, blank = cleared); unplayed
  2026 games mislabeled as home losses in the training frame; recommender's bye
  handling was dead code pre-#92 (tool now derives on_bye from the schedule);
  --apply refuses on Yahoo week mismatch.
- tools/team_operator.py is THE entry point (read-only default; --apply submits
  lineup moves only; waivers never auto-submitted). Audit logs/team-operator.jsonl;
  flock logs/team-operator.lock (exit 3 = already_running); exit 2 = not ok.
- CRON INSTALLED (JST): 08:24/20:24 daily monitor; Mon 01:23 (= Sun ~12:23 ET)
  --apply lineup set; Wed 20:11 waiver scan + data refresh. Log:
  logs/team-operator-cron.log. Manage via `crontab -l/-e`.
- Open follow-ups: #89 (user-side: rotate Yahoo league invite), #96 (deferred
  transaction scope: IR moves, claim cancel/edit, multi-claim ordering), #98
  (pre-existing negative/zero proj_week values).
- Session persistence SOLVED: --use-mock-keychain (CfT is ad-hoc signed; without
  it cookies are memory-only). Profile backup: tools/profile_backup.py ->
  ~/edge-profile-backups/; launchd com.fdnation.browser re-runs preflight at
  login. Browser on 9222 must NEVER be killed (user rule).

## In-season transactions + strategy (2026-09-13)
- Deep-dive (all 10 rosters vs model): team ranks 5/10 season-long (1430.4 vs
  leader 1577.7); QB slot 10/10 (Purdy), RB 3/10, TE 3/10, WR1 8/10. Week-8 bye
  landmine: Purdy+McCaffrey+Kittle+Olave ALL out. Trackers: #102 (wk8 byes),
  #103 (trade RB surplus for WR1), #104 (league-strength tool).
- TX 1 (2026-09-13): ADDED Baker Mayfield (FA, no priority spent), DROPPED
  Brian Robinson (was team_mismatch dead spot). #101 closed. Waiver tool's
  false HALT on immediate FA adds filed as #105.

## Analyzer blind-spot fixes + Tate ruling (2026-09-13, evening)
- CARNELL TATE = HOLD. The analyzer flagged him "dead spot (matched)" but he is
  a 2026 ROOKIE (NFL draft 1st round pick 4, TEN), a STARTING WR on every
  depth-chart update since Aug 29, not injured. The flag was a model blind
  spot, not worthlessness. Do NOT drop him on the tool's say-so; re-evaluate
  after 2-3 weeks of real 2026 stats land in the corpus.
- #108 (PR #109): matched-but-unprojected players now get map_status
  no_projection; excluded from auto drop nominations; hygiene rec reads
  "model blind spot … verify manually; not an auto-drop".
- #110 (PR #111): ROOT CAUSE fixed — rookie injection omitted seasons_played,
  so proj_total was NaN for ALL 76 rookies (Tate had ppg 5.42 but no season
  total). Now every rookie gets a conservative half-season total (Tate 46.1,
  rank ~182). Consequence: the 5/10 season-strength read was UNDERSTATED
  (rookies counted as zero on every roster) — re-run team_analyzer.py after
  the Wed data refresh for the truer rank.
- #105 (PR #113): immediate FA adds now verify by exact-ID roster read-back
  (receipt "completed") instead of demanding a pending claim. k3 review caught
  a real blocker (read-back on wrong page → TeamReadError); fixed + pinned.
- #112 (PR #114): groupby player_id-only (nflverse position relabels duped 4
  DL); nightly test_projections_sane green again.
- Review flow note: CodeRabbit OSS quota = 1 review/hour on this repo; k3
  independent reviewer subagent is the approved fallback (user rule).

## WAF hardening #106 (2026-09-13, PR #115)
- waf_blocked is now a first-class outcome: preflight exit 3 (throttling, NOT
  logout — do NOT re-login; back off 15-30 min of zero automation), operator/
  analyzer/league_report report status waf_blocked and abort. league reads
  fail fast on the 'Request denied' signature (yahoo/waf.py, LeagueWafBlocked).
- Analyzer has --light (my roster + standings + matchup only, ~5 reads) for
  gentle checks; full runs stay for weekly deep-dives.
- WAF-blocked runs SKIP the tab-restore navigation (any request can extend
  the throttle); next green run restores tab hygiene.
- Suite: 164 fast tests.

## Session persistence #117 (2026-09-13, PR #118)
- Login is cookie-based, not password-based (main Login Data store is empty).
  Yahoo A1/A3 → 2027-09; SPT/SPTB rolling; Google SID/__Secure-1PSID → 2027-10.
  Cookies die early only on server-side revoke (password change, logout,
  security challenge) — a plain relaunch never clears them.
- Recovery ladder: (1) relaunch same profile+flags → logged in; (2) profile
  lost → ensure_browser auto-restores ~/edge-profile-backups → logged in;
  (3) Yahoo revoked but Google alive → login.yahoo.com "Sign in with Google"
  is a button click, no password; (4) both dead → one manual Google login,
  then re-run tools/profile_backup.py. Backup refreshed 2026-09-13.
- tools/verify_relaunch.py = the drill: copies profile (or --from-backup),
  headless throwaway on OS-assigned port (DevToolsActivePort read-back),
  same-origin probe with redirect:'manual', verdict signed_in(0) /
  login_required(1, positive evidence only) / inconclusive(2, WAF/infra).
  NEVER touches the live browser. Verified live: exit 0 vs copy AND backup.
- Live demo for the user: killed + relaunched the operator browser via
  tools/launch_browser.py → check_login 200 + Doge. No password needed.
- Drill gotchas burned into tests: denied-wins ordering, status None and
  429/5xx are inconclusive (never logout), 302 retries (anonymous early
  probe races the cookie store), 401/403/3xx = real logout, 404 = stale path.
- Suite: 187 fast tests.

## Cron/browser adaptation review #119 (2026-09-13, PR #120)
- Chain verified: every cron run of team_operator.py starts with preflight →
  ensure_browser (relaunch with profile if CDP down, backup auto-restore if
  profile missing, CfT download if binary missing). launchd com.fdnation.browser
  runs preflight at login. Evidence: 08:24 cron run = ok right after the
  kill/relaunch demo.
- Crontab changes on the host (backup /tmp/crontab.bak):
  - ADDED 47 23 * * 0 --apply = Sunday 23:47 JST (10:47 ET) safety net; the
    01:23 JST Monday final set fires when the Mac is likely asleep and cron
    has no catch-up. --apply is a no-op when the lineup is already optimal
    (submission gated on proposal.moves), so double-apply is harmless.
  - ADDED 37 9 * * 0 profile_backup.py = weekly backup, local-only (no Yahoo
    requests, no browser stop), keeps recovery-ladder rung 2 fresh.
- Wednesday 20:11 waiver-scan vs 20:24 daily: LOCK_NB skip is harmless
  (waiver run produces the full report). Cron logs grow ~KB/day; fine.
- Docs synced: TEAM_OPERATOR crontab block + GAME_PLAN Part 9 table (5 entries).

## Web UI team pages #121 (2026-09-13/14, PR #122)
- Local web UI (127.0.0.1:5000) gained /team (latest operator report:
  matchup, lineup plan, monitor flags, applied moves), /league (standings +
  matchup from logs/league-report.json, my row highlighted), /cron (run
  history + schedule). Nav gained My Team / League / Cron.
- Architecture rule: the web process reads LOCAL artifacts only
  (logs/team-operator.jsonl, logs/league-report.json); live Yahoo reads stay
  with the WAF-aware cron jobs. New cron entry: 19 21 * * * league_report.py
  --out logs/league-report.json (nightly 21:19).
- league_report --out: atomic (mkstemp + replace), captured_at stamp on the
  file copy only; waf_blocked never overwrites the last good snapshot;
  persist OSError never loses the printed report.
- Loaders normalize/tolerate: non-dict lines, bad UTF-8, null moves/plan,
  non-dict matchup/standings — corrupted artifacts render honest pages,
  never 500. Suite: 206 fast tests.

## Web nav grouping #123 (2026-09-14, PR #124)
- Header now two labeled groups: FD nation (My Team / League / Cron) first,
  then Prediction engines (Dashboard / Players / Win Predictions / Ratings /
  Strategy / SOS). Groups are unbreakable spans (narrow windows never split a
  label from its links). Test pins labels + order. Suite: 206 fast + 18 web.

## League team detail pages #125 (2026-09-14, PR #126)
- /league names are links to /league/team/<name>: standing + derived stats,
  season trajectory (from the new nightly audit history), matchup card +
  15-man roster for the current opponent, honest 404 for unknown teams.
- Nightly cron now: league_report.py --opponent-roster --out logs/league-report.json
  --audit logs/league-report.jsonl (21:19). The .jsonl accumulates the season.
- Hard lessons pinned by tests: bonus roster read degrades on LeagueReadError
  but RE-RAISES LeagueWafBlocked (subclass!) so a mid-roster block keeps the
  full waf_blocked contract; standings parser strips comma thousands (PF >
  1,000 would have killed the snapshot mid-season); detail page coerces
  numerics at the boundary (junk types → 0.0, never 500).
- Yahoo WAF is NOT Cloudflare: edge answers "server: ATS" (Yahoo's own Apache
  Traffic Server); blocks are volume-based (Request denied / 999), clearing
  after 15-30 min quiet. OAuth/API path rejected by user (app approval takes
  weeks) — CDP+JS in the real browser stays the method.
- Suite: 220 fast tests.

## All-teams rosters #127 (2026-09-14, PR #128)
- Nightly job is now: league_report.py --all-rosters --out … --audit …
  (21:19). team_ids() maps name → roster number from standings-page anchors
  for FREE (same page as standings; path-validated fail-closed — the
  ordering invariant standings → team_ids → matchup is pinned by a test
  because matchup() navigates away and the regression bit once already).
- --all-rosters: 9 paced reads (~5s each incl. 3s --roster-delay + 2s
  settle, ~60-90s total); per-team LeagueReadError degrades with a warning;
  LeagueWafBlocked re-raised (exit 2, no persistence, no restore-nav).
  TEAM_ID filtered before the paced loop. Rosters persist under
  report["rosters"] = {name: [players]}.
- matchup() live-game fix: score regex accepts "vs." (live layout) and
  projections fall back to "Orig Proj" (ordered opponent, team — verified
  against the live body). Attribution is pure _build_matchup_score + tests.
- Detail pages: roster from the all-teams map → history fallback (dated,
  newest wins) → legacy opponent-only field. Verified live: all 9 teams,
  15-17 players each (Namaste → Lamar Jackson).
- Suite: 232 fast tests.

## 2026-09-14 — #129 live league scoreboard + game-day refresh (PR #130)

- Problem: web UI showed only our matchup from the nightly snapshot; the other
  8 teams' live scores were invisible during games, and everything sat stale
  for a day. (Standings 0-0-0 in week 1 is correct Yahoo behavior — records/PF
  count completed weeks only.)
- `yahoo/league.py scoreboard()`: reads ALL matchups of the week off the
  league-home scoreboard section (UL with `/f1/<league>/matchup?week=N&mid1=&mid2=`
  links). Evaluates on the page standings() already loaded → zero extra Yahoo
  requests. (id,name) pairs per anchor, deduped by id, in DOM order — the same
  order the nums regex reads — so name↔score attribution is structural (k3
  caught the mid-order variant crossing attribution). Duplicate team names
  survive via ids; matchup link needed only for the week.
- `league_report.py --light`: game-day refresh — standings + scoreboard +
  matchup only (~3 page loads, no rosters); `--out` merges via merge_report()
  so the nightly 9-team roster map survives; leftover waf_blocked status /
  stale captured_at popped. Conflicts with roster flags.
- Host crontab gained light runs at :05/:35 in NFL windows (JST): Fri 08-13
  (TNF), Mon 02-13 (Sun slate), Tue 08-13 (MNF). Web UI stays ~30 min from
  live during games. Nightly 21:19 full --all-rosters unchanged.
- Web: /league "Week N scoreboard" card (all matchups, live scores, proj,
  links to team detail pages, ours highlighted); /cron lists new entries.
- Process: CodeRabbit reviewed round 1 (CdpError degrade + id-dedup findings,
  both applied), rate-limited on re-review → k3 gated the rest alone
  (user-approved fallback). k3 round 3 caught the attribution-crossing issue.
- Suite: 243 fast tests. Verified live: light run captured all 5 week-1
  matchups with scores moving between captures; merged snapshot kept rosters.
- Reminder burned in twice this session: manual CDP pokes MUST restore the
  league tab to /f1/1329011/2 — find_team_target fails otherwise, and the
  404 /f1/1329011/scoreboard route does not exist (scoreboard lives on
  league home).

## 2026-09-14 — #131 self-healing team-tab anchor (PR #132)

- find_team_target() no longer hard-fails on a drifted league tab: exact
  match returns as before (2+ exact matches stay fatal); no exact match but
  ≥1 tab on the fantasy host → first tab navigated back to /f1/1329011/2
  (one page load, stderr note), re-selected fresh, returned; no fantasy tab
  → original "found 0" (sports.yahoo.com articles never hijacked; stays the
  session-liveness signal). All 7 tools heal automatically.
- Contract now: heal at start (find_team_target) + restore at end
  (league_report finally). Cron runs are drift-proof.
- Live drill: tab moved to league home → league_report --light logged the
  recovery, exit 0, tab restored. Suite: 249 fast tests.
- CodeRabbit rate-limited → k3 gated alone again (APPROVE; log-ordering nit
  applied). k3 side notes (accepted, not bugs): navigate() doesn't tolerate
  transient evaluate errors mid-commit (pre-existing, shared with restore);
  first-candidate could sacrifice a half-filled human form (user-sanctioned).

## 2026-09-20 — where the stats actually come from (provenance chain)

- One central source: in-stadium official scorers feed the NFL's GSIS (Game
  Statistics & Information System); Elias Sports Bureau is the NFL's official
  statistician and issues official stat corrections midweek (land by Thursday
  US). Every fantasy platform mirrors these (Yahoo has a statcorrections page).
- Distribution: Sportradar is the NFL's official data distribution partner
  (licensed real-time feeds to Yahoo/ESPN/etc.); Next Gen Stats tracking is a
  separate feed (Zebra RFID chips + AWS). Yahoo player projections are
  Rotowire-powered (fine print on their pages).
- This repo never touches Yahoo for stats: src/ingest.py pulls nflverse
  release CSVs, which scrape the same official nfl.com/GSIS play-by-play.
  One source, two paths.
- Operational rule: our tables and Yahoo's can drift midweek until corrections
  land — run `cli.py ingest --refresh` (or team_operator `--refresh-data`)
  after Thursday US corrections, before weekend lineup decisions.

## 2026-09-20 — Cloudflare tunnel + persistent web UI (jra-van-re method)

- Three user LaunchAgents (`tools/install_launchd.py --agent {browser,cloudflared,web}`):
  `com.fdnation.browser` (keepalive, pre-existing), `com.fdnation.web` (Flask UI on
  127.0.0.1:5000, KeepAlive, logs/web.log — added after a session-bound process died
  and took the public URL down), `com.fdnation.cloudflared` (quick tunnel).
- Tunnel: `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:5000`;
  `tools/launchd/cloudflared-url-watch` greps logs/cloudflared.log, health-gates the
  edge, publishes the live URL atomically (0600) to **logs/cloudflared-url.txt**.
- Caveats: URL is **ephemeral** (changes on cloudflared restart, watcher republishes)
  and **unauthenticated** — anyone with the URL reads every page; treat the file like
  a password. Stable URL would need a named tunnel on a domain (unresolved, same as jra).
- Same day cleanup: jra-van-re's cloudflared (port 4173) had a duplicate orphan +
  double-loaded job (gui + system domains); gui copy booted out + disabled, system
  LaunchDaemon booted out + disabled via sudo. jra stack not running; only the nfl
  tunnel (5000) remains. jra plists left on disk (reversible).
