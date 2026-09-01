# nfl

Fantasy football toolkit. Ingests public NFL player/stat data, scores it, ranks
players, and builds a weekly lineup.

> **Two parts, one repo:**
> 1. **Toolkit** — ingest, score, rank, project, and model NFL players (sections below).
> 2. **FD nation draft automation** — a self-contained module that auto-drafts a
>    specific Yahoo league through the Edge browser. See
>    [FD nation draft automation (module)](#fd-nation-draft-automation-module).

## What is fantasy football? (ELI5)

Imagine you're a coach, not a player. Before the NFL season you "draft" real
players onto your own fake team. Every week those real players rack up points from
what they actually do in games — touchdowns, yards, catches, field goals. Your
team's points go head-to-head against another person's team; the higher score
wins that week. Do it for ~15 weeks and the best record (or playoff bracket) wins
the league. It's a season-long game of "which real players will do best?"

## Is money involved?

It depends on the league — this repo doesn't decide that. Many leagues are free
and just-for-fun among friends; others have a small buy-in or prizes. **This
codebase is a pure analysis + automation tool**: it builds projections, ranks
players, and (for FD nation) auto-drafts. It is **not** a betting or gambling
system and it places no wagers. See the honesty notes under
[Known limitations](#known-limitations) and
[FD nation → Honest limitations](#honest-limitations).

## Contents

- [What is fantasy football? (ELI5)](#what-is-fantasy-football-eli5)
- [Is money involved?](#is-money-involved)
- [Data source](#data-source)
- [Setup](#setup)
- [CLI](#cli)
- [2026 projection engine](#2026-projection-engine)
- [Win-probability model](#win-probability-model-predicting-the-winning-team)
- [Web UI](#web-ui)
- [Scoring](#scoring)
- [Tests](#tests)
- [Known limitations](#known-limitations)
- [FD nation draft automation (module)](#fd-nation-draft-automation-module)
- [Data sources & winning strategy](docs/DATA_SOURCES.md)

## Data source

Player stats, rosters, and schedules are pulled from the public
[nflverse-data](https://github.com/nflverse/nflverse-data) GitHub release assets
(no API key required). Data is cached under `data/raw/` and not committed.

The "current" season is configured in `src/config.py`:
- `SCHEDULE_SEASON = 2026` — the game schedule we pull.
- `STATS_SEASON = 2025` — the most recent season with published *player* stats.
  As of late August 2026 the 2026 regular season has not yet produced game stats,
  so rankings currently use 2025 player stats. When nflverse publishes 2026 weekly
  stats, set `STATS_SEASON = 2026` and re-run `python cli.py ingest --refresh`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python cli.py ingest        # download + cache data into data/raw/
```

## CLI

```bash
python cli.py ingest                  # download + cache nflverse data
python cli.py schedule                # print the 2026 game schedule
python cli.py rank --preset ppr --top 15
python cli.py week 9 --preset half-ppr --top 10
python cli.py lineup --preset ppr
python cli.py validate                # compare our scoring vs nflverse's shipped numbers

# --- 2026 projection engine ---
python cli.py corpus                  # download + assemble the full 2026 corpus (~80MB)
python cli.py projections --top 30   # 2026 projections (multi-year + role + SOS)
python cli.py consistency --top 30   # weekly consistency / boom-bust
python cli.py matchups 1 --top 25    # 2026 Week 1 start/sit board
python cli.py sos                     # 2026 team strength-of-schedule ranking
```

Presets: `standard`, `ppr`, `half-ppr`, `fd-nation`. The default `fd-nation`
profile matches the authenticated Yahoo settings verified on 2026-09-01: 0.5
points per reception, 4-point passing touchdowns, and -1 per interception.
The generic presets retain nflverse's -2 interception weight so `validate`
continues to compare like-for-like against nflverse's shipped columns. Most
commands accept `--season <YEAR>` to override the stats year (the schedule
command uses `SCHEDULE_SEASON`).

## 2026 projection engine

`corpus.py` assembles a projection corpus from nflverse:
- historical weekly player stats **2022-2025** (`player_week_stats_week_{y}`),
- the **2026 roster** (`players`) and **2026 depth charts** (`depth_charts_2026`)
  for role/starter status,
- the **2026 schedule** (`games`) filtered to 2026,
- **derived team defense** (points allowed) computed from the games table.

`projections.py` produces 2026 projections in four transparent steps:
1. **Weighted baseline** — per-game fantasy mean across 2022-2025, recent seasons
   weighted more (1.0 / 1.5 / 2.0 / 2.5).
2. **Regression to the mean** — blended with the position league mean by a
   confidence weight that grows with games played (lightly-used players pulled
   toward average).
3. **Role adjustment** — scaled by 2026 depth-chart role share (starters ~0.60).
4. **Strength-of-Schedule** — adjusted by the average defensive SOS of the
   player's 2026 opponents.

`analysis.py` adds consistency (CV, boom/bust rates), SOS rankings, and a
weekly matchup/start-sit board.

## Win-probability model (predicting the winning team)

`src/model.py` trains a **calibrated** logistic-regression model to predict
`home_win`, benchmarked honestly against the Vegas-favorite baseline. Features come
from `src/features.py`, which engineers them from **play-by-play** (not season
summaries) with strict leakage control.

### Feature engineering (`src/features.py`) — the rigor layer
- Team efficiency is computed from play-by-play (offense/defense EPA per play,
  success rate, red-zone TD rate, 3rd-down EPA, pass/rush EPA split).
- Ratings are **as-of** each (season, week): a game in week W uses team ratings
  built only from weeks 1..W-1 of that season; week 1 uses the most recent
  **strictly-prior** season's full-year efficiency. No future games leak into a
  game's features.
- When no leakage-free prior exists — 2022 week 1, the first season we hold PBP
  for — the game is **dropped** rather than rated on a future season. That costs
  16 of 1,087 games (2022–2025). See `docs/REMEDIATION.md` #17: this was a real
  bug until 2026-08-31, when `max([...prior seasons] + [STATS_SEASON])` rated
  every week-1 game from 2022 to 2025 on full-year **2025** data.
- Results are cached to `data/processed/` (csv.gz) for fast, reproducible reads.
  Delete a cache (or pass `refresh=True`) after changing the window logic.

### Model evaluation (`src/model.py`)
- Strict time-based train/test split (train 2022–23, test 2024–25).
- Time-series (expanding-window) cross-validation for stability.
- Probability calibration (Platt) + accuracy / log-loss / Brier reported.
- Reported **both with and without** the Vegas spread as a feature.

Real results (2022–2025 PBP, 1,071 games after dropping the 16 with no
leakage-free prior; train 2022–23 = 527, test 2024–25 = 544):

| | Accuracy | Log-loss | Brier |
|---|---|---|---|
| Model WITHOUT spread | **61.2%** | 0.654 | 0.231 |
| Model WITH spread | **68.0%** | 0.616 | 0.214 |
| Vegas-favorite baseline | **68.4%** | — | — |

Time-series CV (expanding window): 2023 63.2%, 2024 69.5%, 2025 66.2%,
**mean 66.3%**.

These figures were re-measured on 2026-08-31 after fixing the week-1 leakage bug
(#17). The previously published numbers (60.9 / 68.2 / 68.4 / 67.0) were measured
on leaked features; the honest numbers are within ~0.7pp of them. The bug was
severe in principle — every week-1 game from 2022 to 2025 was rated on full-year
2025 data — but week 1 is only 64 of 1,087 games, so the headline accuracy barely
moved. Detail in `docs/REMEDIATION.md`.

Beating the closing spread is genuinely hard, so the model is built to *match* it
and is reported honestly — not overstated. Analytical tool, not a betting system.

Run `python cli.py predict` for 2026 win probabilities (add a week number, e.g.
`predict 1`, to narrow it).

Two calibrated variants are fitted on the completed seasons and cached to
`data/processed/win_prob_model.joblib`; predictions use whichever applies and
record it in a `model` column:

- `with_spread` — used when the game's spread is already published. More
  accurate, but it largely tracks Vegas (on 2026 week 1 it picks the same
  favourite in 16/16 games).
- `no_spread` — EPA and rest only. Less accurate (61.2%) but it is the variant
  that expresses an independent opinion rather than echoing the line.

Before the season starts only week 1 is computable: later weeks need in-season
2026 play-by-play to build as-of ratings, and `team_ratings_asof()` returns empty
rather than scoring a week-12 game on week-1 knowledge. `cli.py predict` skips
those weeks with a warning.

### Game-strategy analysis (`src/features.py: strategy_breakdown`)
Situation-level splits per team from PBP: overall, red-zone, 3rd-down, pass vs
rush EPA/play, success rate, and pass/shotgun tendency.

## Web UI

A local Flask app (no build step) shows player stats, team ratings, and predictions:

```bash
python cli.py web            # http://127.0.0.1:5000
# or: python web/app.py
```

Pages: dashboard (projections + model card), players (search + per-player
history/projection), win predictions by week, team **ratings**, game **strategy**
breakdowns, and SOS ranking. API: `/api/modelcard`, `/api/predictions`.

## Scoring

The generic preset weights were reverse-engineered from nflverse's own shipped `fantasy_points` /
`fantasy_points_ppr` columns via least-squares regression (R^2 = 1.000 on the
2024 weekly table), so `cli.py validate` shows a max delta of 0.00 across all
presets. Highlights that differ from generic textbook scoring:
- interceptions: −2.0
- every fumble LOST: −2.0 (split across rushing / receiving / sack fumbles)
- 2-point conversions: +2.0

FD nation overrides only interceptions to -1.0 and receptions to 0.5, matching
the live Yahoo league settings. There are no listed yardage or touchdown
milestone bonuses.

See `src/config.py` for the full weight table.

## Tests

```bash
python -m pytest tests/ -q
```

The suite includes:

| File | Covers |
|---|---|
| `tests/test_scoring.py` | our scoring reproduces nflverse's numbers within rounding; PPR = standard + receptions |
| `tests/test_projections.py` | 2026 projection engine (corpus, weighting, consistency, SOS) |
| `tests/test_model.py` | win-probability model, calibration, time-based split |
| `tests/test_original_board.py` | nflverse draft board: shape, depth, and the size invariant |
| `tests/test_draft_driver.py` | driver pick logic: guardrails, DEF name mapping, off-board fallback |
| `tests/test_cdp_browser.py` | isolated Chromium/CDP checks for identity-safe clicks and a complete 15-round mock draft |

The full suite takes several minutes (`test_scoring.py` and `test_model.py` load the
~95 MB PBP corpus). To iterate quickly, run a single file:

```bash
python -m pytest tests/test_draft_driver.py -q
```

`tests/test_original_board.py` and `tests/test_draft_driver.py` are the two that gate
draft-day changes; together they run in about 10 seconds.

Browser-level CDP tests are opt-in locally and run on every CI push. Start an
isolated Chromium instance on `127.0.0.1:9222`, then run:

```bash
RUN_CDP_BROWSER_TESTS=1 python -m pytest -m cdp -q
```

The harness creates and closes only local mock-draft tabs; it does not navigate
to Yahoo or use an authenticated session.

## Known limitations

- The nflverse *player* stat table scores Kickers and Team-Defense as 0 (defense
  is team-level data). The lineup optimizer therefore leaves the K/DEF slots empty
  rather than fabricating 0-point picks. Feed those datasets in to fill them.
- The lineup optimizer is a greedy "best available" heuristic, not an optimal
  integer-program solver.

## FD nation draft automation (module)

Yahoo Fantasy Football league **"FD nation"** (ID `1329011`), manager **Doge** (team #2).
An automated draft driver + read-only scrapers driven via Edge Chrome DevTools
Protocol (CDP). Lives as a self-contained module alongside the toolkit above.

### Layout
- `driver/draft_driver.py` — live draft driver (board + guardrails + human-like CDP clicks). Runs on Windows via `py.exe`. **This is the only copy in the repo.**
- `skills/` — Hermes skills (edge-cdp, fantasy-read, fantasy-draft) for reuse in Hermes Desktop. Documentation only; they point at the deployed driver, they do not bundle one.
- `memory/fantasy_fd_nation.md` — persistent league context for the agent.
- `data/board/` — original draft board (`original_board.json`, nflverse-derived, zero external deps, **250 players**) + K/DEF ADP reference.
- `data/scrapes/` — roster/standings/settings extracts from the live tab. **Local-only: gitignored and never committed** (it contains real league member names + session state); the driver reads it from disk at runtime.
- `tools/` — load-bearing utilities only: `scrape_league_adp.py` (league ADP scrape), `check_login.py` / `login_yahoo.py` (auth), `simulate_draft.py` (offline regression harness, used by `tests/test_simulation.py`), `mock_draft_run.py` + `mock_draft_room.html` (pre-draft click validation), `check_draft_state.py` / `back_to_league.py` / `recover_tab.py` / `edge_alive.py` (CDP health & recovery), and `deploy.ps1` (one-command verified deploy). Throwaway debug probes live in `tools/debug/` and are not part of the pipeline.
- `validation/` — mock-draft + click validation logs (2026-08-21).
- `docs/REMEDIATION.md` — phase-by-phase log of the 2026-08-31 review.

**Deploy target:** the driver does not run from the repo. Copy it and the board to
`C:\edge-debug-profile\` (the driver resolves `original_board.json` next to itself,
and also checks `data/board/` in the repo, so `py.exe driver/draft_driver.py` from
the repo root works too — neither documented invocation can silently downgrade to the
static board). A change to either file is not live until it is copied there via
`tools/deploy.ps1` — see "How to run the draft" below.
- **Log file** — created at draft time; every pick decision logged here. Resolved in
  this order: `$FD_DRAFT_LOG` → Windows default `C:\edge-debug-profile\draft_log.txt`
  → other platforms `./draft_log.txt`. (`.gitignore` covers root-level
  `draft_log.txt` and all `logs/*.txt`; if you point `FD_DRAFT_LOG` somewhere
  else, keep it out of git.)
- `images/` — proof screenshots.

### League facts (verified live 2026-08-28)
.5 PPR, H2H, 15 rounds, 1 min/pick, snake, **10 teams**. Roster: 1QB/2WR/2RB/1TE/1WRT/1K/1DEF/6BN/2IR.
Draft: **Tue Sep 1 2026, 5:00pm EDT** (= 2026-09-02 06:00 JST on the machine).

### How to run the draft
> Windows instructions below. For a **headless macOS** deployment (launchd
> instead of the scheduled task, headless Chromium instead of GUI Edge) see
> [docs/MAC_SETUP.md](docs/MAC_SETUP.md).
Edge must be open on port 9222, bound to loopback (`--remote-debugging-address=127.0.0.1`), with `--remote-allow-origins=*` and the user logged in. See the security note below for the required firewall restriction.

> **Security note (read before opening the port).** CDP exposes a *full browser-control
> interface* on the debug port — anyone who can reach `http://127.0.0.1:9222` can drive
> the browser and read every open tab, **including your logged-in Yahoo session**.
> - Bind to loopback only: launch Edge with `--remote-debugging-address=127.0.0.1`
>   (pass it alongside `--remote-debugging-port=9222 --remote-allow-origins=*`).
> - Ensure **no firewall / port-forward rule** exposes 9222 to the network.
> - Close Edge (or the port) when you're not drafting.
> Treat the debug port like an unlocked door to your accounts.

Then on Windows:
```
py.exe driver/draft_driver.py
```
Or let the scheduled task **FDnationDraftDriver** fire automatically at draft time.

#### Draft board (default: original, nflverse-only)
By default the driver drafts from the **original board** built entirely from our
own nflverse-derived data — **no FantasyPros, no Yahoo, no third-party feed**.
Generate it once (needs network the first time) with:
```
python cli.py original-board
```
This writes `data/board/original_board.json` (skill projections + K from the
weekly kicking columns + DEF from derived team defense). Copy it next to the
deployed driver (`C:\edge-debug-profile\original_board.json`) before the draft.
The driver reads it and drafts best-player-available by projected value + 10-team
scarcity/anchor guardrails, and logs `BOARD_MODE=ORIGINAL(nflverse)`. Without
this file it falls back to the built-in static board (regardless of `FP_API_KEY`).

#### FantasyPros cross-check (optional, opt-in)
Only if you set `DRAFT_ENGINE=fantasypros` (and a key is present) does the driver
instead build a FantasyPros value board (ECR + Real-Time ADP scrape, Yahoo ADP as a
live patch) — the legacy path described in
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md). The mere presence of `FP_API_KEY`
does NOT switch engines; the original nflverse board is the hard default.

```bat
setx FP_API_KEY "your-free-key"
```
```ini
# .env  (repo root; already git-ignored)
FP_API_KEY=your-free-key
# or the short alias the driver also accepts:
API=your-free-key
```

See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) for the full strategy,
pricing, and setup.

### Safety net
Yahoo default pre-rank is the auto-draft fallback if the driver errors.

### Honest limitations
- Cannot guarantee wins (real NFL games decide outcomes).
- Live pick→Draft-button flow validated at mechanism level, not end-to-end (Yahoo mock gated).
- Keep Edge + machine on at draft time.
