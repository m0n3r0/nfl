# Codebase Review — m0n3r0/nfl (Yahoo Fantasy Football 2026 Draft Engine)

**Date:** 2026-08-31 · **HEAD:** `fb34de6` · **Language:** Python · **Lines:** ~3,659 (src) + 1,138 (driver) + tests + tools

---

## Executive Summary

This is a **two-layer fantasy football system**: a data/projection layer built
on nflverse public data, and a live draft automation layer (CDP browser driver)
that picks players on Yahoo during a real draft. The projection engine is
methodologically sound (weighted multi-year baseline → regression → role → SOS
→ rookie prior) and the draft driver has real guardrails (anchor deadlines,
scarcity premium, reach guard, pick-number dedup). The system is genuinely
more transparent than paid tools like FantasyPros — you know exactly why every
pick was made.

The architecture is clean, the tests are real (49 tests across 6 files), and
the CI has a smart fast/full split. But there are significant gaps that
separate it from being "superior to the paid one": no keeper/dynasty support,
no live injury awareness, a greedy lineup optimizer, and no Yahoo API
integration (it scrapes via CDP instead).

---

## 1. Architecture (what it is)

```
┌──────────────────────────────────────────────────────────┐
│                    DATA LAYER                             │
│  ingest.py → nflverse release assets → data/raw/          │
│  corpus.py → assemble: players, games, depth_charts,     │
│              weekly_history 2022–2025, team_defense      │
│  features.py → PBP-derived team ratings (EPA, SR, RZ)    │
│              with strict leakage control (as-of weeks)   │
├──────────────────────────────────────────────────────────┤
│                  PROJECTION LAYER                         │
│  projections.py:                                          │
│    1. weighted per-game baseline (2022–25, 1.0/1.5/2.0/2.5)│
│    2. regression to position mean (confidence = games/20)  │
│    3. role adjustment from 2026 depth charts (share/0.60)  │
│    4. SOS adjustment (opponent defense PPG)                │
│    5. rookie prior (draft capital discount 0.80/0.65/0.50) │
├──────────────────────────────────────────────────────────┤
│                   DRAFT LAYER                             │
│  draft_board.py → 250+ player board (skill/K/DEF boards)  │
│  draft_driver.py → CDP-driven live draft on Yahoo          │
│    choose_pick(): VOR or ADP−ECR, anchor deadlines,       │
│    scarcity premium, reach guard, bench caps, off-window  │
│    search, pick-number dedup                              │
├──────────────────────────────────────────────────────────┤
│                   ANALYSIS LAYER                          │
│  analysis.py → consistency (CV, boom/bust), SOS ranking   │
│  model.py → win-probability (logistic, PBP features)      │
│  lineup.py → greedy best-available lineup                 │
├──────────────────────────────────────────────────────────┤
│                   PRESENTATION                            │
│  web/app.py → Flask dashboard (projections, ratings,      │
│               strategy, SOS, predictions)                 │
│  tools/gen_cheat_sheet.py → printable tier board          │
│  tools/simulate_draft.py → dry-run regression check       │
└──────────────────────────────────────────────────────────┘
```

## 2. What makes this system strong

### 2a. The projection engine is methodologically defensible

The 5-step pipeline is transparent and each step is independently justified:
- **Multi-year weighting** (1.0/1.5/2.0/2.5) captures form while discounting
  old seasons.
- **Regression to position mean** with a confidence weight (`games/20`) prevents
  small-sample explosions — a player with 3 games doesn't project 400 points.
- **Depth-chart role share** (`role_share / 0.60`) is the single biggest edge:
  it uses 2026-specific depth chart data that public projection sites lag on.
- **Rookie prior with draft capital discount** (0.80/0.65/0.50 by round) means
  the 2026 class appears on the board with honest expectations rather than
  hype.

### 2b. The draft driver has real guardrails (not just "pick highest")

The `choose_pick()` function is a 5-tier decision cascade:
1. **Anchor deadlines** — force-fill required slots past their deadline (RB by
   R3/R5, WR by R5/R9, TE by R7, QB by R10, K/DEF by R14)
2. **Best value available** — VOR (projection path) or ADP−ECR (live path),
   with timing guards (K/DEF last 2 rounds, QB not before R10)
3. **Bench fallback** — best available, respecting bench caps
4. **Reach-guard bypass** — ignore the reach guard but keep timing guards
5. **Off-board fallback** — pick from Yahoo's visible players not on our board

The **scarcity premium** (RB: 10% of value spread) is a real insight: in a
10-team league the crowd over-drafts RBs, so VALUE = ADP − ECR scores good RBs
negative. The premium biases close calls toward scarce positions without
overriding the anchor guarantee.

