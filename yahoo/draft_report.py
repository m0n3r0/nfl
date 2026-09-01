"""Generate and publish the authoritative FD nation draft report."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .mock_draft import Pick
from .real_draft import LEAGUE_ID, TEAM_ID

REPORT_PATH = Path("docs/drafts/2026-09-02-fd-nation.md")
RESULT_BRANCH = "draft/2026-fd-nation-results"


def _records(audit_path: Path) -> list[dict[str, Any]]:
    records = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("league") == LEAGUE_ID and record.get("team") == TEAM_ID:
            records.append(record)
    return records


def _provenance(decision: dict[str, Any]) -> str:
    """Return an honest, human-readable source for a recorded decision."""
    source = decision.get("source")
    path = decision.get("selection_path")
    if source == "yahoo_autopick":
        return "Yahoo autopick"
    if path == "live_yahoo_rank":
        return "Yahoo XRank recovery fallback"
    if path in {"full_board_search", "visible_fallback"}:
        return "Internal FD nation board"
    if source == "manual_recovery":
        return "Manual live recovery"
    if source == "operator_selection":
        return "Operator selection; rationale reconstructed retrospectively"
    return "Unknown or incomplete audit provenance"


def render_draft_report(picks: Iterable[Pick], audit_path: Path) -> str:
    """Render pick-specific rationale from Yahoo-confirmed picks and audit data."""
    picks = sorted(picks, key=lambda pick: pick.round)
    if len(picks) != 15 or [pick.round for pick in picks] != list(range(1, 16)):
        raise ValueError("report requires exactly one authoritative pick for every round")
    decisions = {
        (record.get("round"), str(record.get("player_id"))): record
        for record in _records(audit_path)
        if record.get("event") == "decision"
    }
    provenance = Counter(
        _provenance(decisions.get((pick.round, pick.player.id), {}))
        for pick in picks
    )
    lines = [
        "# FD nation 2026 draft results and rationale",
        "",
        f"League `{LEAGUE_ID}`, team `{TEAM_ID}` (Shiba Innu).",
        "",
        "This roster was reconstructed from Yahoo's authoritative completed draft state. "
        "Rationales may be contemporaneous or retrospective; each pick states its audited selection provenance.",
        "",
        "## Selection-source summary",
        "",
        *[f"- {source}: {count}" for source, count in sorted(provenance.items())],
        "",
        "## Picks",
        "",
    ]
    for pick in picks:
        player = pick.player
        decision = decisions.get((pick.round, player.id), {})
        name = str(decision.get("board_player") or player.name)
        lines.extend([
            f"### Round {pick.round}, overall {pick.pick}: {name} ({player.team} — {player.pos})",
            "",
            f"Selection provenance: {_provenance(decision)}.",
            "",
            str(decision.get("reason") or
                "Yahoo confirmed this roster pick, but no contemporaneous operator rationale was recoverable."),
        ])
        details = []
        if decision.get("board_value") is not None:
            details.append(f"board value {decision['board_value']}")
        if decision.get("yahoo_xrank"):
            details.append(f"Yahoo XRank {decision['yahoo_xrank']:g}")
        if decision.get("yahoo_adp"):
            details.append(f"Yahoo ADP {decision['yahoo_adp']:g}")
        if details:
            lines.extend(["", "Decision evidence: " + "; ".join(details) + "."])
        alternatives = decision.get("alternatives_unavailable") or []
        if alternatives:
            lines.extend(["", "Higher-priority board targets checked but unavailable: " +
                          ", ".join(str(value) for value in alternatives) + "."])
        lines.append("")
    lines.extend([
        "## Method",
        "",
        "Yahoo roster history—not local counters—was the final authority for the completed roster. "
        "The source summary is derived from each decision's audit fields; it does not infer internal-model use "
        "from the presence of Yahoo XRank or ADP evidence.",
        "",
        f"Report generated {dt.datetime.now(dt.timezone.utc).isoformat()}.",
        "",
    ])
    return "\n".join(lines)


def write_draft_report(root: Path, picks: Iterable[Pick], audit_path: Path) -> Path:
    """Write the completed draft report inside the repository."""
    path = root / REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_draft_report(picks, audit_path), encoding="utf-8")
    return path


def _git(root: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def publish_draft_report(root: Path, report_path: Path, remote: str = "orign") -> str:
    """Commit, push, and open a PR for the completed report."""
    branch = _git(root, "branch", "--show-current", capture=True)
    if branch != RESULT_BRANCH:
        local_branches = _git(root, "branch", "--format=%(refname:short)", capture=True).splitlines()
        if RESULT_BRANCH in local_branches:
            _git(root, "switch", RESULT_BRANCH)
        else:
            _git(root, "switch", "-c", RESULT_BRANCH)
    _git(root, "add", str(report_path.relative_to(root)))
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root).returncode
    if staged:
        _git(root, "commit", "-m", "docs(draft): record FD nation roster and rationale")
    _git(root, "push", "-u", remote, RESULT_BRANCH)
    existing = subprocess.run(
        ["gh", "pr", "list", "--head", RESULT_BRANCH, "--state", "open", "--json", "url", "--jq", ".[0].url"],
        cwd=root, check=True, text=True, stdout=subprocess.PIPE,
    ).stdout.strip()
    if existing:
        return existing
    return subprocess.run(
        ["gh", "pr", "create", "--base", "main", "--head", RESULT_BRANCH,
         "--title", "docs(draft): record FD nation roster and rationale",
         "--body", "Records Yahoo's authoritative completed roster and the contemporaneous rationale for every pick."],
        cwd=root, check=True, text=True, stdout=subprocess.PIPE,
    ).stdout.strip()