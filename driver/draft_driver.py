"""
FD nation (league 1329011) LIVE DRAFT DRIVER for team #2 (Doge)
Runs against Edge on ws://127.0.0.1:9222 (launched with --remote-allow-origins=*).
Strategy: position-target-aware board picking with guardrails.
Guarantees a legal lineup: required slots (QB,2RB,2WR,TE,K,DEF) filled by
their deadlines, bench (6 BN) filled with best available afterwards.
All decisions logged to C:\edge-debug-profile\draft_log.txt
"""
import json, os, re, urllib.request, websocket, time, random, math, sys, io, datetime

CDP = "http://127.0.0.1:9222"
LEAGUE = "1329011"
TEAM_ID = "2"
LOG = r"C:\edge-debug-profile\draft_log.txt"
TOTAL_ROUNDS = 15
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
    ("Brock Bowers","LV","TE",21.1),("Nico Collins","Hou","WR",22.2),
    ("George Pickens","Dal","WR",22.4),("A.J. Brown","NE","WR",25.0),
    ("Trey McBride","Ari","TE",25.4),("Travis Kelce","KC","TE",35.0),("George Kittle","SF","TE",40.0),("Sam LaPorta","Det","TE",45.0),("T.J. Hockenson","Min","TE",55.0),("Mark Andrews","Bal","TE",70.0),("Kyle Pitts","Atl","TE",80.0),("Jeremiyah Love","Ari","RB",27.2),
    ("DeVonta Smith","Phi","WR",29.4),("Kyren Williams","LAR","RB",29.6),
    ("Josh Jacobs","GB","RB",32.8),("Chris Olave","NO","WR",34.0),
    # K tier (draft only last rounds)
    ("Brandon Aubrey","Dal","K",85.0),("Ka'imi Fairbairn","Hou","K",119.0),
    ("Cameron Dicker","LAC","K",123.0),("Jason Myers","Sea","K",124.0),
    ("Cam Little","Jax","K",129.0),("Harrison Butker","KC","K",115.0),("Justin Tucker","Bal","K",135.0),
    # DEF tier (draft only last rounds)
    ("Rams","LAR","DEF",89.0),("Texans","Hou","DEF",93.0),
    ("Broncos","Den","DEF",101.0),("Seahawks","Sea","DEF",107.0),
    ("Eagles","Phi","DEF",123.0),("Patriots","NE","DEF",127.0),("Bills","Buf","DEF",115.0),("49ers","SF","DEF",120.0),
]

# Required starting slots (filled by deadline); bench fills the rest.
REQUIRED = {"QB":1, "RB":2, "WR":2, "TE":1, "K":1, "DEF":1}

# Anchor schedule: by which round the Nth still-needed player at POS must be
# taken (forced if still missing). Tuned for a 12-team league where the RB/TE
# wells run dry fast: lock 2 RBs by round 5, 2 WRs by round 9, TE by 7, etc.
ANCHOR_BY_ROUND = {
    "RB":  [3, 5],     # 1st RB by R3, 2nd RB by R5
    "WR":  [5, 9],     # 1st WR by R5, 2nd WR by R9
    "TE":  [7],        # TE by R7
    "QB":  [10],       # QB by R10
    "K":   [14],       # K/DEF in last 2 rounds
    "DEF": [14],
}

# Positional-scarcity soft premium. In a 12-team league the crowd OVER-drafts
# RBs (low Yahoo ADP), so VALUE = Yahoo_ADP - ECR scores good RBs NEGATIVE and
# would let the bot skip them for "higher-value" WRs -- then the RB well runs
# dry. While we still NEED a scarce position, add this premium to its effective
# value so the bot anchors it early. The anchor schedule above is the hard
# guarantee; this premium just biases close calls toward scarce positions.
SCARCITY_BONUS = {"RB": 8.0}

def log(s):
    line = datetime.datetime.now().strftime("%H:%M:%S") + " " + str(s)
    with io.open(LOG,"a",encoding="utf-8") as f:
        f.write(line+"\n")
    print(line)

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

