#!/usr/bin/env python3
"""Atomically swap a list of (old_album_id, new_album_id) pairs in favorites.
Adds the new album first, then removes the old. If add fails, skip the remove.
"""
import json
import sys
import time
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

TOKEN_DATA = json.load(open(Path.home() / ".qobuz-mcp" / "token.json"))
TOKEN = TOKEN_DATA["user_auth_token"]
APP_ID = TOKEN_DATA["app_id"]
BASE = "https://www.qobuz.com/api.json/0.2"
HEADERS = {"X-User-Auth-Token": TOKEN, "X-App-Id": APP_ID}


def post(endpoint, **params):
    params["app_id"] = APP_ID
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{BASE}/{endpoint}", data=data, headers=HEADERS, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


# (old_id, new_id, label)
SWAPS = [
    # Category 1 — clean swaps, same year, similar tracks
    ("tl5b6j817p75a",  "svmm08y2moec3",  "Aerosmith — Toys In The Attic"),
    ("vmogh6gh9wcpa",  "c3t7oglptvdpc",  "Afrika Bambaataa — Planet Rock"),
    ("y8h3hcicegn2b",  "tmec0lxgpoh1a",  "Elysian Fields — What Should I Say"),
    ("momzfj7nrz3ea",  "m8jcn0spavl3e",  "Jedi Mind Tricks — Best of"),
    ("gc5uq5r7gswjc",  "kfmecrafy1m7a",  "Paul Weller — True Meanings"),
    ("vm4dfm0bi2j4a",  "j3ynsqvy7a42b",  "Pixies — Trompe le Monde"),
    ("d6l6gtl3kwyab",  "0060253782280",  "R.E.M. — Murmur (24/192!)"),
    ("rpup01ep291pc",  "kvbsg8x9kijxc",  "Sonic Youth — Rather Ripped"),
    ("0093624994077", "0093624918646",  "Tegan And Sara — The Con (24/192!)"),
    ("ql0hj3sci7m0b",  "u3q1gdjebed6a",  "The Golden Palominos — Visions of Excess"),
    ("zmq945zuuiv2a",  "0060253774686",  "Tori Amos — Unrepentant Geraldines"),
    ("0724384893651", "jcvt1stsyi4bc",  "Smashing Pumpkins — Machina"),
    # Category 2 — Hi-Res with track expansion (deluxe / anniversary editions)
    ("oncrmw184dqlb",  "kxmqp83995ldc",  "Anne Dudley — Plays The Art Of Noise (2021 reissue)"),
    ("0036172007868", "ktckrad0zeskc",  "Calexico — Feast of Wire (16→27t)"),
    ("q7uxo0mjgw3uc",  "lp54ino03dngb",  "Elliot Moss — Highspeeds (13→18t)"),
    ("thgd6idr7el9b",  "bcba0qihelmgb",  "Fine Young Cannibals — Raw & Cooked (10→32t deluxe)"),
    ("ecbs09zs5u0tb",  "z2tmhhnr049eb",  "I Monster — Neveroddoreven (12→16t)"),
    ("0801061003630", "o5ukhemty5owb",  "Nightmares On Wax — Smokers Delight (16→20t)"),
    ("acg4j639ebtfc",  "rpybmqhcgs2wa",  "Nouvelle Vague — Bande à Part (14→23t)"),
    ("mi6cw0y98wiaa",  "nl2w3o783wneb",  "Nouvelle Vague — Nouvelle vague (13→25t)"),
    ("0607618007867", "bjmoo5s3wfbhb",  "The Icicle Works (14→18t)"),
    ("0081227407261", "whbazsfvqyggb",  "The Pogues — Rum Sodomy & The Lash (24/96, 18→25t)"),
    ("0018777376167", "gzfbc4kfyibib",  "The Replacements — Let It Be (24/96, 11→53t mega-deluxe)"),
    ("t7g05fm26d9fa",  "0060254714372",  "The Who — Who's Next (24/96, 9→16t)"),
]

print(f"Performing {len(SWAPS)} album swaps...\n")
success, failed = 0, 0
for old_id, new_id, label in SWAPS:
    print(f"--- {label}")
    try:
        add = post("favorite/create", album_ids=new_id)
        print(f"  add  {new_id} → {add}")
    except Exception as e:
        print(f"  ADD FAILED for {new_id}: {e} — skipping delete")
        failed += 1
        continue
    time.sleep(0.15)
    try:
        rm = post("favorite/delete", album_ids=old_id)
        print(f"  drop {old_id} → {rm}")
        success += 1
    except Exception as e:
        print(f"  DELETE FAILED for {old_id}: {e}")
        failed += 1
    time.sleep(0.15)

print(f"\nDone. {success} swaps complete, {failed} failed.")
