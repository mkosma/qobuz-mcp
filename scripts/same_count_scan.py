#!/usr/bin/env python3
"""Find playlists with identical or near-identical contents but DIFFERENT names.

Strategy:
1. List all playlists.
2. Bucket by tracks_count (only fetch tracks for buckets with 2+ playlists).
3. Within each bucket, compute pairwise Jaccard overlap on track-ID sets.
4. Report exact matches, high overlap (≥0.8), and subset relationships.
"""
import json
import time
from pathlib import Path
from collections import defaultdict
import urllib.request
import urllib.parse
import urllib.error

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
    out, offset = [], 0
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
    ids, offset = [], 0
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


print("Fetching playlists...")
playlists = get_all_playlists()
print(f"Got {len(playlists)} playlists\n")

# Bucket by tracks_count
by_count = defaultdict(list)
for p in playlists:
    by_count[p.get("tracks_count", 0)].append({
        "id": str(p["id"]),
        "name": p["name"],
        "tracks": p.get("tracks_count", 0),
        "public": bool(p.get("is_public")),
    })

# Only buckets with ≥2 playlists need fetching for the strict same-count check.
# But we also want subset detection across counts, so fetch ALL non-empty playlists.
fetch_targets = [p for p in playlists if p.get("tracks_count", 0) > 0]
print(f"Fetching track lists for {len(fetch_targets)} non-empty playlists...")

track_sets = {}
for i, p in enumerate(fetch_targets, 1):
    pid = str(p["id"])
    track_sets[pid] = get_track_ids(pid, p["tracks_count"])
    if i % 25 == 0:
        print(f"  {i}/{len(fetch_targets)}...")
    time.sleep(0.05)

print("\nDone fetching. Analyzing...\n")

playlists_by_id = {str(p["id"]): p for p in playlists}

# === Same-count exact / near matches ===
exact_pairs = []        # identical track sets
near_pairs = []         # Jaccard ≥ 0.8 within same bucket
for count, group in by_count.items():
    if count == 0 or len(group) < 2:
        continue
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            a, b = group[i], group[j]
            sa, sb = track_sets.get(a["id"], set()), track_sets.get(b["id"], set())
            if not sa or not sb:
                continue
            inter = len(sa & sb)
            union = len(sa | sb)
            jac = inter / union if union else 0
            if sa == sb:
                exact_pairs.append((a, b))
            elif jac >= 0.8:
                near_pairs.append((a, b, jac, inter, union))

# === Subset relationships across all counts ===
# Skip pairs already flagged as exact/near
flagged = set()
for a, b in exact_pairs:
    flagged.add(frozenset([a["id"], b["id"]]))
for a, b, *_ in near_pairs:
    flagged.add(frozenset([a["id"], b["id"]]))

subset_pairs = []  # (smaller, larger, coverage)
ids = list(track_sets.keys())
# To bound work: only check subset if smaller has ≥10 tracks AND ≥80% of its tracks are in the larger
for i in range(len(ids)):
    for j in range(len(ids)):
        if i == j:
            continue
        sa = track_sets[ids[i]]
        sb = track_sets[ids[j]]
        if len(sa) < 10 or len(sa) >= len(sb):
            continue
        if frozenset([ids[i], ids[j]]) in flagged:
            continue
        inter = len(sa & sb)
        if inter / len(sa) >= 0.8:
            coverage = inter / len(sa)
            subset_pairs.append((ids[i], ids[j], coverage, inter, len(sa)))

# Print results
print("=" * 80)
print(f"EXACT DUPLICATES (same track-ID set, different names): {len(exact_pairs)}")
print("=" * 80)
for a, b in exact_pairs:
    print(f"  [{a['tracks']}t]")
    print(f"    {a['id']:>10}  {a['name']!r}  ({'pub' if a['public'] else 'priv'})")
    print(f"    {b['id']:>10}  {b['name']!r}  ({'pub' if b['public'] else 'priv'})")

print()
print("=" * 80)
print(f"NEAR-DUPLICATES (same count, Jaccard ≥ 0.8): {len(near_pairs)}")
print("=" * 80)
for a, b, jac, inter, union in sorted(near_pairs, key=lambda x: -x[2]):
    print(f"  [{a['tracks']}t each, jaccard={jac:.2f}, {inter}/{union} shared]")
    print(f"    {a['id']:>10}  {a['name']!r}")
    print(f"    {b['id']:>10}  {b['name']!r}")

print()
print("=" * 80)
print(f"SUBSET CANDIDATES (smaller is ≥80% inside larger, different counts): {len(subset_pairs)}")
print("=" * 80)
for sm, lg, cov, inter, sm_size in sorted(subset_pairs, key=lambda x: -x[2]):
    sp = playlists_by_id[sm]
    lp = playlists_by_id[lg]
    print(f"  {cov*100:.0f}% coverage ({inter}/{sm_size}):")
    print(f"    SMALL  {sm:>10}  [{sp['tracks_count']}t]  {sp['name']!r}")
    print(f"    LARGE  {lg:>10}  [{lp['tracks_count']}t]  {lp['name']!r}")
