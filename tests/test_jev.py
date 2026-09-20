"""Hermetic tests for src/jev.py: request shape, answer parsing, fail-loud paths."""

from __future__ import annotations

import pytest
import requests

from src import jev


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", json_error=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeSession:
    """requests-like stand-in recording the last call; raise_to exercise transport errors."""

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json,
                           "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.response


LIVE_SHAPED_PAYLOAD = {
    "model": "jev-1.13.0",
    "answers": {
        "is_ready": {"type": "noul", "noul": 0.98},
        "priority": {"type": "score", "score": 2.13, "confidence": 0.52,
                     "legend": {"0": "ignore", "1": "watchlist", "2": "claim"},
                     "probabilities": {"0": 0.03, "1": 0.11, "2": 0.86}},
        "profile": {"type": "choice", "choice": "breakout", "confidence": 0.71,
                    "probabilities": {"breakout": 0.6, "spike": 0.4}},
    },
    "usage": {"input_tokens": 360, "output_tokens": 37},
}


def test_request_shape_and_headers():
    session = FakeSession(FakeResponse(payload=LIVE_SHAPED_PAYLOAD))
    questions = {"is_ready": jev.noul("Is the player active?")}
    resp = jev.ask({"note": "x"}, questions, api_key="k", session=session,
                   timeout=12)
    (call,) = session.calls
    assert call["url"] == jev.API_URL
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["timeout"] == 12
    assert call["json"]["model"] == jev.DEFAULT_MODEL
    assert call["json"]["state"] == {"note": "x"}
    assert call["json"]["questions"]["is_ready"]["type"] == "noul"
    assert resp.model == "jev-1.13.0"
    assert resp.usage["input_tokens"] == 360


def test_parse_all_three_answer_types():
    session = FakeSession(FakeResponse(payload=LIVE_SHAPED_PAYLOAD))
    resp = jev.ask("state", {"a": jev.noul("q")}, api_key="k", session=session)
    assert resp.answers["is_ready"].noul == 0.98
    assert resp.answers["priority"].score == 2.13
    assert resp.answers["priority"].legend["2"] == "claim"
    assert resp.answers["profile"].choice == "breakout"
    assert resp.answers["profile"].confidence == 0.71


def test_missing_key_raises_before_http(monkeypatch):
    monkeypatch.setattr(jev, "typesafe_api_key", lambda: None)
    session = FakeSession(FakeResponse(payload=LIVE_SHAPED_PAYLOAD))
    with pytest.raises(jev.JevError, match="TYPESAFE_API_KEY"):
        jev.ask("state", {"a": jev.noul("q")}, session=session)
    assert session.calls == []


def test_non_200_raises_with_status():
    session = FakeSession(FakeResponse(status_code=429, text="rate limited"))
    with pytest.raises(jev.JevError, match="429"):
        jev.ask("state", {"a": jev.noul("q")}, api_key="k", session=session)


def test_transport_error_wrapped():
    session = FakeSession(exc=requests.Timeout("slow"))
    with pytest.raises(jev.JevError, match="slow"):
        jev.ask("state", {"a": jev.noul("q")}, api_key="k", session=session)


@pytest.mark.parametrize("payload", [
    None,
    {"model": "jev-1.13.0"},
    {"answers": ["not-a-dict"]},
    {"answers": {"a": {"type": "mystery"}}},
    {"answers": {"a": "not-a-dict"}},
])
def test_malformed_payloads_raise(payload):
    session = FakeSession(FakeResponse(payload=payload))
    with pytest.raises(jev.JevError):
        jev.ask("state", {"a": jev.noul("q")}, api_key="k", session=session)


def test_invalid_questions_rejected_locally():
    session = FakeSession(FakeResponse(payload=LIVE_SHAPED_PAYLOAD))
    with pytest.raises(jev.JevError, match="unknown type"):
        jev.ask("s", {"bad": {"type": "essay", "instructions": "x"}},
                api_key="k", session=session)
    with pytest.raises(jev.JevError, match="instructions"):
        jev.ask("s", {"empty": {"type": "noul"}}, api_key="k", session=session)
    assert session.calls == []


def test_question_builders():
    assert jev.choice("pick", {"a": "A", "b": "B"})["criteria"]["b"] == "B"
    assert jev.score("rate", ["low", "high"])["criteria"] == ["low", "high"]
    assert jev.noul("yn", criteria={"yes": "y", "no": "n"})["criteria"]["yes"] == "y"
    assert "criteria" not in jev.noul("yn")


def test_key_resolution_falls_back_to_config(monkeypatch):
    monkeypatch.setattr(jev, "typesafe_api_key", lambda: "from-config")
    session = FakeSession(FakeResponse(payload=LIVE_SHAPED_PAYLOAD))
    jev.ask("s", {"a": jev.noul("q")}, session=session)
    assert session.calls[0]["headers"]["Authorization"] == "Bearer from-config"
