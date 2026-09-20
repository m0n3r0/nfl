"""Jev (TypeSafe System One) client: typed judgments over a state snapshot.

Jev is not a language model: it answers typed *questions* about a *state* and
returns structured values (choice / score / noul) with probabilities, never
prose. It carries no live NFL data of its own, so the state must contain every
fact the judgment needs; Jev supplies a fast second-opinion layer on top of
the numbers the projection model produces. Callers stay fail-closed on the
projection side and treat Jev answers as advisory only.

API key comes from ``TYPESAFE_API_KEY`` (env or repo-root .env). The official
``typesafe-sdk`` requires Python 3.10+ while this repo's venv runs 3.9, so
this is a thin ``requests`` client against ``POST /v1/systemone`` instead.

Response shape (verified against the live API 2026-09-20, model jev-1.13.0)::

    {"model": "...", "usage": {"input_tokens": N, "output_tokens": M},
     "answers": {"qid": {"type": "noul", "noul": 0.98},
                 "q2":  {"type": "score", "score": 2.13, "confidence": 0.52,
                         "legend": {"0": "avoid", ...}, "probabilities": {...}},
                 "q3":  {"type": "choice", "choice": "x",
                         "probabilities": {...}, "confidence": 0.71}}}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import requests

from .config import typesafe_api_key

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

QUESTION_TYPES = ("choice", "score", "noul")


class JevError(RuntimeError):
    """The Jev call failed or returned an unparseable payload; never guess."""


@dataclass(frozen=True)
class JevAnswer:
    """One question's typed answer; only the fields of its type are set."""

    type: str
    noul: float | None = None
    choice: str | None = None
    score: float | None = None
    confidence: float | None = None
    probabilities: Mapping[str, float] | None = None
    legend: Mapping[str, str] | None = None


@dataclass(frozen=True)
class JevResponse:
    model: str
    answers: Mapping[str, JevAnswer]
    usage: Mapping[str, int] = field(default_factory=dict)


def noul(instructions: str, criteria: Mapping[str, str] | None = None) -> dict:
    """Yes/no question; the returned ``noul`` is the probability of yes."""
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria is not None:
        q["criteria"] = dict(criteria)
    return q


def choice(instructions: str, criteria: Mapping[str, str]) -> dict:
    """Pick one of the given options (option id -> description)."""
    return {"type": "choice", "instructions": instructions,
            "criteria": dict(criteria)}


def score(instructions: str, criteria: list[str]) -> dict:
    """Position along the given ordered levels (low to high)."""
    return {"type": "score", "instructions": instructions,
            "criteria": list(criteria)}


def ask(state: Any, questions: Mapping[str, dict], *,
        model: str = DEFAULT_MODEL, timeout: float = 30,
        api_key: str | None = None, session: Any = None) -> JevResponse:
    """Evaluate every question against the state in one request.

    ``session`` is a requests-like object (tests inject a fake); a missing
    API key raises before any HTTP happens so callers fail fast and loud.
    """
    key = api_key or typesafe_api_key()
    if not key:
        raise JevError("TYPESAFE_API_KEY is not set (env or repo-root .env)")
    for qid, q in questions.items():
        if q.get("type") not in QUESTION_TYPES:
            raise JevError(f"question {qid!r}: unknown type {q.get('type')!r}")
        if not q.get("instructions"):
            raise JevError(f"question {qid!r}: instructions are required")
    http = session or requests
    try:
        resp = http.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "state": state, "questions": dict(questions)},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise JevError(f"Jev request failed: {exc}") from exc
    if resp.status_code != 200:
        raise JevError(f"Jev API returned {resp.status_code}: {resp.text[:300]}")
    try:
        payload = resp.json()
        raw_answers = payload["answers"]
    except (ValueError, KeyError, TypeError) as exc:
        raise JevError(f"Jev payload malformed: {exc}") from exc
    if not isinstance(raw_answers, dict):
        raise JevError("Jev payload malformed: 'answers' is not an object")
    return JevResponse(
        model=str(payload.get("model", model)),
        answers={qid: _parse_answer(qid, raw) for qid, raw in raw_answers.items()},
        usage=payload.get("usage") or {},
    )


def _parse_answer(qid: str, raw: Any) -> JevAnswer:
    if not isinstance(raw, dict) or raw.get("type") not in QUESTION_TYPES:
        raise JevError(f"answer {qid!r}: malformed or unknown type")
    return JevAnswer(
        type=raw["type"],
        noul=raw.get("noul"),
        choice=raw.get("choice"),
        score=raw.get("score"),
        confidence=raw.get("confidence"),
        probabilities=raw.get("probabilities"),
        legend=raw.get("legend"),
    )
