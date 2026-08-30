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

## Repository topology

**Local repo:** `C:\nfl-win` (branch `main`). **Remote:** `github` ->
`https://github.com/m0n3r0/nfl` (branch `main`).

A second remote named `origin` used to point at `C:\nfl`, a bare repo holding the
pre-rebuild artifact-import history. That history is **not** an ancestor of `main` — the
two have no merge-base, because `main` was rebuilt from scratch ("Professional-grade
rebuild", `f29c5ef`). The two branches had diverged by 17 commits vs 6.

Only one thing on the old branch was not already in `main`: `intel/` (14 files — an
autonomous collector plus ~126k lines of raw 2026-08-27 JSON snapshots: players,
schedule, game boxscores). Everything else (images, validation logs, board rows,
`data/scrapes/`, `memory/`) had been carried across.

Cleaned up on 2026-08-31:

- Backed the whole thing up first, including the orphan branch, to
  `nfl-cdrive-mirror-backup.bundle` (kept outside the repo; `git bundle verify` passes
  and it records `refs/heads/master` at `d19d1a7`).
- Removed the `origin` remote. `github` is now the only remote, matching the fact that
  `nfl-win` is the local repo of record.

`intel/` is therefore not in `main` and is not referenced by any code or doc in it. It
was a parallel collector superseded by `src/ingest.py` (nflverse). Recover it from the
bundle if it is ever wanted; it was deliberately left out rather than deleted.

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

### Deep pass (second look, same day)

Re-reviewing the three fixes turned up four more problems, all now fixed.

**1. The deploy was stale — which made every fix above theoretical.** The skill runs
`C:\edge-debug-profile\draft_driver.py`, not the repo copy, and it was still the old
driver with the old 121-player board (12,417 vs 24,911 bytes). Backed up to
`C:\edge-debug-profile\backup_pre_phase1_*\`, deployed both, and verified by importing
the *deployed* path. **A driver or board change is not live until it is copied there.**

**2. `def_map` could degrade to worse than the bug it replaced.** `run_draft()` builds the
map with a comprehension over the active board, so a board with no `DEF` rows yields `{}`
— falsy but not `None` — and the old `if def_map is None` check would have honoured it,
leaving *every* defense unresolved. The supplied map is now layered **on top of** the
static one, so the two failure modes cancel: a code missing from the active board still
resolves via the static tuple. Regression test:
`test_normalize_available_empty_def_map_falls_back_to_static`.

**3. The README's own run command silently downgraded the board.** It documented
`py.exe driver/draft_driver.py`, but `load_original_board()` only looked next to the
script, and the board lives in `data/board/` — so that command fell back to the built-in
**30-player** static board. `load_original_board()` now searches the deploy layout, the
repo layout, and the CWD, logging which one it used.

**4. A third, stale copy of the driver.** `skills/fantasy-draft/scripts/draft_driver.py`
was a 36,621-byte pre-Phase-1 snapshot: it still had the #10 bare-name assignment and
lacked `_fallback_pick` entirely. Nothing referenced it (the skill points at the deployed
path), but three divergent copies is precisely what caused #10. Removed; the repo driver
is now the only copy.

### Documentation corrected

- Board size: three docs still said "~67 players" (and the SKILL.md said the board was
  *embedded in the script*, contradicting the paragraph beneath it). Now says 250 and
  names the JSON path.
- Log path: the README said `logs/draft_log.txt`. The driver actually resolves
  `$FD_DRAFT_LOG` → `C:\edge-debug-profile\draft_log.txt` (Windows) → `./draft_log.txt`.
- Tests section: listed only `test_scoring.py`; now covers all five files, and flags the
  two fast ones that gate draft-day changes.
- Deploy step: the README and SKILL.md now state plainly that the driver runs from
  `C:\edge-debug-profile\`, not the repo.
- Removed the duplicate `__pycache__/` entry in `.gitignore`.
- The SKILL.md validation section described the 2026-08-21 static-board era as if it were
  current; superseded sections are now labelled historical and the 2026-08-31 simulation
  results documented.

---

## Phase 2 — correctness (in progress)

### #17 Leakage in `team_ratings_asof()` — **fixed**

`src/features.py` appended `STATS_SEASON` (2025) unconditionally to the prior-season
candidate list:

```python
prev = max([s for s in PBP_SEASONS if s < season] + [STATS_SEASON])
```

Because `STATS_SEASON` (2025) is itself the newest entry in `PBP_SEASONS`, that `max()`
returned **2025 for every season <= 2025**. A 2022 week-1 game was rated on full-year
2025 efficiency. The proof: the `team_ratings_2022_w1` and `team_ratings_2024_w1` caches
were byte-identical — the same 2025 data written under two season labels. Every week-1
game in both the train split (2022-23) and the test split (2024-25) was contaminated.

Fix:

- The prior-season choice is now a separate pure function, `prior_season(season)`, which
  returns the newest *strictly-earlier* season or `None`. It takes no PBP load, so the
  leakage rule is unit-testable in milliseconds instead of requiring a 95 MB download.
- `team_ratings_asof()` returns an **empty DataFrame** when there is no prior, and that
  empty result is deliberately **not** cached (it is a "no data" signal, not data).
- `build_model_frame()` skips games with no prior. 2022 week 1 is the only affected
  window — 16 games out of 1,090 across 2022-2025 are dropped.
- Two other call sites assumed a non-empty result and would have thrown:
  `model.predict_2026()` now raises an explicit `RuntimeError`, and `web/app.py:/ratings`
  renders an explanatory notice. `/ratings` also had `2025` twice in its season dropdown
  (`list(PBP_SEASONS) + [STATS_SEASON]`); it is now `sorted(set(...))`.
- The four poisoned caches (2022-2025 w1) are quarantined in
  `data/processed/_poisoned_w1_backup/`. `data/processed/` is gitignored, so this is a
  local-only artefact. `team_ratings_2026_w1` was left in place: 2025 *is* strictly prior
  to 2026, so it was never poisoned.

Regression tests in `tests/test_model.py` (all fast, no PBP load):
`test_prior_season_is_strictly_prior`, `test_prior_season_never_returns_future`,
`test_week1_of_first_pbp_season_has_no_ratings`. Verified they fail against the old
expression — `prior_season(2022)` returned `2025` instead of `None`, and 2023/2024/2025
all returned a prior that was not strictly earlier. The last of the three also refuses to
pass if a poisoned `team_ratings_<first>_w1` cache is ever restored, since the cache is
read before the prior logic runs.

> The pre-existing `test_features_asof_no_leakage()` did **not** catch this: it only
> asserted 32 rows for 2025 week 3, and week 3 was never poisoned.

**Re-measured accuracy** (train 2022–23 = 527 games, test 2024–25 = 544, 1,071 retained
of 1,087):

| | Before (leaked) | After (honest) | Delta |
|---|---|---|---|
| Model WITHOUT spread | 60.9% | **61.2%** | +0.3pp |
| Model WITH spread | 68.2% | **68.0%** | −0.2pp |
| Vegas baseline | 68.4% | **68.4%** | 0.0pp |
| Time-series CV mean | 67.0% | **66.3%** | −0.7pp |

Worth being straight about: the fix made the headline numbers *very slightly worse*, not
better, and the movement is under 1pp everywhere. The bug was serious in kind — up to
four years of future results in the features of 64 week-1 games — but week 1 is only 5.9%
of the corpus, so it moved the aggregate very little. The reason to fix it was never the
scoreboard; it was that the reported numbers were measuring something the model cannot
actually know at prediction time.

Sanity check that the rebuilt caches are genuinely distinct: the top-3 offences by EPA/play
are now KC/PHI/BUF for 2023 w1 (from 2022), SF/BUF/DAL for 2024 w1 (from 2023), and
BAL/BUF/DET for 2025 w1 (from 2024) — each matching its actual prior season.

### #18 `predict_2026()` never used the trained model — **fixed**

It scored every game with `0.5 + 1.2 * epa_diff`: one hand-tuned number. The model was
fitted on 14 standardized features. Those are different functions, so the published
"model predictions" were never model output at all — the README and the `/predictions`
page were presenting a formula as a fitted result.

Fix:

- The feature row is now built in exactly one place, `features.game_feature_row()`,
  used by **both** `build_model_frame()` (training) and `predict_2026()` (inference).
  That is the actual fix — sharing the builder is what makes train/predict drift
  impossible rather than merely unlikely.
- The canonical column list (`FEATURE_COLS`) lives in `features.py`, because
  `model.py` imports `features` and not the reverse. `model._feature_cols()` now just
  returns it.
- `train_and_persist()` fits **both** variants over all completed seasons and saves them
  to `data/processed/win_prob_model.joblib` (gitignored build artifact):
  - `no_spread` — the 14 EPA/rest features
  - `with_spread` — those plus the Vegas spread (68.0% vs 61.2% accuracy)
- `predict_2026()` uses `with_spread` where the spread is already published and
  `no_spread` otherwise, and records which one in a new `model` column so the output
  can never be mistaken for something it is not. The old linear formula survives only
  as `_linear_fallback()`, used when the artifact is missing, and tags its rows
  `model="fallback_linear"`.
- Each game is now scored with ratings **as of its own week**. Previously the whole
  schedule was scored on week-1 ratings, so a week-12 game was predicted from
  week-1 knowledge.

Verified the refactor is data-neutral: the training frame is unchanged at 1,071 rows,
with every one of the 14 feature means and standard deviations identical to
pre-refactor (e.g. `home_off_epa_pp` mean −0.007736, std 0.116088; `home_rest` mean
7.425770).

**Four further bugs found while fixing this:**

- `team_ratings_asof(2026, 2)` did not return empty — it tried to download
  `play_by_play_2026.csv` and raised an unhandled `HTTPError: 404`. Any future season
  crashed, including `/ratings?season=2026`. Now `_load_pbp_or_empty()` treats a season
  outside `PBP_SEASONS` as unrated and warns once per season (17 identical warnings
  otherwise). Seasons *inside* `PBP_SEASONS` still re-raise, so a genuine download
  failure during training can never be silently swallowed into dropped rows.
- The membership check runs **before** any network call. Without it, asking for a full
  season meant 17 doomed HTTP requests — `/predictions` took 45 s and mostly waited on
  404s. Now 12 s on a cold process, 1.2 s warm.
- `cli.py predict` with no week asks for all 272 games. Under the strict version that
  raised on week 2, breaking the documented default command. Unavailable weeks are now
  skipped with a warning; it raises only if *nothing* is computable.
- `web/templates/predictions.html` rendered a **"TO diff"** column from `g.to_diff`,
  a field `predict_2026()` has never produced — a permanently empty column with a
  header. Replaced with the `spread` and `model` columns the function actually returns,
  and the stale caption ("from 2025 team efficiency (EPA differential)") was corrected
  since the output is model output now.

Also: `load_model()` re-unpickled the bundle on every call, ~9 s of sklearn import and
deserialization per web request. The bundle is now memoized (9 s → 0.006 s on repeat).

Week 1 2026 output (16 games, all `with_spread`, since week-1 spreads are published):
probabilities range 0.399–0.801, mean 0.583. The with-spread model sides with the Vegas
favourite on 16/16 — expected, since the spread dominates that variant. The EPA features
move the *magnitude*, not the sign. The `no_spread` variant is the one that expresses an
independent opinion, at 61.2% accuracy.

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

- [x] **Board path** — fixed in Phase 1. `load_original_board()` now searches the deploy
  layout, the repo layout, and the CWD, so the documented `py.exe driver/draft_driver.py`
  finds the 250-player board instead of silently falling back to the 30-player static one.
- [x] **Log path** — fixed in Phase 1 (`$FD_DRAFT_LOG` → Windows
  `C:\edge-debug-profile\draft_log.txt` → other platforms `./draft_log.txt`).
- [x] **Accuracy figures** — re-measured on 2026-08-31 after #17 (see that entry for the
  numbers). Replaced the four bare figures with a table including Brier and per-fold CV.
- [x] **Leakage claim** — the README asserted "No future games leak into a game's
  features", which was false at the time. Now states the strictly-prior rule and that
  16 of 1,087 games are dropped for having no leakage-free prior.
- [x] **Model section** — `cli.py predict` genuinely produces model output now that #18
  has landed.
- Tests section: list all five test files.
- `.gitignore`: remove the duplicate `__pycache__/` entry.
