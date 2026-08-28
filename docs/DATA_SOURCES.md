# Data sources & winning strategy

This document captures *what actually moves the needle* for a winning fantasy
team, *which sources to tap*, and *how this repo uses them*. It backs up the
"better source to tap" discussion and the live value-board in
`driver/draft_driver.py`.

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
consensus) — enough for a strong live best-player-available board. What it does
**not** give is **ADP**: the `adp` and `ros-rankings` endpoints return
`403 Missing Authentication Token` on the free key, so the true `VALUE = ADP − ECR`
metric requires either a paid FantasyPros tier **or** Yahoo's own ADP (scraped
from the draft room via the existing Edge automation). The paid tiers mostly add
ADP, rate limits, in-season news, and convenience. So:

- **Start at $0** with the FantasyPros free prototype key (ECR best-player-available).
- **Want true value (ADP−ECR)?** Upgrade to HOF (~$8.99/mo) **or** wire Yahoo
  ADP — both expose ADP the free key hides.
- The free call volume is tiny (~6 calls/draft, one per position), so rate limits
  are a non-issue.

Spend the money elsewhere (or not at all) unless you specifically want ETR's
in-season analysis or Draft Sharks' live draft sync.

## How the live value board works (`driver/draft_driver.py`)

The driver no longer drafts from a fixed list. At draft start it builds a
**value board**:

```
VALUE = ADP − ECR        # paid FantasyPros tier (ADP available)
     = −ECR              # free tier (ECR only → best-player-available)
```

- **Paid tier (ADP present):** a player the experts rank #5 but the crowd drafts
  at #20 has `VALUE = +15` (great — drafted later than they should be). We pick
  the **highest VALUE** available player.
- **Free tier (ECR only):** ADP isn't available, so we draft the **best player
  available by ECR** (`VALUE = −ECR`, i.e. lowest expert rank first). Still a
  strong live strategy; just not the ADP−ECR "value" metric.
- Both modes respect the same position/timing guardrails (required slots forced
  by their deadline, K/DEF only late, QB after round 10).

### Source

- **Primary:** [FantasyPros consensus rankings API](https://www.fantasypros.com/api-data/)
  — `GET /nfl/{season}/consensus-rankings?position={POS}&scoring={SCORING}`,
  authenticated with an `x-api-key` header. On the free key it returns
  `rank_ecr` (+ `tier`, consensus spread) per player; **`adp` is absent** (the
  ADP route is paid). Defenses are requested as `position=DST` and matched back
  to `BOARD` by `player_team_id`.
- **Fallback:** if `FP_API_KEY` is missing **or** any fetch fails, the driver
  silently falls back to the static `BOARD` (original ADP-ordered behaviour) and
  logs `BOARD_MODE=STATIC`. The draft never breaks.

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
`VALUE_BOARD: live coverage N/M [MODE]` where MODE is `ADP-ECR (paid tier)` or
`ECR-only (free tier, BPA)`.

## Caveats

- Fantasy has real variance — no source *guarantees* a winning team. The goal is
  to maximize expected value and minimize busts.
- The live path is implemented but **only exercised with a valid `FP_API_KEY`**;
  without one it is untested beyond the graceful fallback (verified: returns
  `None`, driver uses static board). Validate once with a real key before the
  draft if you intend to use it.
- All dollar figures above are 2026 estimates — confirm on each vendor's site.
