# Remediation log

Tracking the 2026-08-31 code review. Every finding is a GitHub issue on
`m0n3r0/nfl`; this file records which phase fixed what, and where.

| Phase | Issues | Theme | Status |
|---|---|---|---|
| 1 | #9, #10, #11 | Draft-blocking: board size, DEF map, no-pick stall | **done** |
| 2 | #17, #18, #19, #20, #21 | Correctness: leakage, predict, VOR, scale, deploy | not started |
| 3 | #22, #23, #24, #25, #26 | Privacy, robustness, performance, CI | not started |
| 4 | #27, #28, #29, #30, #31 | Hygiene, tests, docs | not started |

Phases 2-4 below describe the **intended** fix, not work already shipped. They are
written up in advance so each phase can be executed without re-deriving the diagnosis;
each section is struck from the "not started" column only when its code lands.

---

## Phase 1 — draft blockers (done)

**Draft:** Tue Sep 1 2026, 5:00pm EDT. These three would each have cost us the draft.

### #9 Board was 29 players too small

`data/board/original_board.json` held 121 players; a 10-team x 15-round snake consumes
150. The board ran dry around round 12, `choose_pick()` returned `None`, and Yahoo
auto-drafted the rest of our team — including the K and DEF slots.

- `src/draft_board.py`: `_SKILL_DEPTH` 15/30/35/15 -> 32/60/70/32, `K_TOP`/`DEF_TOP`
  12 -> 28, rookie carve-out floor 20.0 -> 5.0 (`_ROOKIE_MIN_PROJ`). Board is now 250.
- Added `MIN_BOARD_SIZE = 250` and a hard guard in `write_original_board()` so a future
  edit cannot silently ship a short board again.
- `tools/simulate_draft.py` (new) replays the full draft offline as a regression gate.

### #10 `DEF_CODE_TO_NAME` rebuild was dead code

`run_draft()` assigned to the bare name without a `global` statement, so it bound a local
that nothing read. `normalize_available()` kept using the stale map built from the static
`BOARD`, leaving 5 of the board's 12 defenses (BAL, CHI, KC, LAC, TB) permanently
undraftable — including the Ravens, the highest-rated defense on the board.

- `normalize_available()` now takes an explicit `def_map` argument.
- `run_draft()` builds the map from the **active** board and threads it through.
- Verified: the simulation now drafts the Ravens at R15.

### #11 `choose_pick()` returned `None` with no fallback

Added `_fallback_pick()`: when no board candidate survives, draft a player Yahoo is
showing rather than stalling. Prefers a slot we still need, then best Yahoo ADP, and
deliberately does **not** override the K/DEF and QB timing guards (Yahoo's auto-draft
beats spending a round-5 pick on a kicker).

Also added `pos_map` (name -> position) so the fallback can be slot-aware for players who
are not on our board at all.

### Verification

```
board: 250 players (draft needs 150)
picks made: 15 / 15
R14  K   Caleb Shudak      R15  DEF  Ravens
```

Tests: `test_draft_driver.py` + `test_original_board.py` = 27 passing, including three new
regression tests (active DEF map, off-board fallback, board larger than the draft).

### Known-remaining (Phase 2)

