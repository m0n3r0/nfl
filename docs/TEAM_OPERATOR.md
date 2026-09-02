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

## Planned transaction stages

Issue #62 tracks add/drop, waiver/FAAB, and trade execution. Each transaction
will require exact Yahoo IDs, explicit intent, game-lock and eligibility checks,
a durable audit record, and authoritative read-back before success is reported.
Read-only recommendations and mutations remain separate.
