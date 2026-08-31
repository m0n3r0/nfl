#!/usr/bin/env python3
"""Yahoo Fantasy Sports OAuth2 flow.

Handles the full OAuth2 authorization code flow for the Yahoo Fantasy API:
  1. Opens the auth URL in your browser
  2. You log in and grant access
  3. Yahoo redirects to your redirect URI (or shows the code for oob)
  4. You paste the code back
  5. The script exchanges it for an access token + refresh token
  6. Tokens are saved to .env (or printed) for future API calls

Usage:
  python scripts/yahoo_oauth.py              # full flow (browser + paste)
  python scripts/yahoo_oauth.py --refresh    # refresh an expired token
"""
import os
import sys
import json
import base64
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

def save_tokens(access, refresh):
    env_path = ROOT / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    out = []
    replaced = set()
    for line in lines:
        if line.startswith("YAHOO_ACCESS_TOKEN="):
            out.append(f"YAHOO_ACCESS_TOKEN={access}"); replaced.add("a")
        elif line.startswith("YAHOO_REFRESH_TOKEN="):
            out.append(f"YAHOO_REFRESH_TOKEN={refresh}"); replaced.add("r")
        else:
            out.append(line)
    if "a" not in replaced: out.append(f"YAHOO_ACCESS_TOKEN={access}")
    if "r" not in replaced: out.append(f"YAHOO_REFRESH_TOKEN={refresh}")
    env_path.write_text("\n".join(out) + "\n")

def main():
    load_env()
    client_id = os.environ.get("YAHOO_CLIENT_ID")
    client_secret = os.environ.get("YAHOO_CLIENT_SECRET")
    redirect = os.environ.get("YAHOO_REDIRECT_URI", "oob")
    if not client_id or not client_secret:
        sys.exit("[!] Set YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET in .env")

    auth_url = (
        "https://api.login.yahoo.com/oauth2/request_auth"
        f"?client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect)}"
        "&response_type=code"
        "&scope=fspt-r"
    )

    if "--refresh" in sys.argv:
        refresh_token = os.environ.get("YAHOO_REFRESH_TOKEN")
        if not refresh_token:
            sys.exit("[!] No refresh token found. Run the full flow first.")
        print("[*] Refreshing token...")
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode()
    else:
        print("[*] Open this URL in your browser and authorize the app:\n")
        print(auth_url)
        print()
        code = input("[?] Paste the authorization code: ").strip()
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
        }).encode()

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        "https://api.login.yahoo.com/oauth2/get_token",
        data=data,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    access = resp.get("access_token")
    refresh = resp.get("refresh_token")

    print(f"\n[+] Access token: {access[:20]}...")
    print(f"[+] Refresh token: {(refresh or '')[:20]}...")
    save_tokens(access, refresh or "")
    print("[+] Tokens saved to .env")
    print("\n[*] Test with:")
    print(f"    curl -H 'Authorization: Bearer {access[:20]}...' "
          "https://fantasysports.yahooapis.com/fantasy/v2/game/nfl?format=json")

if __name__ == "__main__":
    main()
