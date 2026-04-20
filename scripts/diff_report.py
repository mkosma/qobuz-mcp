#!/usr/bin/env python3
"""Generate diff report for all duplicate-name Qobuz playlist groups.
Shows track-set differences across copies to inform merge decisions."""
import json
import time
from pathlib import Path
from collections import defaultdict
import urllib.request
import urllib.parse

TOKEN_DATA = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN = TOKEN_DATA["user_auth_token"]
APP_ID = TOKEN_DATA["app_id"]
USER_ID = TOKEN_DATA["user_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
HEADERS = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}


def _do(req):
    last = None
    for attempt in range(6):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (500, 502, 503, 504, 429):
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(2 ** attempt)
    raise last

def api_get(endpoint, params):
    params = {**params, "app_id": APP_ID}
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    return _do(urllib.request.Request(url, headers=HEADERS))


def get_all_playlists():
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


def get_track_ids(playlist_id, count):
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


print("Fetching playlists (post-cleanup)...")
playlists = get_all_playlists()
print(f"Got {len(playlists)} playlists\n")

groups = defaultdict(list)
for p in playlists:
    key = p["name"].lower().strip()
    groups[key].append({
        "id": str(p["id"]),
        "name": p["name"],
        "tracks": p.get("tracks_count", 0),
        "public": bool(p.get("is_public")),
    })

dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
print(f"Duplicate-name groups remaining: {len(dup_groups)}\n")

identical = []           # all track sets match
needs_review = []        # track sets differ

for i, (key, copies) in enumerate(sorted(dup_groups.items()), 1):
    name = copies[0]["name"]
    # fetch track sets
    sets = {}
    for c in copies:
        sets[c["id"]] = get_track_ids(c["id"], c["tracks"]) if c["tracks"] > 0 else set()
        time.sleep(0.05)

    values = list(sets.values())
    if all(s == values[0] for s in values):
        identical.append((name, copies))
    else:
        # Compute union and per-copy unique tracks
        union = set().union(*values)
        entries = []
        for c in copies:
            s = sets[c["id"]]
            others_union = set().union(*[sets[x["id"]] for x in copies if x["id"] != c["id"]])
            unique_here = s - others_union
            entries.append({**c, "track_set": s, "unique_count": len(unique_here)})
        needs_review.append((name, entries, len(union)))

    if i % 10 == 0:
        print(f"  processed {i}/{len(dup_groups)} groups...")

print(f"\n\n{'='*80}\nSUMMARY\n{'='*80}")
print(f"Identical track sets (can dedup): {len(identical)}")
print(f"Differing track sets (need review): {len(needs_review)}\n")

print(f"{'='*80}\nIDENTICAL — safe to dedup now\n{'='*80}")
for name, copies in identical:
    pub_count = sum(1 for c in copies if c["public"])
    print(f"  [{name}] {copies[0]['tracks']}t × {len(copies)} copies ({pub_count} public)")

print(f"\n{'='*80}\nNEEDS REVIEW — same name, different track contents\n{'='*80}")
for name, entries, union_size in sorted(needs_review, key=lambda x: -x[2]):
    print(f"\n[{name}]  union={union_size} unique tracks across {len(entries)} copies")
    for e in sorted(entries, key=lambda x: -x["tracks"]):
        vis = "pub " if e["public"] else "priv"
        u = e["unique_count"]
        print(f"  {e['id']:>10}  {e['tracks']:>5}t  {vis}  unique-to-this: {u}")

# Save the needs_review data to file for potential merge script
out = {"identical": [{"name": n, "copies": c} for n, c in identical],
       "needs_review": [{"name": n, "copies": [{k: (list(v) if isinstance(v, set) else v) for k, v in e.items()} for e in es], "union_size": u}
                        for n, es, u in needs_review]}
Path("/tmp/duplicates_report.json").write_text(json.dumps(out, indent=2, default=str))
print(f"\nDetailed data saved to /tmp/duplicates_report.json")
