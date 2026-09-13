# Yahoo team operator

The in-season Yahoo operator is being delivered in fail-closed stages. It can
read authoritative team state, apply an exact starter/bench permutation, and
prepare/submit an exact waiver claim for league `1329011`, team `2`. Free-agent
adds and trades remain limited (see "Remaining transaction scope").

## Browser keepalive and preflight

The operators need a Chromium browser with CDP on `127.0.0.1:9222` and a live
Yahoo session in the `~/edge-draft-profile` profile. `tools/preflight.py`
verifies the whole chain and heals what it can:

```bash
python tools/preflight.py        # exits 0 only when cdp + team tab + auth are green
```

It launches the browser when CDP is down (`yahoo/browser.py`: finds the binary
via `CHROME_PATH`, the `/tmp/cft` install shared with the games repo, or a
persistent install under `~/Applications` — downloading Chrome for Testing
there when nothing exists), opens the team page in a **new** tab when none is
present (it never navigates a tab it didn't create), and checks the session
with the same credentialed fetch `tools/check_login.py` uses. When only the
auth check is red, the session needs re-login (preflight reports it and exits
2). Re-login paths, in order: open login.yahoo.com in the operator browser and
click "Sign in with Google" — the persisted Google session normally
auto-approves with no password (see the recovery ladder under "Profile backup
and session persistence"); `python tools/login_yahoo.py` for a native Yahoo
login via CDP (stops with `CAPTCHA_BLOCKED` if a captcha appears); or one
manual headful login via Screen Sharing when captcha/2FA blocks automation.

Exit codes at a glance:

| Code | Meaning | Action |
|---|---|---|
| 0 | cdp + team tab + auth green | proceed |
| 2 | auth red or other failure | re-login (above) or read the error |
| 3 | `waf_blocked` — Yahoo WAF throttling | back off 15-30 min; do NOT re-login |

A Yahoo WAF 'Request denied' block (denial body or
status 999) is reported as `waf_blocked` with exit 3 — that is throttling, not
a logout: the session is fine, so back off for ~15-30 minutes and do NOT
re-login. The team operator and analyzer surface the same condition as
`"status": "waf_blocked"` and abort the run instead of multiplying requests
into the block; all league reads fail fast on the denial signature for the
same reason, and a blocked run even skips its tab-restore navigation (any
request can extend the throttle; the next green run restores the tab). Note the exit-code asymmetry: preflight exits 3 for a WAF block,
but the operator/analyzer exit 2 for any non-ok status (3 is the operator's
lock-contention code) — read the JSON `status` field to tell `waf_blocked`
apart from other failures. `tools/league_report.py` shares the same contract
(exit 2 + `{"status": "waf_blocked"}` + skipped restore on a blocked run).

A launchd agent re-runs this preflight at every login so the browser survives
reboots (`/tmp` clears). The plist is a template; the installer renders the
actual repo paths and loads it:

```bash
python tools/install_launchd.py
```

## Profile backup and session persistence

The launcher always passes `--use-mock-keychain`. Chrome for Testing is
ad-hoc signed and cannot use the macOS Keychain, so without that flag its
cookie store is memory-only and every login dies with the browser process.
With the flag, cookies persist to disk (encrypted with Chrome's built-in mock
key) and later launches decrypt them. Tradeoff: anyone with read access to
`~/edge-draft-profile` can decrypt its cookies — keep the profile dir
user-private; the CDP endpoint stays loopback-only for the same reason.

`tools/profile_backup.py` snapshots the profile (cookies + saved logins) to
`~/edge-profile-backups/`:

```bash
python tools/profile_backup.py                    # live snapshot
python tools/profile_backup.py --stop-browser     # consistent snapshot + auto relaunch
python tools/profile_backup.py --restore          # restore the profile from backup
```

Like the profile, a backup is encrypted with Chrome's built-in mock key, so
keep `~/edge-profile-backups` as private as the profile. When the profile dir
is missing, `ensure_browser` restores the backup automatically before
launching. The restore only brings back the cookies the backup held — it does
not verify them — so a wiped profile (or a fresh machine image with the backup
synced over) comes back logged in exactly when those cookies are still valid.
`python tools/verify_relaunch.py --from-backup` proves that without touching
anything live.

### What actually keeps the session alive (verified 2026-09-13)

The login is cookie-based, not password-based — no password is stored in the
profile's main `Login Data` store. The cookies that matter, all persistent:

- Yahoo auth `A1`/`A3` — expire 2027-09 (~1 year out);
- fantasy app `SPT` (rolling, ~weekly refresh) and `SPTB` (~monthly);
- Google account SID/`__Secure-1PSID` set — expire 2027-10 (~13 months out).
  This is the identity behind "Sign in with Google".

Session cookies die early only on a server-side revoke (password change,
explicit logout, security challenge) — a plain browser relaunch never clears
them. **Verified by drill**: a fresh headless Chrome launched against a *copy*
of the profile fetched the protected team page as signed-in (HTTP 200 +
manager name), no login prompt.

Recovery ladder, best case to worst:

1. Profile intact → relaunch with the same `--user-data-dir` +
   `--use-mock-keychain` (preflight/`ensure_browser` do this) → logged in.
2. Profile lost → backup auto-restores (above) → logged in.
3. Yahoo cookies revoked but Google session alive → open login.yahoo.com and
   click "Sign in with Google": the Google session auto-approves, no password.
4. Both dead → one manual Google login, then re-run `tools/profile_backup.py`.

Run the drill anytime to prove rungs 1-2 still hold (uses a throwaway copy on
a spare port; the live browser is never touched):

```bash
python tools/verify_relaunch.py                  # drill the live profile copy
python tools/verify_relaunch.py --from-backup    # drill the latest backup
```

Exit 0 = a relaunch comes back logged in; exit 1 = session dead (positive
evidence — do rung 3 or 4, then re-backup); exit 2 = inconclusive — Yahoo WAF
throttling (back off ~15-30 minutes and retry) or a drill infrastructure
problem (the JSON `status` says which: `inconclusive` vs `error` + `detail`).

## Read-only snapshot

Keep the authenticated Yahoo team page open in the loopback-only CDP browser, then run:

```bash
python tools/yahoo_team.py
```

The command accepts `--endpoint http://127.0.0.1:9222`; non-loopback endpoints are rejected by the shared CDP transport. It performs no clicks, form changes, lineup changes, claims, or transactions.

The reader fails closed unless all of these hold:

- the page path is exactly `/f1/1329011/2`;
- Yahoo is signed in and renders FD nation / Shiba Innu identity;
- 15 unique active-roster Yahoo player IDs are present, plus at most two IR players;
- the lineup contains the configured nine starters and six bench slots;
- record, current matchup, and waiver priority parse successfully.

## Lineup changes

Lineup requests name every player by Yahoo ID and include the expected current
slot. Without `--apply`, the command only prints its intent:

```bash
python tools/yahoo_lineup.py \
  --move 41900:W/R/T:BN \
  --move 33989:BN:W/R/T
```

Add `--apply` only after reviewing the dry run. Before submitting, the operator
re-reads the authoritative roster, verifies each expected slot, verifies that
Yahoo offers the unlocked destination, and proves the complete permutation
preserves the legal slot counts. It submits the exact roster form and reports
success only after a second authoritative snapshot contains every requested
slot. Repeating an already-applied request returns `already_applied` without a
second submission.

The tool never chooses players. A recommendation/model layer must produce the
IDs and explain the projected delta separately.

## Waiver claims

Prepare an exact claim without creating it:

```bash
python tools/yahoo_waiver.py \
  --add-id 30971 --add-name "Baker Mayfield" \
  --drop-id 34054 --drop-name "Brian Robinson"
```

The default stops on Yahoo's final confirmation and returns the browser to the
team page. `--apply` creates the claim. Both paths verify the drop player against
the authoritative roster, verify Yahoo's exact add/drop IDs at selection and
confirmation, and never retry a POST. Applied claims succeed two ways: waiver
claims return `pending` when the add/drop names appear together in Yahoo's
waiver-transactions view, while immediate free-agent adds never create one and
return `completed` after an exact-ID roster read-back (add present, drop gone).
Repeating a pending claim returns `already_pending` without submission. Every
run appends a redacted intent/result record to `logs/yahoo-waiver-audit.jsonl`.

The operator does not decide whether a claim is strategically worthwhile. Run
the identity map first and reject candidates whose model mapping is not
actionable.

## Remaining transaction scope

Immediate free-agent adds share the Yahoo add/drop form, exact-ID
preconditions, and the `--apply` flow above; they are confirmed by roster
read-back (`completed`) rather than a pending claim (#105). Trade execution is
intentionally not generalized before a real offer exists: proposal shape,
roster constraints, and the authoritative confirmation page must be captured
from that offer instead of guessed in advance. Read-only recommendations and
mutations remain separate.

## Yahoo/model identity map

Before using an internal projection for a Yahoo player, build the current
read-only reconciliation report:

```bash
python tools/yahoo_identity_map.py
```

The tool reads the current roster and every available QB/RB/WR/TE result page,
then persists Yahoo ID, full name, position, current Yahoo team, internal ID,
and mapping status. It never expands initials or surname abbreviations. A
projection is actionable only when exactly one full-name/position match exists
and Yahoo's current NFL team agrees with the model. Team changes, unknown
players, and collisions remain visible as `team_mismatch`, `unmapped`, or
`ambiguous`; they cannot silently fall back to Yahoo ranking.

The default output is `logs/yahoo-player-map.json`, which is runtime state and
must not be committed. Rebuild it before each recommendation or mutation rather
than treating IDs, availability, or NFL teams as static season data.

## Scheduled operation

`tools/team_operator.py` is the single entry point for in-season maintenance:
preflight, roster snapshot, corpus build, current-week projections, monitor
report, lineup proposal, matchup context, and one JSON report plus an audit
line in `logs/team-operator.jsonl`. An flock (`logs/team-operator.lock`)
prevents overlapping cron/manual runs. Read-only by default; `--apply` submits
only the recommended lineup moves through the verified operator. Waiver claims
are never auto-submitted — `--waiver-scan` only ranks targets for a human.
`--week N` overrides the week used for projections/proposal (default: Yahoo's
current week from the snapshot); `--apply` refuses to run when it disagrees
with Yahoo's week. `--top N` caps the waiver-target list (default 10);
`--refresh-data` re-downloads nflverse data first; `--endpoint` overrides the
CDP endpoint.

Suggested crontab (times are JST, the host's local zone). Replace
`/path/to/nfl` with the local clone path — the launchd installer
(`tools/install_launchd.py`) renders repo paths the same way:

```cron
24 8,20 * * *  cd /path/to/nfl && .venv/bin/python tools/team_operator.py >> logs/team-operator-cron.log 2>&1
47 23 * * 0    cd /path/to/nfl && .venv/bin/python tools/team_operator.py --apply >> logs/team-operator-cron.log 2>&1
23 1 * * 1     cd /path/to/nfl && .venv/bin/python tools/team_operator.py --apply >> logs/team-operator-cron.log 2>&1
11 20 * * 3    cd /path/to/nfl && .venv/bin/python tools/team_operator.py --waiver-scan --refresh-data >> logs/team-operator-cron.log 2>&1
37 9 * * 0     cd /path/to/nfl && .venv/bin/python tools/profile_backup.py >> logs/profile-backup-cron.log 2>&1
```

- twice daily (08:24 / 20:24): monitor + report; catches injury/lineup news.
- Sunday 23:47 (= Sunday ~10:47 ET): `--apply` safety net — cron has no
  catch-up when the Mac sleeps, and the 01:23 fire below lands when the host
  is likely asleep. The apply is idempotent, so running it twice is harmless.
- Monday 01:23 (= Sunday ~12:23 ET): final lineup set with `--apply`, after
  the inactives lists and before the Sunday 1pm ET kickoff window. During EST
  the same fire lands an hour earlier ET, still ahead of kickoff.
- Wednesday 20:11 (= Wednesday ~07:11 ET): waiver scan after Yahoo's
  overnight waiver run, plus a data refresh for the new week's projections.
  If it still holds the flock at 20:24 the daily run simply skips — the
  waiver run already produces the full report.
- Sunday 09:37: weekly profile backup (local-only file copy — no Yahoo
  requests), keeping rung 2 of the recovery ladder fresh as cookies rotate.

## Manual team analyzer

`tools/team_analyzer.py` answers "is my team doing well, and what needs
doing" on demand (read-only, ~2 min with the wire scan):

```bash
python tools/team_analyzer.py            # human-readable report
python tools/team_analyzer.py --json     # machine-readable
python tools/team_analyzer.py --no-wire  # skip the wire scan (fast)
python tools/team_analyzer.py --light    # gentle: my roster + standings +
                                         # matchup only; league-wide sections skipped
```

Light mode is the WAF-friendly routine check (~5 reads instead of 120+): no
opponent roster pulls and no wire scan, so strength ranks, position ranks,
and waiver/standing recommendations are omitted for that run.

It pulls every league roster live, maps them to the model's projections, and
reports: matchup status, optimal-lineup strength rank across the league,
per-position ranks vs league (best rostered), alerts (locks, injuries, unevaluated
players, bye-week concentration), and a ranked recommendation list (lineup,
weak slots, waiver upgrades with drop candidates, dead spots, model blind
spots — players the model cannot price, flagged "verify manually", never
auto-drop — bye planning).
The pure analysis lives in `yahoo/league_strength.py` and is hermetically
tested; the tool is the browser glue.

Politeness: all Yahoo reads are paced, the wire scan covers the first pages
per position only (top targets sort first), and a Yahoo 'Request denied'
page aborts the scan instantly (reported as a skipped section, never a
crash). Do not run heavy scans back-to-back — Yahoo's WAF rate-limits.
