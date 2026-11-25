# nfl-webd — Rust web UI architecture

> Human-oriented companion to [RUST_WEB.md](code/RUST_WEB.md) (file-by-file
> reference). This document explains the **shape** of the Rust code: what
> each layer does, how a request flows, and where the refactor of
> 2026-11-24 simplified it. All charts use the shared color legend below.

Color legend:
- 🩵 **teal** — entry point (browser, route, launchd)
- 🟢 **green** — handler / function
- 🔵 **blue** — input data (local artifact, query param)
- 🟡 **amber** — output (rendered page, JSON, broadcast)
- 🩷 **pink** — guard / fail-closed decision
- 🟣 **purple** — external process (Python cron producer)

---

## 1. The one-sentence model

One loopback axum process (`nfl-webd`) reads local JSON artifacts that
Python robots wrote offline and renders every page with minijinja. No
request computes, calls Yahoo/ESPN, or waits on Python.

```mermaid
flowchart LR
    BROWSER["🩵 browser"] --> ROUTER["🟢 axum router<br/>lib.rs"]
    ROUTER --> PAGES["🟢 pages.rs<br/>fantasy pages"]
    ROUTER --> ANA["🟢 analytics.rs<br/>prediction pages"]
    ROUTER --> WS["🟢 /ws + /live-points<br/>live push"]
    PAGES & ANA --> ART["🟢 artifacts.rs<br/>readers"]
    WS --> ART
    ART --> FILES["🔵 logs/*.json[l]<br/>data/web/*.json<br/>data/pins.json"]
    PY["🟣 Python robots<br/>cron + launchd"] -->|write| FILES
    PAGES & ANA --> RENDER["🟢 render.rs<br/>minijinja"]
    RENDER --> HTML["🟡 HTML"]
    WS --> PUSH["🟡 WebSocket frames"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef in fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    classDef ext fill:#3b1e4a,stroke:#9b41d9,color:#fff
    class BROWSER entry
    class ROUTER,PAGES,ANA,WS,ART,RENDER fn
    class FILES in
    class HTML,PUSH out
    class PY ext
```

---

## 1b. HTTP building blocks — what replaces apache/nginx

An httpd (Apache, nginx) is a program that opens a socket, parses HTTP,
routes a request to application code, and writes the response. axum is a
**library** that does those same jobs inside our own binary — so `nfl-webd`
is both the web server and the application. No separate daemon, docroot,
vhost config, CGI or reverse proxy is needed.

| Building block | Role | What it replaces |
|---|---|---|
| `tokio` | async runtime: non-blocking socket I/O (kqueue on macOS), tasks, timers | the event loop / worker model inside httpd |
| `hyper` (inside axum) | HTTP/1.1 protocol: parse request line/headers/body, frame responses, keep-alive | httpd's HTTP parser and connection handling |
| `axum::Router` + handlers | method + path dispatch, extractors (`Path`, `Query`, `Json`, `State`) | vhost/location blocks, CGI or CGI-like dispatch |
| `tower` / `tower-http` | middleware layers (logging, CORS, static files via `ServeDir`) | httpd modules (`mod_log`, `mod_rewrite`, `Alias`) |
| `minijinja` | HTML templates (this repo) | PHP/SSR templating in the web process |
| axum `ws` feature | WebSocket upgrade + frames on the same socket | httpd proxy/upgrade modules |
| **Tailscale Funnel** | public TLS termination at the edge → HTTP to :5000 | httpd's TLS listener / cert config (none local) |

```mermaid
flowchart TD
    EDGE["🟣 HTTPS/WSS edge<br/>Tailscale Funnel (TLS)"] -->|plain HTTP :5000| SOCK["🩵 tokio TcpListener<br/>kernel socket"]
    SOCK --> HYPER["🟢 hyper<br/>HTTP/1.1 parse + framing"]
    HYPER --> ROUTER["🟢 axum Router<br/>method + path → handler"]
    ROUTER --> HANDLER["🟢 handler fn<br/>extractors + local artifacts"]
    HANDLER --> RESP["🟡 IntoResponse<br/>HTML / JSON / WS frame"]
    RESP --> EDGE
    classDef edge fill:#3b1e4a,stroke:#9b41d9,color:#fff
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    class EDGE edge
    class SOCK entry
    class HYPER,ROUTER,HANDLER fn
    class RESP out
```

