"""
FD nation (league 1329011) LIVE DRAFT DRIVER for team #2 (Doge)
Runs against Edge on ws://127.0.0.1:9222 (launched with --remote-allow-origins=*).
Strategy: position-target-aware board picking with guardrails.
Guarantees a legal lineup: required slots (QB,2RB,2WR,TE,K,DEF) filled by
their deadlines, bench (6 BN) filled with best available afterwards.
All decisions logged to C:\\edge-debug-profile\\draft_log.txt
"""
import json, os, re, urllib.request, websocket, time, random, math, sys, io, datetime, hashlib
from pathlib import Path

CDP = "http://127.0.0.1:9222"
LEAGUE = "1329011"
TEAM_ID = "2"
# Decision log. Windows keeps the historical default; other platforms (e.g.
# headless macOS) take $FD_DRAFT_LOG or ./draft_log.txt (set the launchd
# working directory to where you want it). The env var wins everywhere.
LOG = (os.environ.get("FD_DRAFT_LOG")
       or (r"C:\edge-debug-profile\draft_log.txt" if sys.platform.startswith("win")
           else os.path.join(os.getcwd(), "draft_log.txt")))
TOTAL_ROUNDS = 15
TEAMS = 10                   # league size (verified live 2026-08-28)
MY_PICK_ROUNDS_QB = 10      # don't take QB before this round
K_DEF_LAST_ROUNDS = 2       # K/DEF only in last N rounds
ADP_WINDOW = 40              # reach guard: skip board pick if ADP >> board rank

