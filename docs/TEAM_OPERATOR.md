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
auth check is red, a human (or `tools/login_yahoo.py`) must re-login; preflight
reports it and exits 2.

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

Backups restore and decrypt only on the machine/user that created them. When
the profile dir is missing, `ensure_browser` restores the backup automatically
before launching, so a wiped profile (or a fresh machine image with the
backup synced over) comes back logged in without human involvement.

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

Suggested crontab (times are JST, the host's local zone). Replace
`/path/to/nfl` with the local clone path — the launchd installer
(`tools/install_launchd.py`) renders repo paths the same way:

```cron
24 8,20 * * *   cd /path/to/nfl && .venv/bin/python tools/team_operator.py >> logs/team-operator-cron.log 2>&1
23 1 * * 1      cd /path/to/nfl && .venv/bin/python tools/team_operator.py --apply >> logs/team-operator-cron.log 2>&1
11 20 * * 3     cd /path/to/nfl && .venv/bin/python tools/team_operator.py --waiver-scan --refresh-data >> logs/team-operator-cron.log 2>&1
```

- twice daily (08:24 / 20:24): monitor + report; catches injury/lineup news.
- Monday 01:23 (= Sunday ~12:23 ET): final lineup set with `--apply`, before
  the Sunday 1pm ET kickoff window. During EST the same fire lands an hour
  earlier ET, still ahead of kickoff.
- Wednesday 20:11 (= Wednesday ~07:11 ET): waiver scan after Yahoo's
  overnight waiver run, plus a data refresh for the new week's projections.

## Manual team analyzer

`tools/team_analyzer.py` answers "is my team doing well, and what needs
doing" on demand (read-only, ~2 min with the wire scan):

```bash
python tools/team_analyzer.py            # human-readable report
python tools/team_analyzer.py --json     # machine-readable
python tools/team_analyzer.py --no-wire  # skip the wire scan (fast)
```

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
