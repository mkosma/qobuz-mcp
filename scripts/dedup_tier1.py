#!/usr/bin/env python3
"""Delete Tier 1 duplicate Qobuz playlists (same name, same track count).
Validates track sets match before each deletion.
Keep rule: highest-ID public copy, else highest-ID overall."""
import json
import sys
import time
from pathlib import Path
import urllib.request
import urllib.parse

TOKEN_DATA = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN = TOKEN_DATA["user_auth_token"]
APP_ID = TOKEN_DATA["app_id"]
USER_ID = TOKEN_DATA["user_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
HEADERS = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}

DRY_RUN = "--apply" not in sys.argv

def api_get(endpoint, params):
    params = {**params, "app_id": APP_ID}
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def api_post(endpoint, data):
    data = {**data, "app_id": APP_ID}
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f"{BASE}/{endpoint}", data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def get_all_playlists():
    """Fetch all user playlists across pagination."""
    out = []
    offset = 0
    while True:
        d = api_get("playlist/getUserPlaylists",
                    {"user_id": USER_ID, "limit": 500, "offset": offset})
        items = d.get("playlists", {}).get("items", [])
        if not items:
            break
        out.extend(items)
        if len(items) < 500:
            break
        offset += 500
    return out

def track_ids(playlist_id, count):
    """Fetch all track IDs for a playlist (paginates if needed)."""
    ids = []
    offset = 0
    while len(ids) < count:
        d = api_get("playlist/get",
                    {"playlist_id": playlist_id, "limit": 500, "offset": offset, "extra": "tracks"})
        items = d.get("tracks", {}).get("items", [])
        if not items:
            break
        ids.extend(str(t.get("id")) for t in items)
        if len(items) < 500:
            break
        offset += 500
    return set(ids)

print(f"{'DRY RUN' if DRY_RUN else 'LIVE'} mode\n")
print("Fetching playlists...")
playlists = get_all_playlists()
print(f"Got {len(playlists)} playlists\n")

# Group by lowercase name
from collections import defaultdict
groups = defaultdict(list)
for p in playlists:
    key = p["name"].lower().strip()
    groups[key].append({
        "id": str(p["id"]),
        "name": p["name"],
        "tracks": p.get("tracks_count", 0),
        "public": bool(p.get("is_public")),
    })

# Tier 1: duplicates with all-same track count
tier1 = {k: v for k, v in groups.items()
         if len(v) > 1 and len(set(e["tracks"] for e in v)) == 1}
print(f"Tier 1 groups: {len(tier1)}")

deletes_planned = []
groups_skipped_mismatch = []

for key, copies in sorted(tier1.items()):
    name = copies[0]["name"]
    count = copies[0]["tracks"]

    # Validate track sets match
    if count > 0:
        sets = {}
        for c in copies:
            sets[c["id"]] = track_ids(c["id"], count)
            time.sleep(0.05)
        first = next(iter(sets.values()))
        all_match = all(s == first for s in sets.values())
        if not all_match:
            groups_skipped_mismatch.append((name, copies))
            print(f"SKIP [{name}] — track sets differ across copies")
            continue
    # else 0-track playlists, trivially equal

    # Pick keeper: highest-ID public, else highest-ID overall
    publics = [c for c in copies if c["public"]]
    pool = publics if publics else copies
    keeper = max(pool, key=lambda c: int(c["id"]))
    losers = [c for c in copies if c["id"] != keeper["id"]]
    for l in losers:
        deletes_planned.append({"name": name, "keep_id": keeper["id"], "delete_id": l["id"], "count": count})

print(f"\nPlanned deletes: {len(deletes_planned)}")
print(f"Groups skipped (track set mismatch): {len(groups_skipped_mismatch)}\n")

for d in deletes_planned[:10]:
    print(f"  [{d['name']}] {d['count']}t — keep {d['keep_id']}, delete {d['delete_id']}")
if len(deletes_planned) > 10:
    print(f"  ... and {len(deletes_planned)-10} more")

if groups_skipped_mismatch:
    print("\nSkipped groups (need manual review):")
    for name, copies in groups_skipped_mismatch:
        print(f"  [{name}] {[c['id'] for c in copies]}")

if not DRY_RUN:
    print("\nExecuting deletes...")
    failed = []
    for i, d in enumerate(deletes_planned, 1):
        try:
            r = api_post("playlist/delete", {"playlist_id": d["delete_id"]})
            ok = r.get("status") == "success" or r == {} or "code" not in r
            print(f"  [{i}/{len(deletes_planned)}] {d['name']} ({d['delete_id']}) — {'OK' if ok else 'FAIL: ' + str(r)}")
            if not ok:
                failed.append(d)
        except Exception as e:
            print(f"  [{i}/{len(deletes_planned)}] {d['name']} ({d['delete_id']}) — ERROR: {e}")
            failed.append(d)
        time.sleep(0.1)
    print(f"\nDone. {len(deletes_planned) - len(failed)} succeeded, {len(failed)} failed.")
