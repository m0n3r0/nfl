# Yahoo mock-draft operator

`tools/yahoo_mock_draft.py` consolidates the temporary lobby inspection, exact
room/slot join, current draft-client parser, player selection, and postcondition
checks used during live mock validation.

Safety boundary:

- CDP must be HTTP on loopback (`127.0.0.1`, `localhost`, or `::1`).
- Room IDs must be exactly eight digits.
- Real league `1329011` is explicitly rejected.
- Joining verifies a ten-team room and the exact requested slot.
- Running requires a fresh room: round 1 and `YOUR TEAM (0/15)`.
- A pick is committed locally only after Yahoo changes the authoritative roster
  count by exactly one and removes that player ID from the available board.
- An uncertain submission is never replayed.
- Completion requires Yahoo to report `YOUR TEAM (15/15)`.

The operator uses the repository's original board and `choose_pick()` strategy,
with Yahoo XRank/ADP as a fail-closed fallback when no board candidate can be
resolved to one exact row. It excludes Out, IR, PUP, and Commissioner Exempt
players.

Commands:

```
python tools/yahoo_mock_draft.py list
python tools/yahoo_mock_draft.py join --room <eight-digit-room> --slot <1-10>
python tools/yahoo_mock_draft.py run --room <eight-digit-room> --log logs/mock-draft.jsonl
```

The current client DOM contract is covered by
`tools/yahoo_draft_client_fixture.html`, `tools/test_yahoo_mock_cdp.py`, and the
`cdp` CI job. Unit tests cover protocol errors, JavaScript exceptions, mock/real
separation, state parsing, full 15-pick reconciliation, and refusal to resume an
unknown partial roster.

This module does not validate the real draft. Migrating the real driver to the
strict shared transport and authoritative roster reconciliation remains tracked
in issues #38 and #44.