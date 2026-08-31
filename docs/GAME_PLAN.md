# 🏈 FD nation — The Complete Game Plan (for absolute beginners)

Everything you need to know to *win this fantasy football league*, explained like
you've never played before. No jargon left unexplained.

---

## Part 0 — The 60-second version

You are the general manager of a fake NFL team. On **draft day** you pick real
NFL players. Every week those players earn **fantasy points** from what they
actually do in games — yards, touchdowns, catches, field goals. You go
head-to-head against one other manager each week; the higher score wins. Do
this all season, make the playoffs, and win the final.

**We have built a robot that does the draft for you**, plus a toolbox that
helps you make smart lineup and waiver decisions all season long.

**Your league at a glance (FD nation):**

| Setting | Value |
| --- | --- |
| League name / ID | **FD nation** / `1329011` (Yahoo) |
| Your team | **Doge**, team #2 |
| League size | **10 teams** |
| Scoring | **Half PPR** (0.5 pts per catch) |
| Draft type | **Live snake**, 15 rounds, **1 min per pick** |
| Draft date | **Tue Sep 1, 2026, 5:00 PM EDT** (= Sep 2, 06:00 AM JST on this machine) |
| Roster | 1 QB · 2 WR · 2 RB · 1 TE · 1 flex (WR/RB/TE) · 1 K · 1 DEF · 6 bench · 2 IR |
| Playoffs | Top 4 teams, Weeks 16–17 |
| Waivers | 2-day rolling list (first-come after claims) |

---

## Part 1 — What is fantasy football?

1. Before the season, all 10 managers take turns **drafting** real NFL players.
   Each manager ends with a full roster (the table above).
2. Every NFL week, your players score points for what they do:
   - Rushing/receiving **yards**, **touchdowns**, **receptions** (0.5 pts each here)
   - QBs get points for passing yards/TDs (and **−2 for interceptions**)
   - Kickers for field goals/XPs; defenses for sacks, picks, and fewest points allowed
3. Your weekly total = the sum of your **best legal lineup** (set your starters
   before kickoff).
4. You play one opponent per week (**head-to-head**). Higher total wins the week.
5. After ~14 regular-season weeks, the top 4 records make the **playoffs**
   (Weeks 16–17). A good record **and** a good lineup every week is how you get there.

> The game is *not* about picking the single best player. It's about out-scoring
> one opponent every week, all season — and avoiding avoidable mistakes (empty
> slots, injured starters, missed waivers).

---

## Part 2 — The three phases of a winning season

Fantasy football is won in three places. Our system covers all three:

### Phase 1 — The draft (biggest single lever, ~50% of success)
The draft is the most important day. Get it right and you're in the race all
year; get it wrong and you're chasing every week. **The draft bot does this for
us** — see [Part 3](#part-3--the-draft-bot-what-it-picks-and-why).

### Phase 2 — Waivers (where leagues are actually won)
After the draft there is a free-agent pool of undrafted players. When a breakout
player (a nobody who suddenly gets a big role) is added, the first managers to
claim him get him. The first 2–3 weeks of the season are where leagues are won
or lost — breakout claim-offs decide rosters. **We have a 2-day rolling waiver
system and read-only tools to scout the wire.** After the waiver window it's
first-come, first-served.

### Phase 3 — Weekly lineup edge (the steady grind)
Each week you must start your **best** players. League-mates who "go with their
gut" leave points on the bench. **We have tools that tell you who to start based
on data** — projections, matchup (defense vs. that position), and consistency
(boom-or-bust risk). See the [command cheat-sheet](#part-6--the-command-cheat-sheet).

> **Realistic expectations:** Nothing guarantees wins — real NFL games decide
> outcomes. What this system does is maximize your *expected* value and
> eliminate *avoidable* mistakes (timer-expiry panic picks, empty lineup slots,
> missing a key waiver claim). That alone beats most managers.

---

## Part 3 — The draft bot: what it picks and why

### The plan (approved by you, the manager)
The bot drafts **Best Player Available (BPA)** by *our own* projections, with
guardrails that guarantee a legal, balanced team. It does **not** chase
third-party rankings.

### How each pick is decided
At each of our 15 turns the bot looks at who's still available and picks:

1. **Highest projected value first** — our 2026 projections (multi-year stats +
   role + schedule) decide who's "best".
2. **League ADP as a sanity check** — we scraped your league's own Average Draft
   Position from Yahoo. If the crowd drafts a player *way* later than our board
   ranks him (40+ picks), that's a red flag (injury/news we missed) → skip him.
3. **Position anchors (the guardrails that guarantee a legal team):**
   - 1st RB by Round 3 · 2nd RB by Round 5
   - 1st/2nd WR by Rounds 5/9 · TE by Round 7
   - **No QB before Round 10** · K/DEF only in Rounds 14–15
   - RBs get a small value bonus early (they're the scarcest position in 10-team)
4. **It never panics.** A 1-minute clock sounds scary, but the bot has already
   decided its pick *before* its turn starts — it just clicks the answer. No
   fumbling, no timer-expiry random picks.
5. **Safety net.** If the machine or the bot ever fails mid-draft, Yahoo's own
   auto-draft (ranked by the crowd's ADP) takes over. Worst case, we get players
   the room values highly — never an empty slot.

### Draft day — what you actually do
Almost nothing, and that's the point:

1. **Machine on, Edge logged into Yahoo** the morning of **Tue Sep 1**.
2. A scheduled Windows task (`FDnationDraftDriver`) opens the draft room and runs
   the bot automatically at **5:00 PM EDT (= Sep 2, 06:00 AM JST)**.
3. Watch the room and enjoy — the bot drafts all 15 rounds in ~15 minutes.

> Morning-of, the bot re-checks your league's ADP for late-breaking injury news
> and rebuilds the board if anything changed, so you draft from the freshest
> possible list.

---

## Part 4 — Waivers & the free-agent pool (Phase 2)

The draft only fills the 15 drafted roster slots. During the season players get
injured, underperform, or lose their jobs — and **new** names (breakouts) appear
every week. Replacing dead weight with breakouts is how leagues are actually won.

### How it works in FD nation
- Every week, unclaimed players sit in the **free-agent pool**.
- **Waiver claims** are processed by a **2-day rolling list**: at the deadline,
  the manager with priority (worst record) gets their claim first.
- After the 2-day window it is **first-come, first-served**: anyone can grab any
  player the moment they become a free agent.

### What we have
- **Read-only scouting tools** that open the live free-agent list (through the
  Edge connection) and *read* what's available — no clicks, no risk of
  accidentally spending a claim.
- **Our own rankings & projections** (Part 6 cheat-sheet: `rank`, `projections`,
  `consistency`) to decide whether a free agent is actually an upgrade over
  someone on our bench. The crowd hypes names; the data says who scores.

### How to scout the wire
1. See what's available and who projects highest (`rank` / `projections`).
2. Grab the player who projects *much* higher than the one you'd drop.
3. In the first 2–3 weeks especially, be aggressive — that's when season-altering
   breakouts (a late-round nobody who wins a starting job) hit the wire.

---

## Part 5 — The weekly lineup edge (Phase 3)

Every week you set your starting lineup before kickoff (before the Thursday night
game). This is the steady grind that wins a season: league-mates who "go with
their gut" leave real points on the bench every single week.

### Rule of thumb
- **Start the highest-projected players** who are healthy and playing.
- **Never leave a slot empty** — a 3-point kicker beats a 0.
- Check **injury status** (Q/O/IR tags) before kickoff; a 0 from an inactive
  player is the most common avoidable loss.

### What we have
- **Matchups** — every player's 2026 schedule vs. the defense he faces (some
  defenses get shredded by RBs, others by WRs).
- **Consistency** — boom-or-bust risk: a player who scores ~8 every week is safer
  than one who scores 2 or 28.
- **Projections** — our own multi-year + role + schedule numbers per player.
- **Lineup tool** — a greedy best-legal-lineup suggestion from those numbers.
- **Web dashboard** — a local page to eyeball all of it at once.

The three words to remember: **matchups**, **consistency**, **lineup**. Exact
commands in Part 6.

---

## Part 6 — The command cheat-sheet

Run everything from the project folder on Windows with the virtualenv active:

```bat
cd C:\nfl-win
.venv\Scripts\python.exe cli.py <command>
```

(or just `python cli.py <command>` if the venv is activated).

| When | Command | What it gives you |
| --- | --- | --- |
| First time | `cli.py ingest` | Downloads + caches the league's player data |
| Any time | `cli.py schedule` | The 2026 game schedule |
| Rankings | `cli.py rank --preset half-ppr --top 20` | Season leaders by fantasy points |
| By week | `cli.py week 1 --preset half-ppr --top 20` | Who scored highest that week |
| Lineup | `cli.py lineup --preset half-ppr` | Suggested best legal lineup |
| Scoring check | `cli.py validate` | Verifies our scoring matches nflverse |
| Projections | `cli.py corpus` | Build 2026 projection data (needs internet once) |
| Projections | `cli.py projections --preset half-ppr --top 30` | 2026 projected value per player |
| Consistency | `cli.py consistency --preset half-ppr --top 30` | Boom-or-bust risk per player |
| Matchups | `cli.py matchups 1 --top 25` | Week-1 start/sit board (defense vs. position) |
| Schedule | `cli.py sos` | Team strength-of-schedule ranking |
| Win probs | `cli.py predict` | 2026 game win probabilities |
| Web UI | `cli.py web` | Local dashboard at http://127.0.0.1:5000 |
| Draft board | `cli.py original-board` | Rebuild the board the bot drafts from |
| Rookies | `cli.py draft-class --season 2026` | Summarize the real 2026 NFL draft class |

> **Draft-morning data refresh (issue #50):** before `original-board`, run
> `cli.py corpus --refresh` to pull the latest depth charts (post-cutdown
> waiver moves) and the current-season injuries file. Until nflverse publishes
> `injuries_2026.csv` (Week 1 practice reports), the board logs a
> `STALE INJURY DATA` warning and ignores last season's flags on purpose —
> healthy stars stay on the board.

**Our league is `.5 PPR`** — use `--preset half-ppr` on every scoring command so
the numbers match the league's actual scoring.

### Draft day (Sep 1)
```bat
:: Edge must be open on port 9222 and logged into Yahoo (the bot talks to it).
py.exe C:\edge-debug-profile\draft_driver.py
:: ...or rely on the scheduled task FDnationDraftDriver (fires at 5:00 PM EDT).
```

> **Security note:** the 9222 port lets anyone who can reach it control the
> browser *and* the logged-in Yahoo session. Keep it bound to this machine only,
> and close Edge when you're not drafting.