The simulation reported `QB under-filled` and `4 TEs drafted`. That is not a Phase 1
regression — it is the missing VOR normalisation (#20): raw projected points are
QB-inflated, so rivals hoard quarterbacks and TEs outrank remaining WRs. Fixed in Phase 2.

---

## Phase 2 — correctness (planned, not started)

### #17 Leakage in `team_ratings_asof()`

`src/features.py:113` appends `STATS_SEASON` (2025) unconditionally to the prior-season
candidate list, so `max()` returns 2025 for **every** season <= 2025. All 64 week-1 games
across 2022-2025 are rated on full-year 2025 data, contaminating both the train split
(2022-23) and the test split (2024-25).

Planned fix:

- Use only strictly-prior seasons; return an empty frame when there is none (2022 week 1
  has no valid prior, so those games get excluded from the model frame instead of being
  rated on future data).
- Delete the stale `data/processed/team_ratings_*_w1.csv.gz` caches.
- Re-measure the README accuracy figures afterwards (#31) — the current numbers are
  optimistic because they are measured on leaked data.

### #18 `predict_2026()` never used the trained model

It uses a hardcoded `0.5 + 1.2 * epa_diff` instead of the fitted pipeline.

Planned fix: fit a `CalibratedClassifierCV` over the same 14 features on all completed
seasons, persist it, and have `predict_2026()` load it and call `predict_proba()`, falling
back to the linear formula only if the artifact is missing.

### #19 + #20 Value scales and VOR

Board `value` mixes season points (QB 393, K 153) with a defensive rating (DEF 6.1), and
raw points are QB-inflated — which is why the simulation drafted four tight ends and no
quarterback.

Planned fix:

- Convert every position to **VOR** (value over replacement). Replacement level is the
  Nth-best player at each position, where N is the number a 10-team league starts, so VOR
  is directly comparable across positions.
- Put DEF on a season-points footing before VOR, so it is commensurable with K.
- Make `SCARCITY_BONUS` a fraction of the position's value spread instead of an absolute
  8.0, so it stays meaningful at any scale.
- Add a soft cap so the bench path cannot draft more than 2 QBs.

### #21 Deploy drift

Planned fix: `tools/deploy.ps1` copies the driver and board to the deploy directory and
verifies both with `Get-FileHash`. The driver stamps its git SHA at startup so a stale
deploy is visible.

---

## Phase 3 — privacy, robustness, performance, CI (planned, not started)

### #22 `data/scrapes/` holds real names and session state

Six tracked files list all ten league managers by name and record
`LOGGED_IN_INDICATOR True`. Planned fix: add `data/scrapes/` to `.gitignore` and
`git rm --cached` the files.

### #23 `read_available()` scans only 40 rows

Planned fix: search-driven fallback — when the best remaining board candidate is not in
the visible rows, type the name into Yahoo's player search and read the result instead of
silently substituting a worse pick.

### #24 Ratings re-read once per game

`build_model_frame()` calls `team_ratings_asof()` per game — ~1,087 gz reads. Planned fix:
memoize on `(season, week)`, cutting it to ~72.

### #25 Slow tests, no CI

Planned fix: `conftest.py` with session-scoped fixtures so the ~95 MB CSV/PBP data loads
once per session; add `pytest.ini` and `.github/workflows/ci.yml` (fast tests on push/PR,
full suite nightly).

### #26 `is_my_pick()` could latch on a stale Draft button

Planned fix: demote the button scan to a secondary signal scoped to the active pick
region, and track the pick number so the same turn cannot be picked twice.

---

## Phase 4 — hygiene and docs (planned, not started)

### #27 Invalid escape sequence

The multi-line JavaScript strings in `read_available()` and `click_player()` need to be
raw strings, clearing the `DeprecationWarning` that becomes a `SyntaxError` in a future
Python.

### #28 Ties labelled as losses

Planned fix: `build_model_frame()` drops tied games instead of encoding them as a home
loss.

### #29 `tools/` cleanup

Planned fix: move one-off debug probes to `tools/debug/`; keep load-bearing utilities in
`tools/`.

### #30 Board-size invariant (code done in Phase 1)

`test_real_board_depth_if_present` checked per-position depth >= 10, which passed on the
broken 121-player board. Added `test_real_board_is_larger_than_the_whole_draft`, which
asserts `len(board) >= TEAMS * TOTAL_ROUNDS` using the driver's own constants. The test is
landed; this entry stays open until the phase is committed as a whole.

### #31 README corrections

- Board path: the README says to copy the board next to the deployed driver, but
  `load_original_board()` resolves against the driver's own directory. Either fix the
  documented layout or make the driver also check `data/board/`.
- Log path: correct to the real `FD_DRAFT_LOG` / Windows defaults.
- Model section: stop implying `cli.py predict` output comes from the model (true only
  after #18).
- Accuracy figures: re-measure after the leakage fix (#17).
- Tests section: list all five test files.
- `.gitignore`: remove the duplicate `__pycache__/` entry.
