# Data sources & winning strategy

This document captures *what actually moves the needle* for a winning fantasy
team, *which sources to tap*, and *how this repo uses them*. It backs up the
"better source to tap" discussion and the live value-board in
`driver/draft_driver.py`.

## Original board engine (PRIMARY — zero external dependencies)

The draft board the driver actually uses is built **entirely from our own
nflverse-derived corpus** — no FantasyPros, no Yahoo, no third-party feed at draft
time. It is produced by `src/draft_board.py::build_original_board` and serialized to
`data/board/original_board.json` via `python cli.py original-board`. The deployed
driver reads that JSON with stdlib `json` only (it cannot import `src`).

  * **Skill QB/RB/WR/TE** — `src.projections.project_players` (multi-year weighted
    baseline → regression to mean → 2026 depth-chart role → SOS).
  * **K** — scored from the weekly kicking columns (`fg_made_0_19` … `fg_made_60_`,
    `xp_made`); nflverse zeroes K in the player table, so we score FG/XPs ourselves,
    distance-tiered.
  * **DEF** — from the derived team defense (points allowed + SOS); lower points
    allowed = higher value.

Each board entry carries `value = projected 2026 fantasy points`; the driver drafts
best-player-available by that value, still applying the 10-team scarcity premium and
anchor guardrails.

**This is the hard default engine.** `driver/draft_driver.py` selects it whenever the
board JSON is present — the mere presence of `FP_API_KEY` no longer switches engines
(it used to, which silently overrode the original method whenever a `.env` carrying the
key was on the working path). FantasyPros is only used if `DRAFT_ENGINE=fantasypros` is
set explicitly (and a key is present). See `run_draft`'s engine-selection block.

**Honest trade-off:** without a crowd signal we lose `VALUE = ADP − ECR` — the
ability to exploit opponents' drafting errors (snagging players the crowd
undervalues). The original engine instead maximizes **our own expected points**
(BPA by our projection + scarcity/need overlay). That is the correct reading of "an
original engine that does not depend on others": we are no longer leaning on
anyone else's rankings, at the cost of forfeiting the crowd-arbitrage edge.
FantasyPros/Yahoo below are an **optional, opt-in legacy cross-check** (only when
`DRAFT_ENGINE=fantasypros` is set), not the primary input.

## What actually wins (the honest version)

The repo already pulls from **nflverse**, which is the best *free* historical +
weekly stat corpus. The catch: **everyone has nflverse.** It is published data,
so it gives a solid baseline but **zero edge** — your league mates can compute
the same thing.

Fantasy is won on what others don't have or don't *act* on, not on a secret
stats feed. Three real levers, in order of impact:

1. **The draft** (biggest lever in a redraft league like FD nation). Wins come
   from drafting players *later than their true rank* — i.e. **value**.
2. **In-season timeliness** — acting faster on injury/beat-report news and on
   *opportunity* data (snap counts, target shares), not last week's box score.
3. **Your own model** — the projection engine + leakage-safe model here is a
   genuine differentiator vs people who eyeball. (Note: that model predicts
   *game outcomes*, not fantasy points — it can be repurposed to feed player
   opportunity, but it is not the draft input.)

## Free sources (start here)

