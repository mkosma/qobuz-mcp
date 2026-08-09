#!/usr/bin/env python3
"""Qobuz API performance baseline.

Server-side perf only — measures wall-clock latency and result counts for
queries the Qobuz API supports natively. No client-side joins or filters.
Each test runs once for warmup, then 3 timed runs; reports best-of-3.
"""
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

TOKEN_DATA = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN = TOKEN_DATA["user_auth_token"]
APP_ID = TOKEN_DATA["app_id"]
USER_ID = TOKEN_DATA["user_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
HEADERS = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}


def api_get(endpoint, params):
    params = {**params, "app_id": APP_ID}
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=HEADERS), timeout=60).read())


def best_of_3(fn):
    """Prime once, then 3 timed runs, return (best_ms, count, notes)."""
    fn()  # prime
    runs = []
    for _ in range(3):
        t0 = time.perf_counter()
        try:
            count, notes = fn()
        except Exception as e:
            return (0, 0, f"ERROR: {e}")
        ms = int((time.perf_counter() - t0) * 1000)
        runs.append((ms, count, notes))
        time.sleep(0.2)
    runs.sort(key=lambda x: x[0])
    return runs[0]


# --- Q1: list first 500 favorited albums ---
def q1():
    d = api_get("favorite/getUserFavorites",
                {"user_id": USER_ID, "type": "albums", "limit": 500, "offset": 0})
    items = (d.get("albums") or {}).get("items") or []
    return (len(items), "")


# --- Q2: list ALL favorited albums (paged) ---
def q2():
    out, offset, pages = [], 0, 0
    while True:
        d = api_get("favorite/getUserFavorites",
                    {"user_id": USER_ID, "type": "albums", "limit": 500, "offset": offset})
        items = (d.get("albums") or {}).get("items") or []
        pages += 1
        if not items:
            break
        out.extend(items)
        if len(items) < 500:
            break
        offset += 500
    return (len(out), f"{pages} pages")


# --- Q3: get one album with all tracks ---
def q3():
    # Use a known good album from R.E.M. Murmur Hi-Res added during the cleanup
    aid = "0060253782280"
    d = api_get("album/get", {"album_id": aid})
    tracks = (d.get("tracks") or {}).get("items") or []
    return (len(tracks), f"album={d.get('title')}")


# --- Q4: search "Murmur" catalog ---
def q4():
    d = api_get("album/search", {"query": "Murmur", "limit": 10})
    items = (d.get("albums") or {}).get("items") or []
    return (len(items), "")


# --- Q5: get artist + their albums ---
def q5():
    # Search for Built To Spill to get an artist_id, then fetch with extras
    s = api_get("artist/search", {"query": "Built To Spill", "limit": 5})
    arts = (s.get("artists") or {}).get("items") or []
    if not arts:
        return (0, "no artist found")
    aid = arts[0].get("id")
    d = api_get("artist/get", {"artist_id": aid, "extra": "albums"})
    albums = ((d.get("albums") or {}).get("items")) or []
    return (len(albums), f"artist={d.get('name')}")


# --- Q6: get one playlist with tracks ---
def q6():
    # Use the user's "DM Remixes" playlist that we just renamed
    pid = 44811097
    d = api_get("playlist/get", {"playlist_id": pid, "limit": 500, "offset": 0, "extra": "tracks"})
    tracks = (d.get("tracks") or {}).get("items") or []
    return (len(tracks), f"playlist={d.get('name')}")


TESTS = [
    ("Q1", "List first 500 favorited albums (limit=500)", q1),
    ("Q2", "List ALL favorited albums (paged 500)", q2),
    ("Q3", "Get one album with track listing", q3),
    ("Q4", "Search 'Murmur' (limit=10)", q4),
    ("Q5", "Get artist + albums (Built To Spill)", q5),
    ("Q6", "Get one playlist with tracks", q6),
]


def main():
    print("\n# Qobuz API perf baseline\n")
    print("| Test | Description | Best ms | Count | Notes |")
    print("|---|---|---:|---:|---|")
    for tid, desc, fn in TESTS:
        ms, count, notes = best_of_3(fn)
        print(f"| {tid} | {desc} | {ms} | {count} | {notes} |")
    print()


if __name__ == "__main__":
    main()
