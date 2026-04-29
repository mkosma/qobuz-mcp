#!/usr/bin/env python3
"""For each given album_id, find duplicates in user's favorites
(same artist + similar title) and compare audio quality.

Reports which version is highest quality so the others can be removed.
"""
import json
import re
import time
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

TOKEN_DATA = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN = TOKEN_DATA["user_auth_token"]
APP_ID = TOKEN_DATA["app_id"]
USER_ID = TOKEN_DATA["user_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
HEADERS = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}

# Albums I just added — verify each isn't a lower-quality dupe of something already favorited
TARGET_IDS = [
    ("k57fsw0n6y8da", "The Decemberists — What A Terrible World, What A Beautiful World"),
    ("0886443927087", "Daft Punk — Random Access Memories"),
    ("0652637353051", "EL VY — Return to the Moon"),
    ("5099923203853", "Massive Attack — Blue Lines"),
    ("0889176452642", "The Glitch Mob — Love Death Immortality (Remixes)"),
]


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
    """Return list of album dicts (full metadata)."""
    out = []
    offset = 0
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
    """Strip parentheticals, edition tags, punctuation."""
    if not t:
        return ""
    t = t.lower()
    # Remove common edition tags
    t = re.sub(r'\(.*?(deluxe|remaster|edition|version|expanded|anniversary|live).*?\)', '', t)
    t = re.sub(r'\[.*?(deluxe|remaster|edition|version|expanded|anniversary|live).*?\]', '', t)
    t = re.sub(r'\s*-\s*(deluxe|remaster|edition|version|expanded|anniversary|live).*$', '', t)
    # Strip all punctuation and collapse whitespace
    t = re.sub(r'[^\w\s]', ' ', t)
    t = ' '.join(t.split())
    return t.strip()


def quality_summary(a):
    """Build a quality string + sortable tuple for an album."""
    # Common audio fields: maximum_bit_depth, maximum_sampling_rate, hires, hires_streamable
    bd = a.get("maximum_bit_depth") or 0
    sr = a.get("maximum_sampling_rate") or 0
    hires = bool(a.get("hires"))
    streamable = a.get("streamable", True)
    label = f"{bd}-bit / {sr} kHz"
    if hires:
        label += " (Hi-Res)"
    if not streamable:
        label += " [NOT STREAMABLE]"
    # Higher = better. Hi-Res > 24-bit/96 > 24-bit > 16-bit
    sort_key = (int(streamable), int(hires), bd or 0, sr or 0)
    return label, sort_key


print("Loading all favorited albums...")
favs = get_all_favorited_albums()
print(f"Got {len(favs)} favorited albums.\n")

# Build lookup: artist_name (lowered) → list of (album_id, title, normalized_title, full_dict)
from collections import defaultdict
by_artist = defaultdict(list)
for a in favs:
    artist = ((a.get("artist") or {}).get("name") or "").lower().strip()
    by_artist[artist].append(a)

for target_id, label in TARGET_IDS:
    print("=" * 80)
    print(label)
    print("=" * 80)
    target = next((a for a in favs if str(a.get("id")) == target_id), None)
    if not target:
        print(f"  ERR: target album_id={target_id} not found in favorites")
        print()
        continue
    target_artist = ((target.get("artist") or {}).get("name") or "").lower().strip()
    target_title_norm = normalize_title(target.get("title", ""))

    # Find candidates: same artist, similar title
    candidates = []
    for a in by_artist[target_artist]:
        a_title_norm = normalize_title(a.get("title", ""))
        if a_title_norm == target_title_norm:
            candidates.append(a)

    if len(candidates) <= 1:
        print(f"  No duplicate versions in favorites — only one copy. ✓")
        ql, _ = quality_summary(target)
        print(f"  Quality: {ql}")
        print()
        continue

    print(f"  FOUND {len(candidates)} versions in favorites:")
    ranked = sorted(candidates, key=lambda a: quality_summary(a)[1], reverse=True)
    for i, a in enumerate(ranked):
        marker = "★ HIGHEST" if i == 0 else "  remove?"
        is_target = " <-- just added" if str(a.get("id")) == target_id else ""
        ql, _ = quality_summary(a)
        print(f"    {marker}  {a.get('id')}  {a.get('title')!r}  [{ql}]{is_target}")
        # Extra info
        track_count = a.get("tracks_count", "?")
        release = a.get("release_date_original") or a.get("released_at") or "?"
        label_name = (a.get("label") or {}).get("name", "?")
        print(f"               {track_count} tracks, released {release}, label: {label_name}")
    print()
