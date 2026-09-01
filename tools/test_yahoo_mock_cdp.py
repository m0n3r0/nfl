#!/usr/bin/env python3
"""Browser regression for Yahoo's current draft-client parser and submitter."""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from yahoo.cdp import CdpClient, list_targets  # noqa: E402
from yahoo.mock_draft import MockDraftPage  # noqa: E402

ENDPOINT = "http://127.0.0.1:9222"
FIXTURE = (ROOT / "tools" / "yahoo_draft_client_fixture.html").as_uri()


def main() -> int:
    """Open an isolated fixture tab, exercise one pick, then close it."""
    request = urllib.request.Request(
        ENDPOINT + "/json/new?" + urllib.parse.quote(FIXTURE, safe=":/"),
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        created = json.load(response)
    target_id = str(created["id"])
    try:
        deadline = time.monotonic() + 8
        target = None
        while time.monotonic() < deadline:
            target = next((item for item in list_targets(ENDPOINT) if item.id == target_id), None)
            if target:
                break
            time.sleep(0.1)
        assert target is not None, "fixture target did not appear"
        with CdpClient(target, ENDPOINT) as client:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if client.evaluate("document.readyState") == "complete":
                    break
                time.sleep(0.1)
            page = object.__new__(MockDraftPage)
            page.client = client
            page.room = "10401633"
            before = page.read_state()
            assert before.my_turn and (before.round, before.pick) == (1, 4), before
            assert before.team_count == 0 and len(before.rows) == 1, before
            assert before.rows[0].id == "40168"
            page.submit(before.rows[0], 4)
            after = page.read_state()
            assert after.team_count == 1 and not after.my_turn, after
            assert not after.rows
        print("CURRENT YAHOO DRAFT-CLIENT FIXTURE PASSED")
        return 0
    finally:
        try:
            urllib.request.urlopen(ENDPOINT + "/json/close/" + target_id, timeout=5).read()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
