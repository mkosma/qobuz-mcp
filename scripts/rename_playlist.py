#!/usr/bin/env python3
"""Rename one or more Qobuz playlists. Usage: rename_playlist.py <id> <new_name> [<id> <new_name> ...]"""
import json
import sys
import time
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

TOKEN_DATA = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN = TOKEN_DATA["user_auth_token"]
APP_ID = TOKEN_DATA["app_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
HEADERS = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}


def api_post(endpoint, params):
    params = {**params, "app_id": APP_ID}
    url = f"{BASE}/{endpoint}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, headers=HEADERS, data=data, method="POST")
    last = None
    for attempt in range(6):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (500, 502, 503, 504, 429):
                time.sleep(2 ** attempt)
                continue
            print(f"  HTTP {e.code}: {e.read().decode()}")
            raise
        except Exception as e:
            last = e
            time.sleep(2 ** attempt)
    raise last


args = sys.argv[1:]
if len(args) < 2 or len(args) % 2 != 0:
    print("Usage: rename_playlist.py <id> <new_name> [<id> <new_name> ...]")
    sys.exit(1)

pairs = list(zip(args[::2], args[1::2]))
for pid, new_name in pairs:
    print(f"Renaming {pid} → {new_name!r}")
    res = api_post("playlist/update", {"playlist_id": pid, "name": new_name})
    if isinstance(res, dict) and res.get("status") == "success":
        print(f"  ok")
    else:
        print(f"  response: {res}")
    time.sleep(0.2)
