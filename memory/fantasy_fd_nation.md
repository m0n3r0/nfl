# Fantasy Football — League "FD nation" (Yahoo, ID 1329011)

Persistent context for the user's Yahoo Fantasy Football league. Load this whenever
the user mentions fantasy football, their league, the draft, lineup, waivers, or Edge/CDP.

> **Naming note (2026-11-24):** the page old entries call **"Team View"** at
> `/league/teamview` is now **Matchup** at `/league/matchup` (template
> `matchup.html`, handler `pages::matchup`). Historical entries below keep
> their original wording as a dated record; `/league/teamview` still 302s to
> the new path with the query intact.

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
  **Team names re-verified 2026-11-20** (managers rename mid-season; current
  standings/logos capture): Namaste, Shiba Innu (us), Take it in the Browns,
  KNP Dripp, Gateway Guardians, Otto-matic Win!, Neal Before Zod, Game of
  Throws, Victory Formation, "My other team is a Ferrari.".
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
  Full review: docs/CODEBASE_REVIEW_INSEASON.md.
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

## 2026-09-20 — Jev advisory layer wired across the codebase

- src/jev.py holds the typesafe-sdk facade + all fantasy question packs
  (waiver / injury / trade). LEAGUE_CONTEXT fixed to the real 10-team .5PPR
  format (the first inline copy wrongly said 12-team).
- Consumers: tools/waiver_targets.py --jev N; tools/team_operator.py --jev N
  (injury triage for tagged roster players + top-N wire review in the report;
  fail-soft — Jev down never changes run status or blocks --apply);
  tools/trade_check.py --give X --receive Y (manual verdict + proj delta).
- Cron: Wednesday waiver-scan now runs --jev 5; the twice-daily runs stay
  Jev-free to bound API cost. Jev is advisory only — projections remain the
  source of truth.

## 2026-11-20 — Repo move to ~/m0n3r0/nfl + manual lineup pins

- Repo moved /Users/user/nfl → /Users/user/m0n3r0/nfl. Crontab (9 entries)
  rewritten to the new path — installed manually: `crontab <file>` hangs on
  this host (reads fine, writes block; no lock file visible in tabs/).
  com.fdnation.web reinstalled via tools/install_launchd.py (fixed the
  post-move certifi 500: the old process cached the old CA-bundle path).
  cloudflared + browser plists still reference the old path — running
  processes survived, but reinstall before their next restart (a cloudflared
  restart issues a NEW trycloudflare URL; watcher republishes).
- Manual pins (user request: Sun 23:47 / Mon 01:23 --apply runs were
  reverting manual start/sit calls — audit shows 6 moves applied Nov 15):
  /team pin toggles → data/pins.json (git-ignored, atomic, flock).
  propose_lineup(..., pinned=...) keeps pinned players' current slots like
  game locks; optimizer works around them. Operator loads pins fail-closed:
  corrupt file → status pins_error BEFORE any Yahoo navigation; web refuses
  toggles (409) and shows a notice. Audit reports carry "pinned": [ids].
  Tests: test_pins.py + pin cases in recommend/web/operator suites (296 fast
  pass). Docs: TEAM_OPERATOR "Manual pins", README web section.
- Roster sanity error since Nov 18 20:24 JST: "expected 15-17 roster players
  including IR, found 14" — a drop without replacement blocks ALL operator
  runs (even monitors) until the roster is back to 15+. **(RESOLVED Nov 20
  ~01:00 JST: roster back to 15+, runs green since — last error was the
  Nov 19 20:24 JST monitor.)**

## 2026-11-20 — HTTP engine swapped to Rust/axum (jra-van-re method)

