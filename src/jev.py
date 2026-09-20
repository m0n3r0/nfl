"""Jev (TypeSafe System One) client: typed judgments over a state snapshot.

Jev is not a language model: it answers typed *questions* about a *state* and
returns structured values (choice / score / noul) with probabilities, never
prose. It carries no live NFL data of its own, so the state must contain every
fact the judgment needs; Jev supplies a fast second-opinion layer on top of
the numbers the projection model produces. Callers stay fail-closed on the
projection side and treat Jev answers as advisory only.

This module is a thin facade over the official ``typesafe-sdk`` (pinned in
requirements.txt): the builders return SDK question objects, and ask() maps
the SDK's typed answers back into plain dataclasses so the rest of the repo
never imports the SDK directly. The API key comes from ``TYPESAFE_API_KEY``
(env or repo-root .env) and is passed to the SDK explicitly, because the SDK
alone would only look at the process environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import typesafe_sdk as ts

from .config import typesafe_api_key

DEFAULT_MODEL = str(ts.constants.DEFAULT_MODEL)  # "jev-latest"

Question = ts.Noul | ts.Choice | ts.Score


class JevError(RuntimeError):
    """The Jev call failed or returned an unexpected payload; never guess."""


@dataclass(frozen=True)
class JevAnswer:
    """One question's typed answer; only the fields of its type are set.

    Score legend/probability keys are normalized to str (the SDK returns
    int keys) so answers serialize to JSON the way the raw API does.
    """

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


def noul(instructions: str, criteria: Mapping[str, Any] | None = None) -> ts.Noul:
    """Yes/no question; the answer's ``noul`` is the probability of yes.

    ``criteria`` optionally describes the outcomes, keys ``true``/``false``.
    """
    return ts.Noul(instructions=instructions,
                   criteria=dict(criteria) if criteria else None)


def choice(instructions: str, criteria: Mapping[str, Any]) -> ts.Choice:
    """Pick one of the given options (option id -> description)."""
    return ts.Choice(instructions=instructions, criteria=dict(criteria))


def score(instructions: str, criteria: list[str]) -> ts.Score:
    """Position along the given ordered levels (low to high)."""
    return ts.Score(instructions=instructions, criteria=list(criteria))


def connect(*, model: str = DEFAULT_MODEL, timeout: float = 30,
            api_key: str | None = None) -> ts.TypeSafeClient:
    """Create an SDK client; use as a context manager to reuse across calls.

    Raises JevError before any HTTP when the key is missing so callers fail
    fast and loud.
    """
    key = api_key or typesafe_api_key()
    if not key:
        raise JevError("TYPESAFE_API_KEY is not set (env or repo-root .env)")
    return ts.TypeSafeClient(api_key=key, model=model, timeout=timeout)


def ask(state: Any, questions: Mapping[str, Question], *,
        client: Any = None, **connect_kwargs: Any) -> JevResponse:
    """Evaluate every question against the state in one request.

    Pass ``client`` (from connect()) to reuse a connection across calls;
    otherwise a client is created and closed for this call. ``client`` is
    duck-typed so tests inject a fake; connect_kwargs apply only when no
    client is given.
    """
    _validate_questions(questions)
    if client is not None:
        return _ask_with(client, state, questions)
    with connect(**connect_kwargs) as owned:
        return _ask_with(owned, state, questions)


def _validate_questions(questions: Mapping[str, Any]) -> None:
    for qid, q in questions.items():
        if not isinstance(q, (ts.Noul, ts.Choice, ts.Score)):
            raise JevError(
                f"question {qid!r}: build with jev.noul/choice/score, "
                f"got {type(q).__name__}")
        if not q.instructions:
            raise JevError(f"question {qid!r}: instructions are required")


def _ask_with(client: Any, state: Any, questions: Mapping[str, Question]) -> JevResponse:
    try:
        resp = client.system_one(state=state, questions=dict(questions))
    except ts.TypeSafeError as exc:
        raise JevError(f"Jev request failed: {exc}") from exc
    return JevResponse(
        model=resp.model,
        answers={qid: _convert(qid, a) for qid, a in resp.answers.items()},
        usage={k: v for k, v in
               (("input_tokens", resp.usage.input_tokens),
                ("output_tokens", resp.usage.output_tokens)) if v is not None},
    )


def _convert(qid: str, a: Any) -> JevAnswer:
    if isinstance(a, ts.NoulAnswer):
        return JevAnswer(type="noul", noul=a.noul)
    if isinstance(a, ts.ChoiceAnswer):
        return JevAnswer(type="choice", choice=a.choice,
                         confidence=a.confidence,
                         probabilities=dict(a.probabilities))
    if isinstance(a, ts.ScoreAnswer):
        return JevAnswer(type="score", score=a.score,
                         confidence=a.confidence,
                         legend={str(k): str(v) for k, v in a.legend.items()},
                         probabilities={str(k): v for k, v in a.probabilities.items()})
    raise JevError(f"answer {qid!r}: unexpected type {type(a).__name__}")


# ---------------------------------------------------------------------------
# Fantasy question packs (FD nation domain layer)
#
# Jev has no live NFL knowledge: every pack puts the facts (projections,
# statuses, league format) into the state and asks only for judgment over
# them. Answers are advisory; projections stay the source of truth.
# ---------------------------------------------------------------------------

LEAGUE_CONTEXT = ("10-team half-PPR Yahoo league; weekly lineup "
                  "QB/2RB/2WR/TE/W-R-T/K/DEF plus a 6-man bench.")


def waiver_state(target: Mapping[str, Any], week: int) -> dict:
    """Compact per-player state for a wire target; Jev judges only this."""
    return {
        "task": "Assess an available free agent for a fantasy football waiver claim.",
        "league": LEAGUE_CONTEXT,
        "week": week,
        "player": {k: target[k] for k in
                   ("name", "position", "team", "availability", "injury_status")},
        "proj_points_this_week": target["proj_week"],
    }


def waiver_questions() -> dict[str, Question]:
    return {
        "profile": choice(
            "Which profile best fits `player` as a waiver target right now?",
            {"steady_starter": "Reliable weekly starter talent.",
             "breakout": "Emerging role with sustainable upside.",
             "injury_fillin": "Value depends on a teammate's injury.",
             "one_week_spike": "Recent hype driven by a fluke game.",
             "depth_piece": "Bench depth or handcuff only."}),
        "claim": score(
            "Recommended waiver action for `player` this week.",
            ["ignore", "watchlist", "stream if needed", "claim now"]),
        "risk": noul(
            "Does `player` carry injury or role risk the projection may not capture?"),
    }


def _summarize(answers: Mapping[str, JevAnswer]) -> dict:
    out: dict[str, Any] = {}
    for qid, a in answers.items():
        if a.type == "noul":
            out[qid] = a.noul
        elif a.type == "choice":
            out[qid] = a.choice
        else:
            out[qid] = a.score
            out[f"{qid}_legend"] = a.legend
    return out


def review_waiver_targets(targets: list[dict], week: int, *,
                          client: Any = None) -> list[tuple[str, str]]:
    """Attach an advisory 'jev' block to each target in place.

    Returns (name, error) pairs for the players Jev could not judge; callers
    decide how loudly to report them.
    """
    failures: list[tuple[str, str]] = []
    for target in targets:
        try:
            resp = ask(waiver_state(target, week), waiver_questions(), client=client)
            target["jev"] = _summarize(resp.answers)
        except JevError as exc:
            failures.append((str(target.get("name", "?")), str(exc)))
    return failures


def injury_state(player: Mapping[str, Any], week: int) -> dict:
    """State for one roster player carrying an injury tag (Q/D/O)."""
    return {
        "task": "Assess a rostered fantasy football player's injury tag.",
        "league": LEAGUE_CONTEXT,
        "week": week,
        "player": {k: player.get(k) for k in
                   ("name", "position", "team", "injury_status", "slot")},
        "proj_points_this_week": player.get("proj_week"),
    }


def injury_questions() -> dict[str, Question]:
    return {
        "likely_out": noul(
            "Is `player` likely to be inactive or leave early this week, "
            "given `player.injury_status`?"),
        "impact": score(
            "If `player` plays through this tag, expected fantasy impact.",
            ["full risk of a dud", "limited snap share", "near-normal", "no concern"]),
        "bench_now": noul(
            "Should a cautious manager bench `player` for a healthy "
            "comparable option this week?"),
    }


def review_injured_players(players: list[dict], week: int, *,
                           client: Any = None) -> list[tuple[str, str]]:
    """Attach an advisory 'jev' block to each injured-player dict in place."""
    failures: list[tuple[str, str]] = []
    for player in players:
        try:
            resp = ask(injury_state(player, week), injury_questions(), client=client)
            player["jev"] = _summarize(resp.answers)
        except JevError as exc:
            failures.append((str(player.get("name", "?")), str(exc)))
    return failures


def trade_state(give: list[dict], receive: list[dict]) -> dict:
    """State for a proposed trade; numbers come from our season projections."""
    return {
        "task": "Judge a proposed fantasy football trade from our side.",
        "league": LEAGUE_CONTEXT,
        "we_give": give,
        "we_receive": receive,
    }


def trade_questions() -> dict[str, Question]:
    return {
        "verdict": choice(
            "Overall verdict on the trade for us, given `we_give` and `we_receive`.",
            {"accept": "Clearly improves our roster.",
             "roughly_fair": "Close enough that context decides.",
             "reject": "Weakens our roster."}),
        "fairness": score(
            "How lopsided is the trade in our favor?",
            ["big loss", "slight loss", "fair", "slight win", "big win"]),
        "risk": noul(
            "Does either side carry material injury or role risk?"),
    }


def judge_trade(give: list[dict], receive: list[dict], *,
                client: Any = None) -> dict:
    """One Jev call for a proposed trade; returns the summarized verdict."""
    resp = ask(trade_state(give, receive), trade_questions(), client=client)
    return _summarize(resp.answers)
