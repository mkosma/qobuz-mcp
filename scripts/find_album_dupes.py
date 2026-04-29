#!/usr/bin/env python3
"""Scan all favorited albums and find duplicates: same artist + same title
(after edition-tag normalization), multiple album_ids.

For each duplicate group, ranks by audio quality and shows which to keep.
"""
import json
import re
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


def get_all_favorited_albums():
    out, offset = [], 0
    while True:
        d = api_get("favorite/getUserFavorites",
                    {"user_id": USER_ID, "type": "albums", "limit": 500, "offset": offset})
        items = (d.get("albums") or {}).get("items") or []
        if not items:
            break
        out.extend(items)
        if len(items) < 500:
            break
        offset += 500
    return out


def normalize_title(t):
    if not t:
        return ""
    t = t.lower()
    # Strip common edition tags inside parens/brackets
    t = re.sub(r'\(.*?(deluxe|remaster|edition|version|expanded|anniversary|live|bonus|special|reissue|stereo|mono|hi-res|hires|24[-\s]?bit).*?\)', '', t)
    t = re.sub(r'\[.*?(deluxe|remaster|edition|version|expanded|anniversary|live|bonus|special|reissue|stereo|mono|hi-res|hires|24[-\s]?bit).*?\]', '', t)
    # Strip dash-suffix edition tags
    t = re.sub(r'\s*[-–—]\s*(deluxe|remaster|edition|version|expanded|anniversary|live|bonus|special|reissue|stereo|mono|hi-res|hires|24[-\s]?bit).*$', '', t)
    # Strip all punctuation, collapse whitespace
    t = re.sub(r'[^\w\s]', ' ', t)
    t = ' '.join(t.split())
    return t.strip()


def quality_summary(a):
    bd = a.get("maximum_bit_depth") or 0
    sr = a.get("maximum_sampling_rate") or 0
    hires = bool(a.get("hires"))
    streamable = a.get("streamable", True)
    label = f"{bd}-bit/{sr}kHz"
    if hires:
        label += " Hi-Res"
    if not streamable:
        label += " [NOT STREAMABLE]"
    sort_key = (int(streamable), int(hires), bd or 0, sr or 0)
    return label, sort_key


print("Loading all favorited albums...")
favs = get_all_favorited_albums()
print(f"Got {len(favs)} favorited albums.\n")

# Group by (artist, normalized_title)
groups = defaultdict(list)
for a in favs:
    artist = ((a.get("artist") or {}).get("name") or "").lower().strip()
    title_norm = normalize_title(a.get("title", ""))
    if not artist or not title_norm:
        continue
    groups[(artist, title_norm)].append(a)

dupes = {k: v for k, v in groups.items() if len(v) > 1}
print(f"Found {len(dupes)} duplicate-album groups ({sum(len(v) for v in dupes.values())} albums total).\n")

# Sort: largest groups first, then by artist
for (artist, title_norm), albums in sorted(dupes.items(), key=lambda x: (-len(x[1]), x[0])):
    ranked = sorted(albums, key=lambda a: quality_summary(a)[1], reverse=True)
    print(f"[{len(albums)}] {ranked[0].get('artist',{}).get('name','?')} — {title_norm!r}")
    for i, a in enumerate(ranked):
        marker = "★ KEEP   " if i == 0 else "  remove?"
        ql, _ = quality_summary(a)
        title = a.get("title", "?")
        tracks = a.get("tracks_count", "?")
        date = a.get("release_date_original") or "?"
        label_name = (a.get("label") or {}).get("name", "?")
        print(f"  {marker}  {a.get('id'):>15}  {title!r:50}  [{ql}]")
        print(f"             {tracks}t  {date}  {label_name}")
    print()