Note: axum has **no** built-in TLS listener. Public HTTPS here is terminated
by Tailscale Funnel; if the app ever needed local HTTPS, that would mean an
extra crate (e.g. `axum-server` + rustls) plus a certificate — not a config
flag. `axum-server`/`rustls` are already in the local Cargo cache, but this
repo deliberately keeps the server plain-HTTP behind the tunnel.

---

## 2. Startup and request path

`main.rs` binds the configured address, `Config::from_env()` discovers the
repo root, `router()` wires every route once, and `spawn_live_watcher`
polls `live-points.json` mtime every 2 s. Graceful shutdown on ctrl-c or
SIGTERM.

```mermaid
flowchart TD
    START["🩵 main()"] --> CFG["🟢 Config::from_env<br/>NFL_WEBD_BIND / ROOT"]
    CFG --> ROOT{"🩷 discover_root:<br/>cwd or exe ancestors<br/>have web/templates?"}
    ROOT -->|no| CWD["🟡 fall back to cwd"]
    ROOT -->|yes| ENV["🟢 render::environment<br/>load templates once"]
    ENV --> CH["🟢 broadcast channel(64)"]
    CH --> WATCH["🟢 spawn_live_watcher<br/>mtime poll every 2s"]
    CH --> RTR["🟢 router() → AppState"]
    RTR --> BIND["🟡 axum::serve + graceful shutdown"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef guard fill:#4a1e3b,stroke:#d941a4,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    class START entry
    class CFG,ENV,CH,WATCH,RTR fn
    class ROOT guard
    class CWD,BIND out
```

---

## 3. Every route → handler → artifact

The route table is declared in one place (`lib.rs::router`). Unknown paths
get a plain-text 404 — there is no upstream to proxy to.

```mermaid
flowchart TD
    REQ["🩵 HTTP request"] --> R{"🩷 route match"}
    R -->|/| REDIR["🟡 302 /league"]
    R -->|/league| LG["🟢 pages::league"]
    R -->|/team · /team/pin| TM["🟢 pages::team / pin_toggle"]
    R -->|"/league/team/{name}"| LT["🟢 pages::league_team"]
    R -->|"/league/matchup · /league/matchup/{team}"| TV["🟢 pages::matchup / matchup_named"]
    R -->|/cron| CR["🟢 pages::cron"]
    R -->|"/dashboard · /players · /player/{id} · /predictions · /ratings · /strategy · /sos"| AN["🟢 analytics::*"]
    R -->|/api/*| API["🟢 analytics::api_* → JSON"]
    R -->|/live-points| LP["🟢 lib::live_points → JSON"]
    R -->|/ws| WS["🟢 lib::ws_upgrade"]
    R -->|"/logos/{file}"| LO["🟢 lib::logo (charset guard)"]
    R -->|other| NF["🟡 plain 404"]
    LG & TM & LT & TV & CR & AN & API & LP & WS & LO --> ART["🟢 artifacts.rs"]
    ART --> DISK["🔵 local JSON"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef in fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    classDef guard fill:#4a1e3b,stroke:#d941a4,color:#fff
    class REQ entry
    class LG,TM,LT,TV,CR,AN,API,LP,WS,LO,ART fn
    class DISK in
    class REDIR,NF,API,LP out
    class R guard
```

---

## 4. Matchup — the most involved page (after the 2026-11-24 refactor)

`matchup` used to be one 298-line function. It now reads top-to-bottom as
six plain steps; the two non-trivial decisions (past-week snapshot merge,
operator plan) are small named helpers. The opponent is always derived
from that week's scoreboard — no b parameter, no dropdown.

