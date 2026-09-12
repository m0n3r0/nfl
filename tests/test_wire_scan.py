"""Hermetic tests for yahoo/wire.py scan_available WAF handling."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from yahoo import wire  # noqa: E402
from yahoo.players import AvailablePlayer, PlayerReadError  # noqa: E402


class FakeClient:
    def __init__(self, denied=False):
        self.denied = denied
        self.navigations = 0

    def navigate(self, url, expected, timeout=20):
        self.navigations += 1
        return url

    def evaluate(self, expression):
        if "Request denied" in expression:
            return self.denied
        return True


def _player(idx):
    return AvailablePlayer(yahoo_id=str(idx), name=f"Player {idx}", team="KC",
                           position="QB", availability="FA", injury_status="", game="")


class FakeReader:
    """page() fails `failures` times, then serves `pages` scripted pages."""

    def __init__(self, failures=0, pages=((),)):
        self.failures = failures
        self.pages = list(pages)
        self.calls = 0

    def page(self):
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise PlayerReadError("not rendered yet")
        return self.pages.pop(0) if self.pages else ()


def _scan(monkeypatch, client, reader, **kw):
    monkeypatch.setattr(wire, "YahooPlayerReader", lambda c: reader)
    monkeypatch.setattr(wire.time, "sleep", lambda s: None)  # keep tests instant
    return wire.scan_available(client, 1, positions=("QB",), **kw)


def test_retries_until_page_renders(monkeypatch):
    full = tuple(_player(i) for i in range(25))
    reader = FakeReader(failures=2, pages=(full, ()))
    result = _scan(monkeypatch, FakeClient(), reader)

    assert len(result) == 25
    assert reader.calls == 4  # 2 failures + full page + short page


def test_denial_page_aborts_immediately(monkeypatch):
    client = FakeClient(denied=True)
    reader = FakeReader(failures=99)

    with pytest.raises(wire.WireScanBlocked):
        _scan(monkeypatch, client, reader)

    assert client.navigations == 1  # never hammers a denied page


def test_render_deadline_still_raises(monkeypatch):
    reader = FakeReader(failures=99)
    monkeypatch.setattr(wire, "YahooPlayerReader", lambda c: reader)
    monkeypatch.setattr(wire.time, "sleep", lambda s: None)
    clock = iter([0.0, 100.0])  # first check, then past the deadline
    monkeypatch.setattr(wire.time, "monotonic", lambda: next(clock))

    with pytest.raises(PlayerReadError):
        wire.scan_available(FakeClient(), 1, positions=("QB",), pause=0.1)


def test_stops_after_short_page(monkeypatch):
    reader = FakeReader(pages=(tuple(_player(i) for i in range(10)),))
    result = _scan(monkeypatch, FakeClient(), reader)

    assert len(result) == 10
    assert reader.calls == 1  # a short page ends pagination for that position


def test_empty_first_page_is_retried_not_accepted(monkeypatch):
    full = tuple(_player(i) for i in range(25))
    reader = FakeReader(pages=((), full, ()))  # empty first = mid-render
    result = _scan(monkeypatch, FakeClient(), reader)

    assert len(result) == 25
    assert reader.calls == 3