def build_value_board():
    """Live board: BOARD names annotated with FantasyPros ECR (+ADP if the key's
    plan exposes it), ordered by value:
      - ADP available (paid tier): VALUE = ADP - ECR (true value: drafted later
        than experts rank = best value).
      - ECR only (free tier):      VALUE = -ECR (best-player-available by expert
        consensus; higher ECR rank = worse, so we negate).
    Players we can't match to the feed (e.g. defenses, whose feed uses full team
    names; or players beyond the free tier's 10-per-position cap) keep their
    static ADP but are pushed far down the board (value = -(adp+1000)) so they
    never sort ABOVE a real match.
    Returns None if no key / fetch fails, so the caller falls back to
    static_board()."""
    if not FP_API_KEY:
        log("VALUE_BOARD: no FP_API_KEY -> static BOARD")
        return None
    fp = {}          # name(lower) -> row
    fp_team = {}     # team(lower) -> row  (defenses match by team id)
    has_adp = False
    for pos in sorted(set(b[2] for b in BOARD)):
        try:
            rows = fetch_fp_consensus(pos)
        except Exception as e:
            log("VALUE_BOARD: fetch failed (%s) -> static BOARD" % repr(e))
            return None
        for r in rows:
            if r["name"]:
                fp[r["name"].lower()] = r
            if r.get("team"):
                fp_team[r["team"].lower()] = r
            if r.get("adp") is not None:
                has_adp = True
    out = {}
    live = 0
    for (name, team, pos, adp) in BOARD:
        r = fp.get(name.lower())
        if r is None and pos == "DEF":        # feed uses full team names
            r = fp_team.get(team.lower())
        if r and r.get("ecr") is not None:
            if r.get("adp") is not None:
                value = float(r["adp"]) - float(r["ecr"])
            else:
                value = -float(r["ecr"])
            out[name] = {"name": name, "team": team, "pos": pos,
                         "ecr": r["ecr"], "adp": r.get("adp"), "value": value}
            live += 1
        else:
            out[name] = {"name": name, "team": team, "pos": pos,
                         "adp": adp, "value": -(float(adp) + 1000.0)}
    mode = "ADP-ECR (paid tier)" if has_adp else "ECR-only (free tier, BPA)"
    log("VALUE_BOARD: live coverage %d/%d [%s]" % (live, len(out), mode))
    return out

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
    return ev(ws,"""(function(){
      var out=[];
      var seen={};
      var rows=document.querySelectorAll('tr, li');
      for(var i=0;i<rows.length;i++){
        var t=rows[i].innerText.replace(/\\s+/g,' ').trim();
        // player name pattern: "First Last" followed by "TEAM - POS"
        var m=t.match(/([A-Z][a-z]+(?:['’]\\w+)?\\.?[ -][A-Z][a-z]+(?:['’]\\w+)?(?:[ -][A-Z][a-z]+)?)\\s+(?:[A-Z]{2,4}\\s*-\\s*(?:QB|RB|WR|TE|K|DEF|DST))/);
        if(m && !seen[m[1]]){ seen[m[1]]=1; out.push([m[1], t]); }
      }
      return out.slice(0,40);
    })()""")

def is_my_pick(ws):
    return ev(ws,"""(function(){
      var b=document.body?document.body.innerText.toUpperCase():'';
      if(/YOUR TURN|ON THE CLOCK/.test(b)) return true;
      var btns=document.querySelectorAll('button');
      for(var i=0;i<btns.length;i++){ if(/draft/i.test(btns[i].textContent)&&!btns[i].disabled) return true; }
      return false;
    })()""")