# ---- Live value board (FantasyPros API) -------------------------------------
# Instead of drafting from a fixed list, we pull live Expert Consensus Rankings
# (ECR) from FantasyPros and draft the best available player by ECR (a strong
# best-player-available signal). If the key's plan also exposes ADP (a PAID
# FantasyPros tier), we upgrade to true VALUE = ADP - ECR (players the experts
# rank well above where the crowd drafts = best value).
# Requires an API key (https://www.fantasypros.com/api-data/) in FP_API_KEY
# (or API= in a .env file). If the key is missing or the fetch fails, we fall
# back to the static BOARD (original behaviour). Set FP_SCORING to match your
# league (.5 PPR -> HALF).
def _load_dotenv():
    """Minimal .env loader (no python-dotenv dependency). Loads the first
    .env found at the repo root or the current working directory, setting only
    vars that aren't already in the environment (real env vars win)."""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with io.open(path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            return

_load_dotenv()
# Canonical env var is FP_API_KEY; accept a bare API= alias for convenience.
FP_API_KEY = os.environ.get("FP_API_KEY") or os.environ.get("API")
FP_BASE = "https://api.fantasypros.com/public/v2/json"
FP_SEASON = 2026
FP_SCORING = "HALF"          # FD nation is .5 PPR

# FantasyPros Real-Time ADP page: the FREE ADP source (no API key). It renders a
# live "REAL-TIME" ADP column derived from the same expert pool as the ECR feed,
# so we can compute true VALUE = ADP - ECR without paying for the ADP API tier.
# We scrape it from a fresh Edge tab via CDP at draft start (see
# scrape_fp_realtime_adp). The "YAHOO" column on that same page is a useful
# cross-platform sanity check but we standardize on the REAL-TIME column.
RT_ADP_URL = "https://www.fantasypros.com/nfl/real-time-adp/"

# ---- Pre-built board: (name, team, pos, adp) from verified Yahoo ADP scrape ----
# Skill + K/DEF tiers added 2026-08-21 after mock-draft validation found the
# original board lacked K/DEF (would have left lineup illegal).
BOARD = [
    # skill players (top ~30 ADP)
    ("Jahmyr Gibbs","Det","RB",1.5),("Bijan Robinson","Atl","RB",1.9),
    ("Ja'Marr Chase","Cin","WR",3.3),("Puka Nacua","LAR","WR",4.7),
    ("Christian McCaffrey","SF","RB",5.5),("Amon-Ra St. Brown","Det","WR",8.0),
    ("Jaxon Smith-Njigba","Sea","WR",6.7),("Jonathan Taylor","Ind","RB",7.1),
    ("CeeDee Lamb","Dal","WR",10.2),("James Cook III","Buf","RB",9.9),
    ("Saquon Barkley","Phi","RB",12.4),("Justin Jefferson","Min","WR",12.4),
    ("Ashton Jeanty","LV","RB",14.1),("Chase Brown","Cin","RB",16.6),
    ("De'Von Achane","Mia","RB",15.7),("Kenneth Walker III","KC","RB",17.0),
    ("Derrick Henry","Bal","RB",18.2),("Drake London","Atl","WR",18.6),
    ("Omarion Hampton","LAC","RB",18.7),("Josh Allen","Buf","QB",19.6),("Lamar Jackson","Bal","QB",30.0),("Jayden Daniels","Wsh","QB",35.0),("Joe Burrow","Cin","QB",45.0),
    ("Justin Herbert","LAC","QB",55.0),("Patrick Mahomes","KC","QB",60.0),("Jalen Hurts","Phi","QB",65.0),("Dak Prescott","Dal","QB",70.0),
    ("Baker Mayfield","TB","QB",80.0),("Bo Nix","Den","QB",90.0),
    ("Brock Bowers","LV","TE",21.1),("Nico Collins","Hou","WR",22.2),
    ("George Pickens","Dal","WR",22.4),("A.J. Brown","NE","WR",25.0),
    ("Trey McBride","Ari","TE",25.4),("Travis Kelce","KC","TE",35.0),("George Kittle","SF","TE",40.0),("Sam LaPorta","Det","TE",45.0),("T.J. Hockenson","Min","TE",55.0),("Mark Andrews","Bal","TE",70.0),("Kyle Pitts","Atl","TE",80.0),("David Njoku","Cle","TE",85.0),("Tucker Kraft","GB","TE",90.0),("Jeremiyah Love","Ari","RB",27.2),
    ("DeVonta Smith","Phi","WR",29.4),("Kyren Williams","LAR","RB",29.6),
    ("Josh Jacobs","GB","RB",32.8),("Chris Olave","NO","WR",34.0),
    # K tier (draft only last rounds) -- 10 for 10-team depth
    ("Brandon Aubrey","Dal","K",85.0),("Ka'imi Fairbairn","Hou","K",119.0),
    ("Cameron Dicker","LAC","K",123.0),("Jason Myers","Sea","K",124.0),
    ("Cam Little","Jax","K",129.0),("Harrison Butker","KC","K",115.0),("Justin Tucker","Bal","K",135.0),
    ("Jake Elliott","Phi","K",140.0),("Younghoe Koo","Atl","K",145.0),("Wil Lutz","Den","K",150.0),
    # DEF tier (draft only last rounds) -- 10 for 10-team depth
    ("Rams","LAR","DEF",89.0),("Texans","Hou","DEF",93.0),
    ("Broncos","Den","DEF",101.0),("Seahawks","Sea","DEF",107.0),
    ("Eagles","Phi","DEF",123.0),("Patriots","NE","DEF",127.0),("Bills","Buf","DEF",115.0),("49ers","SF","DEF",120.0),
    ("Steelers","Pit","DEF",125.0),("Packers","GB","DEF",130.0),
]

# Map a Yahoo team-defense code to the BOARD's short DEF key, so a defense
# shown as 'Los Angeles Rams LAR - DEF' (or 'Rams LAR - DEF') resolves to the
# BOARD key 'Rams' and choose_pick can match it. Built from BOARD so it stays
# in sync if the DEF list changes.
DEF_CODE_TO_NAME = {t.upper(): n for (n, t, p, a) in BOARD if p == "DEF"}

# Required starting slots (filled by deadline); bench fills the rest.
REQUIRED = {"QB":1, "RB":2, "WR":2, "TE":1, "K":1, "DEF":1}

# Anchor schedule: by which round the Nth still-needed player at POS must be
# taken (forced if still missing). Tuned for a 10-team league where the RB/TE
# wells run dry fast: lock 2 RBs by round 5, 2 WRs by round 9, TE by 7, etc.
ANCHOR_BY_ROUND = {
    "RB":  [3, 5],     # 1st RB by R3, 2nd RB by R5
    "WR":  [5, 9],     # 1st WR by R5, 2nd WR by R9
    "TE":  [7],        # TE by R7
    "QB":  [10],       # QB by R10
    "K":   [14],       # K/DEF in last 2 rounds
    "DEF": [14],
}

# Positional-scarcity soft premium. In a 10-team league the crowd OVER-drafts
# RBs (low Yahoo ADP), so VALUE = Yahoo_ADP - ECR scores good RBs NEGATIVE and
# would let the bot skip them for "higher-value" WRs -- then the RB well runs
# dry. While we still NEED a scarce position, add this premium to its effective
# value so the bot anchors it early. The anchor schedule above is the hard
# guarantee; this premium just biases close calls toward scarce positions.
#
# It is a FRACTION of the position's value spread, not an absolute number
# (issue #20). As an absolute 8.0 it was meaningless against 300-point
# projections and overwhelming against rank differences of ~5; scaled to the
# spread it means the same thing on either board.
SCARCITY_FRACTION = {"RB": 0.10}

# ---- Value over replacement (issues #19 + #20) -----------------------------
# Raw projected points are not comparable across positions. The top QB projects
# for ~393 points and the top TE for ~195, but we have to START one of each
# either way, so the question is never "who scores more" -- it is "how much more
# than the best alternative I could pick up for free". That difference is VOR,
# and it is the only number that is comparable across positions.
#
# Replacement level = the Nth-best player at a position, where N is how many a
# 10-team league starts. Past that line a player is waiver-wire material, so his
# marginal value to this roster is about zero.
REPLACEMENT_COUNT = {
    "QB":  10,   # 1 per team
    "RB":  24,   # 2 per team + ~4 of the 10 WRT flex slots
    "WR":  25,   # 2 per team + ~5 of the 10 WRT flex slots
    "TE":  12,   # 1 per team + ~2 flex
    "K":   10,
    "DEF": 10,
}

# Bench guardrails. The bench path takes best-player-available regardless of
# need, which without these will happily roster a 4th quarterback or a 2nd
# kicker because their raw projection still beats a WR3's.
BENCH_CAP = {"QB": 2, "K": 1, "DEF": 1, "TE": 2}


def replacement_values(board):
    """Value of the last *startable* player at each position (waiver level).

    Used to turn raw projections into VOR. Positions with no configured
    replacement count fall back to 10 (one starter per team).
    """
    by_pos = {}
    for v in board.values():
        by_pos.setdefault(v["pos"], []).append(float(v.get("value") or 0.0))
    repl = {}
    for pos, vals in by_pos.items():
        vals.sort(reverse=True)
        n = REPLACEMENT_COUNT.get(pos, 10)
        if len(vals) < n:
            # Fewer than the replacement number of players on the board: every
            # one of them is above the waiver-wire level, so treat replacement as
            # 0. This keeps VOR == raw value on a thin board (e.g. a 2-player
            # unit test) instead of collapsing every position to 0 and hiding
            # real value gaps between positions. The real 250-player board has
            # >= n players at every position, so live behaviour is unaffected.
            repl[pos] = 0.0
            continue
        repl[pos] = vals[n - 1]
    return repl


def vor(value, pos, repl):
    """Value over replacement: points above the best free alternative."""
    return float(value) - repl.get(pos, 0.0)

def log(s):
    line = datetime.datetime.now().strftime("%H:%M:%S") + " " + str(s)
    with io.open(LOG,"a",encoding="utf-8") as f:
        f.write(line+"\n")
    print(line)

def _driver_sha256():
    """Content fingerprint of this driver file (drift detection).

    Two deployed copies with different bytes hash differently, so a stale deploy
    shows up in the draft log even though the deployed copy has no .git to query.
    """
    try:
        h = hashlib.sha256()
        with open(Path(__file__).resolve(), "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:12]
    except OSError:
        return "unknown"


def log_deploy_identity():
    """Stamp which code is actually running, so a stale deploy is visible (issue #21).

    We log (a) the git SHA written next to this file by tools/deploy.ps1, and
    (b) a content hash of the file itself, which catches drift even when the
    sidecar is missing. A deploy step that copies a new driver must also refresh
    DEPLOY_SHA.txt, or the SHA will disagree with the running file.
    """
    sha_file = Path(__file__).resolve().parent / "DEPLOY_SHA.txt"
    git_sha = "unknown"
    try:
        git_sha = sha_file.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        pass
    log("DEPLOY_GIT_SHA=%s FILE_SHA256=%s" % (git_sha, _driver_sha256()))

def http_get(path):
    with urllib.request.urlopen(CDP+path,timeout=8) as r:
        return json.loads(r.read().decode())

# ---- Live value board -------------------------------------------------------
def _fp_get(path):
    url = FP_BASE + path
    req = urllib.request.Request(url, headers={
        "x-api-key": FP_API_KEY, "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())

def fetch_fp_consensus(position):
    """Pull FantasyPros consensus rankings (ECR + ADP) for one position.
    Returns a list of dicts with name/team/pos/ecr/adp (adp may be None)."""
    # FantasyPros codes defenses as DST; our board/logic use DEF internally.
    api_pos = "DST" if position == "DEF" else position
    data = _fp_get("/nfl/%d/consensus-rankings?position=%s&scoring=%s"
                   % (FP_SEASON, api_pos, FP_SCORING))
    out = []
    for p in data.get("players", []):
        name = p.get("player_name")
        if not name:
            continue
        # Use explicit None checks: `or` coalescing would treat a legitimate
        # adp/ecr of 0 (e.g. undrafted rookies, or any player the API scores 0)
        # as missing and drop the player from the live board.
        ecr = p.get("rank_ecr")
        if ecr is None:
            ecr = p.get("ecr")
        if ecr is None:
            ecr = p.get("rank")
        adp = p.get("adp")
        if adp is None:
            adp = p.get("rank_adp")
        if adp is None:
            adp = p.get("avg_adp")
        if adp is None:
            adp = p.get("adp_rank")
        out.append({"name": name, "team": p.get("player_team_id"),
                    "pos": position, "ecr": ecr, "adp": adp})
    return out

def static_board():
    """Fallback board: same universe as BOARD, ordered by static ADP.
    value = -adp so sorting desc drafts lowest ADP first (original behaviour)."""
    return {b[0]: {"name": b[0], "team": b[1], "pos": b[2], "adp": b[3],
                   "value": -b[3]} for b in BOARD}


# ---- Original board (zero third-party dependency) ----------------------------
# Built by `python cli.py original-board` from nflverse-derived data only (skill
# projections + K from kicking columns + DEF from derived team defense) and
# serialized to original_board.json. The deployed driver reads that JSON with
# stdlib json so it never imports src or calls FantasyPros. This is the DEFAULT
# board when no FP_API_KEY is configured.
def _board_list_to_map(board_list):
    """Convert the JSON board list into the dict shape choose_pick expects."""
    return {b["name"]: {"name": b["name"], "team": b["team"], "pos": b["pos"],
                        "adp": b.get("adp"), "ecr": b.get("ecr"),
                        "value": b["value"]}
            for b in board_list}


def _board_search_paths():
    """Candidate locations for original_board.json, most specific first.

    The deployed driver sits in C:\\edge-debug-profile\\ with the board beside it,
    but the README also tells you to run `py.exe driver/draft_driver.py` straight
    from the repo -- where the board actually lives in data/board/. It used to
    look ONLY next to itself, so that documented command silently fell back to
    the built-in 30-player static board. Searching both layouts means neither
    documented invocation can silently downgrade the board.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(here, "original_board.json"),                    # deploy layout
        os.path.join(here, os.pardir, "data", "board",
                     "original_board.json"),                          # repo layout
        os.path.join(os.getcwd(), "data", "board",
                     "original_board.json"),                          # repo root CWD
    ]


def load_original_board(path=None):
    """Load the original nflverse-only board from JSON. Returns the driver board
    map, or None if the file is missing/unreadable. With no `path`, the known
    locations are searched in order (see _board_search_paths)."""
    if path is None:
        for candidate in _board_search_paths():
            if os.path.exists(candidate):
                path = candidate
                break
        else:
            log("ORIGINAL_BOARD: not found in any of: %s"
                % ", ".join(_board_search_paths()))
            return None
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            board_list = json.load(f)
    except Exception as e:
        log("ORIGINAL_BOARD: load failed (%s) -> None" % repr(e))
        return None
    if not isinstance(board_list, list) or not board_list:
        log("ORIGINAL_BOARD: empty/invalid -> None")
        return None
    log("ORIGINAL_BOARD: loaded %d players from %s" % (len(board_list), path))
    return _board_list_to_map(board_list)

def _norm_name(full, team=None):
    """Normalize a full player name to the FantasyPros Real-Time ADP table key
    format: 'First Last' -> 'F. Last' (first initial + last; apostrophes/dots
    stripped, trailing generational suffix dropped). When `team` is supplied the
    key is made UNIQUE as 'F. Last|TEAM' so two players who abbreviate to the
    same 'Initial. Last' do NOT collide -- e.g. A.J. Brown and Amon-Ra St. Brown
    both render as 'A. Brown', but 'A. Brown|NE' and 'A. Brown|DET' stay distinct.
    Examples:
        _norm_name('Jahmyr Gibbs', 'Det')   -> 'J. Gibbs|DET'
        "Ja'Marr Chase", 'Cin'              -> 'J. Chase|CIN'
        'James Cook III', 'Buf'             -> 'J. Cook|BUF'
    Applied to BOTH the BOARD full names and the scraped RT rows (team parsed
    from the row's 2nd line), so lookups line up regardless of which side the
    abbreviation comes from."""
    parts = full.replace("'", "").replace(".", "").split()
    # drop a trailing generational suffix (III / II / IV / Jr / Sr)
    if parts and re.match(r"^(IV|III|II|I|Jr|SR)$", parts[-1], re.I):
        parts = parts[:-1]
    if len(parts) < 2:
        base = full
    else:
        base = parts[0][0].upper() + ". " + parts[-1]
    if team:
        return base + "|" + team.upper()
    return base

def to_display(full, team=None):
    """Convert a full board name to Yahoo's draft-room display form ('J. Burrow').
    Mirrors _norm_name's normalization so DOM searches match whatever abbreviated
    name Yahoo actually renders. Single-token names (defenses: 'Ravens') pass through."""
    parts = full.replace("'", "").replace(".", "").split()
    if parts and re.match(r"^(IV|III|II|I|Jr|SR)$", parts[-1], re.I):
        parts = parts[:-1]
    if len(parts) < 2:
        return full
    return parts[0][0].upper() + ". " + parts[-1]

# Reverse maps (built once at import) so Yahoo's abbreviated display names
# ("J. Burrow") resolve to full board names ("Joe Burrow"). _norm_name normalizes
# BOTH sides to the same 'F. Last|TEAM' key, so this also covers the (unknown)
# case where Yahoo renders the full name. Discovered 2026-08-31 via a live mock
# draft: Yahoo's roster/room shows "J. Burrow" while our board keys are "Joe Burrow",
# which left choose_pick thinking every available player was off-board.
ABBREV_TO_FULL = {_norm_name(n, t): n for (n, t, p, a) in BOARD}
ABBREV_TO_FULL_NT = {_norm_name(n, None): n for (n, t, p, a) in BOARD}
NAME_TO_TEAM = {n: t for (n, t, p, a) in BOARD}

def build_value_board(adp_map=None):
    """Live board: BOARD names annotated with FantasyPros ECR combined with ADP,
    ordered by value. ADP comes from (in priority order):
      (a) the Real-Time ADP scrape of fantasypros.com/nfl/real-time-adp/ (free,
          no key) passed in via adp_map={norm_name: adp_float}, OR
      (b) the paid FantasyPros API tier (adp field on the consensus response).
    VALUE = ADP - ECR when an ADP is available (true value: drafted later than
    the experts rank = best value); otherwise VALUE = -ECR (best-player-available
    by expert consensus; higher ECR rank = worse, so we negate).
    Players we can't match to the feed (e.g. defenses, whose feed uses full team
    names; or players beyond the free tier's per-position cap) keep their static
    ADP but are pushed far down the board (value = -(adp+1000)) so they never
    sort ABOVE a real match.
    Returns None (caller falls back to static_board) only when we have NEITHER an
    FP key (no ECR) NOR any RT ADP to build a live board from."""
    adp_map = adp_map or {}
    if not FP_API_KEY and not adp_map:
        log("VALUE_BOARD: no FP_API_KEY and no RT adp -> static BOARD")
        return None
    fp = {}          # name(lower) -> row
    fp_team = {}     # team(lower) -> row  (defenses match by team id)
    has_ecr = False
    for pos in sorted(set(b[2] for b in BOARD)):
        try:
            rows = fetch_fp_consensus(pos)
        except Exception as e:
            if not adp_map:
                log("VALUE_BOARD: fetch failed (%s) -> static BOARD" % repr(e))
                return None
            rows = []   # no ECR for this pos; RT adp (if any) still drives it
        for r in rows:
            if r["name"]:
                fp[r["name"].lower()] = r
            # Only defenses match by team id (their feed uses full team names
            # like 'Houston Texans'). Restricting fp_team to DEF rows prevents a
            # same-team kicker (e.g. Ka'imi Fairbairn / HOU) from overwriting the
            # Houston Texans DST record keyed by the same team id.
            if r.get("team") and pos == "DEF":
                fp_team[r["team"].lower()] = r
            if r.get("ecr") is not None:
                has_ecr = True
    out = {}
    live = 0
    used_rt = 0
    for (name, team, pos, adp) in BOARD:
        r = fp.get(name.lower())
        if r is None and pos == "DEF":        # feed uses full team names
            r = fp_team.get(team.lower())
        # Prefer the free RT ADP scrape (same source as ECR => consistent);
        # fall back to the paid API's adp field only if RT didn't cover it.
        # Join by team-suffixed name first, then by name-only (covers rows whose
        # team we couldn't parse or where BOARD/RT team codes differ).
        rt = None
        if adp_map:
            rt = adp_map.get(_norm_name(name, team)) or adp_map.get(_norm_name(name))
        if r and r.get("ecr") is not None:
            used_adp = rt if rt is not None else r.get("adp")
            if used_adp is not None:
                value = float(used_adp) - float(r["ecr"])
                if rt is not None:
                    used_rt += 1
            else:
                value = -float(r["ecr"])
            out[name] = {"name": name, "team": team, "pos": pos,
                         "ecr": r["ecr"], "adp": used_adp, "value": value}
            live += 1
        elif rt is not None:
            # No ECR (no FP key / all fetches failed) but we DO have the free RT
            # ADP: rank purely by ADP (lowest first) rather than discarding it.
            used_rt += 1
            out[name] = {"name": name, "team": team, "pos": pos,
                         "adp": float(rt), "value": -float(rt)}
            live += 1
        else:
            out[name] = {"name": name, "team": team, "pos": pos,
                         "adp": adp, "value": -(float(adp) + 1000.0)}
    if used_rt and has_ecr:
        mode = "ADP-ECR (FantasyPros real-time scrape)"
    elif has_ecr:
        mode = "ECR-only (free tier, BPA)"   # no ADP source => BPA by ECR
    elif used_rt:
        mode = "ADP-only (RT scrape, no ECR)"
    else:
        mode = "STATIC fallback"
    log("VALUE_BOARD: live coverage %d/%d [RT_adp=%d] [%s]"
        % (live, len(out), used_rt, mode))
    return out

def scrape_fp_realtime_adp():
    """Open the FantasyPros Real-Time ADP page in a FRESH Edge tab via CDP and
    scrape the REAL-TIME column (column index 3 of the first table) into
    {key: adp_float}, keyed by the team-suffixed normalized name ('F. Last|TEAM')
    so players that abbreviate to the same 'Initial. Last' stay distinct. FREE
    (no API key); uses the same expert pool as ECR so VALUE = ADP - ECR stays
    consistent. Returns {} on ANY failure (caller then keeps the Yahoo live patch
    / ECR-only board). The orphan tab and both sockets are ALWAYS closed (finally
    block), so a failure never leaves a dangling tab in the Edge instance running
    the live draft."""
    pws = nws = None
    new_id = None
    try:
        targets = json.loads(urllib.request.urlopen(CDP+"/json/list", timeout=8).read())
        page = next((t for t in targets if t.get("type") == "page"), None)
        if not page:
            log("RT_ADP: no page target in /json/list"); return {}
        pws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10,
                                          header={"Origin": CDP})
        pws.send(json.dumps({"id": 1, "method": "Target.enable", "params": {}}))
        # Open a dedicated tab for the RT ADP page so we never disturb the live
        # draft tab/session.
        wid = random.randint(100, 99999)
        pws.send(json.dumps({"id": wid, "method": "Target.createTarget",
                             "params": {"url": RT_ADP_URL}}))
        new_id = None
        while True:
            o = json.loads(pws.recv())
            if o.get("id") == wid:
                new_id = o.get("result", {}).get("targetId")
                break
        if not new_id:
            log("RT_ADP: createTarget returned no targetId"); return {}
        time.sleep(8)   # let the table render
        targets = json.loads(urllib.request.urlopen(CDP+"/json/list", timeout=8).read())
        # /json/list keys the target id under "id" (the "targetId" field is None
        # there), so match against that.
        ntab = next((t for t in targets if t.get("id") == new_id), None)
        if not ntab:
            log("RT_ADP: new tab not found in /json/list"); return {}
        nws = websocket.create_connection(ntab["webSocketDebuggerUrl"], timeout=10,
                                          header={"Origin": CDP})
        nws.send(json.dumps({"id": 2, "method": "Runtime.enable", "params": {}}))
        rows = ev(nws, """(function(){
          var out=[];
          var tbls=document.querySelectorAll('table');
          if(!tbls.length) return out;
          var trs=tbls[0].querySelectorAll('tr');
          for(var i=0;i<trs.length;i++){
            var tds=trs[i].querySelectorAll('td');
            if(tds.length<4) continue;                 // skip header / junk rows
            var lines=tds[1].innerText.trim().split('\\n');
            var name=lines[0];                         // 1st line = 'J. Gibbs'
            var tm=(lines[1]||'').match(/([A-Z]{2,4})/); // 2nd line = 'DET (6)'
            var team=tm?tm[1]:'';
            var adp=tds[3].innerText.trim();           // REAL-TIME column (idx 3)
            out.push([name, team, adp]);
          }
          return out;
        })()""")
        out = {}
        for name, team, adp in (rows or []):
            try:
                adp = float(adp)
            except (ValueError, TypeError):
                continue
            # Team-suffixed key keeps 'A.J. Brown|NE' and 'Amon-Ra St. Brown|DET'
            # distinct. The team-less key is a fallback for rows whose team we
            # couldn't parse (or BOARD/RT team-code mismatches), with a min-dedup
            # as a last-resort guard against same-name collisions.
            if team:
                k = _norm_name(name, team)
                if k not in out or adp < out[k]:
                    out[k] = adp
            k0 = _norm_name(name)
            if k0 not in out or adp < out[k0]:
                out[k0] = adp
        log("RT_ADP: scraped %d rows" % len(out))
        return out
    except Exception as e:
        log("RT_ADP: scrape failed (%s) -> {}" % repr(e))
        return {}
    finally:
        for sock in (nws, pws):
            if sock is not None:
                try:
                    sock.close()
                except Exception as e:
                    log("RT_ADP: socket close failed (%s)" % repr(e))
        if new_id:
            try:
                urllib.request.urlopen(CDP + "/json/close/" + new_id, timeout=5).read()
            except Exception as e:
                log("RT_ADP: tab close failed (%s)" % repr(e))

def connect():
    targets = http_get("/json/list")
    t = [x for x in targets if x.get("type")=="page"][0]
    ws = websocket.create_connection(t["webSocketDebuggerUrl"],timeout=10,header={"Origin":"http://127.0.0.1:9222"})
    ws.send(json.dumps({"id":1,"method":"Runtime.enable","params":{}}))
    ws.send(json.dumps({"id":2,"method":"Page.enable","params":{}}))
    ws.send(json.dumps({"id":3,"method":"Input.enable","params":{}}))
    return ws

def ev(ws,expr):
    wid = random.randint(100,99999)
    ws.send(json.dumps({"id":wid,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}))
    while True:
        o=json.loads(ws.recv())
        if o.get("id")==wid: return o.get("result",{}).get("result",{}).get("value")

# ---- CDP resilience (#38) ------------------------------------------------
# DOM reads can fail transiently: Yahoo may be slow to render, the websocket
# may drop a frame, or the page may be mid-navigation. Retry with exponential
# backoff before giving up, and capture a screenshot on final failure for
# post-mortem debugging.

DOM_RETRIES = 3
DOM_BACKOFF_BASE = 1.5  # seconds; doubles each retry

def _ev_retry(ws, expr, what="dom read"):
    """Call ev() with retry + exponential backoff. On final failure, capture
    a CDP screenshot for post-mortem and re-raise. Does NOT change the return
    value — this is purely a resilience wrapper around the transport."""
    last_err = None
    for attempt in range(1, DOM_RETRIES + 1):
        try:
            result = ev(ws, expr)
            if result is not None:
                return result
            # None is a valid return for some expressions (e.g. void functions);
            # only treat it as a failure for reads that expect data.
            return result
        except (websocket.WebSocketException, ConnectionError, OSError,
                json.JSONDecodeError, KeyError) as e:
            last_err = e
            wait = DOM_BACKOFF_BASE ** attempt
            log("DOM_RETRY %s attempt %d/%d failed (%s) — retrying in %.1fs"
                % (what, attempt, DOM_RETRIES, repr(e)[:80], wait))
            time.sleep(wait)
    # All retries exhausted: capture a screenshot for post-mortem, then raise.
    try:
        _cdp_screenshot(ws, what)
    except Exception:
        pass
    raise last_err  # type: ignore[misc]


def _cdp_screenshot(ws, context="failure"):
    """Capture a PNG screenshot via CDP Page.captureScreenshot and save it
    to the draft log directory. Best-effort: a screenshot failure is logged
    but never masks the original error."""
    try:
        wid = random.randint(100, 99999)
        ws.send(json.dumps({"id": wid, "method": "Page.captureScreenshot",
                            "params": {"format": "png"}}))
        deadline = time.time() + 5
        while time.time() < deadline:
            o = json.loads(ws.recv())
            if o.get("id") == wid:
                data = o.get("result", {}).get("result", {}).get("data")
                if data:
                    import base64
                    png = base64.b64decode(data)
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = os.path.join(os.path.dirname(LOG),
                                        f"cdp_fail_{context}_{ts}.png")
                    with open(path, "wb") as f:
                        f.write(png)
                    log("SCREENSHOT saved %s (%d bytes)" % (path, len(png)))
                return
    except Exception as e:
        log("SCREENSHOT failed: %s" % repr(e))


# ---- end CDP resilience (#38) --------------------------------------------

def navigate(ws,url):
    wid=random.randint(100,99999)
    ws.send(json.dumps({"id":wid,"method":"Page.navigate","params":{"url":url}}))
    time.sleep(4)

def move_to(ws,x,y,steps=None,jitter=3):
    cur=getattr(move_to,"cur",(x,y)); sx,sy=cur
    if steps is None: steps=max(8,int(math.hypot(x-sx,y-sy)/12))
    mx,my=(sx+x)/2+random.uniform(-25,25),(sy+y)/2+random.uniform(-25,25)
    for i in range(1,steps+1):
        tt=i/steps
        bx=(1-tt)**2*sx+2*(1-tt)*tt*mx+tt**2*x
        by=(1-tt)**2*sy+2*(1-tt)*tt*my+tt**2*y
        jx=bx+random.uniform(-jitter,jitter); jy=by+random.uniform(-jitter,jitter)
        ws.send(json.dumps({"id":0,"method":"Input.dispatchMouseEvent","params":{"type":"mouseMoved","x":round(jx),"y":round(jy)}}))
        time.sleep(random.uniform(0.004,0.016))
    move_to.cur=(x,y)

def click_at(ws,x,y,button="left"):
    move_to(ws,x,y); time.sleep(random.uniform(0.05,0.2))
    ws.send(json.dumps({"id":0,"method":"Input.dispatchMouseEvent","params":{"type":"mousePressed","x":x,"y":y,"button":button,"clickCount":1}}))
    time.sleep(random.uniform(0.04,0.12))
    ws.send(json.dumps({"id":0,"method":"Input.dispatchMouseEvent","params":{"type":"mouseReleased","x":x,"y":y,"button":button,"clickCount":1}}))
    time.sleep(random.uniform(0.1,0.4))

_ADP_RE = re.compile(r"ADP\s*[:#]?\s*(\d{1,3}(?:\.\d+)?)", re.I)

def parse_adp(text):
    """Extract a Yahoo Average Draft Position from a draft-row's text.
    Yahoo shows ADP with an explicit 'ADP' label, so we only match that label
    (avoids mistaking a jersey number for ADP). Returns float or None."""
    m = _ADP_RE.search(text or "")
    return float(m.group(1)) if m else None

def read_available(ws):
    # Name-based scan (Yahoo player rows hold the name in a cell, NOT inside the
    # /nfl/players/ anchor which only wraps an icon). Return [name, row_text] so
    # the caller can also pull Yahoo ADP (Average Draft Position) from the row.
    return _ev_retry(ws,r"""(function(){
      var out=[];
      var seen={};
      var rows=document.querySelectorAll('tr, li');
      for(var i=0;i<rows.length;i++){
        var t=rows[i].innerText.replace(/\s+/g,' ').trim();
        // Yahoo renders names abbreviated ("J. Burrow", "A.J. Brown", "C. McCaffrey")
        // AND full ("Joe Burrow"). Capture the name greedily-but-minimally up to the
        // "TEAM - POS" code -- the only reliably-structured token -- so BOTH forms
        // survive intact. The old pattern chopped "J. Burrow" to "Burrow" and
        // "McCaffrey" to "Caffrey", which broke downstream board matching (issue #32).
        // An optional leading draft-rank ("12. ") is skipped; defenses ("Ravens") pass.
        var m=t.match(/^(?:\d+\.?\s*)?(.*?)\s+([A-Za-z]{2,4})\s*-\s*(QB|RB|WR|TE|K|DEF|DST)/);
        if(m && !seen[m[1]]){ seen[m[1]]=1; out.push([m[1], m[2], m[3], t]); }
      }
      return out.slice(0,40);
    })()""")


def search_player(ws, name):
    """Bring a specific player into the Yahoo draft search box and return the
    (now-filtered) row, so a player below read_available()'s first-40 virtualized
    window is still selectable (issue #23). Returns [name, code, pos, text] or None
    on any failure; the caller then proceeds with the plain 40-row list."""
    q = name.replace("'", "").strip()
    try:
        ev(ws, """(function(q){
          var inp=document.querySelector('input[type=search]')
               || document.querySelector('input[placeholder*="earch" i]')
               || document.querySelector('.draft-search input');
          if(!inp) return;
          var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
          inp.focus();
          setter.call(inp,''); inp.dispatchEvent(new Event('input',{bubbles:true}));
          setter.call(inp,q); inp.dispatchEvent(new Event('input',{bubbles:true}));
        })(""" + json.dumps(q) + ")")
        time.sleep(1.0)
        rows = read_available(ws)
        for r in rows:
            if r[0].lower() == q.lower() or q.lower() in r[0].lower():
                return r
        return rows[0] if rows else None
    except Exception as e:
        log("SEARCH_PLAYER_FAIL " + name + " " + repr(e))
        return None

def normalize_available(raw, def_map=None):
    """Convert read_available() rows ([name, code, pos, text]) into the form
    choose_pick expects. Team defenses are keyed by their short BOARD name
    (e.g. 'LAR' -> 'Rams') so the forced DEF pick can match them; a one-token or
    city-prefixed Yahoo DEF label such as 'Rams LAR - DEF' / 'Los Angeles Rams
    LAR - DEF' would otherwise never equal the BOARD key 'Rams'.

    `def_map` is the team-code -> short-name map to use. It MUST be derived from
    the ACTIVE board, not the static BOARD tuple -- otherwise defenses that only
    exist on the original nflverse board (BAL/CHI/KC/LAC/TB) can never resolve.

    It is layered ON TOP of the static map rather than replacing it, so the two
    failure modes cancel: a code missing from the active board still resolves via
    the static tuple, and a board with no DEF rows at all does not silently
    degrade to an empty map (an empty dict is falsy but not None, which would
    otherwise defeat the fallback entirely).

    Returns (names, adp_map, pos_map):
      names    - normalized names in Yahoo's display order
      adp_map  - lowercased name -> Yahoo ADP parsed from the row text
      pos_map  - lowercased name -> position Yahoo reported, so the off-board
                 fallback in choose_pick can respect slot needs
    """
    merged_map = dict(DEF_CODE_TO_NAME)
    if def_map:
        merged_map.update(def_map)
    def_map = merged_map
    names, adp_map, pos_map = [], {}, {}
    for row in raw:
        # Re-extract code/pos from the row text rather than trusting the exact field
        # ordering returned by read_available()'s JS push (it omits the position group).
        text = (list(row) + [None, None, None, None])[3]
        name = (list(row) + [None, None, None, None])[0]
        m = re.search(r"\b([A-Za-z]{2,4})\s*-\s*(QB|RB|WR|TE|K|DEF|DST)", text or "")
        code = m.group(1) if m else None
        pos = m.group(2).upper() if m else None
        if pos in ("DEF", "DST"):
            name = def_map.get((code or "").upper(), name)
            pos = "DEF"
        else:
            # Yahoo renders names abbreviated ("J. Burrow"); map them back to the full
            # board key ("Joe Burrow") so choose_pick's board matching works. The team
            # code disambiguates collisions (A.J. Brown NE vs Amon-Ra St. Brown DET).
            full = ABBREV_TO_FULL.get(_norm_name(name, code))
            if not full:
                full = ABBREV_TO_FULL_NT.get(_norm_name(name, None), name)
            if full:
                name = full
        names.append(name)
        if pos:
            pos_map[name.lower()] = pos
        a = parse_adp(text)
        if a is not None:
            adp_map[name.lower()] = a
    return names, adp_map, pos_map

def is_my_pick(ws):
    return _ev_retry(ws,"""(function(){
      var b=document.body?document.body.innerText.toUpperCase():'';
      if(/YOUR TURN|ON THE CLOCK/.test(b)) return true;
      var btns=document.querySelectorAll('button');
      for(var i=0;i<btns.length;i++){ if(/draft/i.test(btns[i].textContent)&&!btns[i].disabled) return true; }
      return false;
    })()""")


def read_pick_number(ws):
    """Best-effort read of the current overall pick number from the draft page.

    Returns int, or None if it can't be parsed. Used only to guard against a
    latched/stale is_my_pick() replaying the same turn (issue #26); a None result
    disables the guard rather than blocking picks."""
    try:
        body = ev(ws, "document.body ? document.body.innerText : ''")
    except Exception:
        return None
    if not body:
        return None
    # Prefer an explicit "Overall Pick N of M" / "Pick N of M".
    m = re.search(r"Overall\s+Pick\s+(\d+)", body, re.I)
    if not m:
        m = re.search(r"Pick\s+(\d+)\s+of\s+\d+", body, re.I)
    if not m:
        m = re.search(r"Round\s+\d+,\s*Pick\s+(\d+)", body, re.I)
    return int(m.group(1)) if m else None


def _pick_number_changed(pn, last_pick_no):
    """Guard against a stale/latched is_my_pick() acting twice on one turn.

    Returns True (safe to act) when the page pick number is unreadable (pn is
    None) or has advanced since the last pick we made. A repeated turn yields
    only one pick. See issue #26."""
    if pn is None:
        return True
    return pn != last_pick_no

def _crowd_reach(c, round_num):
    """True when the crowd drafts this player far later than our board ranks him.

    League ADP (from the board's 'adp' field, merged from the live Yahoo league
    scrape) more than ADP_WINDOW picks beyond the current round's window means
    our projection is a heavy outlier vs. our own league-mates -- usually stale
    value (injury/role news we missed). Skipped UNLESS an anchor forces the slot
    (step 1) or nothing else is available (step 4). Players without a known ADP
    (most of the board) always pass.
    """
    adp = c.get("adp")
    if adp is None:
        return False
    exp_pick = (round_num - 1) * TEAMS + TEAMS  # end of the current round window
    return float(adp) - exp_pick > ADP_WINDOW


def _fallback_pick(available, board, drafted, round_num, adp_map, pos_map):
    """Last-resort pick from players NOT on our board, so we always fill the slot.

    Our board is finite; in a 10-team x 15-round draft it can be exhausted before
    the later rounds. Previously choose_pick returned None in that case, run_draft
    logged NO_VALID_PICK and looped, and Yahoo's clock expired -- auto-drafting the
    rest of our team including the K and DEF slots (issue #11).

    Yahoo's own board order (its ADP column) is a sane default. We prefer a slot we
    still need; failing that, the lowest available ADP. Returns None only when
    `available` is genuinely empty.
    """
    board_names = {v["name"].lower() for v in board.values()}
    off_board = [n for n in available if n.lower() not in board_names]
    if not off_board:
        return None

    def rank(name):
        # Unknown ADP sorts last, but still ahead of drafting nobody.
        return adp_map.get(name.lower(), 9999.0)

    def pos_of(name):
        return (pos_map.get(name.lower()) or "").upper()

    def timing_ok(pos):
        if pos in ("K", "DEF") and round_num < (TOTAL_ROUNDS - K_DEF_LAST_ROUNDS + 1):
            return False
        if pos == "QB" and round_num < MY_PICK_ROUNDS_QB:
            return False
        return True

    ordered = sorted(off_board, key=rank)

    # Prefer an unfilled required slot whose timing window is open.
    for name in ordered:
        pos = pos_of(name)
        if pos in REQUIRED and drafted.get(pos, 0) < REQUIRED[pos] and timing_ok(pos):
            log("PICK_FALLBACK round=" + str(round_num) + " need " + pos
                + " -> " + name + " (off-board, adp=" + str(adp_map.get(name.lower())) + ")")
            return (name, None, pos, adp_map.get(name.lower()) or 0)

    # Otherwise best available by Yahoo ADP, still respecting the timing windows.
    for name in ordered:
        pos = pos_of(name)
        if timing_ok(pos):
            log("PICK_FALLBACK round=" + str(round_num) + " best-available -> " + name
                + " (off-board, adp=" + str(adp_map.get(name.lower())) + ")")
            return (name, None, pos or None, adp_map.get(name.lower()) or 0)

    # Only timing-guarded names remain (e.g. a kicker in round 5). We deliberately
    # do NOT override the guards here: Yahoo's auto-draft picks from its pre-rank,
    # which beats spending an early pick on a K/DEF. In the late rounds -- the case
    # this fallback exists for -- the K/DEF window is open anyway, so real
    # exhaustion still resolves.
    log("PICK_FALLBACK round=" + str(round_num) + " none available within timing guards")
    return None


def choose_pick(available, drafted, round_num, board, adp_map=None, pos_map=None):
    """Position-target-aware pick driven by a value board.

    `board` is a dict name -> {name, team, pos, adp, value, ecr?}. Candidates are
    the board entries whose name is still available, sorted by effective VALUE
    desc:
      - If a live Yahoo ADP is known for the player AND we have a FantasyPros ECR,
        effective VALUE = Yahoo_ADP - ECR (true value: drafted later than experts
        rank = best value).
      - Otherwise fall back to the board's precomputed value (ECR-based, or
        ADP-based if a paid FantasyPros tier supplied ADP).
    1) If a REQUIRED slot is still unfilled AND we're at/past its anchor
       deadline (ANCHOR_BY_ROUND), force the highest-value available player at
       that position.
    2) Otherwise pick the highest-value available player respecting timing guards.
    3) Fallback: best available ignoring need (still respect timing) -- bench.
    4) Ignore the reach guard, keep the timing guards.
    5) Off-board fallback: pick from players Yahoo shows but our board does not
       know, so an exhausted board degrades instead of returning None (see
       _fallback_pick and issue #11).

    `pos_map` (lowercased name -> position, from normalize_available) is only used
    by step 5, for players who are not on our board at all."""
    adp_map = adp_map or {}
    pos_map = pos_map or {}
    avail_lower = {n.lower() for n in available}
    repl = replacement_values(board)

    scored = []
    for v in board.values():
        if v["name"].lower() not in avail_lower:
            continue
        ecr = v.get("ecr")
        ya = adp_map.get(v["name"].lower()) if ecr is not None else None
        if ecr is not None and ya is not None:
            # Live market path: Yahoo ADP - FantasyPros ECR. Both are RANKS, so
            # this is already comparable across positions. Do NOT VOR it -- VOR
            # is a correction for projected POINTS, and applying it to rank
            # differences would be meaningless.
            eff = float(ya) - float(ecr)
        else:
            # Projection path: convert raw points to value over replacement.
            # Without this a 195-point TE outranks every remaining WR and the
            # bot drafts four tight ends and no quarterback (issues #19/#20).
            eff = vor(v.get("value", 0.0), v["pos"], repl)
        scored.append((eff, v))

    # 10-team positional-scarcity soft premium, scaled to the value spread
    # actually in play so it means the same thing on either board. While we
    # still NEED a scarce position, lift it so the crowd's RB inflation can't
    # price us out before the anchor deadline forces the slot anyway.
    spread = {}
    for eff, v in scored:
        lo, hi = spread.get(v["pos"], (eff, eff))
        spread[v["pos"]] = (min(lo, eff), max(hi, eff))
    adjusted = []
    for eff, v in scored:
        need = REQUIRED.get(v["pos"], 0) - drafted.get(v["pos"], 0)
        if need > 0 and v["pos"] in SCARCITY_FRACTION:
            lo, hi = spread[v["pos"]]
            eff += SCARCITY_FRACTION[v["pos"]] * (hi - lo)
        adjusted.append((eff, v))
    adjusted.sort(key=lambda x: x[0], reverse=True)
    cands = [v for _, v in adjusted]

    # 1) forced fills for required slots past their anchor deadline
    for pos, need in REQUIRED.items():
        have = drafted.get(pos, 0)
        if have < need and round_num >= ANCHOR_BY_ROUND[pos][have]:
            for c in cands:
                if c["pos"] == pos:
                    return (c["name"], c.get("team"), pos, c.get("adp") or 0)

    # 2) highest value available, with timing guards + need awareness
    for c in cands:
        pos = c["pos"]
        if pos in ("K", "DEF") and round_num < (TOTAL_ROUNDS - K_DEF_LAST_ROUNDS + 1):
            continue
        if pos == "QB" and round_num < MY_PICK_ROUNDS_QB:
            continue
        if pos in REQUIRED and drafted.get(pos, 0) >= REQUIRED[pos]:
            continue
        if _crowd_reach(c, round_num):
            log("REACH_GUARD skip %s (board round %d, league ADP %s)"
                % (c["name"], round_num, str(c.get("adp"))))
            continue
        return (c["name"], c.get("team"), pos, c.get("adp") or 0)

    # 3) bench / fallback: every REQUIRED slot is already filled (or still
    #    timing-guarded), so draft the best available player by value to fill
    #    the bench. We intentionally do NOT skip already-filled positions here
    #    -- a 2nd RB/WR on the bench is fine. Still respect the K/DEF-last and
    #    QB-round timing guards so we don't reach for K/DEF before their window,
    #    and BENCH_CAP so we don't end up rostering a 4th QB over a WR3.
    for c in cands:
        pos = c["pos"]
        if pos in ("K", "DEF") and round_num < (TOTAL_ROUNDS - K_DEF_LAST_ROUNDS + 1):
            continue
        if pos == "QB" and round_num < MY_PICK_ROUNDS_QB:
            continue
        cap = BENCH_CAP.get(pos)
        if cap is not None and drafted.get(pos, 0) >= cap:
            continue
        if _crowd_reach(c, round_num):
            log("REACH_GUARD skip %s (bench path, league ADP %s)"
                % (c["name"], str(c.get("adp"))))
            continue
        return (c["name"], c.get("team"), pos, c.get("adp") or 0)

    # 4) last resort: ignore the reach guard (keep timing guards) so a board
    #    where every candidate trips the guard still yields a pick instead of
    #    timing out. Anchors (step 1) already bypassed the guard by design.
    for c in cands:
        pos = c["pos"]
        if pos in ("K", "DEF") and round_num < (TOTAL_ROUNDS - K_DEF_LAST_ROUNDS + 1):
            continue
        if pos == "QB" and round_num < MY_PICK_ROUNDS_QB:
            continue
        return (c["name"], c.get("team"), pos, c.get("adp") or 0)

    # 5) off-board fallback: no board candidate survives (board exhausted, or
    #    every candidate tripped a guard). Draft a player Yahoo is showing rather
    #    than returning None, which would stall until Yahoo auto-drafts our slot.
    return _fallback_pick(available, board, drafted, round_num,
                          adp_map or {}, pos_map or {})

def click_player(ws,name):
    # Robust name-based row finder (Yahoo holds the name in a cell, not in the
    # /nfl/players/ anchor). Climb to the nearest TR/LI, scroll into view, click center.
    # `name` is the full board name ("Joe Burrow") but Yahoo renders it abbreviated
    # ("J. Burrow"); try BOTH so we match whatever the room actually displays.
    disp = to_display(name, NAME_TO_TEAM.get(name))
    candidates = [name, disp]
    box = None
    for cand in candidates:
        box = ev(ws,"""(function(){
      var name=%r;
      var all=document.querySelectorAll('*');
      for(var i=0;i<all.length;i++){
        if(all[i].children.length<4 && all[i].textContent.indexOf(name)>=0){
          var el=all[i];
          while(el && el.parentElement && el.tagName!=='TR' && el.tagName!=='LI'){ el=el.parentElement; }
          if(el && (el.tagName==='TR'||el.tagName==='LI')){
            el.scrollIntoView({block:'center'});
            var r=el.getBoundingClientRect();
            return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};
          }
        }
      }
      return null;
    })()"""%cand)
        if box:
            break
    if not box: return False
    click_at(ws,int(box["x"]),int(box["y"]))
    time.sleep(random.uniform(0.3,0.8))
    # Click the DRAFT button inside the chosen player's own row, NOT the first
    # enabled draft button on the page. The displayed list is sorted by Yahoo
    # (ADP / default board order), so the value pick we chose is usually NOT the
    # top row -- clicking the top button would draft the wrong player. Scope the
    # button search to the row that holds the chosen name.
    btn = None
    for cand in candidates:
        btn = ev(ws,"""(function(){
      var name=%r;
      var all=document.querySelectorAll('*');
      var row=null;
      for(var i=0;i<all.length;i++){
        if(all[i].children.length<4 && all[i].textContent.indexOf(name)>=0){
          var el=all[i];
          while(el && el.parentElement && el.tagName!=='TR' && el.tagName!=='LI'){ el=el.parentElement; }
          if(el && (el.tagName==='TR'||el.tagName==='LI')){ row=el; break; }
        }
      }
      if(row){
        var bs=row.querySelectorAll('button');
        for(var j=0;j<bs.length;j++){
          if(/draft|select|confirm/i.test(bs[j].textContent) && !bs[j].disabled){
            var r=bs[j].getBoundingClientRect();
            return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};
          }
        }
      }
      return null; })()"""%cand)
        if btn:
            break
    if btn:
        click_at(ws,int(btn["x"]),int(btn["y"]))
        return True
    return False

def verify_session(ws):
    """Best-effort pre-draft guard. Confirms we're on the FD nation (league
    1329011) / Doge draft before any click. Returns False only on a CLEAR
    mismatch (login wall or a different league) so the bot aborts into Yahoo's
    default auto-draft rather than drafting the wrong room. Inconclusive reads
    return True so a page-layout change can't disable the bot."""
    try:
        body = ev(ws, "document.body?document.body.innerText:''") or ""
    except Exception as e:
        log("VERIFY: body read failed (%s) -> proceed" % repr(e))
        return True
    low = body.lower()
    if "sign in" in low or "log in" in low or "please log in" in low:
        log("VERIFY: login wall detected -> abort")
        return False
    if "1329011" not in body and "fd nation" not in low and "fantasy" in low:
        log("VERIFY: FD nation / league 1329011 not detected -> abort")
        return False
    return True


def _confirm_pick(ws, name, timeout=8):
    """Best-effort confirmation that a pick registered: wait (bounded) for our
    turn to end (is_my_pick False) and the player to leave the available list.
    Returns True if observed, False on timeout. Never raises; a detection
    failure yields False and the caller proceeds (transparent log)."""
    deadline = time.time() + timeout
    low = name.lower()
    disp = to_display(name, NAME_TO_TEAM.get(name)).lower()
    while time.time() < deadline:
        try:
            if not is_my_pick(ws):
                av = read_available(ws)
                names = [r[0].lower() for r in av]
                if low not in names and disp not in names:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def run_draft():
    log("DRAFT_DRIVER_START team="+TEAM_ID)
    log_deploy_identity()
    ws=connect()
    navigate(ws,"https://football.fantasysports.yahoo.com/f1/%s/draft"%LEAGUE)
    # Guard: confirm we're on the FD nation / Doge draft before any click. A clear
    # mismatch (login wall, wrong league) aborts so we fall back to Yahoo's default
    # auto-draft instead of drafting into the wrong room.
    if not verify_session(ws):
        log("DRAFT_DRIVER_ABORT: session verification failed (see VERIFY log)")
        return
    # Engine selection. The original nflverse-built board (self-built, no
    # third-party dependency) is the DEFAULT draft engine. FantasyPros is an
    # OPT-IN legacy overlay enabled ONLY by an explicit DRAFT_ENGINE=fantasypros
    # env var -- the mere presence of FP_API_KEY no longer switches engines
    # (it used to, which silently overrode the original method whenever a .env
    # carrying the key was on the working path). User mandate: FD nation drafts
    # from the original board.
    engine = (os.environ.get("DRAFT_ENGINE") or "original").strip().lower()
    if engine == "fantasypros" and FP_API_KEY:
        rt_adp = scrape_fp_realtime_adp()
        vb = build_value_board(adp_map=rt_adp)
        board = vb if vb else static_board()
        log("ADP_SOURCE=" + ("FANTASYPROS_REALTIME" if rt_adp else "NONE"))
        log("BOARD_MODE=" + ("LIVE(FantasyPros)" if vb else "STATIC"))
    else:
        ob = load_original_board()
        if ob is not None:
            board = ob
            log("BOARD_MODE=ORIGINAL(nflverse)")
        else:
            board = static_board()
            log("BOARD_MODE=STATIC (no original board JSON)")
        if engine == "fantasypros" and not FP_API_KEY:
            log("ENGINE_OVERRIDE_IGNORED: DRAFT_ENGINE=fantasypros set but FP_API_KEY missing -> original board used")
    # Rebuild the DEF name map from the ACTIVE board so any defense it includes
    # (keyed by its team code) resolves when Yahoo shows 'CODE - DEF'.
    #
    # This MUST be threaded explicitly into normalize_available(). A previous
    # version assigned to the bare name here, which (with no `global` statement)
    # created a local that nothing ever read -- leaving normalize_available() on
    # the stale map built from the static BOARD, so BAL/CHI/KC/LAC/TB could never
    # be drafted. See issue #10.
    def_map = {v["team"].upper(): v["name"]
               for v in board.values() if v.get("pos") == "DEF"}
    drafted={}
    round_num=1
    picks_made=0
    last_pick_no = None  # overall pick number of our last successful pick (issue #26 guard)
    deadline=time.time()+ (3*3600)
    while time.time()<deadline and picks_made<TOTAL_ROUNDS:
        try:
            if is_my_pick(ws):
                # Guard against a latched/stale "your turn" indicator (issue #26):
                # only act when the overall pick number has actually advanced since
                # our last pick. A repeated number means we already acted this turn.
                pn = read_pick_number(ws)
                if not _pick_number_changed(pn, last_pick_no):
                    log("PICK_GUARD skip: pick number unchanged (%s)" % pn)
                    time.sleep(2)
                    continue
                # read_available returns [name, code, pos, text]; normalize maps
                # DEF codes to ACTIVE-board keys and parses live Yahoo ADP per row.
                raw_rows = read_available(ws)
                available, adp_map, pos_map = normalize_available(raw_rows, def_map=def_map)
                log("MY_PICK round="+str(round_num)+" avail="+str(len(available))
                    + " yahoo_adp="+str(len(adp_map)))
                pick=choose_pick(available,drafted,round_num,board,
                                 adp_map=adp_map,pos_map=pos_map)
                if pick:
                    name,team,pos,adp=pick
                    # Issue #23: read_available() only virtualizes the first ~40
                    # DOM rows, so a high-value target Yahoo ranks deeper than row
                    # 40 never appears in the 40-row window and is unclickable. If
                    # the chosen name isn't in the current window, ask Yahoo to
                    # search for it -- which filters the DOM down to that player --
                    # before we click, so deep targets are still selectable.
                    if name.lower() not in {n.lower() for n in available}:
                        log("OFF_WINDOW_SEARCH for " + name)
                        search_player(ws, name)
                    ok=click_player(ws,name)
                    if ok:
                        # Best-effort confirmation: wait (bounded) for the pick to
                        # register before advancing local state, so a missed click
                        # doesn't silently diverge our roster from Yahoo's. Never
                        # blocks past the timeout; on uncertainty we proceed (logged).
                        if _confirm_pick(ws, name):
                            log("PICK_CONFIRMED round="+str(round_num)+" "+name)
                        else:
                            log("PICK_CONFIRM_TIMEOUT round="+str(round_num)+" "+name+" (proceeding)")
                        drafted[pos]=drafted.get(pos,0)+1
                        picks_made+=1
                        last_pick_no = pn  # record so a stale indicator can't replay this turn
                        log("PICKED round="+str(round_num)+" "+name+" ("+pos+") ADP="+str(adp))
                        round_num+=1
                        time.sleep(random.uniform(1.5,3.0))
                    else:
                        log("PICK_CLICK_FAILED "+str(name))
                else:
                    # choose_pick returned None (board exhausted / only timing-guarded
                    # names remain). Don't spin: let the 1-min clock expire and Yahoo
                    # auto-draft our slot. The pick-number guard above also prevents
                    # re-entering this branch on a stale "your turn" indicator. See #26.
                    log("NO_VALID_PICK round="+str(round_num)+" (yielding to auto-draft)")
            else:
                time.sleep(random.uniform(2,5))
        except Exception as e:
            log("ERR "+repr(e)); time.sleep(5)
    log("DRAFT_DRIVER_DONE picks="+str(picks_made))

if __name__=="__main__":
    run_draft()
