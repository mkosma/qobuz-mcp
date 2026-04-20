#!/usr/bin/env python3
"""Union-merge Qobuz playlist duplicates with two safety features:

1. ABORT-ON-FAILURE: if any track-add batch fails, do NOT delete any losers.
2. AUTO-SPLIT: if union exceeds 2000 (Qobuz limit), rename keeper to
   "NAME (1 of N)" and create overflow playlists "NAME (2 of N)" etc.

Usage: python3 merge_playlist.py <name_lowercase> [--apply]
"""
import json, math, sys, time, urllib.request, urllib.parse
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: merge_playlist.py <name_lowercase> [--apply]")
    sys.exit(1)

target = sys.argv[1].lower()
DRY_RUN = "--apply" not in sys.argv

td = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN, APP_ID, USER_ID = td["user_auth_token"], td["app_id"], td["user_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
H = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}
LIMIT = 2000  # Qobuz playlist max
CHUNK = 50

def _do(req):
    last = None
    for attempt in range(5):
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

def api_get(ep, p):
    p = {**p, "app_id": APP_ID}
    return _do(urllib.request.Request(f"{BASE}/{ep}?{urllib.parse.urlencode(p)}", headers=H))

def api_post(ep, data):
    data = {**data, "app_id": APP_ID}
    body = urllib.parse.urlencode(data).encode()
    return _do(urllib.request.Request(f"{BASE}/{ep}", data=body, headers=H, method="POST"))

# Fetch all playlists
out, off = [], 0
while True:
    d = api_get("playlist/getUserPlaylists", {"user_id": USER_ID, "limit": 500, "offset": off})
    items = d.get("playlists", {}).get("items", [])
    if not items: break
    out.extend(items)
    if len(items) < 500: break
    off += 500

matches = [p for p in out if p["name"].lower().strip() == target]
if not matches:
    print(f"No playlists named '{target}' found.")
    sys.exit(1)

original_name = matches[0]["name"]
print(f"Found {len(matches)} copies of '{original_name}':")
for p in matches:
    print(f"  ID {p['id']:>10} — {p.get('tracks_count',0)}t ({'public' if p.get('is_public') else 'private'})")

# Pick keeper: largest, then prefer public, then highest ID
def keeper_score(p):
    return (p.get('tracks_count', 0), 1 if p.get('is_public') else 0, int(p['id']))
keeper = max(matches, key=keeper_score)
losers = [p for p in matches if p['id'] != keeper['id']]
print(f"\nKeeper: {keeper['id']} ({keeper.get('tracks_count',0)}t, "
      f"{'public' if keeper.get('is_public') else 'private'})")

def get_track_ids(pid, count):
    ids, off = [], 0
    while len(ids) < count:
        d = api_get("playlist/get", {"playlist_id": pid, "limit": 500, "offset": off, "extra": "tracks"})
        items = d.get("tracks", {}).get("items", [])
        if not items: break
        ids.extend(str(t.get("id")) for t in items)
        if len(items) < 500: break
        off += 500
    return ids

print("\nFetching tracks...")
keeper_ids = get_track_ids(keeper['id'], keeper.get('tracks_count', 0))
keeper_set = set(keeper_ids)
print(f"  Keeper has {len(keeper_set)} tracks")

new_ordered = []
new_set = set()
for L in sorted(losers, key=lambda x: int(x['id'])):
    L_ids = get_track_ids(L['id'], L.get('tracks_count', 0))
    nu = [t for t in L_ids if t not in keeper_set and t not in new_set]
    print(f"  Loser {L['id']} has {len(L_ids)}t; +{len(nu)} new")
    for t in nu:
        new_ordered.append(t)
        new_set.add(t)
    time.sleep(0.05)

# Qobuz counts duplicates toward the 2000 cap, so use reported track_count
# (not unique-set length) to compute free space in the keeper.
keeper_reported = keeper.get('tracks_count', 0)
total_union = keeper_reported + len(new_ordered)
print(f"\nTotal union: {total_union} tracks "
      f"({keeper_reported} in keeper [reported] + {len(new_ordered)} new)")

if total_union <= LIMIT:
    plan = [("keeper", keeper, new_ordered)]
    print(f"Will fit in single playlist ({total_union}/{LIMIT}).")
else:
    n_parts = math.ceil(total_union / LIMIT)
    print(f"Exceeds limit — will split into {n_parts} parts (max {LIMIT}/part).")
    # Part 1 = keeper renamed, fill with new tracks up to LIMIT
    space_in_keeper = LIMIT - keeper_reported
    part1_new = new_ordered[:space_in_keeper]
    remaining = new_ordered[space_in_keeper:]
    plan = [("keeper", keeper, part1_new)]
    # Subsequent parts: create new playlists with chunks of remaining
    for i in range(2, n_parts + 1):
        chunk = remaining[:LIMIT]
        remaining = remaining[LIMIT:]
        plan.append(("new", f"{original_name} ({i} of {n_parts})", chunk))
    new_keeper_name = f"{original_name} (1 of {n_parts})"
    print(f"  Part 1 of {n_parts}: rename keeper to \"{new_keeper_name}\", add {len(part1_new)} tracks")
    for i, (kind, ref, tracks) in enumerate(plan[1:], 2):
        print(f"  Part {i} of {n_parts}: create \"{ref}\" with {len(tracks)} tracks")

