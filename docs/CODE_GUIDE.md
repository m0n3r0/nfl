# Code guide — every file, explained

> Companion to the [README](../README.md) (what the system does) and the
> [architecture diagram](../README.md#architecture) (how the pieces connect).
> This guide explains **how each file is coded**: its functions, its
> invariants, and colored flowcharts of what happens inside.
> Written 2026-11-20 from a full independent review of the codebase.

## The five layers

| Doc | Covers | One-line role |
|---|---|---|
| [SRC_ENGINE.md](code/SRC_ENGINE.md) | `src/*.py` (16 files) | The Python brain: scoring, projections, win model, live scoring, pins |
| [YAHOO_LAYER.md](code/YAHOO_LAYER.md) | `yahoo/*.py` (13 files) | The hands: fail-closed CDP reads and exact-ID mutations of Yahoo |
| [TOOLS.md](code/TOOLS.md) | `cli.py` + `tools/*.py` (26 files) | The robots: cron/launchd entry points and manual utilities |
| [RUST_WEB.md](code/RUST_WEB.md) | `rust/src/*.rs` (8 files) | The face: one axum daemon serving every page from local artifacts |
| [RUST_WEB_ARCHITECTURE.md](RUST_WEB_ARCHITECTURE.md) | colored mermaid flowcharts of the Rust web daemon (request flow, Matchup, analytics, pins, live push) — the human-friendly view of the Rust code |
| [TESTS_INFRA.md](code/TESTS_INFRA.md) | `tests/`, `tools/launchd/`, CI, templates | The safety net: hermetic tests, launchd agents, templates |

## The one rule everything follows

**Robots compute and write artifacts; the web only reads artifacts.**
No web request ever touches Yahoo, ESPN, or pandas. Yahoo is read slowly
by cron jobs through one logged-in Chrome tab; ESPN is polled by the
live-points agent; the Python engine computes offline into `data/web/`;
nfl-webd serves all of it as millisecond file reads.

## Color legend (used in every chart below)

- 🔵 **blue** — inputs / data sources
- 🟢 **green** — functions / processing steps
- 🟡 **amber** — outputs / artifacts written to disk
- 🩷 **pink** — guards, decisions, fail-closed checks
- 🟣 **purple** — external systems (Yahoo, ESPN, nflverse, TypeSafe)
- 🩵 **teal** — entry points (CLI, cron, launchd, you)

## Whole-codebase map

```mermaid
flowchart LR
    subgraph ENTRY["🩵 Entry points"]
        CLI["cli.py<br/>manual analytics commands"]
        CRON["crontab<br/>9 scheduled jobs"]
        LAUNCHD["launchd agents<br/>web · livepoints · predreport<br/>browser · cloudflared"]
    end

    subgraph TOOLS["🟢 tools/ — the robots"]
        OPER["team_operator.py<br/>check→monitor→advise→adjust"]
        LEAGR["league_report.py<br/>standings·scoreboard·rosters"]
        LIVEP["live_points.py<br/>ESPN poll → Yahoo-exact points"]
        PREDR["predictions_report.py<br/>offline engine → web artifacts"]
        HELPERS["preflight · logo_sync ·<br/>profile_backup · install_launchd ·<br/>waiver/lineup/trade utilities"]
    end

    subgraph YAHOO["🟢 yahoo/ — the hands"]
        CDP["cdp.py transport<br/>loopback-only, deadlines"]
        READS["team · league · players ·<br/>identity · wire (read-only)"]
        WRITES["lineup · waivers<br/>exact-ID, read-back verified"]
        SAFETY["waf.py · browser.py<br/>block detection · session heal"]
    end

    subgraph SRC["🟢 src/ — the brain"]
        ENGINE["corpus · projections · features ·<br/>model · scoring · analysis"]
        LIVESCORE["live_scoring.py<br/>ESPN stats → Yahoo weights"]
        PINS["pins.py<br/>manual start/sit locks"]
        JEV["jev.py<br/>TypeSafe advisory (second opinion)"]
    end

    subgraph ART["🟡 Local artifacts (git-ignored)"]
        LOGS["logs/*.json[l]<br/>operator runs · league snapshots ·<br/>live points · weekly archives"]
        DATAWEB["data/web/*.json<br/>analytics page data"]
        STATE["data/pins.json · data/logos/ ·<br/>data/raw · data/processed"]
    end

    subgraph WEB["🩷 rust/ — the face"]
        NFLWEBD["nfl-webd (axum)<br/>ALL pages native · /ws push"]
    end

    YAHOOEXT["🟣 Yahoo Fantasy"]
    ESPNEXT["🟣 ESPN public API"]
    NFLVERSE["🟣 nflverse releases"]
    TYPESAFE["🟣 TypeSafe (Jev)"]
    YOU["🩵 your browser"]

    CRON --> OPER & LEAGR
    LAUNCHD --> LIVEP & PREDR & NFLWEBD
    CLI --> ENGINE
    OPER --> READS & WRITES
    OPER --> ENGINE & PINS & JEV
    LEAGR --> READS
    HELPERS --> SAFETY
    READS & WRITES --> CDP
    CDP --> YAHOOEXT
    LIVEP --> ESPNEXT
    LIVEP --> LIVESCORE
    PREDR --> ENGINE
    ENGINE --> NFLVERSE
    JEV --> TYPESAFE
    OPER & LEAGR --> LOGS
    LIVEP --> LOGS
    PREDR --> DATAWEB
    ENGINE --> STATE
    PINS --> STATE
    LOGS & DATAWEB & STATE --> NFLWEBD
    NFLWEBD <--> YOU
```

## Suggested reading order

1. **New to the repo?** README → this map → [RUST_WEB.md](code/RUST_WEB.md)
   (what you see in the browser) → [TOOLS.md](code/TOOLS.md) (what runs on schedule).
2. **Working on projections/model?** [SRC_ENGINE.md](code/SRC_ENGINE.md)
   in order: config → ingest → corpus → scoring → projections → features → model.
3. **Working on Yahoo automation?** [YAHOO_LAYER.md](code/YAHOO_LAYER.md)
   in order: cdp → waf → browser → team → lineup/waivers, then the
   [TEAM_OPERATOR runbook](TEAM_OPERATOR.md) for operational contracts.
4. **Before changing anything:** [TESTS_INFRA.md](code/TESTS_INFRA.md) —
   the suite pins nearly every contract described in these docs.