| Source | What it gives | Use in this repo |
| --- | --- | --- |
| [nflverse-data](https://github.com/nflverse/nflverse-data) | Historical + weekly player/stat data, schedules, rosters | Toolkit ingest/scoring/projections (already used) |
| [FantasyPros API](https://www.fantasypros.com/api-data/) — **free key** | Expert Consensus Rankings (ECR) only; ADP/projections gated behind paid tier | **Live value board** (ECR best-player-available; see below) |
| [FantasyPros Real-Time ADP](https://www.fantasypros.com/nfl/real-time-adp/) — **free, no key** | Live "REAL-TIME" ADP column, from the *same* expert pool as ECR | **Primary ADP source** for `VALUE = ADP − ECR` (scraped from a fresh Edge tab; see below) |
| [Sleeper](https://sleeper.com) | League host; public player API | Reference (note: `adp` field is null pre-season, so not used live) |
| [NFL Next Gen Stats](https://nextgenstats.nfl.com) | Routes run, separation, air-yard share | In-season opportunity reads |
| Official NFL injury report | Verified injury/designation status | Waiver/start-sit timing |

## Paid sources — pricing deep-dive (2026)

Prices change; verify on each site before paying. Figures below are 2026 and
sourced where linked.

| Source | Price (2026) | What you get | Verdict for this project |
| --- | --- | --- | --- |
| **FantasyPros API — Free tier** | **$0/mo** (prototype key) | ECR only (consensus-rankings endpoint); ADP is **not** included — the `adp`/`ros-rankings` routes return `403 Missing Authentication Token` on the free key. ~10 players per position. | **CORE for ECR.** Enough for a live best-player-available board; true ADP−ECR value needs a paid tier (or Yahoo ADP). |
| FantasyPros HOF / Premium | ~$8.99/mo (bundled w/ HOF) | Production personal key, higher rate limits, all 4 sports | Upgrade **only if** we hit the free-tier call limit (unlikely: ~6 calls/draft). |
| [Establish The Run — NFL](https://establishtherun.com/subscribe/) | $119.99/season ($89.99/mo, $59.99/wk) | Elite in-season analysis, DFS | Optional; redundant for *drafting*. |
| [4for4](https://www.4for4.com/plans) | Lite/Pro/DFS tiers (~$30–$60/season, verify) | Rankings + live draft sync | Alternative rankings; redundant vs FP free. |
| RotoWire Draft Kit | ~$39 (one-time) ([ref](https://www.cheatsheetwarroom.com/blog/fantasy-football/draft/best-kit)) | Draft kit + news | Cheap optional add. |
| Draft Sharks | Premium, no free tier; Draft War Room ~$100/season (verify) ([review](https://www.draftsharks.com/kb/best-fantasy-football-websites)) | Most-accurate rankings + live draft sync | Strong but pricey; optional. |
| Footballguys | ~$20–$50/season | Deep rankings/projections | Alternative; optional. |
| FantasyNerds | Free API key available | Consensus + dynasty rankings API | Alternative data API. |

### Recommendation for *this* project

For a "serious project," the free FantasyPros key **delivers live ECR** (expert
consensus) — enough for a strong live best-player-available board. The `adp` and
`ros-rankings` endpoints return `403 Missing Authentication Token` on the free
key, **but** the separate **Real-Time ADP page** is free and exposes ADP from the
*same* expert pool as ECR, so the true `VALUE = ADP − ECR` value metric costs
**$0** — no paid tier needed. Yahoo's own ADP (scraped live) is kept only as a
per-turn patch for the handful of names the RT scrape doesn't cover. So:

- **Start at $0** with the FantasyPros free prototype key (ECR) **plus** the free
  Real-Time ADP scrape (ADP) → full `VALUE = ADP − ECR` board, no payment.
- **Upgrade to HOF (~$8.99/mo) only if** we hit the free-tier ECR call limit
  (unlikely: ~6 calls/draft) or want in-season news.
- The free call volume is tiny (~6 calls/draft, one per position), so rate limits
  are a non-issue.

Spend the money elsewhere (or not at all) unless you specifically want ETR's
in-season analysis or Draft Sharks' live draft sync.

## FantasyPros value board (OPT-IN LEGACY cross-check)

The driver no longer drafts from a fixed list. **By default it drafts from the
original nflverse-only board above.** Only when `FP_API_KEY` is configured does it
instead build a FantasyPros value board (this legacy cross-check):

```
VALUE = FantasyPros_RT_ADP − FantasyPros_ECR   # PRIMARY (free): RT scrape + ECR
     = Yahoo_ADP − FantasyPros_ECR             # per-turn patch for uncovered players
     = FantasyPros_ADP − ECR                  # if a paid FP key exposes ADP
     = −ECR                                   # fallback when no ADP is available
```

- **Recommended (free key + FantasyPros Real-Time ADP):** FantasyPros' free tier
  gives ECR but hides ADP behind a paid tier. The **Real-Time ADP page** is a
  *separate, free* page that renders a live "REAL-TIME" ADP column from the
  **same expert pool as ECR**, so `VALUE = FantasyPros_RT_ADP − ECR` is the true
  value metric at **$0** — a player experts rank #5 but the crowd drafts at #20
  has `VALUE = +15` (great). We scrape it from a fresh Edge tab at draft start
  (`scrape_fp_realtime_adp`) and join it to `BOARD` by normalized name. This is
  now the **primary** ADP source — no paid tier required.
- **Yahoo ADP (per-turn patch):** scraped live from the draft room each turn for
  the *available* players; it only overrides a player's value when the RT scrape
  didn't cover that name (rare — ~53/54 BOARD names match). Cross-platform sanity
  check, not the primary feed.
- **Paid FantasyPros tier (ADP present):** `VALUE = FantasyPros_ADP − ECR` (used
  only as a fallback when the RT scrape misses a name).
- **No ADP available:** we draft **best-player-available by ECR** (`VALUE = −ECR`,
  lowest expert rank first). Still a strong live strategy.
- All modes respect the same position/timing guardrails (required slots forced
  by their deadline, K/DEF only late, QB after round 10).

### 10-team scarcity anchor (positional overlay)

FD nation is a **10-team** league, so the RB/TE wells run dry fast. The catch:
the crowd *over-drafts* RBs (low Yahoo ADP), which makes `VALUE = Yahoo_ADP − ECR`
score good RBs *negative* — left to raw value, the bot would skip RBs for
"higher-value" WRs and get shut out of the scarcest position. Two guardrails fix
this (both in `choose_pick`):

- **Soft scarcity premium** (`SCARCITY_BONUS`) — while we still *need* a scarce
  position (RB), its effective value gets a `+8` lift so close calls anchor it
  early instead of being out-ranked by WRs. Once the slot is filled the premium
  drops to zero (we don't hoard RBs).
- **Hard anchor schedule** (`ANCHOR_BY_ROUND`) — the Nth still-needed player at
  each position is *forced* if the round has passed its deadline: 1st RB by R3,
  2nd RB by R5, 1st/2nd WR by R5/R9, TE by R7, QB by R10, K/DEF by R14. This
  guarantees a legal lineup and a 2-RB foundation regardless of how the value
  board scores.

### Source

- **ECR:** [FantasyPros consensus rankings API](https://www.fantasypros.com/api-data/)
  — `GET /nfl/{season}/consensus-rankings?position={POS}&scoring={SCORING}`,
  authenticated with an `x-api-key` header. On the free key it returns
  `rank_ecr` (+ `tier`, consensus spread) per player; **`adp` is absent** (the
  ADP route is paid). Defenses are requested as `position=DST` and matched back
  to `BOARD` by `player_team_id`.
- **ADP (primary, free):** the **[FantasyPros Real-Time ADP](https://www.fantasypros.com/nfl/real-time-adp/)
  page**, scraped from a *fresh* Edge tab at draft start via CDP
  (`scrape_fp_realtime_adp` → `RT_ADP_URL`). The "REAL-TIME" column (table index
  3) is the ADP; it comes from the same expert pool as ECR, so `VALUE = ADP − ECR`
  stays consistent. No key required. The orphan tab is created and closed inside
  the scrape so the live draft tab is never disturbed. If the scrape fails for
  any reason it returns `{}` and the driver transparently falls back to the
  Yahoo per-turn patch / ECR-only board.
- **ADP (per-turn patch):** **Yahoo's own Average Draft Position**, scraped live
  from the draft room each turn for the *available* players (`read_available`
  reads the ADP label off each row; `parse_adp` extracts it). Used only to
  override a player's value when the RT scrape didn't cover that name. *(The
  exact row selector should be confirmed with a 30-second look at the live draft
  room on draft day — Sep 1; if Yahoo doesn't render the `ADP` label, this patch
  is simply skipped.)*
- **Fallback:** if `FP_API_KEY` is missing **and** the RT scrape returns nothing
  (or any fetch fails), the driver silently falls back to the static `BOARD`
  (original ADP-ordered behaviour) and logs `BOARD_MODE=STATIC`. The draft never
  breaks.

### Setup

1. Request a free key: <https://www.fantasypros.com/api-data/> (look for
   "Request a key" / the API-keys request page).
2. Export it on the machine that runs the draft — either as an environment
   variable, or in a repo-root `.env` file (already git-ignored):
   ```bat
   setx FP_API_KEY "your-free-key"
   ```
   ```ini
   # .env  (FP_API_KEY=, or the short API= alias the driver also accepts)
   FP_API_KEY=your-free-key
   ```
   (The driver loads `.env` automatically and reads `FP_API_KEY`, falling back
   to `API`.)
3. Confirm the scoring constant matches your league — `FP_SCORING = "HALF"` for
   FD nation's `.5 PPR`. Change to `"PPR"` or `"STD"` if needed.

### Name-matching note

The live board is scoped to the **existing `BOARD` names** (verified
Yahoo-clickable names). FantasyPros ECR is used to *order* that universe by
value, not to introduce new names the driver couldn't click in Yahoo. Players
FantasyPros returns that aren't in `BOARD` are ignored. `BOARD` players
FantasyPros doesn't return (e.g. defenses, whose feed uses full team names like
"Houston Texans"; or players beyond the free tier's ~10-per-position cap) keep
their static ADP but are **deprioritized** (`VALUE = −(adp + 1000)`) so they
sort *below* every matched player instead of above. Coverage is logged as
`VALUE_BOARD: live coverage N/M [RT_adp=K] [MODE]` where MODE is
`ADP-ECR (FantasyPros real-time scrape)`, `ADP-only (RT scrape, no ECR)`, or
`ECR-only (free tier, BPA)`.

### Name-matching note (RT ADP join)

The RT page abbreviates names to `Initial. Last` (e.g. `J. Gibbs`, `J. Chase`,
`J. Smith-Njigba`), so `_norm_name()` normalizes both the `BOARD` full names and
the scraped rows to that same form (apostrophes/dots stripped, trailing
generational suffix like `III` dropped) for the join. Because the abbreviation
isn't unique, two real players can collide (e.g. Bijan Robinson vs Brian
Robinson both → `B. Robinson`); on collision the **smaller** ADP wins, which
keeps the early-round stud's ADP (the one we actually draft) correct. This
yields ~53/54 BOARD-name coverage with the free RT scrape.

## Caveats

- Fantasy has real variance — no source *guarantees* a winning team. The goal is
  to maximize expected value and minimize busts.
- The live path is implemented and exercised: the RT ADP scrape drives `VALUE =
  ADP − ECR` with **no paid key** (verified live: 276 rows scraped, 53/54 BOARD
  names matched), the ECR fetch is covered by unit tests with a mock key, and the
  graceful fallback (returns `None` → static board) is verified when neither key
  nor RT ADP is present. Validate once against the live draft room on Sep 1.
- All dollar figures above are 2026 estimates — confirm on each vendor's site.
