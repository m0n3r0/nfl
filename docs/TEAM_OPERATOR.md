# Yahoo team operator

The in-season Yahoo operator is being delivered in fail-closed stages. The first stage is read-only: it returns the authoritative current roster, lineup slots, matchup, injury labels, and waiver priority for league `1329011`, team `2`.

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

## Planned mutation stages

Issue #62 tracks lineup, add/drop, waiver/FAAB, and trade execution. Each mutation will require exact Yahoo IDs, explicit intent, game-lock and eligibility checks, a durable audit record, and authoritative read-back before success is reported. Read-only recommendations and mutations remain separate.
