# 🍎 Headless macOS deployment (portable setup)

Everything in this repo is **pure Python except the browser automation**, so a
headless Mac works — with four concrete differences from the Windows box. This
guide gets you from clone → validated draft bot on a Mac with no display.

## Compatibility summary

| Tool | Windows | Headless macOS | Notes |
| --- | --- | --- | --- |
| `cli.py ingest/schedule/rank/week/lineup/validate` | ✅ | ✅ as-is | pure Python |
| `cli.py corpus/projections/consistency/matchups/sos/predict` | ✅ | ✅ as-is | nflverse network data |
| `cli.py original-board` / `draft-class` / `web` | ✅ | ✅ as-is | web UI is localhost Flask |
| `src/` modules + `tests/` | ✅ | ✅ as-is | reinstall deps in a Mac venv |
| CDP tools (`tools/edge_alive.py`, `scrape_league_adp.py`, …) | ✅ | ✅ | need `websocket-client` (now in `requirements.txt`) |
| `driver/draft_driver.py` (live draft) | ✅ | ✅* | *validated headless, live-room unproven (see below) |
| Windows scheduled task `FDnationDraftDriver` | ✅ | ❌ → **launchd** | see Scheduling |

\* The driver itself is OS-agnostic (it only talks to a Chromium browser over
`ws://127.0.0.1:9222`); `driver/draft_driver.py` now picks its decision-log path
per-platform (`$FD_DRAFT_LOG` → Windows default → `./draft_log.txt`).

## 1. Clone + Python env

```bash
git clone https://github.com/m0n3r0/nfl.git && cd nfl
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # now includes websocket-client
```

The committed draft board (`data/board/original_board.json`) is in git — no
network needed for the draft itself. The big `data/raw/` + `data/processed/`
caches are **not** committed: either copy them from the Windows box
(`data/raw/`, `data/processed/`) or rebuild once (`python cli.py ingest` then
`python cli.py corpus`, both need internet).

Copy the `.env` (holds `API=…`) next to the repo, or export the var.

## 2. Verify the toolkit

```bash
python -m pytest tests/ -q              # 35 tests (model ones take ~6 min)
python cli.py projections --preset half-ppr --top 10
```

## 3. A Chromium browser on 9222 (headless)

Any Chromium-family browser works (the driver only needs CDP). Either install
**Microsoft Edge for Mac** or **Google Chrome**, then launch with:

```bash
# Headless (new mode) — no display needed:
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new \
  --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --remote-allow-origins=* \
  --user-data-dir="$HOME/edge-draft-profile" \
  --window-size=1400,900 about:blank &

cat http://127.0.0.1:9222/json/version        # sanity check
```

For Edge: `/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge`
(same flags). Keep 9222 bound to loopback only — anyone who can reach it can
drive the browser **and** your logged-in Yahoo session.

### One-time Yahoo login
The session lives in the profile dir (`--user-data-dir`). Log in once with a
GUI session (or Apple Remote Desktop) and keep the profile; a truly headless
Mac can re-login via CDP later but 2FA/captcha make the one-time GUI login
far more reliable.

## 4. Validate the draft driver headless

The mock room is a **local** page, so it works with no display:

```bash
# sanity checks (read-only)
python tools/edge_alive.py
python tools/check_login.py
python tools/cdp_wiring_check.py

# full 15-round mock through the driver's REAL click path:
export DRAFT_DRIVER="$PWD/driver/draft_driver.py"   # the copy being validated
python tools/mock_draft_run.py
```

> `DRAFT_DRIVER`, `MOCK_HTML`, `MOCK_LOG` override the hardcoded Windows paths
> (now portable defaults on macOS); `FD_DRAFT_LOG` redirects the driver's own log.

### The honest gap (read this)
`--headless=new` ships CDP + real input events, so the *click mechanics* are
validated by the local mock. But the **real Yahoo live-draft room inside a
headless browser has never been exercised**. Before trusting it on draft day:

1. In the headless browser, open
   `https://football.fantasysports.yahoo.com/f1/1329011/draftanalysis` and
   confirm the ADP table renders and the session stays logged in.
2. **Best test:** join one of Yahoo's own mock-draft rooms from the headless
   browser (the league page exposes `/f1/1329011/mock_join?…` links — see
   `validation/mock_join.txt`). That exercises the *real* room DOM, not just
   our local mock. If the driver survives a real Yahoo mock, it's ready.
3. Keep the Windows scheduled task running as a fallback until (2) passes.

## 5. Scheduling (replaces the Windows task scheduler)

Draft time: **Tue Sep 1 2026, 5:00 PM EDT = Wed Sep 2 06:00 JST** (this box
runs JST). Set `StartCalendarInterval` to the Mac's local wall-clock time.

`~/Library/LaunchAgents/com.fdnation.draft.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.fdnation.draft</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>cd /Users/YOU/nfl &amp;&amp; .venv/bin/python driver/draft_driver.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/YOU/nfl</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Month</key><integer>9</integer>
    <key>Day</key><integer>2</integer>
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONIOENCODING</key><string>utf-8</string></dict>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.fdnation.draft.plist
launchctl start com.fdnation.draft   # test the job manually
```

**Keep the Mac awake** at draft time:
```bash
caffeinate -dimsu                       # or, scheduled:
pmset repeat wakeorpoweron MTWRFSU 05:55:00
```

## 6. Morning-of prep (same as on Windows)

Roughly 1–2 h before the draft: re-scrape league ADP + rebuild the board
(new injuries/cuts), then (re)deploy next to the driver:

```bash
python tools/scrape_league_adp.py            # needs the browser on 9222, logged in
python cli.py original-board                  # merges ADP into the board
cp data/board/original_board.json /Users/YOU/edge-draft-profile/original_board.json
```

Verify the deployed copy the driver will read (the driver falls back to its
built-in static board if the JSON is missing).

## 7. Migration checklist

- [ ] `pip install -r requirements.txt` (incl. `websocket-client`)
- [ ] data cached or `ingest` + `corpus` run once
- [ ] `.env` copied; `API`/`FP_API_KEY` exported
- [ ] browser launch command tested; `tools/edge_alive.py` says EDGE OK
- [ ] Yahoo login persisted in the profile; `tools/check_login.py` OK
- [ ] `pytest tests/ -q` green
- [ ] `DRAFT_DRIVER`/`FD_DRAFT_LOG` set for your layout; `mock_draft_run.py` 15/15
- [ ] (strongly recommended) one real Yahoo mock draft from the headless browser
- [ ] launchd plist loaded; `launchctl start` run verified; `caffeinate` on
- [ ] Windows box kept as fallback until a live check passes