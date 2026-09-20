"""Hermetic tests for src/jev.py: SDK wiring, answer mapping, fail-loud paths."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typesafe_sdk as ts

from src import jev


def sdk_response() -> ts.SystemOneResponse:
    return ts.SystemOneResponse(
        model="jev-1.13.0",
        usage=ts.Usage(input_tokens=360, output_tokens=37),
        answers={
            "is_ready": ts.NoulAnswer(type="noul", noul=0.98),
            "priority": ts.ScoreAnswer(
                type="score", score=2.13, confidence=0.52,
                legend={0: "ignore", 1: "watchlist", 2: "claim"},
                probabilities={0: 0.03, 1: 0.11, 2: 0.86}),
            "profile": ts.ChoiceAnswer(
                type="choice", choice="breakout", confidence=0.71,
                probabilities={"breakout": 0.6, "spike": 0.4}),
        })


class FakeClient:
    """Duck-typed TypeSafeClient stand-in recording calls."""

    def __init__(self, response=None, exc=None):
        self.response = response if response is not None else sdk_response()
        self.exc = exc
        self.calls = []

    def system_one(self, state=None, questions=None, **kwargs):
        self.calls.append({"state": state, "questions": questions, **kwargs})
        if self.exc:
            raise self.exc
        return self.response


def test_ask_maps_all_answer_types():
    resp = jev.ask("state", {"q": jev.noul("q?")}, client=FakeClient())
    assert resp.model == "jev-1.13.0"
    assert resp.answers["is_ready"].noul == 0.98
    score = resp.answers["priority"]
    assert score.score == 2.13
    assert score.confidence == 0.52
    assert score.legend == {"0": "ignore", "1": "watchlist", "2": "claim"}
    assert score.probabilities["2"] == 0.86
    choice = resp.answers["profile"]
    assert choice.choice == "breakout"
    assert choice.probabilities == {"breakout": 0.6, "spike": 0.4}
    assert resp.usage == {"input_tokens": 360, "output_tokens": 37}


def test_state_and_questions_forwarded_verbatim():
    client = FakeClient()
    questions = {"a": jev.noul("q?"), "b": jev.score("s?", ["lo", "hi"])}
    jev.ask({"note": "x"}, questions, client=client)
    (call,) = client.calls
    assert call["state"] == {"note": "x"}
    assert call["questions"] == questions


def test_ask_without_client_creates_and_closes_one(monkeypatch):
    closed = []

    class Recorder(FakeClient):
        def __init__(self, **kwargs):
            super().__init__()
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            closed.append(True)

    created = []
    monkeypatch.setattr(jev.ts, "TypeSafeClient",
                        lambda **kw: created.append(Recorder(**kw)) or created[-1])
    resp = jev.ask("s", {"a": jev.noul("q?")}, api_key="k", timeout=12)
    assert resp.model == "jev-1.13.0"
    assert created[0].kwargs["api_key"] == "k"
    assert created[0].kwargs["timeout"] == 12
    assert closed == [True]


def test_connect_uses_config_key_when_no_explicit_key(monkeypatch):
    monkeypatch.setattr(jev, "typesafe_api_key", lambda: "from-config")
    captured = {}
    monkeypatch.setattr(jev.ts, "TypeSafeClient",
                        lambda **kw: captured.update(kw) or FakeClient())
    jev.connect()
    assert captured["api_key"] == "from-config"
    assert captured["model"] == jev.DEFAULT_MODEL


def test_missing_key_raises_before_client_creation(monkeypatch):
    monkeypatch.setattr(jev, "typesafe_api_key", lambda: None)
    monkeypatch.setattr(jev.ts, "TypeSafeClient",
                        lambda **kw: pytest.fail("client must not be created"))
    with pytest.raises(jev.JevError, match="TYPESAFE_API_KEY"):
        jev.connect()
    with pytest.raises(jev.JevError, match="TYPESAFE_API_KEY"):
        jev.ask("s", {"a": jev.noul("q?")})


@pytest.mark.parametrize("exc", [
    ts.TypeSafeAPITimeoutError(timeout=5),
    ts.TypeSafeAPIConnectionError("boom"),
])
def test_sdk_errors_wrapped_in_jev_error(exc):
    with pytest.raises(jev.JevError):
        jev.ask("s", {"a": jev.noul("q?")}, client=FakeClient(exc=exc))


def test_invalid_questions_rejected_before_http():
    client = FakeClient()
    with pytest.raises(jev.JevError, match="build with jev"):
        jev.ask("s", {"bad": {"type": "noul", "instructions": "x"}},
                client=client)
    with pytest.raises(jev.JevError, match="instructions"):
        jev.ask("s", {"empty": ts.Noul()}, client=client)
    assert client.calls == []


def test_unexpected_answer_type_raises():
    bogus = SimpleNamespace(
        model="m", usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        answers={"a": object()})
    with pytest.raises(jev.JevError, match="unexpected type"):
        jev.ask("s", {"a": jev.noul("q?")}, client=FakeClient(response=bogus))


def test_question_builders_return_sdk_objects():
    q = jev.choice("pick", {"a": "A", "b": "B"})
    assert isinstance(q, ts.Choice) and q.criteria["b"] == "B"
    s = jev.score("rate", ["low", "high"])
    assert isinstance(s, ts.Score) and list(s.criteria) == ["low", "high"]
    n = jev.noul("yn", criteria={"true": "yes means", "false": "no means"})
    assert isinstance(n, ts.Noul) and n.criteria["true"] == "yes means"
    assert jev.noul("yn").criteria is None