- nfl-webd (rust/, axum 0.8 + minijinja + reqwest proxy) replaces Werkzeug
  as the serving engine on 127.0.0.1:5000 — same jv-webd front-door pattern:
  native fantasy pages (/team, /team/pin, /league, /league/team/<name>,
  /cron) rendered from the SAME web/templates + local artifacts; everything
  else (/, /players, /player/<id>, /predictions, /sos, /ratings, /strategy,
  /api/*) reverse-proxied to the Flask compute backend, now loopback :5001
  (new com.fdnation.backend agent; PORT=5001). Hop-by-hop stripping, XFF
  anti-spoof (loopback peer appends chain), streaming bodies, 502 on backend
  down, ctrl-c/SIGTERM graceful shutdown — all copied from jv-webd.
- Templates stay single-sourced (Flask + minijinja): url_for bridged as a
  minijinja global, tojson(indent=N) custom filter with Flask's HTML-safe
  escaping; two adjustments: pins.get(id) -> pins[id], pins.items() loop ->
  key loop + set (minijinja maps lack .get/.items). minijinja escapes "/"
  as &#x2f; in attributes (browser-identical). urlencode needs the
  minijinja "urlencode" feature.
- Pins: rust/src/pins.rs is an exact port of src/pins.py (same file/shape,
  flock + atomic rename, fail-closed); both writers interoperate — verified
  live: axum toggle preserved the user's 6 pins.
- install_launchd.py: AGENTS now (browser, cloudflared, web, backend); web
  template runs rust/target/release/nfl-webd (build first!). XML comments
  must not contain "--" or "&&" (plistlib/expat rejects).
- Verified: 16 Rust tests + 297 Python fast tests; all routes 200 via :5000
  and the public tunnel (URL unchanged — cloudflared untouched); dashboard
  proxied in ~4s; SIGTERM exits clean. Werkzeug no longer faces the tunnel.

## 2026-11-20 — Old-web code removed (Flask = analytics backend only)

- Clarification: the old HTTP engine was Werkzeug (Flask's dev server);
  Flask itself stays as the analytics compute backend (:5001) — the
  pandas/sklearn pages proxy through it. Removed the duplicated fantasy
  serving path from Python: web/app.py lost /team, /team/pin, /league,
  /league/team, /cron + artifact readers + CRON_SCHEDULE + pins wiring
  (axum serves all of that natively); cli.py lost the `web` subcommand.
- tests/test_web.py deleted; its 3 artifact-writer tests moved to
  test_league_report.py; the fantasy coverage lives in rust/src/tests.rs
  (added parity tests: bad/non-dict lines, bad UTF-8 tolerance — Rust
  readers now use from_utf8_lossy like Python's errors="replace" —
  garbage league report, nav grouping). 20 Rust + 265 Python fast pass.
- Verified after redeploy: all routes 200 via :5000 and the tunnel;
  backend :5001/team now 404 (fantasy code gone from Python).

## 2026-11-20 — / defaults to My Team

- nfl-webd: / now 302-redirects to /team (the public face is the fantasy
  team, not the model card). Dashboard moved to /dashboard, proxied with a
  path rewrite to the Flask backend's / (Flask unchanged). Nav Dashboard
  link + url_for("dashboard") updated. 22 Rust tests pass (root redirect +
  dashboard rewrite + nav). Verified local and through the tunnel:
  / -> 302 -> /team 200.

## 2026-11-20 — GameChannel-style matchup layout on /league

- Reverse-engineered sports.yahoo.com/nfl/gamechannel/?lid=1329011 via CDP
  (one tab, one navigation, DOM+computed-style dumps; tab closed after).
  Yahoo's method: flex row grow-ratio 5:3:5 — mirrored team blocks
  (left: flex-direction row-reverse + text-align end; right mirrored)
  flanking a center column of value|label|value rows (each row a 1:2:1
  flex, label min-width 60px): scores 26px with a 24px circular "vs"
  badge, Orig Proj + Proj Pts rows 16px/11px; 80px circular avatars;
  team name links to the fantasy team page; manager + record|rank below.
- Implemented in web/templates/league.html (native axum page): same 5:3:5
  flex + mirror + center rows, dark-theme adapted; all 5 matchups stacked,
  ours highlighted; leader green (score when live, else projection);
  record|rank joined from standings via filtered for-loop; initials
  avatars computed in the Rust handler (minijinja strings lack .split();
  template falls back to first letter via |default for engine parity).
  Dropped: manager names, win-% footer, players-remaining (not in our
  artifacts — no fabricated stats). Standings table kept; redundant
  "My matchup" card removed (covered by the highlighted card).
- 22 Rust tests pass (layout assertions added); verified through the
  tunnel with real week-11 data.

## 2026-11-20 — Team View (players side-by-side) on /league/teamview

- Reverse-engineered the GameChannel "Team View" tab via CDP (click tab,
  dump DOM): a real mirrored TABLE — Stats|Player|Proj|Fan Pts|POS|Fan
  Pts|Proj|Player|Stats, Pos column shaded as the center spine, player
  cells = name + 11px NFL-team tag + game-info subline, 37px bordered
  rows, separate starter/bench tbodies, All Players/Starters/Bench tabs.
- Implemented /league/teamview?a=<team>&b=<team> (defaults to the current
  matchup): same mirrored table + Pos spine, dark theme. Rows aligned by
  slot occurrence (QB vs QB, 1st RB vs 1st RB, ...), starters then bench/IR.
  Our side from the latest ok operator plan (HAS projections); other teams
  from league-report rosters (no proj -> "—", never fabricated). Fan Pts /
  Stats / game-info omitted: not in our artifacts. "Team View →" link on
  every /league matchup card. Missing roster -> notice, one-sided rows.
- 24 Rust tests pass; verified through the tunnel: 15 paired rows for
  Shiba Innu vs Take it in the Browns (Purdy/Stafford QB, CMC/Taylor RB...).

## 2026-11-20 — Opponent projections captured (Yahoo Proj Pts)

- opponent_roster (yahoo/league.py) now extracts Yahoo's per-player "Proj
  Pts": the td right after the Fan Pts cell (td.pts); bye rows merge
  FanPts/Proj/%Start into a colspan=3 cell -> proj null (never guessed).
  Numeric-only regex; Python keeps proj as float|None (other fields stay
  strings). Old artifacts without proj still read fine.
- Nightly --all-rosters captures it automatically; --light merges keep the
  last good rosters. Team View (Rust tv_side) reads roster proj; template
  labels sources: left = our model, right = Yahoo Proj Pts.
- Verified live: 9 teams refreshed, opponent 13/15 with proj (Stafford bye
  -> null); /league/teamview shows CMC 16.38 vs Taylor 13.1, Deebo 3.6 vs
  Higgins 14.8 etc. 266 Python fast + 24 Rust tests pass.

## 2026-11-20 — Team logos captured via cron, served by nfl-webd

- yahoo/league.py team_logos(): free evaluate on the league home page (call
  right after standings()); standings-table rows map team name -> avatar URL
  (img[class*=Avatar] inside the link's tr; skip "My Team" nav link). The
  div-based matchup list pairs two teams per container — do NOT use it.
- tools/logo_sync.py: downloads from public CDNs (s.yimg.com / cloudinary),
  magic-byte type sniff (cloudinary URLs lack extensions -> .jpg/.png),
  data/logos/<id>.<ext> + data/logos.json manifest, URL-cache (unchanged URL
  + file present = skip), fail-soft per team. Wired into league_report.py
  after the scoreboard read, so all 4 cron league_report entries refresh
  logos automatically; no crontab edit needed. Standalone retry CLI.
- nfl-webd: /logos/{file} route (allowlist [A-Za-z0-9._-], no "..", 404/400
  on traversal), logo_urls() only maps entries whose file exists; league
  cards (mu-logo img, initials fallback), Team View header logos, team page
  logo. data/logos/ + manifest gitignored (personal photos possible).
- Verified live: 10/10 logos (Shiba Innu = catbot 2.png), tunnel /league has
  10 imgs, /logos/2.png 200 image/png, traversal 400, teamview 2 header
  logos. 274 Python fast + 25 Rust tests pass.

## 2026-11-20 — League is the default homepage; menu League/My Team/Cron

- / now 302 -> /league (was /team); nav order in layout.html: League,
  My Team, Cron (shared template, so analytics pages get it too).
- Tests updated: root_redirects_to_league + explicit nav-order asserts.
- Verified through tunnel: / -> 302 -> /league 200, menu renders in the
  requested order. 25 Rust tests pass.

## 2026-11-20 — Realtime points research: free feeds investigated

- User hypothesis CONFIRMED from Yahoo GameChannel page source: footer
  strings "Certain Data by {first_provider} and {second_provider}" with
  FOOTER_SPORTRADAR="Sportradar", FOOTER_ROTOWIRE="Rotowire". Sportradar is
  the NFL's official data distributor (the "central broadcaster"); paid
  enterprise push feeds. developer.sportradar.com offers a Free Trial
  (REST, rate-limited) — no free WebSocket.
- NO free public WebSocket feed of NFL player points exists. Free path =
  REST polling + our own axum WS push.
- ESPN hidden API VERIFIED LIVE (free, no auth, no key):
  * site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
    (week 11, TNF Colts@Texans 2026-11-20T01:15Z, event id 401873066)
  * .../nfl/summary?event=<id> -> boxscore.players with FULL per-player
    stats: passing C/ATT YDS TD INT, rushing CAR YDS TD, receiving REC
    YDS TD TGTS, fumbles, defensive, kicking, returns. Verified on
    finished week-10 game 401873052 (Daniels 249yds 3TD, Diggs 6/83/1).
    Live cadence unmeasured (no game live at probe time) — measure at TNF.
- NFL.com legacy liveupdate game-center JSON: 404 for 3 eids — endpoint
  appears retired/moved. /api/schedule also 404.
- the-odds-api: NFL odds/props only, not fantasy points; limited free
  credits. api-sports.io: 403 from this network (unverified).
- KEY: we already own the conversion — src/scoring.py score_row(stats,
  weights) + FD nation overrides (INT -1.0, receptions 0.5, no milestone
  bonuses, per README Scoring). ESPN raw stats -> our exact league points
  with zero Yahoo dependency (different host = no WAF risk).
- Plan: game-window poller (ESPN scoreboard -> live game ids -> summary
  boxscores -> score_row -> logs/live-points.json) + axum "ws" feature +
  /ws broadcast + vanilla JS score-cell updates. Latency ~1 min.

## 2026-11-20 — Live points pipeline built (Yahoo-exact requirement)

- REQUIREMENT (user): realtime points MUST match Yahoo, no drift.
- data/league-scoring.json: authoritative weights transcribed from the
  Yahoo settings page via CDP (pass 25yds/pt TD4 INT-1; rush/rec 10yds/pt
  TD6; rec 0.5; 2pt 2; fum lost -2; return TD 6; FG 3/3/3/4/5 by distance,
  XP 1, NO miss penalties; DEF sack1 INT2 fumrec2 TD6 safety2 block2
  returnTD6 xpReturned2; points-allowed tiers 10/7/4/1/0/-1/-4; no
  yards-allowed tiers, no milestone bonuses).
- src/live_scoring.py: ESPN boxscore+scoringPlays -> points. Gotchas:
  2pt conversions hide in the TD play's parenthetical "(X Pass to Y for
  Two-Point Conversion)" (failed ones say Failed); FG distances only in
  scoringPlays text; DEF TDs from play types (Interception Return TD,
  Sack Opp Fumble Recovery, Fumble Return TD) to avoid double counting;
  fum recoveries = opponent fumblesLost; return TDs count for DEF unit.
- VALIDATION: 15/15 roster players exact vs Yahoo week-10 finals (Purdy
  31.66, CMC 44.30, Deebo 24.40, Diggs 17.30, Sanders K 14.00, Steelers
  DEF -3.00...). Frozen as tests/fixtures/live_scoring/ (~100KB, 8 games)
  + tests/test_live_scoring.py. Full poller --week 10 backtest: 933
  players, all spot checks exact.
- tools/live_points.py --loop (launchd com.fdnation.livepoints, installed):
  ESPN only (zero Yahoo WAF risk), 30s cadence in-game, sleeps to next
  window; reconcile vs fresh (<=180s) Yahoo light snapshot, tolerance 0.5,
  drift flag -> UI shows Yahoo's verified number; unmatched starters
  reported (name-drift detector); atomic logs/live-points.json + audit.
- nfl-webd: axum ws feature, /ws (initial artifact + broadcast on file
  mtime change, 30s pings), /live-points JSON fallback. layout.html JS:
  data-live-team/player/def updates, week-guarded, reconnect+poll fallback,
  LIVE/OFFLINE badge, amber drift fallback.
- Verified through tunnel: wss:// connect, initial payload, atomic-update
  push received. 294 Python fast + 27 Rust tests pass. TNF 10:15 JST today
  is the first live game window (poller wakes 2 min before kickoff).

## 2026-11-20 — Live cadence 30s -> 10s, change-gated (polite to free API)

- User: 30s too slow, shorter without spamming. ESPN headers: no ETag;
  cache-control max-age=2 (summary) / 8 (scoreboard) — their freshness
  contract. `enable=` trimming param: ignored (no payload reduction).
- Design: 10s cycle (+/-10% jitter, --interval flag, floor 5s). One
  scoreboard req/cycle; summary re-fetched ONLY when game signature
  changes (period, clock_seconds, scores, situation.lastPlay.id — the
  scoreboard carries all of it). Stopped clock = zero summary requests.
  Forced sweep every 6 cycles (~60s) for stat corrections. >=0.25s between
  requests. Final games fetched once, cached. Fetch failure serves last
  good cache (fetch=stale). fetch_stats {fresh,cached} in artifact + log.
- Verified LIVE during TNF (Colts@Texans): 10s cycles, fresh=1 on active
  drives, fresh=0 cached=1 on stopped clock; points flowing (Nico Collins
  10.7, Stroud 5.72...). 298 Python fast tests pass (4 new gating tests).

## 2026-11-20 — Documentation swarm audit (all docs vs code)

Parallel-lane audit of every doc against the current code/architecture:
- README: added colored mermaid architecture flowchart (6 layers: sources
  blue / robots green / artifacts amber / web pink / edge purple / human
  teal) + plain-language walkthrough; fixed stale `cli.py web` reference
  (removed in f778bcc), completed native route list (/league/teamview,
  /logos, /live-points, /ws), pages + artifact lists, test table (34 Python
  files + 27 Rust tests, new pins/logos/live/launchd rows), layout entries
  (src/pins.py, src/live_scoring.py, rust/, logo_sync, live_points, 5
  launchd agents), scoring section now distinguishes presets (planning)
  vs data/league-scoring.json (realtime authority).
- docs/TEAM_OPERATOR.md: crontab block marked installed at the new path;
  nightly snapshot now documents Proj Pts + logo sync; "~30 min from live"
  replaced with the ~10s live-points feed + reconciliation-backstop role.
- docs/GAME_PLAN.md: stale /Users/user/nfl path fixed (repo moved); Part 8
  trackers #102/#103 marked historical (issues gone, windows passed, now
  week 11); pins + live points added to the human/robot division; cheat
  sheet notes launchd agents (livepoints/web/backend/cloudflared).
- skills/fantasy-read/SKILL.md: v1.1.0 — macOS/Chrome current quick start
  via yahoo/cdp.py, Windows/Edge pattern marked draft-era, endpoints
  re-verified (settings scoring table, ?week=N finals, td.pts/Proj DOM).
- memory league facts: opposing team names re-verified (renames happened).
- Left as-is (correctly historical): docs/archive/* (all banner-marked),
  docs/CODEBASE_REVIEW_INSEASON.md (DELIVERED banner), PROJECTION_BACKTEST.md
  (measurement record), drafts/2026-09-02 (draft record), memory journal
  entries (history is never rewritten).

## 2026-11-20 — Team View rebuilt as the Yahoo /matchup layout

- Reverse-engineered /f1/1329011/matchup via CDP: header card (team blocks
  flanking score + Orig/Live Proj + players remaining), ONE mirrored
  fixed-layout table Stats|Player|Proj|Fan Pts|Pos spine|Fan Pts|Proj|
  Player|Stats, starters + bench bodies, totals row.
- teamview.html rewritten: table-layout fixed + colgroup (5/24/9/9/6/9/9/
  24/5), left side right-aligned toward the spine, right mirrored; player
  cell = name + "SF - QB" + game-info subline; injury/bye tags in Stats col;
  Fan Pts = live points (week-matched artifact), Proj = model (left) /
  Yahoo Proj Pts (right); header scores prefer live totals, fallback to
  the Yahoo snapshot; records from standings; players remaining counted
  from game states (matches Yahoo's 9 vs 7 exactly).
- Rust: TvEntry + position/fan_pts/game_info; tv_norm_name/tv_canon_team
  (Was->WSH etc); tv_team_games from artifact games meta (poller now
  captures homeAway); game times parsed from ESPN's no-seconds dates
  ("%Y-%m-%dT%H:%MZ" fallback) and shown JST-labeled; totals/remaining in
  handler. JS: data-live-fanpts(-def) updates the Fan Pts cells directly.
- GAP FIXED: snapshot rosters held only the OTHER 9 teams — our own roster
  was missing, so our side had no NFL teams/game info. yahoo/league.py
  my_roster() evaluates the shared roster JS on the team page with ZERO
  navigation; league_report --all-rosters now captures it as the last read
  (doubles as the tab restore). Verified live: 15 rows merged, Team View
  shows SF - QB etc + JST game lines + 9/7 remaining + Taylor 4.70 live.
- 299 Python fast + 27 Rust tests pass.

## 2026-11-20 — weekly points archives + Team View week selector

- User asked whether previous weeks' fantasy points survive. Answer was:
  matchup scores/standings/rosters/projections YES (append-only jsonl,
  weeks 1-11), per-player points NO (live-points.json overwritten) but
  recomputable from ESPN. Closed the gap:
- tools/live_points.py archive_if_final(): once all games of a week are
  "post", writes logs/live-points-week-N.json (players/def/def_named/
  totals/games/scoring_sha + archived_at); rewrites only on content
  change (late corrections). Called from loop() and --once/--week.
- Backfilled weeks 1-10 from ESPN (900-1045 players/week, drift=False).
- Team View ?week=N: historical rosters/matchup from the latest
  league-report.jsonl snapshot of that week (scoreboard week is the
  authoritative marker — matchup.week lags at boundaries), finals from
  the archive, plan from that week's operator runs. Week selector 1..N.
  Past-week header shows Yahoo's OFFICIAL final (snapshot outranks our
  recomputed sum); "players remaining" suppressed for past weeks.
- DEF resolution for history: def_named reflects the CURRENT roster, so
  historical DEFs resolve via the archive's def map keyed by ESPN abbr
  (tv_live_maps third map) + tv_def_abbr nickname map ("Steelers"->PIT)
  for plan rows whose team is missing (week-10 snapshot was captured
  AFTER the user dropped Steelers DEF mid-week).
- Verified: week-10 page shows all 9 starters exact vs Yahoo golden
  (Purdy 31.66, CMC 44.30, Kamara 14.90, Olave 4.50, Watson 5.20,
  Strange 7.90, Brown 24.30, Sanders 14.00, Steelers -3.00); header
  143.76-104.02 == Yahoo official final. 301 Python fast + 28 Rust pass.

## 2026-11-20 — fix: opponent side empty on historical Team View

- Root cause: the historical picker took max(captured_at) of week-N
  snapshots — the LAST ones are light runs with NO rosters, so the
  opponent rendered 17 empty cells + missing notice (our side survived
  via the operator plan). Fix: prefer latest snapshot WITH non-empty
  rosters, then latest captured_at (tuple max_by). Every week has daily
  full runs with rosters (12:20 UTC), so all weeks resolve.
- Also: historical snapshots predate own-roster capture, so our plan rows
  had no team/pos — tv_side now borrows team/pos from the CURRENT roster
  when the historical one lacks our team (points/game info stay
  week-archived; DEF nickname map covers dropped DEFs).
- Verified week 10: opponent starters sum EXACTLY to Yahoo's official
  104.02 (Dak 35.42, Jefferson 11.90, Amon-Ra 23.80, McBride 6.20,
  Cam Little 19.00, Ravens DEF 2.00; Irving/Godwin bye = dash).
- Known caveat (documented in README): week-5 opponent rows sum 95.08 vs
  official 96.08 — the snapshot's slots predate late Sunday lineup swaps;
  header always shows Yahoo's official total. Not a scoring bug (week 10
  exact, accuracy gate frozen).
- 29 Rust tests pass (2 new regression tests).

## 2026-11-20 — Team View: other-team history + final-score merge

- User: selecting another team's Team View then a past week snapped back
  to OUR historical matchup. Two bugs: (1) week-selector links dropped
  a/b params; (2) b defaulted to OUR matchup's opponent. Fixed: links
  carry urlencoded a/b; b resolves via opponent_of(a) from the week's
  scoreboard; added team dropdowns (GET form, hidden week) on the page.
- Found while verifying: the with-rosters snapshot is captured Sunday
  morning ET, so its scoreboard is MID-WEEK (week-5 Browns 107.0 vs
  final 134.32; week-10 opponent header was stale 102.02 vs 104.02 —
  earlier "exact" claim had conflated header with totals row). Fix:
  past mode MERGES latest-with-rosters (rosters) + latest-any (final
  scoreboard/standings overlay).
- Verified: Browns wk5 header 134.32-95.52 vs Neal Before Zod (their
  real wk5 opponent), rows sum exactly 134.32; Shiba wk10 143.76-104.02.
- 31 Rust tests (3 new: other-team history, final-scoreboard merge,
  earlier picker/link regression).

## 2026-11-20 — past-week opponent is schedule-locked (no dropdown)

- User: past-week opponents are FIXED by the schedule; the b pulldown was
  wrong — switching team a carried the stale b param, showing the
  previous team's opponent. Fix: in past mode b is ALWAYS opponent_of(a)
  from that week's scoreboard (explicit b param ignored); UI shows the
  opponent as locked text (tv-locked), no b select; week links carry only
  a. Current week keeps the b dropdown for ad-hoc comparison.
- Verified: wk5 Browns + wrong b=Shiba -> still Neal Before Zod; switch
  a to Shiba wk5 -> KNP Dripp (our real wk5 opponent); current week has
  the b dropdown. 31 Rust tests pass.

## 2026-11-20 — five-reviewer system audit (orchestrated)

- R1 web/Rust, R2 pipeline, R3 docs, R4 mermaid, R5 hygiene — independent
  scoped passes (no subagent tool this session). Ledger:
  ~/.hermes/cache/scratch/nfl-audit-20261120.md.
- BUGS FOUND+FIXED: installed launchd plists for browser AND cloudflared
  still pointed at pre-move /Users/user/nfl (browser exit 1 since Sep 15;
  cloudflared a restart time bomb). Reinstalled both via
  install_launchd.py; browser preflight green; tunnel URL rotated
  (watcher published new one, 0600). LESSON: after a repo move, reinstall
  ALL launchd agents, not just the ones that visibly break.
- Docs fixed: README 27->31 Rust tests; mermaid gained the weekly-finals
  archive node/edges (validated by actually rendering with mmdc + Chrome
  for Testing — node v22 available at ~/.local/bin); lib.rs route doc,
  CRON_SCHEDULE sync comment (app.py twin no longer exists), app.py
  docstring, TEAM_OPERATOR nightly bullet (all 10 rosters incl. ours).
- UX: league_team.html now has a Team View link (?a=<team>).
- Clean bills: crontab 9 entries match Rust CRON_SCHEDULE + runbook;
  gitignore/secrets/branches clean; GAME_PLAN/SKILL/BACKTEST docs current;
  CODEBASE_REVIEW_INSEASON intentionally historical.
- 31 Rust + 301 Python fast pass; all routes 200 via the new tunnel URL.

## 2026-11-20 — "My Team" nav is now a team picker

- User: top-menu My Team should be selectable to view other teams (e.g.
  Victory Formation), not fixed to Shiba Innu.
- layout.html: My Team link -> <select class="nav-team"> with all 10
  teams from the latest snapshot standings (fallback roster keys).
  Own team option -> /team (operator view); others -> /league/team/<name>.
  nav_sel preselects the current page's team; plain-link fallback when
  no snapshot exists.
- Fed by BOTH renderers: Rust render() injects nav_teams/nav_my_team into
  every ctx; Flask app.py @app.context_processor does the same for the
  proxied analytics pages. team/league_team handlers set nav_sel.
- Verified live: /league 10 options; Victory Formation page preselects
  Victory Formation; /team preselects My Team: Shiba Innu; /players
  (Flask) has the picker too. 31 Rust + 301 Python fast pass.

## 2026-11-20 — prediction engine moved to Rust (Flask removed)

- User: analytics pages (Dashboard/Players/Win Predictions/Ratings/
  Strategy/SOS) slow via Flask; refactor to the FD nation method, keep
  the Python engine. Orchestrated as scoped passes (audit -> producer ->
  Rust pages -> Flask removal -> verify); no subagent tool this session.
- Audit: /dashboard 3.8s, /players 3.1s, /sos 3.0s — corpus.build +
  project_players (+ model train/CV for dashboard) ran PER REQUEST.
- New: tools/predictions_report.py computes everything OFFLINE into
  data/web/*.json (dashboard, players + per-player files, predictions,
  ratings all season-week combos, strategy all teams x seasons, sos,
  modelcard). Fail-soft per section, atomic writes, JSON-safe via
  df.to_json. com.fdnation.predreport launchd agent: daily 06:12 JST +
  Wed 21:05 (after waiver --refresh-data), RunAtLoad.
- Rust: analytics.rs native handlers (q/pos/week/team/season filtering
  in Rust), same templates (one minijinja fix: k.replace -> |replace
  filter), missing-artifact notice page, /api/* served from artifacts.
- REMOVED: web/app.py, com.fdnation.backend (booted out + plist deleted),
  the whole reverse proxy (reqwest dep gone, Config.backend gone,
  fallback is a plain 404), flask in requirements.txt.
- Results: dashboard 3.8s->3ms, players 3.1s->34ms, sos 3.0s->1.6ms;
  via tunnel everything ~0.3s (network-bound). 308 Python fast + 29
  Rust tests pass. Mermaid updated (PRED robot + DATAWEB artifact,
  FLASK node gone) and re-rendered with mmdc.
- Gotchas hit: XML comments cannot contain "--" (plist template);
  minijinja lacks Python str method calls; first artifact build ~1h
  cold (features cache fill), warm rebuilds minutes.

## 2026-11-21 — DEF city/nickname flip broke past-week Fan Pts (fixed)

- Symptom: /league/teamview?week=8 showed "–" for Shiba's DEF (Chicago)
  even though the week-8 archive had the points (DEF:CHI = 6.0).
- Root cause: Yahoo flips DEF display between NICKNAME ("Bears") and
  CITY/STATE ("Chicago", "Minnesota", "Jacksonville") depending on the
  capture page — the same player (yahoo_id 100003) is recorded both ways
  across operator runs (weeks 3, 7, 8, 10). Historical plan rows carry no
  team abbr, and tv_def_abbr() only knew nicknames, so all three lookup
  paths (def_named / team abbr / name->abbr) missed.
- Fix: tv_def_abbr (rust/src/pages.rs) now maps nicknames + cities/states,
  strips a "D/ST" suffix, and resolves two-team cities (NY, LA) on the full
  name only. Regression tests in rust/src/tests.rs; 37 cargo tests pass.
- Verified live: weeks 3/7/8/10 all render DEF finals (5.00/4.00/6.00/-3.00).
- Cosmetic leftover: the live-badge JS keys off def_named (nickname) — a
  city-named plan row during a LIVE week can miss the badge flash; the
  server-rendered value is still correct on every artifact refresh.

## 2026-11-21 — independent re-review + per-file code guide

- User had Kimi review the code; asked for another independent review +
  new docs explaining every file with colored mermaid charts.
- Independent review findings (both FIXED):
  1. src/features.py docstring said cache was "parquet" — actually
     gzipped CSV (team_ratings_{season}_w{week}.csv.gz). Corrected.
  2. Persisted win_prob_model.joblib was pickled under sklearn 1.6.1 but
     runtime is 1.9.1 (load_model emitted InconsistentVersionWarning).
     Retrained via model.train_and_persist() (n_train 1086) and rebuilt
     data/web artifacts — bundle + runtime now both 1.9.1, skew gone.
     Lesson: retrain the model after any sklearn upgrade.
- Yahoo-layer invariants re-verified intact: loopback-only CDP, identity
  fail-closed, locked-row parsing, WAF signature, pins-before-navigation,
  flock. No new bugs there.
- NEW docs (all mermaid validated with mmdc, 39/39 render):
  docs/CODE_GUIDE.md (index + whole-codebase map + color legend) and
  docs/code/{SRC_ENGINE,YAHOO_LAYER,TOOLS,RUST_WEB,TESTS_INFRA}.md —
  every file's functions + invariants + colored function flowcharts.
  README links the guide from the intro.
- Test counts grew via intervening commits (swarm audit 819579e + DEF fix
  99af36a added regression tests): now 324 Python fast + 37 Rust, green.

## 2026-11-24 — DEF pick-six excluded from points-allowed tier

- User: Team View KNP Dripp vs Otto-matic Win! showed Vikings DEF -3,
  Yahoo had 0; reconciliation delta -3.0 on Otto-matic only.
- Root cause: MIN@SF final 35-10 included SF's Ji'Ayir Brown 18-yd
  INTERCEPTION RETURN TD (+XP = 7 pts). Yahoo's DEF points-allowed
  tiers exclude points scored by the OPPONENT'S DEF/ST (the defense
  wasn't on the field) → allowed 28 (28-34 tier = -1) + 1 sack = 0.
  Our def_points used the raw score 35 → -4 tier + 1 sack = -3.
- Fix: src/live_scoring.py adds defensive_points_allowed(abbr, game):
  walks scoringPlays cumulative away/home deltas, subtracts plays by
  the opponent typed as non-offensive (INT/fumble return, kick/punt
  return, safety, defensive XP/2pt return, blocked kicks). Uses raw
  score for synthetic fixtures lacking cumulative scores (tests pin
  the old semantics there). def_points now uses it for the tier.
- Regression: tests/fixtures/live_scoring/min-sf-week11.json (real
  ESPN summary trimmed) + test_def_pick_six_excluded_from_points_allowed.
- Verified: Vikings 0.0, Otto-matic total 93.16 == Yahoo scoreboard,
  reconciliation delta 0.0, web page shows 0.00. Restarted livepoints
  agent (it cached the old module) — its own poll now holds the fix.
- 325 Python fast + 37 Rust tests pass.

## 2026-11-24 — Team View opponent is ALWAYS schedule-locked (no B dropdown)

- User: the JS auto-sync fix was not enough — current-week Team View must
  NOT offer an opponent dropdown at all, like past weeks. Opponent is
  always fixed by that week's schedule.
- Replaced the JS auto-sync (previous section's approach) with server-side
  lock: b_name = opponent_of(a_name) from the week scoreboard for BOTH
  past and current; explicit b param ignored everywhere. Template shows
  tv-locked text for b; only team A is a dropdown. Removed the
  opponents map / TV_OPPONENTS script.
- Updated 3 Rust tests (no B dropdown, stale b ignored, query override).
  Verified all 10 teams live: each pairs with its schedule opponent;
  stale b=Take it in the Browns with a=Namaste still yields Victory Formation.
- 325 Python + 38 Rust tests pass; web daemon restarted.

- User: current-week Team View team dropdown changed team A but kept the
  old team's opponent as B (e.g. selecting Namaste paired it with Take it
  in the Browns instead of Victory Formation), because both selects submit
  their current values and the handler honors explicit b in current week
  (ad-hoc comparison).
- Fix: rust/src/pages.rs builds an opponents map (team -> scheduled
  opponent, both directions) from the week's scoreboard, passes to the
  template. teamview.html embeds it as TV_OPPONENTS JSON in a <script>
  block; the A select's onchange calls tvSyncOpponent(this) which sets
  B to the scheduled opponent. Past weeks unchanged (B is locked text,
  derived from that week's schedule server-side).
- Verified via node executing the embedded JS with a stub DOM: Namaste ->
  Victory Formation, KNP Dripp -> Otto-matic Win!. Rust regression test
  added (38 Rust tests). 325 Python fast tests pass.

## 2026-11-24 — Rust web UI swarm review + refactor + architecture doc

- User: review overall Rust web code for robustness/clarity without over-
  engineering; colored mermaid docs; update all docs; use swarm subagents.
  No subagent tool exists in this session → five independent scoped passes
  (R1 structure, R2 robustness, R3 docs, R4 tests, R5 behavior). Ledger:
  ~/.hermes/cache/scratch/nfl-rust-swarm-20261124.md.
- Found+fixed:
  * teamview was a 298-line handler → extracted past_week_snapshot(),
    operator_plan(), side_sum(); now ~200 lines, no new abstractions.
  * live-points.json was read 3 different ways → single
    artifacts::read_live_points_text() used by endpoint, WS push, reader.
  * 3 bounded unwrap()s → let-else / match (no panic path).
  * doc comment still described the removed b dropdown → corrected.
- New docs/RUST_WEB_ARCHITECTURE.md: 7 colored mermaid charts (overview,
  startup, route table, Team View, analytics, pins, live WS) + refactor
  rationale. Linked from README + CODE_GUIDE + RUST_WEB.md.
- Doc freshness: 29 → 38 Rust tests in README / RUST_WEB / TESTS_INFRA.
- Verified: 47/47 mermaid blocks across 8 docs render via mmdc; 26/26 doc
  links resolve; 38 Rust + 325 Python fast tests; 12/12 routes 200 via
  tunnel; Team View opponent still schedule-locked (stale b ignored).

## 2026-11-24 — "Team View" renamed to "Matchup"

- User: the link called "Team View" is really a side-by-side matchup with
  the opponent, not a team roster viewer — rename it to "Matchup" and
  update all code and docs, no stale references.
- Renamed: route /league/teamview → /league/matchup (old path kept as a
  302 that preserves the query string so bookmarks survive), template
  teamview.html → matchup.html, handler pages::teamview → pages::matchup,
  internal tv_* helpers → matchup_*, url_for key league_teamview →
  league_matchup, link labels "Team View →" → "Matchup →", page title.
- Docs updated: README, CODE_GUIDE, GAME_PLAN, RUST_WEB_ARCHITECTURE,
  RUST_WEB, TESTS_INFRA, TOOLS, plus comments in league_report.py and
  yahoo/league.py. Historical memory entries keep their original wording
  with a naming note at the top of this file.
- Verified: 39 Rust (new legacy-redirect test) + 325 Python fast tests,
  47/47 mermaid charts render, 0 broken doc links, live tunnel: new route
  renders KNP Dripp vs Otto-matic Win!, old route 302s with a= query,
  League page shows "Matchup →".

## 2026-11-24 — League matchup cards: Yahoo hover-select + click-to-detail

- User: on Yahoo's /f1/1329011/matchup, moving the cursor over a matchup
  SELECTS it (no click) and clicking shows the side-by-side player detail;
  make our /league cards behave the same. Swarm agents (five scoped passes,
  no subagent tool) — ledger: ~/.hermes/cache/scratch/nfl-matchup-hover-swarm-20261124.md.
- RE (live Yahoo, one throwaway CDP tab + one navigation per page, tab closed):
  league home "View Matchup" links carry mid1/mid2; /matchup selector has
  `._yb_xx0e59 li:hover, li[aria-selected="true"] { color: grape-jelly }`.
- Implemented in web/templates/league.html ONLY (no Rust handler change,
  no JS, no new dep): each .mu-card gets an absolutely-positioned stretched
  link .mu-open (inset:0, z-index:1) to /league/matchup?a=&b=; CSS
  :hover/:focus-within highlights the card background + turns the team name
  grape-jelly (#c9a6ff); team-name links stay above (z-index:2) and still
  open the team page. Link labels/hint updated.
- Verified with CDP on OUR page: hover changes bg rgb(29,43,58)->(42,61,82),
  name -> (201,166,255), overlay absolute z1, name z2; all 5 card hrefs
  resolve to correct matchup pages; 39 Rust + 325 Python tests; 48/48
  mermaid charts render; 0 broken doc links. Docs: README, RUST_WEB,
  RUST_WEB_ARCHITECTURE (new colored chart 4b). Web daemon restarted.

## 2026-11-24 — Matchup URL is a clean path (no ?a=&b=)

- User: the ?a=&b= matchup URL is no longer needed — hovering selects the
  pair and clicking anywhere jumps to the side-by-side detail.
- Added /league/matchup/{team} (pages::matchup_named); the selected team is
  a path segment, b stays derived from the schedule. matchup_for() is the
  shared impl; /league/matchup (query a=) still works for old bookmarks,
  /league/teamview still 302s. All generated links now use the path form:
  League cards, their Matchup text link, team-page link, week selectors,
  and the team-picker form (tiny onchange builds the path).
- Docs updated: README (removed stale ?a=/ad-hoc ?b= text), RUST_WEB,
  RUST_WEB_ARCHITECTURE (route map + hover chart). 48/48 mermaid render.
- Verified live: cards link to /league/matchup/Namaste etc (no query),
  path route gives Namaste vs Victory Formation, old query still works,
  week links use /league/matchup/Namaste?week=N. 40 Rust + 325 Python tests.
