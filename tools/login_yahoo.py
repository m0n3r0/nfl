"""Login a headless Chromium browser to Yahoo Fantasy, driven over CDP on 9222.

Use this on the fresh Mac profile (or any browser launched with
--remote-debugging-port=9222 --remote-allow-origins=*). The Yahoo session is
persisted in the browser profile, so later headless launches with the same
--user-data-dir stay logged in and this script just reports "already logged in".

Credentials (never written to disk):
  - env vars YAHOO_USER / YAHOO_PASSWORD (also read from a .env next to the repo
    or cwd, same loader the draft driver uses), or
  - interactive prompts on stdin.

CAVEAT (honest): if Yahoo serves an interactive captcha ("enter the letters",
"verify you're human") in headless mode, no pure-automation path is safe;
fall back to options A/C in docs/MAC_SETUP.md (copy the Windows session, or a
one-time headful login via Screen Sharing).

Safe: this script only fills the login form on login.yahoo.com; it never clicks
inside the live league/draft page.
"""
import getpass
import json
import os
import random
import sys
import time
import urllib.request
import websocket

CDP = os.environ.get("CDP", "http://127.0.0.1:9222")
LEAGUE = "1329011"
LEAGUE_URL = f"https://football.fantasysports.yahoo.com/f1/{LEAGUE}/draftanalysis"
LOGIN_URL = "https://login.yahoo.com/"


def _load_dotenv():
    for path in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
                 os.path.join(os.getcwd(), ".env")):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() and k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            return


_load_dotenv()


def http_get(p):
    with urllib.request.urlopen(CDP + p, timeout=8) as r:
        return json.loads(r.read().decode())


def ev(ws, expr, await_promise=False):
    wid = random.randint(10 ** 5, 10 ** 6)
    ws.send(json.dumps({"id": wid, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True,
                                   "awaitPromise": await_promise}}))
    while True:
        o = json.loads(ws.recv())
        if o.get("id") == wid:
            return o.get("result", {}).get("result", {}).get("value")


def nav(ws, url, wait=7):
    wid = random.randint(10 ** 5, 10 ** 6)
    ws.send(json.dumps({"id": wid, "method": "Page.navigate", "params": {"url": url}}))
    deadline = time.time() + 5
    while time.time() < deadline:
        o = json.loads(ws.recv())
        if o.get("id") == wid:
            break
    time.sleep(wait)


def has(ws, css):
    return bool(ev(ws, f"document.querySelector({css!r}) !== null"))


