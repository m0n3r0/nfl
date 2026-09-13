# 🏈 FD nation — The Game Plan (in-season edition)

> **This doc is LIVE.** The draft is done (15/15 picks, Sep 1–2 2026 — full
> record in [drafts/2026-09-02-fd-nation.md](drafts/2026-09-02-fd-nation.md)).
> This is now the strategy guide for the rest of the season: waivers, weekly
> lineups, and trades. For exact commands and failure modes (preflight,
> `waf_blocked`, claim submission), the runbook is
> [TEAM_OPERATOR.md](TEAM_OPERATOR.md).

Everything you need to know to *win this fantasy football league*, explained like you've never played before. No jargon left unexplained.

---

## Part 0 — The 60-second version

You are the general manager of a fake NFL team. The real NFL players on your
roster earn **fantasy points** from what they actually do in games — yards,
touchdowns, catches, field goals. Every week you go head-to-head against one
other manager; the higher score wins. Finish top 4, then win the playoff final.

**The season runs from this Mac:** a robot watches the team twice a day, sets
the lineup just before Sunday kickoff, and scans the waiver wire mid-week. You
make the judgment calls (claims, trades); the machine does the clicking.

**Your league at a glance (FD nation):**

| Setting | Value |
| --- | --- |
| League name / ID | **FD nation** / `1329011` (Yahoo) |
| Your team | **Shiba Innu** (team #2), managed by **Doge** |
| League size | **10 teams** |
| Scoring | **Half PPR** (0.5 pts per catch), **−1 per interception** |
| Draft | **DONE** — live snake, 15 rounds ([record](drafts/2026-09-02-fd-nation.md)) |
| Roster | 1 QB · 2 WR · 2 RB · 1 TE · 1 flex (WR/RB/TE) · 1 K · 1 DEF · 6 bench · 2 IR |
| Playoffs | Top 4 teams, Weeks 16–17 |
| Waivers | **Rolling waiver priority** (no FAAB money): a successful claim sends you to the back of the line |

---

## Part 1 — What is fantasy football?

1. Before the season, all 10 managers **drafted** real NFL players (done —
   ours are in the draft record linked above).
2. Every NFL week, your players score points for what they do:
   - Rushing/receiving **yards**, **touchdowns**, **receptions** (0.5 pts each here)
   - QBs get points for passing yards/TDs (and **−1 for interceptions**)
   - Kickers for field goals/XPs; defenses for sacks, picks, and fewest points allowed
3. Your weekly total = the sum of your **best legal lineup** (starters set before kickoff).
4. You play one opponent per week (**head-to-head**). Higher total wins the week.
5. After ~14 regular-season weeks, the top 4 records make the **playoffs** (Weeks 16–17).

> The game is *not* about picking the single best player. It's about
> out-scoring one opponent every week, all season — and avoiding avoidable
> mistakes (empty slots, injured starters, missed waivers).

---

## Part 2 — Where the season is won

The draft (~50% of success) is already banked; the rest of the season is the
other half:

- **Waivers (where leagues are actually won).** There is a free-agent pool of
  undrafted players. When a breakout (a nobody who suddenly gets a big role)
  appears, the first managers to claim him get him. The first 2–3 weeks are
  where leagues are won or lost. See Part 4.
- **Weekly lineup edge (the steady grind).** Each week you must start your
  **best** players; league-mates who "go with their gut" leave points on the
  bench. See Part 5.
- **Trades (small lever, ~5%).** Optional, but can fix a roster hole
  mid-season. See Part 6.

> **Realistic expectations:** Nothing guarantees wins — real NFL games decide
> outcomes. What this system does is maximize your *expected* value and
> eliminate *avoidable* mistakes (empty lineup slots, missed waiver claims,
> starting an injured player). That alone beats most managers.

---

## Part 3 — The draft (historical note)

The draft bot executed the plan on Sep 1–2, 2026: 15/15 picks for **Shiba
Innu** — full record in [drafts/2026-09-02-fd-nation.md](drafts/2026-09-02-fd-nation.md).
Draft-era tooling (`original-board`, `draft-class`, `tools/gen_cheat_sheet.py`,
the Windows draft driver) was removed in #82 — none of it is needed in-season.

---

## Part 4 — Waivers & the free-agent pool

The draft only filled 15 slots. In-season, players get injured, underperform,
or lose their jobs — and **new** names (breakouts) appear every week.
Replacing dead weight with breakouts is how leagues are actually won.

### How waivers work in FD nation
- Newly relevant players sit on **waivers** for ~2 days: everyone files
  claims, and the manager with the best **waiver priority** gets the player.
- This league uses **rolling waiver priority — not FAAB** (there is no budget
  of fake money). **A successful claim sends you to the back of the line.**
- After the waiver window clears, leftover players are **first-come,
  first-served** — grab them instantly, no priority spent.

### The tactics (when to spend priority)
- **Spend top priority only on true season-changers** — a breakout who wins a
  starting job (e.g. a rookie RB suddenly getting 15+ carries). Don't burn #1
  priority on a one-week fill-in.
- **File claims early after breakout games** — everyone else saw the same box
  score. **Drop the weakest bench player, not a starter**, to make room.
- In the first 2–3 weeks especially, be aggressive: that's when season-altering
  breakouts hit the wire.

### Who does what (human + robot)
- **Wednesday cron** (`tools/team_operator.py --waiver-scan --refresh-data`)
  refreshes the data, scans the wire, and proposes adds/drops.
- **You approve or veto.** Nothing spends your priority without a human yes.
- **Approved claims are executed** with `tools/yahoo_waiver.py --apply` — by
  default it shows the exact add/drop and stops for confirmation.
- Exact commands and the audit log: [TEAM_OPERATOR.md](TEAM_OPERATOR.md).

---

## Part 5 — The weekly lineup edge

Every week the lineup must be set before kickoff (Thursday night onwards; the
main slate locks Sunday 1:00 PM ET). This grind is what wins a season.

### Rule of thumb
- **Start the highest-projected players** who are healthy and playing.
- **Never leave a slot empty** — a 3-point kicker beats a 0. Never start a
  player on a **bye** (his team's week off).
- Check **injury status** (Q/O/IR tags) Saturday night and Sunday morning. A 0
  from an inactive player is the most common avoidable loss.
- **Flex slot:** start the best of your RB3 / WR3 / TE2, tilted by the week's
  matchup. Start players facing weak defenses; sit players facing elite ones,
  even if their season-long projection is a touch higher.

### Who does what
- **Monday cron** (`tools/team_operator.py --apply`, 01:23 JST = Sunday
  ~12:23 ET, just before the 1 PM kickoffs) applies the best legal lineup.
- **Twice-daily monitor** (08:24 and 20:24 JST) re-checks team state and flags
  anything that needs a human.
- **You** can eyeball the reasoning any time with the league-strength report:
  `tools/team_analyzer.py` (`--light` for a gentle check — just your roster
  and standings). Full command list: [TEAM_OPERATOR.md](TEAM_OPERATOR.md).

### What the decisions are based on
- **Projections** — our own multi-year + role + schedule numbers per player.
- **Matchups** — each player's opponent defense (some get shredded by RBs, others by WRs).
- **Consistency** — boom-or-bust risk: ~8 points every week beats 2-or-28.

---

## Part 6 — Trades

A small lever (~5%), but it can fix a roster hole mid-season.

- **Sell high:** if a player beats his projection by ~30%+ for 2+ weeks, shop
  him for a more consistent producer — his price will never be higher.
- **Buy low:** if a proven top-12 player underperforms for 2–3 weeks because
  of a tough schedule (not injury), offer a bench player for him.
- Live tracker: **issue #103** — trade the RB surplus for a WR1 during the
  **weeks 4–8** window (Part 8).

---

## Part 7 — How good is our engine, honestly?

**Competitive, not strictly superior.** Where we beat paid tools
(FantasyPros, ESPN+):

- **Transparency** — every projection is traceable to its inputs; no black-box consensus.
- **Exact scoring** — our weights match FD nation exactly (.5 PPR, INT −1);
  paid tools use generic presets.
- **Depth-chart currency** — our 2026 role shares update faster than public
  projection sites, which lag by weeks.
- **Rookie honesty** — priors come from draft capital and depth charts, not hype.
- **Automation** — the operator clicks on Yahoo in real time; no paid tool does.

Where paid tools are still ahead:

- **Expert consensus** — 100+ analysts vs. our single model.
- **Real-time injury feeds** — they know about a hamstring pull before the
  official report drops; we don't, so the human still checks the news.
- **Lineup optimization** — their solvers beat our greedy heuristic.

Bottom line: the edge is *currency and fit to this league*, not omniscience — the Saturday/Sunday human eyeball still matters.

---

## Part 8 — Current season trackers

Live strategy items, tracked as GitHub issues:

- **#102 — Week-8 bye concentration.** Purdy, McCaffrey, Kittle, and Olave are
  ALL on bye in week 8. Start preparing ~week 5 — line up fill-ins early
  rather than scrambling in week 7. The one real hole is TE: plan a **TE
  streamer** (a cheap one-week rental off the wire) behind Kittle.
- **#103 — Midseason trade.** Convert the RB surplus into a WR1. Window:
  **weeks 4–8** (tactics in Part 6).

---

## Part 9 — Operations cheat-sheet

Everything runs on **this Mac** from `/Users/user/nfl` with the project
virtualenv — no activation needed, call it directly:

```bash
cd /Users/user/nfl
.venv/bin/python tools/team_operator.py
```

### The cron entries (all times JST)

| Schedule (JST) | What it does |
| --- | --- |
| `24 8,20 * * *` (twice daily) | Monitor: re-check team state, flag anything needing a human |
| `47 23 * * 0` (Sun 23:47 = Sun ~10:47 ET) | Lineup safety net: `--apply` in case the 01:23 fire sleeps through |
| `23 1 * * 1` (Mon 01:23 = Sun ~12:23 ET) | Set the week's lineup: `--apply` |
| `11 20 * * 3` (Wed 20:11) | Waiver scan with fresh data: `--waiver-scan --refresh-data` |
| `37 9 * * 0` (Sun 09:37) | Weekly browser-profile backup (`tools/profile_backup.py`, local-only) |

### The tools you'll touch by hand

| Tool | What it gives you |
| --- | --- |
| `tools/team_operator.py` | The operator: monitor / lineup / waiver scan (cron runs it) |
| `tools/yahoo_waiver.py --apply` | Execute a human-approved waiver claim (shows the claim first) |
| `tools/team_analyzer.py` | League-strength report; `--light` for a gentle check |
| `tools/preflight.py` | Verify browser + Yahoo session are green before anything clicks |

**The authoritative runbook for all execution — preflight, `waf_blocked`,
lineup applies, claim submission, the analyzer — is [TEAM_OPERATOR.md](TEAM_OPERATOR.md).**

### Scoring preset
The `fd-nation` preset is the **default** (`.5 PPR`, INT −1) — no `--preset`
flag needed anywhere. Never use `--preset half-ppr`: that preset keeps INT −2,
which is wrong for this league.

> **Security note:** the browser's CDP port (9222) lets anyone who can reach
> it control the logged-in Yahoo session. Keep it bound to this machine only.