if DRY_RUN:
    print("\n[DRY RUN] Re-run with --apply")
    sys.exit(0)

# === EXECUTE PLAN ===
created_ids = []
abort = False

# Step 1: rename keeper if multi-part
n_parts = len(plan)
if n_parts > 1:
    new_keeper_name = f"{original_name} (1 of {n_parts})"
    print(f"\nRenaming keeper to \"{new_keeper_name}\"...")
    try:
        r = api_post("playlist/update", {"playlist_id": keeper['id'], "name": new_keeper_name})
        if "code" in r and r.get("code") not in (200, None) and r.get("status") != "success":
            print(f"  RENAME FAILED: {r}")
            abort = True
        else:
            print(f"  OK")
    except Exception as e:
        print(f"  RENAME ERROR: {e}")
        abort = True

# Step 2: add tracks to keeper
if not abort:
    _, _, tracks_for_keeper = plan[0]
    if tracks_for_keeper:
        print(f"\nAdding {len(tracks_for_keeper)} tracks to keeper...")
        for i in range(0, len(tracks_for_keeper), CHUNK):
            chunk = tracks_for_keeper[i:i+CHUNK]
            try:
                r = api_post("playlist/addTracks", {"playlist_id": keeper['id'], "track_ids": ",".join(chunk)})
                if "code" in r and r.get("code") not in (200, None):
                    print(f"  Batch {i//CHUNK+1} FAIL: {r}")
                    abort = True
                    break
                else:
                    print(f"  Batch {i//CHUNK+1}: +{len(chunk)} (cum {min(i+CHUNK, len(tracks_for_keeper))}/{len(tracks_for_keeper)})")
            except Exception as e:
                print(f"  Batch {i//CHUNK+1} ERROR: {e}")
                abort = True
                break
            time.sleep(0.15)

# Step 3: create overflow playlists
if not abort and n_parts > 1:
    is_pub = "1" if keeper.get('is_public') else "0"
    for kind, name, tracks in plan[1:]:
        print(f"\nCreating \"{name}\"...")
        try:
            r = api_post("playlist/create", {"name": name, "is_public": is_pub, "is_collaborative": "0"})
            new_id = str(r.get("id") or r.get("playlist", {}).get("id") or "")
            if not new_id:
                print(f"  CREATE FAILED: {r}")
                abort = True
                break
            created_ids.append(new_id)
            print(f"  Created ID {new_id}")
            for i in range(0, len(tracks), CHUNK):
                chunk = tracks[i:i+CHUNK]
                try:
                    r = api_post("playlist/addTracks", {"playlist_id": new_id, "track_ids": ",".join(chunk)})
                    if "code" in r and r.get("code") not in (200, None):
                        print(f"  Batch {i//CHUNK+1} FAIL: {r}")
                        abort = True
                        break
                    print(f"  Batch {i//CHUNK+1}: +{len(chunk)} (cum {min(i+CHUNK, len(tracks))}/{len(tracks)})")
                except Exception as e:
                    print(f"  Batch ERROR: {e}")
                    abort = True
                    break
                time.sleep(0.15)
            if abort:
                break
        except Exception as e:
            print(f"  CREATE ERROR: {e}")
            abort = True
            break

if abort:
    print("\n!!! ABORT !!! Losers NOT deleted. Manually inspect state.")
    print(f"Keeper ID: {keeper['id']}")
    if created_ids:
        print(f"Newly-created overflow IDs (may be partial): {created_ids}")
    sys.exit(1)

# Step 4: delete losers (only if everything succeeded)
print(f"\nAll adds succeeded. Deleting {len(losers)} losers...")
for L in losers:
    try:
        r = api_post("playlist/delete", {"playlist_id": L['id']})
        ok = r.get("status") == "success" or r == {} or "code" not in r
        print(f"  {L['id']} — {'OK' if ok else 'FAIL: '+str(r)}")
    except Exception as e:
        print(f"  {L['id']} — ERROR: {e}")
    time.sleep(0.1)

print("\n=== Final state ===")
final = api_get("playlist/get", {"playlist_id": keeper['id'], "limit": 1, "extra": "tracks"})
print(f"Keeper {keeper['id']} ({final.get('name','?')}): {final.get('tracks_count','?')} tracks")
for nid in created_ids:
    f = api_get("playlist/get", {"playlist_id": nid, "limit": 1, "extra": "tracks"})
    print(f"New     {nid} ({f.get('name','?')}): {f.get('tracks_count','?')} tracks")
