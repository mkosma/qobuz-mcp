#!/usr/bin/env python3
"""For each favorited album that is NOT Hi-Res (16-bit or below), search
Qobuz catalog for a higher-quality release of the same album.

Match criteria:
- same artist (case-insensitive)
- same normalized title (after stripping edition/version tags)
- release year within ±1 of original (to allow remasters)
- candidate quality strictly better (Hi-Res preferred, or higher bit depth/rate)

Outputs both a console summary and a JSON file at /tmp/hires_upgrades.json
for downstream batch action.
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
    t = re.sub(r'\(.*?(deluxe|remaster|edition|version|expanded|anniversary|live|bonus|special|reissue|stereo|mono|hi-res|hires|24[-\s]?bit).*?\)', '', t)
    t = re.sub(r'\[.*?(deluxe|remaster|edition|version|expanded|anniversary|live|bonus|special|reissue|stereo|mono|hi-res|hires|24[-\s]?bit).*?\]', '', t)
    t = re.sub(r'\s*[-–—]\s*(deluxe|remaster|edition|version|expanded|anniversary|live|bonus|special|reissue|stereo|mono|hi-res|hires|24[-\s]?bit).*$', '', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    t = ' '.join(t.split())
    return t.strip()


def quality_tuple(a):
    bd = a.get("maximum_bit_depth") or 0
    sr = a.get("maximum_sampling_rate") or 0
    hires = bool(a.get("hires"))
    return (int(hires), bd, sr)


def quality_label(a):
    bd = a.get("maximum_bit_depth") or 0
    sr = a.get("maximum_sampling_rate") or 0
    hires = bool(a.get("hires"))
    return f"{bd}-bit/{sr}kHz" + (" Hi-Res" if hires else "")


def year_of(a):
    d = a.get("release_date_original") or a.get("release_date_stream") or ""
    return int(d[:4]) if d[:4].isdigit() else 0


print("Loading all favorited albums...")
favs = get_all_favorited_albums()
print(f"Got {len(favs)} favorited albums.")

# Filter to non-Hi-Res candidates
candidates = [a for a in favs if not a.get("hires") and a.get("streamable", True)]
print(f"{len(candidates)} non-Hi-Res candidates to check.\n")

upgrades = []
errors = 0

for i, a in enumerate(candidates, 1):
    artist = ((a.get("artist") or {}).get("name") or "").strip()
    title = (a.get("title") or "").strip()
    if not artist or not title:
        continue
    title_norm = normalize_title(title)
    fav_q = quality_tuple(a)
    fav_year = year_of(a)
    try:
        d = api_get("album/search", {"query": f"{artist} {title}", "limit": 15})
    except Exception as e:
        errors += 1
        if errors < 5:
            print(f"  search err for {artist!r}/{title!r}: {e}")
        continue
    items = (d.get("albums") or {}).get("items") or []
    best = None
    for cand in items:
        cand_artist = ((cand.get("artist") or {}).get("name") or "").strip()
        if cand_artist.lower() != artist.lower():
            continue
        if normalize_title(cand.get("title", "")) != title_norm:
            continue
        cand_year = year_of(cand)
        if fav_year and cand_year and abs(cand_year - fav_year) > 50:
            # Different release year by a lot — could be a wrong-album match. Allow remasters within reason.
            continue
        if not cand.get("streamable", True):
            continue
        cand_q = quality_tuple(cand)
        if cand_q > fav_q:
            if best is None or cand_q > quality_tuple(best):
                best = cand
    if best:
        upgrades.append({
            "favorited_id": str(a.get("id")),
            "favorited_title": title,
            "favorited_quality": quality_label(a),
            "favorited_year": fav_year,
            "favorited_tracks": a.get("tracks_count", 0),
            "artist": artist,
            "upgrade_id": str(best.get("id")),
            "upgrade_title": best.get("title"),
            "upgrade_quality": quality_label(best),
            "upgrade_year": year_of(best),
            "upgrade_tracks": best.get("tracks_count", 0),
            "upgrade_label": (best.get("label") or {}).get("name", "?"),
        })
    if i % 50 == 0:
        print(f"  scanned {i}/{len(candidates)}  upgrades found: {len(upgrades)}  errors: {errors}")
    time.sleep(0.05)

# Save JSON
out_path = Path("/tmp/hires_upgrades.json")
out_path.write_text(json.dumps(upgrades, indent=2))
print(f"\nWrote {out_path} ({len(upgrades)} candidates)")

print(f"\n{'='*80}")
print(f"HI-RES UPGRADES AVAILABLE: {len(upgrades)}")
print(f"{'='*80}\n")

# Sort: biggest quality jumps first (Hi-Res > 24-bit > etc)
def jump_size(u):
    # sort by upgrade quality tuple
    return (u["upgrade_quality"].count("Hi-Res"), u["upgrade_quality"])

for u in sorted(upgrades, key=lambda u: (-jump_size(u)[0], u["artist"], u["favorited_title"])):
    track_diff = ""
    if u["upgrade_tracks"] != u["favorited_tracks"]:
        track_diff = f"  [tracks: {u['favorited_tracks']} → {u['upgrade_tracks']}]"
    print(f"  {u['artist']} — {u['favorited_title']!r}")
    print(f"     have:    {u['favorited_id']:>15}  [{u['favorited_quality']}]  {u['favorited_year']}")
    print(f"     upgrade: {u['upgrade_id']:>15}  [{u['upgrade_quality']}]  {u['upgrade_year']}  {u['upgrade_label']}{track_diff}")
    print()

print(f"Total: {len(upgrades)} possible upgrades. JSON at {out_path}.")
