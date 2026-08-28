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
| [FantasyPros API](https://www.fantasypros.com/api-data/) — **free key** | Expert Consensus Rankings (ECR) + ADP, projections, news | **Live value board** (see below) |
| [Sleeper](https://sleeper.com) | League host; public player API | Reference (note: `adp` field is null pre-season, so not used live) |
| [NFL Next Gen Stats](https://nextgenstats.nfl.com) | Routes run, separation, air-yard share | In-season opportunity reads |
| Official NFL injury report | Verified injury/designation status | Waiver/start-sit timing |

## Paid sources — pricing deep-dive (2026)

Prices change; verify on each site before paying. Figures below are 2026 and
sourced where linked.

| Source | Price (2026) | What you get | Verdict for this project |
| --- | --- | --- | --- |
| **FantasyPros API — Free tier** | **$0/mo** (prototype key) | ECR + ADP + projections + news via REST, 130+ experts | **CORE.** Exactly the live value-board inputs. Use this. |
| FantasyPros HOF / Premium | ~$8.99/mo (bundled w/ HOF) | Production personal key, higher rate limits, all 4 sports | Upgrade **only if** we hit the free-tier call limit (unlikely: ~6 calls/draft). |
| [Establish The Run — NFL](https://establishtherun.com/subscribe/) | $119.99/season ($89.99/mo, $59.99/wk) | Elite in-season analysis, DFS | Optional; redundant for *drafting*. |
| [4for4](https://www.4for4.com/plans) | Lite/Pro/DFS tiers (~$30–$60/season, verify) | Rankings + live draft sync | Alternative rankings; redundant vs FP free. |
| RotoWire Draft Kit | ~$39 (one-time) ([ref](https://www.cheatsheetwarroom.com/blog/fantasy-football/draft/best-kit)) | Draft kit + news | Cheap optional add. |
| Draft Sharks | Premium, no free tier; Draft War Room ~$100/season (verify) ([review](https://www.draftsharks.com/kb/best-fantasy-football-websites)) | Most-accurate rankings + live draft sync | Strong but pricey; optional. |
| Footballguys | ~$20–$50/season | Deep rankings/projections | Alternative; optional. |
| FantasyNerds | Free API key available | Consensus + dynasty rankings API | Alternative data API. |

### Recommendation for *this* project

For a "serious project," the **free FantasyPros API already delivers the exact
ECR + ADP the value board needs at $0.** The paid tiers mostly add rate limits,
in-season news curation, and convenience — not data we can't get free. So:

- **Start at $0** with the FantasyPros free prototype key.
- **Upgrade to HOF ($8.99/mo) only if** we exceed the free call limit — which
  for a single draft is ~6 API calls (one per position), far under any sane cap.

Spend the money elsewhere (or not at all) unless you specifically want ETR's
in-season analysis or Draft Sharks' live draft sync.

## How the live value board works (`driver/draft_driver.py`)

The driver no longer drafts from a fixed list. At draft start it builds a
**value board**:

```
VALUE = ADP − ECR
```

- A player the experts rank #5 but the crowd drafts at #20 has `VALUE = +15`
  (great — being drafted later than they should be). We pick the **highest
  VALUE** available player, subject to the same position/timing guardrails as
  before (required slots forced by their deadline, K/DEF only late, QB after
  round 10).

### Source

- **Primary:** [FantasyPros consensus rankings API](https://www.fantasypros.com/api-data/)
  — `GET /nfl/{season}/consensus-rankings?position={POS}&scoring={SCORING}`,
  authenticated with an `x-api-key` header. Returns `rank_ecr` + `adp` per
  player.
- **Fallback:** if `FP_API_KEY` is missing **or** any fetch fails, the driver
  silently falls back to the static `BOARD` (original ADP-ordered behaviour) and
  logs `BOARD_MODE=STATIC`. The draft never breaks.

### Setup

1. Request a free key: <https://www.fantasypros.com/api-data/> (look for
   "Request a key" / the API-keys request page).
2. Export it on the machine that runs the draft:
   ```bat
   setx FP_API_KEY "your-free-key"
   ```
   (The driver reads `os.environ["FP_API_KEY"]`.)
3. Confirm the scoring constant matches your league — `FP_SCORING = "HALF"` for
   FD nation's `.5 PPR`. Change to `"PPR"` or `"STD"` if needed.

### Name-matching note

The live board is scoped to the **existing `BOARD` names** (verified
Yahoo-clickable names). FantasyPros ECR/ADP is used to *order* that universe by
value, not to introduce new names the driver couldn't click in Yahoo. Players
FantasyPros returns that aren't in `BOARD` are ignored; `BOARD` players FantasyPros
doesn't return keep `VALUE = 0` (drafted by static ADP order). Coverage is
logged as `VALUE_BOARD: live coverage N/M`.

## Caveats

- Fantasy has real variance — no source *guarantees* a winning team. The goal is
  to maximize expected value and minimize busts.
- The live path is implemented but **only exercised with a valid `FP_API_KEY`**;
  without one it is untested beyond the graceful fallback (verified: returns
  `None`, driver uses static board). Validate once with a real key before the
  draft if you intend to use it.
- All dollar figures above are 2026 estimates — confirm on each vendor's site.
