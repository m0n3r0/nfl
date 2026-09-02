# Yahoo team operator

The in-season Yahoo operator is being delivered in fail-closed stages. It can
read authoritative team state and apply an exact starter/bench permutation for
league `1329011`, team `2`. Add/drop, waiver, FAAB, and trade mutations remain
disabled.

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
confirmation, and never retry a POST. Applied claims succeed only when the same
add/drop names appear together in Yahoo's waiver-transactions view. Repeating a
pending claim returns `already_pending` without submission. Every run appends a
redacted intent/result record to `logs/yahoo-waiver-audit.jsonl`.

The operator does not decide whether a claim is strategically worthwhile. Run
the identity map first and reject candidates whose model mapping is not
actionable.

## Remaining transaction scope

Immediate free-agent adds use the same Yahoo add/drop form and exact-ID
preconditions, but have an immediate roster read-back rather than a pending
claim. Trade execution is intentionally not generalized before a real offer
exists: proposal shape, roster constraints, and the authoritative confirmation
page must be captured from that offer instead of guessed in advance. Read-only
recommendations and mutations remain separate.

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
