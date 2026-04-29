#!/usr/bin/env python3
"""Find playlists that are essentially a single album.

For each playlist, fetch tracks with album metadata, group by album_id,
report any playlist where ≥90% of tracks come from one album.
"""
import json
import time
from pathlib import Path
from collections import Counter
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


def get_track_albums(playlist_id, count):
    """Return list of (album_id, album_title, artist) per track."""
    rows, offset = [], 0
    while len(rows) < count:
        d = api_get("playlist/get",
                    {"playlist_id": playlist_id, "limit": 500, "offset": offset, "extra": "tracks"})
        items = d.get("tracks", {}).get("items", [])
        if not items:
            break
        for t in items:
            alb = t.get("album") or {}
            artist = (alb.get("artist") or {}).get("name") or ""
            rows.append((str(alb.get("id") or ""), alb.get("title") or "", artist))
        if len(items) < 500:
            break
        offset += 500
    return rows


print("Fetching playlists...")
playlists = get_all_playlists()
print(f"Got {len(playlists)} playlists\n")

# Skip very large playlists (> 500 tracks) — extremely unlikely to be single-album
candidates = [p for p in playlists if 3 <= p.get("tracks_count", 0) <= 500]
print(f"Scanning {len(candidates)} playlists (3-500 tracks)...\n")

clones = []  # (playlist_dict, dominant_album_id, dominant_album_title, dominant_artist, dominant_count, total)

for i, p in enumerate(candidates, 1):
    pid = str(p["id"])
    total = p["tracks_count"]
    try:
        rows = get_track_albums(pid, total)
    except Exception as e:
        print(f"  ERROR fetching {pid} {p['name']!r}: {e}")
        continue
    if not rows:
        continue
    counts = Counter(r[0] for r in rows if r[0])
    if not counts:
        continue
    top_id, top_n = counts.most_common(1)[0]
    frac = top_n / len(rows)
    if frac >= 0.9 and top_n >= 3:
        # Find title and artist for top album
        title = next((r[1] for r in rows if r[0] == top_id), "?")
        artist = next((r[2] for r in rows if r[0] == top_id), "?")
        clones.append((p, top_id, title, artist, top_n, len(rows), frac))
    if i % 25 == 0:
        print(f"  {i}/{len(candidates)}...")
    time.sleep(0.05)

print(f"\n{'='*80}")
print(f"ALBUM-CLONE PLAYLISTS (≥90% from single album, ≥3 tracks): {len(clones)}")
print(f"{'='*80}\n")

for p, alb_id, title, artist, top_n, total, frac in sorted(clones, key=lambda x: -x[6]):
    pct = int(frac * 100)
    print(f"  [{p['id']}] {p['name']!r}")
    print(f"     {top_n}/{total} tracks ({pct}%) from album: {artist} — {title!r} (album_id={alb_id})")
    print()
