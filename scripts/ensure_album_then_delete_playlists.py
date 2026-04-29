#!/usr/bin/env python3
"""For each (album_id, playlist_id) pair:
1. Check if album is in user's favorites; if not, add it.
2. Delete the playlist.

Targets are hard-coded — this is a one-shot cleanup of 8 album-clone playlists.
"""
import json
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

# (album_id, album_label, playlist_id, playlist_label)
TARGETS = [
    ("k57fsw0n6y8da",  "Decemberists — What A Terrible World, What A Beautiful World", 44812858, "What A Terrible World, What A Beautiful World"),
    ("0886443927087",  "Daft Punk — Random Access Memories",                            44812735, "Random Access Memories"),
    ("v8b2ybjf0wqeb",  "Nick Cave & The Bad Seeds — Ghosteen",                          44811946, "Nick Cave Playlist"),
    ("yp48yz190i87a",  "Get The Blessing — Lope and Antilope",                          44810410, "Get The Blessing – Lope and Antilope"),
    ("0886446538617",  "Arcade Fire — Everything Now",                                  44809931, "Arcade Fire"),
    ("0652637353051",  "EL VY — Return to the Moon",                                    44809790, "El Vy"),
    ("5099923203853",  "Massive Attack — Blue Lines",                                   11927545, "Massive Attack - Blue Lines"),
    ("0889176452642",  "The Glitch Mob — Love Death Immortality (Remixes)",             11927681, "Love Death Immortality Remixes"),
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


def api_post(endpoint, params):
    params = {**params, "app_id": APP_ID}
    data = urllib.parse.urlencode(params).encode()
    url = f"{BASE}/{endpoint}"
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    return _do(req)


def get_favorited_album_ids():
    """Return set of all favorited album IDs."""
    ids = set()
    offset = 0
    while True:
        d = api_get("favorite/getUserFavorites",
                    {"user_id": USER_ID, "type": "albums", "limit": 500, "offset": offset})
        items = (d.get("albums") or {}).get("items") or []
        if not items:
            break
        for a in items:
            ids.add(str(a.get("id")))
        if len(items) < 500:
            break
        offset += 500
    return ids


print("Fetching favorited albums...")
favorites = get_favorited_album_ids()
print(f"You have {len(favorites)} favorited albums.\n")

for album_id, album_label, playlist_id, playlist_label in TARGETS:
    print(f"--- {album_label}")
    if album_id in favorites:
        print(f"   album already favorited (id={album_id}) — skipping add")
    else:
        print(f"   album NOT in favorites (id={album_id}) — adding...")
        try:
            res = api_post("favorite/create", {"album_ids": album_id})
            print(f"   add response: {res}")
        except Exception as e:
            print(f"   ERROR adding album: {e}")
            print(f"   SKIPPING playlist delete to be safe")
            continue
        time.sleep(0.2)

    print(f"   deleting playlist {playlist_id} ({playlist_label!r})...")
    try:
        res = api_post("playlist/delete", {"playlist_id": str(playlist_id)})
        print(f"   delete response: {res}")
    except Exception as e:
        print(f"   ERROR deleting playlist: {e}")
    print()
    time.sleep(0.2)

print("Done.")