def wait_for(ws, css, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if has(ws, css):
            return True
        time.sleep(0.6)
    return False


def signed_in(ws):
    """Definitive same-origin check (mirrors tools/check_login.py): a protected
    team page must return 200 AND contain the manager name. Only meaningful on
    the football.fantasysports.yahoo.com origin."""
    expr = """(function(){
        return fetch('/f1/1329011/team/002', {credentials: 'same-origin'})
          .then(function(r){ if (r.status !== 200) return false; return r.text(); })
          .then(function(h){ return /Doge/i.test(h); })
          .catch(function(){ return false; });
    })()"""
    return bool(ev(ws, expr, await_promise=True))


def rect_of(ws, css):
    return ev(ws, """(function(){
        var el = document.querySelector(%r);
        if (!el) return null;
        var r = el.getBoundingClientRect();
        return {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)};
    })()""" % css)


def type_text(ws, css, text):
    if not wait_for(ws, css, 15):
        return False
    ev(ws, ("(function(){var el=document.querySelector(%r); el.scrollIntoView({block:'center'});"
            " el.focus(); el.click(); return !!el;})()" % css))
    time.sleep(0.3)
    ws.send(json.dumps({"id": 0, "method": "Input.insertText", "params": {"text": text}}))
    time.sleep(0.4)
    return True


def _mouse_click(ws, x, y):
    for _ in range(6):
        ws.send(json.dumps({"id": 0, "method": "Input.dispatchMouseEvent",
                            "params": {"type": "mouseMoved",
                                       "x": x + random.randint(-2, 2),
                                       "y": y + random.randint(-2, 2)}}))
        time.sleep(random.uniform(0.01, 0.03))
    time.sleep(random.uniform(0.05, 0.15))
    ws.send(json.dumps({"id": 0, "method": "Input.dispatchMouseEvent",
                        "params": {"type": "mousePressed", "x": x, "y": y,
                                   "button": "left", "clickCount": 1}}))
    time.sleep(random.uniform(0.04, 0.1))
    ws.send(json.dumps({"id": 0, "method": "Input.dispatchMouseEvent",
                        "params": {"type": "mouseReleased", "x": x, "y": y,
                                   "button": "left", "clickCount": 1}}))
    time.sleep(random.uniform(0.2, 0.6))
    return True


def click_center(ws, css):
    pt = rect_of(ws, css)
    if not pt:
        return False
    return _mouse_click(ws, pt["x"], pt["y"])


def click_label(ws, *labels):
    """Click the first button/submit/link/[role=button] whose text matches."""
    expr = """(function(){
        var want = %r;
        var els = document.querySelectorAll('button, input[type=submit], a[role=button], [role=button]');
        for (var i = 0; i < els.length; i++) {
            var t = ((els[i].innerText || els[i].value) || '').trim().toLowerCase();
            for (var w = 0; w < want.length; w++) {
                if (t === want[w] || t.indexOf(want[w]) >= 0) {
                    var r = els[i].getBoundingClientRect();
                    return {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)};
                }
            }
        }
        return null;
    })()""" % [l.lower() for l in labels]
    pt = ev(ws, expr)
    if not pt:
        return False
    return _mouse_click(ws, pt["x"], pt["y"])


def body_tail(ws, n=30):
    b = ev(ws, "document.body ? document.body.innerText : ''") or ""
    lines = [l.strip() for l in b.splitlines() if l.strip()]
    return "\n".join(lines[-n:]) or "(empty page)"


def _creds():
    user = os.environ.get("YAHOO_USER")
    pwd = os.environ.get("YAHOO_PASSWORD")
    if not user:
        user = input("Yahoo email: ").strip()
    if not pwd:
        pwd = getpass.getpass("Yahoo password: ")
    return user, pwd


def main():
    tabs = [t for t in http_get("/json/list") if t.get("type") == "page"]
    if not tabs:
        print("NO TABS: is the headless browser running with --remote-debugging-port=9222?")
        sys.exit(1)
    tab = next((t for t in tabs if "fantasysports" in t.get("url", "")), None) or tabs[0]
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30,
                                     header={"Origin": "http://127.0.0.1:9222"})

    print("[1] checking existing session on the league page ...")
    nav(ws, LEAGUE_URL, wait=7)
    if signed_in(ws):
        print("ALREADY_LOGGED_IN: no login needed (profile carries the session).")
        ws.close()
        return

    user, pwd = _creds()

    print("[2] navigating to login.yahoo.com ...")
    nav(ws, LOGIN_URL, wait=6)
    if not wait_for(ws, "#login-username"):
        print("NO_USERNAME_FIELD. Page says:\n" + body_tail(ws))
        ws.close()
        sys.exit(2)

    print("[3] typing email ...")
    type_text(ws, "#login-username", user)
    if not (click_label(ws, "next", "continue") or click_center(ws, "#btn-next")):
        click_center(ws, "input[type=submit]")

    if not wait_for(ws, "#login-passwd"):
        print("NO_PASSWORD_FIELD. Page says:\n" + body_tail(ws))
        ws.close()
        sys.exit(2)

    print("[4] typing password ...")
    type_text(ws, "#login-passwd", pwd)
    if not (click_label(ws, "sign in", "login", "submit") or click_center(ws, "#btn-submit")):
        click_center(ws, "input[type=submit]")

    print("[5] waiting through possible 2FA / trust screens ...")
    for _ in range(8):
        time.sleep(4)
        cur = (ev(ws, "location.href") or "")
        if "fantasysports" not in cur:
            # Still inside the auth flow: answer trust/continue prompts only here
            # (never risk an accidental click on the league page).
            if click_label(ws, "continue", "yes", "verify"):
                print("    answered a trust/continue prompt")
                continue
        nav(ws, LEAGUE_URL, wait=6)
        if signed_in(ws):
            print("LOGGED_IN_OK: league tab is authentic (profile now persists session).")
            ws.close()
            return
        nav(ws, LOGIN_URL, wait=4)
        if wait_for(ws, "#otp-code", timeout=3) or wait_for(ws, "input[name*=otp]", timeout=3):
            print("[6] 2FA code prompt detected — enter the code Yahoo sent you:")
            code = input("2FA code: ").strip()
            if wait_for(ws, "#otp-code", timeout=4):
                type_text(ws, "#otp-code", code)
            else:
                for css in ("input[name*=otp]", "#verification-code", "input[maxlength]"):
                    if has(ws, css):
                        type_text(ws, css, code)
                        break
            click_label(ws, "verify", "continue", "submit", "next")
            continue
        tail = body_tail(ws, 40).lower()
        if any(k in tail for k in ("captcha", "are you human", "enter the letters")):
            print("CAPTCHA_BLOCKED: Yahoo served an interactive challenge to headless mode.")
            print("Use docs/MAC_SETUP.md option A (copy the Windows session) or C (one-time\n"
                  "headful login via Screen Sharing), then relaunch headless with that profile.")
            ws.close()
            sys.exit(3)

    print("LOGIN_UNCERTAIN after retries. Last page:\n" + body_tail(ws, 40))
    ws.close()
    sys.exit(4)


if __name__ == "__main__":
    main()