```mermaid
flowchart TD
    Q["🩵 /league/matchup/&lt;team&gt;?week=N"] --> W["🟢 snapshot_week(current)<br/>bound requested to 1..current"]
    W --> PAST{"🩷 past week?"}
    PAST -->|yes| MERGE["🟢 past_week_snapshot(hist, w)<br/>newest rosters + final scores"]
    PAST -->|no| NOW["🟢 current snapshot + live-points.json"]
    MERGE --> OPP["🟢 opponent_of(a) from scoreboard<br/>(b param ignored)"]
    NOW --> OPP
    OPP --> PLAN["🟢 operator_plan(runs, week)"]
    PLAN --> SIDES["🟢 matchup_side(a) + matchup_side(b)<br/>plan for ours · roster for theirs"]
    SIDES --> LIVE["🟢 matchup_live_maps / matchup_team_games<br/>Fan Pts + game info only if week matches"]
    LIVE --> ROWS["🟢 matchup_rows: align by slot<br/>starters + bench"]
    ROWS --> SUM["🟢 side_sum(proj/fan_pts)<br/>Null when unknown"]
    SUM --> CTX["🟡 matchup.html context"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef guard fill:#4a1e3b,stroke:#d941a4,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    class Q entry
    class W,MERGE,NOW,OPP,PLAN,SIDES,LIVE,ROWS,SUM fn
    class PAST guard
    class CTX out
```

---

## 4b. League matchup cards — hover-select, click for detail

The League home copied Yahoo's `/matchup` interaction (reverse-engineered
via CDP 2026-11-24): Yahoo highlights a matchup on `li:hover` and marks the
shown one `aria-selected`, with "View Matchup" links carrying `mid1/mid2`.
Our card does the same with a pure-CSS stretched link — no JS: hovering
selects (background + grape-jelly team name), clicking anywhere on the card
opens `/league/matchup/<team>` (clean path — no `?a=&b=`, the opponent is
derived from the schedule); the team-name links stay on top and still go
to the team page.

```mermaid
flowchart TD
    HOVER["🩵 cursor over a matchup card"] --> SEL["🟢 .mu-card:hover<br/>:focus-within highlight"]
    SEL --> LOOK["🟡 background + grape-jelly name<br/>(Yahoo: li:hover / aria-selected)"]
    CLICK["🩵 click anywhere on card"] --> OPEN["🟢 .mu-open stretched link<br/>absolute inset:0 z-index:1"]
    OPEN --> DETAIL["🟡 /league/matchup/&lt;team&gt;<br/>side-by-side player detail"]
    NAME["🩵 click a team name"] --> TEAM["🟢 .mu-name z-index:2<br/>(above the overlay)"]
    TEAM --> PAGE["🟡 /league/team/&lt;name&gt;"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    class HOVER,CLICK,NAME entry
    class SEL,OPEN,TEAM fn
    class LOOK,DETAIL,PAGE out
```

---

## 5. Analytics pages — the FD nation method

Each analytics handler is the same three lines of thought: read the
artifact, filter in Rust, render. Missing artifact → honest notice.
`side_sum`-style helpers keep the filtering obvious; no ORM, no query
builder, no request-time computation.

```mermaid
flowchart LR
    Q["🩵 /players?q=&pos=<br/>/ratings?season=&week=<br/>/predictions?week="] --> READ{"🩷 artifact exists<br/>and parses?"}
    READ -->|no| MISS["🟡 analytics_missing.html<br/>'run predictions_report.py'"]
    READ -->|yes| FILTER["🟢 Rust retain/map<br/>q · pos · week · season"]
    FILTER --> CTX["🟡 JSON context"]
    CTX --> TPL["🟢 minijinja template"]
    TPL --> HTML["🟡 page"]
    API["🩵 /api/*"] --> RAW["🟡 artifact JSON as-is"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    classDef guard fill:#4a1e3b,stroke:#d941a4,color:#fff
    class Q,API entry
    class FILTER,TPL fn
    class MISS,CTX,HTML,RAW out
    class READ guard
```

---

## 6. Pins — the fail-closed write path

`pins.rs` is a direct port of `src/pins.py`: same file, same shape, same
flock + atomic rename. A corrupt pin file is an error, never an empty set.
The web toggle returns 409 and re-renders the error instead of resetting
the user's protection.

```mermaid
flowchart TD
    BTN["🩵 pin button POST /team/pin"] --> FORM["🟢 PinForm → yahoo_id"]
    FORM --> EMPTY{"🩷 empty id?"}
    EMPTY -->|yes| 400["🟡 400"]
    EMPTY -->|no| LOCK["🟢 flock pins.json.lock"]
    LOCK --> LOAD["🟢 load_pins (fail closed)"]
    LOAD -->|corrupt| ERR["🟡 409 + error notice<br/>file untouched"]
    LOAD -->|ok| FLIP["🟢 toggle + save_pins<br/>tmp → rename"]
    FLIP --> ATOMIC["🟡 data/pins.json"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    classDef guard fill:#4a1e3b,stroke:#d941a4,color:#fff
    class BTN entry
    class FORM,LOCK,LOAD,FLIP fn
    class ATOMIC,ERR,400 out
    class EMPTY guard
```