def choose_pick(available, drafted, round_num, board, adp_map=None):
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
    3) Fallback: best available ignoring need (still respect timing)."""
    adp_map = adp_map or {}
    avail_lower = {n.lower() for n in available}
    scored = []
    for v in board.values():
        if v["name"].lower() not in avail_lower:
            continue
        eff = v.get("value", 0.0)
        ecr = v.get("ecr")
        if ecr is not None:
            ya = adp_map.get(v["name"].lower())
            if ya is not None:
                eff = float(ya) - float(ecr)   # Yahoo ADP - FantasyPros ECR
        # 12-team positional-scarcity soft premium: while we still NEED a scarce
        # position, lift its effective value so the crowd's RB inflation can't
        # price us out of the position before the anchor deadline forces it.
        need = REQUIRED.get(v["pos"], 0) - drafted.get(v["pos"], 0)
        if need > 0 and v["pos"] in SCARCITY_BONUS:
            eff += SCARCITY_BONUS[v["pos"]]
        scored.append((eff, v))
    scored.sort(key=lambda x: x[0], reverse=True)
    cands = [v for _, v in scored]

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
        return (c["name"], c.get("team"), pos, c.get("adp") or 0)

    # 3) fallback: best available by value ignoring need (still respect timing)
    for c in cands:
        pos = c["pos"]
        if pos in ("K", "DEF") and round_num < (TOTAL_ROUNDS - K_DEF_LAST_ROUNDS + 1):
            continue
        if pos == "QB" and round_num < MY_PICK_ROUNDS_QB:
            continue
        return (c["name"], c.get("team"), pos, c.get("adp") or 0)
    return None

def click_player(ws,name):
    # Robust name-based row finder (Yahoo holds the name in a cell, not in the
    # /nfl/players/ anchor). Climb to the nearest TR/LI, scroll into view, click center.
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
    })()"""%name)
    if not box: return False
    click_at(ws,int(box["x"]),int(box["y"]))
    time.sleep(random.uniform(0.3,0.8))
    btn = ev(ws,"""(function(){
      var bs=document.querySelectorAll('button');
      for(var i=0;i<bs.length;i++){ if(/draft|select|confirm/i.test(bs[i].textContent)&&!bs[i].disabled){var r=bs[i].getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};} }
      return null; })()""")
    if btn:
        click_at(ws,int(btn["x"]),int(btn["y"]))
        return True
    return False

def run_draft():
    log("DRAFT_DRIVER_START team="+TEAM_ID)
    ws=connect()
    navigate(ws,"https://football.fantasysports.yahoo.com/f1/%s/draft"%LEAGUE)
    # Build the value board once: live (FantasyPros) if possible, else static BOARD.
    vb = build_value_board()
    board = vb if vb else static_board()
    log("BOARD_MODE=" + ("LIVE(FantasyPros)" if vb else "STATIC"))
    drafted={}
    round_num=1
    picks_made=0
    deadline=time.time()+ (3*3600)
    while time.time()<deadline and picks_made<TOTAL_ROUNDS:
        try:
            if is_my_pick(ws):
                raw_avail = read_available(ws)
                available = [n for n, _ in raw_avail]
                # Yahoo ADP (Average Draft Position) per available player, scraped
                # live from the draft-room row. Drives true VALUE = ADP - ECR.
                adp_map = {}
                for n, text in raw_avail:
                    a = parse_adp(text)
                    if a is not None:
                        adp_map[n.lower()] = a
                log("MY_PICK round="+str(round_num)+" avail="+str(len(available))
                    + " yahoo_adp="+str(len(adp_map)))
                pick=choose_pick(available,drafted,round_num,board,adp_map=adp_map)
                if pick:
                    name,team,pos,adp=pick
                    ok=click_player(ws,name)
                    if ok:
                        drafted[pos]=drafted.get(pos,0)+1
                        picks_made+=1
                        log("PICKED round="+str(round_num)+" "+name+" ("+pos+") ADP="+str(adp))
                        round_num+=1
                        time.sleep(random.uniform(1.5,3.0))
                    else:
                        log("PICK_CLICK_FAILED "+str(name))
                else:
                    log("NO_VALID_PICK round="+str(round_num))
            else:
                time.sleep(random.uniform(2,5))
        except Exception as e:
            log("ERR "+repr(e)); time.sleep(5)
    log("DRAFT_DRIVER_DONE picks="+str(picks_made))

if __name__=="__main__":
    run_draft()
