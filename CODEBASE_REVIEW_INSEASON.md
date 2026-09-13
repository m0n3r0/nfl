# In-Season Codebase Review — m0n3r0/nfl

> **STATUS: DELIVERED (2026-09-13).** Every issue mapped here (#79-#89) is
> closed and the #80 epic shipped: the operator/crons it proposes exist as
> `tools/team_operator.py` + `tools/team_analyzer.py` (runbook:
> `docs/TEAM_OPERATOR.md`). Keep this as the design rationale and issue map;
> for the current state of the code, see README.md and the runbook. Historical
> references below point into `docs/archive/`.

**Date:** 2026-09-12 · **HEAD:** `3cc467c` · **Scope:** every tracked file (src, yahoo, tools incl. debug, driver, tests, web, docs, skills, CI) · Supersedes the draft-centric docs/archive/CODEBASE_REVIEW.md (2026-08-31) as the current-state reference.

**Context:** the draft completed Sep 1–2 (15/15, see `docs/drafts/2026-09-02-fd-nation.md`). The repo now pivots to **in-season team maintenance**: one operator, runnable manually or via cron, that checks → monitors → adjusts → reports every day through the Week 16–17 playoffs. Tracked as epic **#80**.

**Verdict:** the operator does not start from zero. The *execution* half (live read/lineup/waiver operators, hermetically tested, fail-closed) exists; the *data* half (projections/matchups/lineup advice) is preseason-frozen and needs week-awareness plumbing. One P0 bug blocks the whole live path Thu–Mon.

---

## 1. Issue map (filed from this review)

| Issue | Title | Layer |
| --- | --- | --- |
| #79 | P0: roster reader fails Thu–Mon (locked rows) | live |
| #80 | Epic: in-season maintenance operator | meta |
| #81 | Browser/session keepalive (Chrome in /tmp, no relaunch) | live |
| #82 | Post-draft cleanup (cron block, `3}`, logs/, docs) | hygiene |
| #83 | Week/kickoff awareness (schedule drops gameday/gametime) | data |
| #84 | Bye weeks invisible (bye players stay startable) | data |
| #85 | Injury pipeline dead-ends at the draft board | data |
| #86 | 2026 in-season stats don't flow (STATS_SEASON=2025) | data |
| #87 | Weekly lineup recommender → exact Yahoo moves | feature |
| #88 | Missing reads (standings, matchup score) and writes (FA add, IR) | live |
| #89 | PRIVACY: league invite tokens in images/human_demo.png | security |

Dependency order: **#79 → #81 → (#83, #84, #85, #86) → #87 → #88**, with #82/#89 independent.

---

## 2. Live Yahoo layer (`yahoo/`, `tools/`, `driver/`, `scripts/`)

### Confirmed bugs

- **#79 — `yahoo/team.py:156`** scans only `tr.editable`; locked players (game kicked off) vanish → `TeamReadError: expected 15-17 ... found 12` every Thu–Mon. Reproduced live 2026-09-12. The same parse feeds lineup preconditions (`yahoo/lineup.py:99`), lineup read-back (`lineup.py:168`), waiver drop precondition (`waivers.py:56`), and `tools/yahoo_identity_map.py:36` — all blocked by one selector. Test `tests/test_yahoo_team.py:97` pins the buggy selector and must change with the fix. The fix is small: also parse locked rows; slot from `.pos-label` fallback already exists at `team.py:162`.
- `yahoo/team.py:181` hardcodes `team_name='Shiba Innu'`; summary regexes (`team.py:128-131`) hard-fail the whole snapshot if Yahoo changes matchup/waiver text — relax.

### Building blocks for the operator (REUSE)

- **Transport:** `yahoo/cdp.py` `CdpClient`/`select_target`/`navigate` — loopback-enforced, deadlines, typed errors. As-is.
- **Session chain:** `tools/edge_alive.py` (CDP reachability) → `tools/check_login.py` (definitive auth: credentialed fetch + Doge marker) → `tools/login_yahoo.py` (full re-login, 2FA prompt, captcha abort) → `tools/recover_tab.py`. Missing: browser relaunch (#81).
- **Reads:** `YahooTeamReader.snapshot` (after #79); `yahoo/players.py` available-players reader (FA / `W (date)` availability, injury, game text) + pagination loop in `tools/yahoo_identity_map.py:41-54`; pending-transactions read in `waivers.py:69-79`.
- **Writes (verified, dry-run default, fail-closed):** `YahooLineupOperator.apply` (form-identity, exact-ID preconditions, disabled-option lock check `lineup.py:79-80`, legal-slot invariant, read-back confirm, idempotent `already_applied`) and `YahooWaiverOperator` (add+drop one transaction, stage-3 ID re-verification, in-flight no-replay marker, pending read-back, audit JSONL in `tools/yahoo_waiver.py:42-45`). Lineup CLI lacks the audit writer — add it.
- **Projection bridge:** `yahoo/identity.py` `reconcile_identities` (unique full-name+position+team match; ambiguous/unmapped fail closed).
- **Cron scaffolding to copy:** date gate + `fcntl` lock + reconnect loop from `tools/yahoo_real_draft.py:43-83` (removed in #82; recoverable from git history); launchd plist pattern in `docs/archive/MAC_SETUP.md:140-183`.
- **Official API option:** `scripts/yahoo_oauth.py` (OAuth2, token refresh) — unused today; an API read path would remove most DOM fragility. Worth evaluating under #88.

### Dead in-season (archive candidates, not blocking)

`yahoo/real_draft.py` (harvest auth/audit/no-replay patterns first), `yahoo/mock_draft.py`, `yahoo/draft_report.py`, `driver/draft_driver.py` (1419-line legacy driver; keep the human-like mouse helpers), `tools/{yahoo_real_draft,yahoo_mock_draft,simulate_draft,gen_cheat_sheet,opponent_model,mock_draft_run,test_abbrev,test_driver_cdp,_live_read,check_draft_state,scrape_league_adp,deploy.ps1}`, all of `tools/debug/` (18 one-shot probes; maybe keep `scrape_draft_results.py` — the only other-teams reader — and the two `smoke_*` data checks), `skills/fantasy-draft/`, Windows-era `skills/edge-cdp/` guidance.

---

## 3. Data / projection layer (`src/`, `cli.py`, `web/`)

Verified data state (Sep 12): `data/raw/games.csv` is an Aug 31 cache (2026 week-1 scores NaN for games already played); 2026 REG = 18 weeks, 272 games, **byes in weeks 5–11, 13, 14**. Only `injuries_2025.csv` on disk; no 2026 weekly stats or PBP.

- **#83 week awareness:** nothing computes the current week; `corpus.build_schedule_2026` discards `gameday/gametime/weekday/rest` (`corpus.py:85-93`); `RosterPlayer.game` strings never parsed to lock times. The only live week source is the Yahoo page parse (`yahoo/team.py:128-138`).
- **#84 byes:** bye players keep full projections and stay startable (`projections.py:178`, `analysis.py:76-80`); matchup tests cover week 1 only.
- **#85 injuries:** `corpus --refresh` fetches the injuries file, but flags flow only into the draft board (`draft_board.py:123-162`); `corpus.build()` has no injuries table (`corpus.py:139-145`).
- **#86 2026 stats:** `STATS_SEASON = 2025` (`config.py:35` — its docstring describes exactly this moment); HISTORY/PBP seasons end 2025; `collect_corpus` skips `player_week_stats_2026` and `play_by_play_2026` (`ingest.py:201-225`). Effects today: `rank`/`week`/`lineup`/`validate` silently describe 2025; `predict 2` raises (`model.py:295-302`), web `/predictions?week=2` 500s; nightly CI ingests preseason datasets only (`ci.yml:65`). Only `build_team_defense` self-updates (drops NaN-score games, `corpus.py:55-59`).
- **#87 lineup advice:** `src/lineup.py` greedy optimizer's slot template matches the league exactly (`lineup.py:20-28` vs `yahoo/team.py:22`); but no (week, roster) interface — cli feeds it the 2025 season table (best-single-week output, `cli.py:75-95`), K/DEF always empty (`lineup.py:59-65`).
- Smaller items: `analysis.weekly_matchups` dead `preset` param (`analysis.py:65-83`); `sos_ranking` full-season only; `validate_against_nflverse` preset map lacks `fd-nation` (`scoring.py:112-116`, unreachable via CLI); `web/app.py` fully season-level (no 2026 in `/ratings` dropdown, no roster pages); `requirements.txt` missing explicit `joblib` (`src/model.py:96,117`).

**What already works and should be reused:** league-exact `scoring.py`; `project_for_week` + `weekly_matchups` weekly-board skeleton; `backtest.py` (leakage-safe validation harness for any in-season projection blend); the injury status maps; the lineup slot template.

---

## 4. Tests

- Fast suite green locally: **101 passed, 21 deselected** (`-m "not slow and not cdp"`). CI has a sensible fast/cdp/nightly split; `pytest.ini` has no `addopts`, so bare local `pytest` tries data-dependent slow tests.
- In-season coverage that exists: hermetic Yahoo operator tests (`test_yahoo_team/lineup/waivers/identity` — the fake-client harness in `test_yahoo_lineup.py` is the model for future operator tests), `test_corpus` (guards the one auto-adapting path), `test_league_scoring`, `test_projection_logic`, `test_backtest`.
- Gaps: no bye-week tests; no injury-effect tests outside the draft board; no current-week/lock-time tests; no lineup test with week/roster/K-DEF input; `test_yahoo_team.py:97` pins the #79 buggy selector.
- Draft-only now (historical regression gates): `test_simulation`, `test_round_sync`, `test_draft_driver`, `test_cheat_sheet`, `test_original_board`, `test_yahoo_real_draft`, `test_yahoo_mock_draft`.

---

## 5. Docs, hygiene, privacy

- **#89 privacy:** `images/human_demo.png` shows a live league-invite URL with `key=`/`ikey=` tokens in a PUBLIC repo — delete, purge history, rotate invite. Rest checked clean (manager names already initial-only in `memory/`; drafts doc clean; no credentials tracked).
- **#82 cleanup:** `3}` = zero-byte redirect junk (delete); `logs/real-draft.lock` stale (delete); `.gitignore` misses `logs/real-draft-cron.log` and `logs/yahoo-player-map.json` → ignore `logs/` wholesale; add `joblib` to requirements; remove the draft cron block from crontab.
- **Docs:** `docs/TEAM_OPERATOR.md` is the current in-season runbook (read/lineup/waiver stages, fail-closed) — needs the cron/cadence spec added (#80). `docs/archive/WINNING_STRATEGY.md` §4 is the human playbook (start/sit, waiver, trade rules); :111 says "FAAB" but FD nation is a 2-day rolling-waiver league — fix. README:380 contradicts the shipped waiver operator (claims mutations disabled under #62) — fix. Draft-era docs (REAL_DRAFT, MANUAL_FAILOVER, DRAFT_CHEAT_SHEET, MAC_SETUP draft sections, GAME_PLAN Part 3) → label completed/historical; harvest MAC_SETUP's launchd pattern. `memory/fantasy_fd_nation.md` needs a post-draft entry.
- CI: green-friendly as configured; nightly job doesn't cover 2026 datasets (#86).

---

## 6. Proposed operator shape (for #80)

```
preflight  edge_alive → check_login → (login_yahoo) → recover_tab   [#81]
read       YahooTeamReader.snapshot (post-#79) + players pages + pending tx
monitor    week/kickoff [#83] · byes [#84] · injuries [#85] · 2026 data [#86]
advise     project_for_week + roster filter → lineup moves [#87] → waiver targets [#88]
adjust     dry-run default; --apply via verified lineup/waiver operators; audit JSONL
report     one durable JSONL line per run + human summary; fail closed, never replay
```

Cadence: daily JST morning (read+monitor+report); Sun ~01:25 JST lineup-finalize before 1pm ET lock; Tue–Wed waiver-window watch (priority 4th, 2-day rolling). Cron scaffolding from `tools/yahoo_real_draft.py:43-83` (removed in #82); launchd pattern from `docs/archive/MAC_SETUP.md`.