---

## 7. Live updates — one file, one broadcast

The Python poller writes `live-points.json` atomically. The Rust watcher
notices the mtime change, broadcasts the file text, and each `/ws`
connection sends it to the browser. One artifact, one read path
(`artifacts::read_live_points_text`) shared by the HTTP endpoint, the
initial WebSocket push, and the parsed page readers.

```mermaid
flowchart LR
    PY["🟣 live_points.py --loop<br/>atomic write"] --> FILE["🔵 logs/live-points.json"]
    WATCH["🟢 mtime poll 2s<br/>(lib.rs)"] --> FILE
    WATCH --> TX["🟡 broadcast::Sender&lt;String&gt;"]
    TX --> RX["🟢 /ws per-connection receiver"]
    FILE --> INIT["🟢 initial push on connect"]
    RX --> PUSH["🟡 WebSocket frame"]
    INIT --> PUSH
    BROWSER["🩵 browser /ws client"] --> PUSH
    PING["🟢 30s ping keeps tunnel alive"] --> PUSH
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef in fill:#1e3a5f,stroke:#4a90d9,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    classDef ext fill:#3b1e4a,stroke:#9b41d9,color:#fff
    class BROWSER entry
    class WATCH,RX,INIT,PING fn
    class FILE in
    class TX,PUSH out
    class PY ext
```

---

## 7b. On-page team picker — plain top menu, selector in the body

The FD nation top menu is plain links (League · My Team · Cron). The team
selector lives in the page body of `/team` and `/league/team/<name>` via the
`team_picker.html` partial; `add_team_picker()` feeds it from `team_names()`,
the one helper that reads standings order (or sorted roster keys) — also
used by the matchup page's team list. Selecting a team jumps to that team's
page. No global nav context, no menu cache.

```mermaid
flowchart TD
    LINK["🩵 click 'My Team' (plain top-menu link)"] --> PAGE["🟢 /team or /league/team/&lt;name&gt;"]
    PAGE --> CTX["🟢 add_team_picker(ctx, current)<br/>team_names(snapshot) + current"]
    CTX --> SEL["🟡 'Viewing team:' select in page body<br/>all teams, current selected"]
    SEL --> JUMP["🟢 onchange → /league/team/&lt;name&gt;"]
    TOP["🩵 FD nation top menu"] --> PLAIN["🟢 League · My Team · Cron<br/>(no select, no dropdown)"]
    classDef entry fill:#1e4a4a,stroke:#41d9d9,color:#fff
    classDef fn fill:#2d4a22,stroke:#6abf4b,color:#fff
    classDef out fill:#4a3b1e,stroke:#d9a441,color:#fff
    class LINK,TOP entry
    class PAGE,CTX,SEL,JUMP,PLAIN fn
    class SEL out
```

---

## 8. What the 2026-11-24 refactor changed (and deliberately did not)

| Change | Why |
|---|---|
| `matchup` 298 → ~200 lines via `past_week_snapshot`, `operator_plan`, `side_sum` | three cohesive decisions got names; no new abstraction layer |
| `live-points.json` read in one place (`read_live_points_text`) | three callers had three slightly different behaviors |
| 3 bounded `unwrap()`s → `let Some ... else` / `match` | same behavior, no panic path to reason about |
| Doc comment updated to the schedule-locked opponent | docs described the removed b dropdown |
| `team_names()` / `safe_segment()` — two duplicated idioms became one helper each | standings/roster extraction and path-segment validation had two copies; one source of truth |
| `url_for` compat global removed, `nav_*` context removed, menu cache removed | dead Flask-era abstraction plus a top-menu dropdown the user asked to drop |

Deliberately **not** done: no traits for renderers, no generic artifact
cache, no new crate, no config DSL. Those would add indirection without
buying correctness for a daemon whose whole job is "read JSON, render
template".
