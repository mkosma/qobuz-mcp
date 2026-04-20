#!/usr/bin/env python3
"""Delete Category A duplicates: largest copy is superset of all others. Zero track loss."""
import json
import sys
import time
from pathlib import Path
import urllib.request
import urllib.parse

TOKEN_DATA = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN = TOKEN_DATA["user_auth_token"]
APP_ID = TOKEN_DATA["app_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
HEADERS = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}

DRY_RUN = "--apply" not in sys.argv

def api_post(endpoint, data):
    data = {**data, "app_id": APP_ID}
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f"{BASE}/{endpoint}", data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

d = json.load(open('/tmp/duplicates_report.json'))

deletes = []
for g in d['needs_review']:
    name = g['name']
    copies = g['copies']
    sorted_copies = sorted(copies, key=lambda c: -c['tracks'])
    largest = sorted_copies[0]
    largest_set = set(largest['track_set'])
    others = sorted_copies[1:]

    # All non-largest tracks union — must be subset of largest for cat A
    all_loser_unique = set()
    for o in others:
        all_loser_unique |= (set(o['track_set']) - largest_set)
    if len(all_loser_unique) == 0:
        for o in others:
            deletes.append({"name": name, "keep_id": largest['id'], "keep_count": largest['tracks'],
                           "delete_id": o['id'], "delete_count": o['tracks'], "public_kept": largest['public']})

print(f"{'DRY RUN' if DRY_RUN else 'LIVE'} mode\n")
print(f"Planned deletes: {len(deletes)}\n")
for x in deletes[:5]:
    print(f"  [{x['name']}] keep {x['keep_id']} ({x['keep_count']}t) — delete {x['delete_id']} ({x['delete_count']}t)")
print(f"  ... and {len(deletes)-5} more\n")

if not DRY_RUN:
    failed = []
    for i, x in enumerate(deletes, 1):
        try:
            r = api_post("playlist/delete", {"playlist_id": x['delete_id']})
            ok = r.get("status") == "success" or r == {} or "code" not in r
            print(f"  [{i}/{len(deletes)}] {x['name']} ({x['delete_id']}) — {'OK' if ok else 'FAIL: ' + str(r)}")
            if not ok:
                failed.append(x)
        except Exception as e:
            print(f"  [{i}/{len(deletes)}] {x['name']} ({x['delete_id']}) — ERROR: {e}")
            failed.append(x)
        time.sleep(0.1)
    print(f"\nDone. {len(deletes) - len(failed)} succeeded, {len(failed)} failed.")
    if failed:
        print("Failures:")
        for f in failed:
            print(f"  {f}")
