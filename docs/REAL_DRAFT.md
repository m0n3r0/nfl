# FD nation real-draft runbook

The real-draft operator is intentionally separate from the mock operator. It can
only target league `1329011`, team `2`, and requires the exact value
`1329011/2` in both `--confirm-real-draft` and
`FD_REAL_DRAFT_AUTHORIZATION`.

## Schedule

Yahoo's authenticated Draft Central showed `0 days 06:31:39` at 23:28 JST on
2026-09-01, placing the draft at 06:00 JST on 2026-09-02. The one-date cron job
starts at 05:20 JST, waits for Yahoo's exact draft-client link, and exits on any
other local date.

## Safety and recovery

- CDP remains loopback-only and exactly one FD nation page/draft target is
  required.
- Before entering, the page must show the authenticated FD nation and Shiba
  Innu/Doge identity.
- The operator reconstructs every completed round from Yahoo roster history
  before each decision. The rendered count and history must agree.
- Deep board targets are searched by player identity. Up to twenty already-taken
  targets are durably recorded and skipped before an identity-qualified visible
  fallback is used.
- Every click is preceded by a durable `submit_intent` audit record.
- Confirmation requires the roster count to advance exactly one and the exact
  player ID to appear at the expected overall pick.
- A timeout is never replayed. Restart reconciliation either observes the exact
  player, observes a different Yahoo/autopick result, or halts.
- Yahoo autodraft is disabled only when its checked state is authoritative.
- An execution lock prevents duplicate cron/manual operators.

## Command

```bash
FD_REAL_DRAFT_AUTHORIZATION=1329011/2 .venv/bin/python \
  tools/yahoo_real_draft.py \
  --confirm-real-draft 1329011/2 \
  --expected-date 2026-09-02
```

Audit records are written to `logs/real-draft-audit.jsonl`; cron output goes to
`logs/real-draft-cron.log`.

## Failover and rollback

On an uncertain submit, identity mismatch, roster-history mismatch, auth loss,
or changed DOM, the operator exits instead of clicking again. Yahoo's own
pre-rank/autodraft is the failover. Do not delete the audit file during the
draft: it is the cross-process no-replay journal.

To stop before launch, remove the line between
`# BEGIN NFL REAL DRAFT 2026-09-02` and `# END NFL REAL DRAFT 2026-09-02` from
`crontab -e`. If already running, terminate only the
`tools/yahoo_real_draft.py` process; leave Chrome and its authenticated profile
open.
