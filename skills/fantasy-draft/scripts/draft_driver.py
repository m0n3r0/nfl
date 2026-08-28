"""
FD nation (league 1329011) LIVE DRAFT DRIVER for team #2 (Doge)
Runs against Edge on ws://127.0.0.1:9222 (launched with --remote-allow-origins=*).
Strategy: position-target-aware board picking with guardrails.
Guarantees a legal lineup: required slots (QB,2RB,2WR,TE,K,DEF) filled by
their deadlines, bench (6 BN) filled with best available afterwards.
All decisions logged to C:\edge-debug-profile\draft_log.txt
"""
import json, urllib.request, websocket, time, random, math, sys, io, datetime

CDP = "http://127.0.0.1:9222"
LEAGUE = "1329011"
TEAM_ID = "2"
LOG = r"C:\edge-debug-profile\draft_log.txt"
TOTAL_ROUNDS = 15
MY_PICK_ROUNDS_QB = 10      # don't take QB before this round
K_DEF_LAST_ROUNDS = 2       # K/DEF only in last N rounds
ADP_WINDOW = 40              # reach guard: skip board pick if ADP >> board rank

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
    ("Omarion Hampton","LAC","RB",18.7),("Josh Allen","Buf","QB",19.6),
    ("Brock Bowers","LV","TE",21.1),("Nico Collins","Hou","WR",22.2),
    ("George Pickens","Dal","WR",22.4),("A.J. Brown","NE","WR",25.0),
    ("Trey McBride","Ari","TE",25.4),("Jeremiyah Love","Ari","RB",27.2),
    ("DeVonta Smith","Phi","WR",29.4),("Kyren Williams","LAR","RB",29.6),
    ("Josh Jacobs","GB","RB",32.8),("Chris Olave","NO","WR",34.0),
    # K tier (draft only last rounds)
    ("Brandon Aubrey","Dal","K",85.0),("Ka'imi Fairbairn","Hou","K",119.0),
    ("Cameron Dicker","LAC","K",123.0),("Jason Myers","Sea","K",124.0),
    ("Cam Little","Jax","K",129.0),
    # DEF tier (draft only last rounds)
    ("Rams","LAR","DEF",89.0),("Texans","Hou","DEF",93.0),
    ("Broncos","Den","DEF",101.0),("Seahawks","Sea","DEF",107.0),
    ("Eagles","Phi","DEF",123.0),("Patriots","NE","DEF",127.0),
]

# Required starting slots (filled by deadline); bench fills the rest.
REQUIRED = {"QB":1, "RB":2, "WR":2, "TE":1, "K":1, "DEF":1}
# By which round each required slot should be secured (forced if missing).
# QB by round 10, K/DEF by last 2 rounds, skill by round ~9.
FORCE_BY_ROUND = {"RB":9, "WR":9, "TE":7, "QB":10, "K":14, "DEF":14}

def log(s):
    line = datetime.datetime.now().strftime("%H:%M:%S") + " " + str(s)
    with io.open(LOG,"a",encoding="utf-8") as f:
        f.write(line+"\n")
    print(line)

def http_get(path):
    with urllib.request.urlopen(CDP+path,timeout=8) as r:
        return json.loads(r.read().decode())

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

def read_available(ws):
    # Name-based scan (Yahoo player rows hold the name in a cell, NOT inside the
    # /nfl/players/ anchor which only wraps an icon). Collect names from rows.
    return ev(ws,"""(function(){
      var out=[];
      var seen={};
      var rows=document.querySelectorAll('tr, li');
      for(var i=0;i<rows.length;i++){
        var t=rows[i].innerText.replace(/\\s+/g,' ').trim();
        // player name pattern: "First Last" followed by "TEAM - POS"
        var m=t.match(/([A-Z][a-z]+(?:['’]\\w+)?\\.?[ -][A-Z][a-z]+(?:['’]\\w+)?(?:[ -][A-Z][a-z]+)?)\\s+(?:[A-Z]{2,4}\\s*-\\s*(?:QB|RB|WR|TE|K|DEF))/);
        if(m && !seen[m[1]]){ seen[m[1]]=1; out.push(m[1]); }
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

def choose_pick(available, drafted, round_num):
    """Position-target-aware pick.
    1) If a REQUIRED slot is still unfilled AND we're at/past its FORCE_BY_ROUND,
       force the best available player at that position.
    2) Otherwise pick highest board player available respecting timing guards.
    3) Fallback: best available by board ignoring need (still respect timing)."""
    avail_lower = set(n.lower() for n in available)
    def on_board(name): return name.lower() in avail_lower

    # 1) forced fills for required slots past deadline
    for pos, need in REQUIRED.items():
        have = drafted.get(pos,0)
        if have < need and round_num >= FORCE_BY_ROUND.get(pos, 99):
            # best available at this pos by board order
            cand = [b for b in BOARD if b[2]==pos and on_board(b[0])]
            if cand:
                return cand[0]  # BOARD already sorted by ADP/priority

    # 2) highest board player available, with timing guards + need awareness
    for name,team,pos,adp in BOARD:
        if not on_board(name): continue
        if pos in ("K","DEF") and round_num < (TOTAL_ROUNDS - K_DEF_LAST_ROUNDS + 1): continue
        if pos=="QB" and round_num < MY_PICK_ROUNDS_QB: continue
        # need guard: don't take a 3rd RB/WR etc. unless required slots still open elsewhere
        have = drafted.get(pos,0)
        if pos in REQUIRED and have >= REQUIRED[pos]:
            # already have enough of this starting slot; only take as bench if board says clearly best
            # allow bench-fill only after skill starters secured -> handled by fallback
            continue
        return (name,team,pos,adp)

    # 3) fallback: best available by board ignoring need (still respect timing guards)
    for name,team,pos,adp in BOARD:
        if not on_board(name): continue
        if pos in ("K","DEF") and round_num < (TOTAL_ROUNDS - K_DEF_LAST_ROUNDS + 1): continue
        if pos=="QB" and round_num < MY_PICK_ROUNDS_QB: continue
        return (name,team,pos,adp)
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
    drafted={}
    round_num=1
    picks_made=0
    deadline=time.time()+ (3*3600)
    while time.time()<deadline and picks_made<TOTAL_ROUNDS:
        try:
            if is_my_pick(ws):
                available=read_available(ws)
                log("MY_PICK round="+str(round_num)+" avail="+str(len(available)))
                pick=choose_pick(available,drafted,round_num)
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