The **pick-number dedup** (issue #26) prevents a latched "your turn" indicator
from causing double-picks. The **off-window search** (issue #23) filters the
DOM to find players deeper than the 40-row window. The **board exhaustion**
fix (issue #11) adds off-board fallback. These are all real bugs that were
found and fixed through testing.

### 2c. The testing is real

49 tests across 6 files, including:
- `test_simulation.py` — full 10-team × 15-round dry run asserting 15 picks,
  every required slot filled, never hitting NO_VALID_PICK
- `test_draft_driver.py` — 18 tests covering choose_pick logic, guardrails,
  and edge cases
- `test_scoring.py` — asserts our scoring reproduces nflverse exactly (R²=1.000)
- `test_model.py` — 11 tests on the win-probability model
- `test_original_board.py` — 12 tests on the board construction

### 2d. The data pipeline is reproducible

 nflverse public release assets → cached → reproducible. The PBP feature
 engineering has strict as-of leakage control (a week-W game uses only weeks
 1..W-1 ratings). The corpus builder handles missing releases gracefully.

## 3. Gaps that separate it from "superior to the paid one"

| Gap | Impact | Difficulty |
|---|---|---|
| **No keeper/dynasty support** | Assumes redraft. Yahoo leagues with keepers need keeper-round tracking and value adjustments. | Medium |
| **Greedy lineup optimizer** | The lineup module is best-available, not integer programming. A week where you need to decide between starting a boom-or-bust WR2 vs a floor TE2 is where paid tools win. | Medium |
| **No live injury awareness** | Projections don't adjust for injury reports, practice participation, or game-time decisions. FantasyPros has real-time injury feeds. | High |
| **No Yahoo Fantasy API integration** | The CDP scraping is fragile (DOM changes break it). Yahoo has an official Fantasy API (OAuth2) that could replace the scraping. | Medium |
| **No weekly lineup optimization** | The system handles the draft, but weekly start/sit decisions are manual. A weekly optimizer (maximize projected points under roster constraints) is the single biggest value-add for the regular season. | Medium |
| **No trade evaluator** | Comparing a trade offer's value across positions with age/contract context. | Low |
| **No auction draft support** | Snake only. | Low |
| **The PBP model (68.2% w/ spread) matches Vegas but doesn't beat it** | Honest reporting, but this means the model doesn't add a competitive edge to the draft — it's a validation tool. The projection engine is the real edge. | — |
| **Edge/CDP automation is fragile** | The draft driver depends on Yahoo's DOM structure. A Yahoo redesign breaks it. The reverse-skill CDP approach is more robust but still browser-dependent. | Medium |

## 4. What would make it "superior to the paid one"

Paid tools (FantasyPros, ESPN+, etc.) have three things this system doesn't:
1. **Expert consensus** (100+ analyst ECR)
2. **Real-time news/injury feeds**
3. **Sophisticated optimization**

But this system has advantages paid tools don't:
1. **Full transparency** — you know exactly why every projection and pick was made
2. **Custom scoring weights** — reverse-engineered to match your league exactly
3. **No API dependency for core projections** — works offline
4. **CDP automation** — the robot actually clicks on Yahoo, which no paid tool does
5. **Self-built rookie priors** — the 2026 class is projected from depth charts and draft capital, not consensus hype

To close the gap, prioritize in this order:
1. **Weekly lineup optimizer** (integer programming, not greedy) — biggest value-add
2. **Yahoo Fantasy API integration** (OAuth2) — replaces fragile CDP scraping
3. **Injury feed integration** (even a simple RSS scrape of nflverse injury data)
4. **Keeper/dynasty support** — if the league ever switches

## 5. Code quality assessment

| Metric | Value |
|---|---|
| Total lines (src + driver) | ~4,800 |
| Tests | 49 across 6 files |
| CI | Fast (hermetic) + Nightly (full corpus) |
| Data source | nflverse public release assets (no API key) |
| Caching | data/raw/ + data/processed/ (csv.gz) |
| Dependencies | pandas, numpy, scikit-learn, requests, flask, websocket-client |
| Code style | Type hints (modern), docstrings on every module/function |
| Error handling | Fail-closed with typed errors, recovery from missing releases |

The code quality is high. Modules are well-documented, concerns are separated,
and the test suite is meaningful (not just coverage theater). The 1,138-line
draft driver is the longest file but it's the core automation — the complexity
is inherent to the problem, not accidental.

---

**Bottom line:** This is a solid, transparent, well-tested system that gives
you full control over your fantasy football decisions. The projection engine
and draft guardrails are genuinely competitive. The main gaps are in the
weekly management phase (lineup optimization, injury awareness, waiver
automation) and the lack of a robust API integration with Yahoo.
