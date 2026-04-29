#!/usr/bin/env python3
"""Bulk-remove a list of album_ids from the user's Qobuz favorites.
Pass IDs as CLI args, or edit IDS list below.
"""
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


def remove_album(album_id):
    data = urllib.parse.urlencode({"album_ids": album_id, "app_id": APP_ID}).encode()
    req = urllib.request.Request(f"{BASE}/favorite/delete", data=data, headers=HEADERS, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


ids = sys.argv[1:]
if not ids:
    print("usage: batch_remove_favorite_albums.py <album_id> [<album_id> ...]", file=sys.stderr)
    sys.exit(1)

for aid in ids:
    try:
        res = remove_album(aid)
        print(f"  {aid}  {res}")
    except Exception as e:
        print(f"  {aid}  ERROR: {e}")
    time.sleep(0.15)
