#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp>=1.0.0",
#   "httpx>=0.27.0",
# ]
# ///
"""
Qobuz MCP Server
Provides search, playlist creation, and track management for Qobuz.

Required environment variables:
  QOBUZ_APP_ID      - Qobuz application ID
  QOBUZ_APP_SECRET  - Qobuz application secret

Authentication (in priority order):
  1. Token file at ~/.qobuz-mcp/token.json (auto-refreshed via refresh_token.py)
  2. QOBUZ_USER_AUTH_TOKEN + QOBUZ_USER_ID env vars
  3. QOBUZ_USERNAME + QOBUZ_PASSWORD (broken since ~April 2026)

When a request returns 401, the server auto-runs refresh_token.py to fetch a
fresh token from the persistent browser session, then retries.
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

server = Server("qobuz-mcp")

QOBUZ_BASE = "https://www.qobuz.com/api.json/0.2"
APP_ID = os.environ.get("QOBUZ_APP_ID", "")
APP_SECRET = os.environ.get("QOBUZ_APP_SECRET", "")
USERNAME = os.environ.get("QOBUZ_USERNAME", "")
PASSWORD = os.environ.get("QOBUZ_PASSWORD", "")

TOKEN_FILE = Path.home() / ".qobuz-mcp" / "token.json"
REFRESH_SCRIPT = Path(__file__).parent / "refresh_token.py"
UV_BIN = "/opt/homebrew/bin/uv"

_auth_token: str = os.environ.get("QOBUZ_USER_AUTH_TOKEN", "")
_user_id: str = os.environ.get("QOBUZ_USER_ID", "")


def _load_token_file() -> bool:
    """Load token from disk if present and newer/different than current."""
    global _auth_token, _user_id, APP_ID
    if not TOKEN_FILE.exists():
        return False
    try:
        data = json.loads(TOKEN_FILE.read_text())
        _auth_token = data.get("user_auth_token", "") or _auth_token
        _user_id = str(data.get("user_id", "")) or _user_id
        APP_ID = data.get("app_id", "") or APP_ID
        return bool(_auth_token and _user_id)
    except Exception as e:
        print(f"Failed to load token file: {e}", file=sys.stderr)
        return False


# Prefer token file over env vars (it's auto-refreshed)
_load_token_file()


def text(s: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=s)]


def _request_sig(endpoint_path: str, params: dict, ts: int) -> str:
    """
    Build the HMAC-style request signature Qobuz needs for some endpoints.
    sig = md5(endpoint_path_no_slashes + sorted_params_values + ts + app_secret)
    """
    path = endpoint_path.lstrip("/").replace("/", "")
    sorted_vals = "".join(str(v) for _, v in sorted(params.items()) if v)
    raw = f"{path}{sorted_vals}{ts}{APP_SECRET}"
    return hashlib.md5(raw.encode()).hexdigest()


async def _refresh_token() -> tuple[bool, str]:
    """Run refresh_token.py to get a new token. Returns (success, message)."""
    if not REFRESH_SCRIPT.exists():
        return False, f"Refresh script not found at {REFRESH_SCRIPT}"
    try:
        proc = await asyncio.create_subprocess_exec(
            UV_BIN, "run", str(REFRESH_SCRIPT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            return False, "Refresh script timed out (60s)"
        if proc.returncode != 0:
            return False, f"Refresh failed: {stderr.decode()[:500]}"
        if not _load_token_file():
            return False, "Refresh ran but token file missing/invalid"
        return True, "Token refreshed"
    except Exception as e:
        return False, f"Refresh error: {e}"


async def _password_login() -> tuple[bool, str]:
    """Legacy password login. Broken since ~April 2026."""
    global _auth_token, _user_id
    if not all([APP_ID, USERNAME, PASSWORD]):
        return False, "No credentials for password login"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{QOBUZ_BASE}/user/login",
                params={"app_id": APP_ID},
                data={
                    "username": USERNAME,
                    "password": hashlib.md5(PASSWORD.encode()).hexdigest(),
                    "app_id": APP_ID,
                },
                timeout=15,
            )
            data = resp.json()
            if "user_auth_token" not in data:
                return False, f"Login failed: {data.get('message', str(data))}"
            _auth_token = data["user_auth_token"]
            _user_id = str(data["user"]["id"])
            return True, ""
        except Exception as e:
            return False, f"Login error: {e}"


async def _ensure_auth() -> tuple[bool, str]:
    """Ensure we have a valid auth token, refreshing or logging in if needed."""
    if _auth_token and _user_id:
        return True, ""
    if TOKEN_FILE.exists() and _load_token_file():
        return True, ""
    ok, msg = await _refresh_token()
    if ok:
        return True, ""
    if USERNAME and PASSWORD:
        return await _password_login()
    return False, (
        "No auth token available. Run: uv run refresh_token.py --login "
        f"(refresh attempt: {msg})"
    )


def _is_auth_error(data: dict) -> bool:
    """Detect Qobuz 401-style auth errors in JSON responses."""
    if data.get("code") == 401:
        return True
    msg = str(data.get("message", "")).lower()
    return "authentication" in msg or "auth_required" in msg


async def _request(method: str, endpoint: str, params: dict | None = None,
                   data: dict | None = None, signed: bool = False,
                   _retried: bool = False) -> dict:
    """Make an authenticated request, auto-refreshing on 401."""
    ok, err = await _ensure_auth()
    if not ok:
        return {"error": err}
    p = dict(params or {})
    p["app_id"] = APP_ID
    if signed:
        ts = int(time.time())
        p["request_ts"] = ts
        p["request_sig"] = _request_sig(endpoint, p, ts)
    headers = {"X-User-Auth-Token": _auth_token, "X-App-Id": APP_ID}
    url = f"{QOBUZ_BASE}/{endpoint.lstrip('/')}"
    async with httpx.AsyncClient() as client:
        try:
            if method == "GET":
                resp = await client.get(url, params=p, headers=headers, timeout=20)
            else:
                d = dict(data or {})
                d["app_id"] = APP_ID
                resp = await client.post(url, params=p, data=d, headers=headers, timeout=20)
            result = resp.json()
        except Exception as e:
            return {"error": str(e)}

    if _is_auth_error(result) and not _retried:
        global _auth_token
        _auth_token = ""  # force refresh
        ok, msg = await _refresh_token()
        if ok:
            return await _request(method, endpoint, params, data, signed, _retried=True)
        return {"error": f"Auth failed and refresh unsuccessful: {msg}"}

    return result


async def _get(endpoint: str, params: dict | None = None, signed: bool = False) -> dict:
    return await _request("GET", endpoint, params=params, signed=signed)


async def _post(endpoint: str, data: dict | None = None) -> dict:
    return await _request("POST", endpoint, data=data)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="qobuz_search",
            description=(
                "Search Qobuz for tracks, albums, or artists. "
                "Returns up to `limit` results with IDs, names, and metadata."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "type": {
                        "type": "string",
                        "enum": ["tracks", "albums", "artists", "playlists"],
                        "description": "Type of content to search for (default: tracks)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 10, max 50)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_user_playlists",
            description="List the current user's Qobuz playlists.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max playlists to return (default 20)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="create_playlist",
            description="Create a new Qobuz playlist.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Playlist name"},
                    "description": {
                        "type": "string",
                        "description": "Optional playlist description",
                    },
                    "is_public": {
                        "type": "boolean",
                        "description": "Whether the playlist is public (default false)",
                        "default": False,
                    },
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="add_tracks_to_playlist",
            description=(
                "Add one or more tracks to a Qobuz playlist by track ID. "
                "Use qobuz_search to find track IDs first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "playlist_id": {
                        "type": "string",
                        "description": "Qobuz playlist ID",
                    },
                    "track_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Qobuz track IDs to add",
                    },
                },
                "required": ["playlist_id", "track_ids"],
            },
        ),
        types.Tool(
            name="get_playlist",
            description="Get details and track listing for a Qobuz playlist.",
            inputSchema={
                "type": "object",
                "properties": {
                    "playlist_id": {
                        "type": "string",
                        "description": "Qobuz playlist ID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max tracks to return (default 50)",
                        "default": 50,
                    },
                },
                "required": ["playlist_id"],
            },
        ),
        types.Tool(
            name="get_track",
            description="Get detailed metadata for a specific Qobuz track by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "track_id": {"type": "string", "description": "Qobuz track ID"},
                },
                "required": ["track_id"],
            },
        ),
        types.Tool(
            name="qobuz_login",
            description=(
                "Authenticate with Qobuz. Loads token from ~/.qobuz-mcp/token.json, "
                "or runs refresh_token.py to fetch one. Auto-called on first use."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="qobuz_refresh_token",
            description=(
                "Force-refresh the Qobuz auth token by running the headless "
                "browser refresh script. Use when search/playback is failing "
                "with auth errors."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    if name == "qobuz_login":
        ok, err = await _ensure_auth()
        if ok:
            return text(f"Authenticated. User ID: {_user_id}")
        return text(f"Login failed: {err}")

    if name == "qobuz_refresh_token":
        ok, msg = await _refresh_token()
        if ok:
            return text(f"Token refreshed. User ID: {_user_id}")
        return text(
            f"Refresh failed: {msg}\n\n"
            "If this is the first run or your saved session has expired, "
            "run manually: uv run refresh_token.py --login"
        )

    if name == "qobuz_search":
        query = arguments.get("query", "").strip()
        search_type = arguments.get("type", "tracks")
        limit = min(int(arguments.get("limit", 10)), 50)
        if not query:
            return text("Error: query is required.")
        data = await _get(
            "catalog/search",
            {"query": query, "type": search_type, "limit": limit, "offset": 0},
        )
        if "error" in data:
            return text(f"Error: {data['error']}")
        results = data.get(search_type, {})
        items = results.get("items", [])
        if not items:
            return text(f"No {search_type} found for '{query}'.")
        lines = [f"Search results for '{query}' ({search_type}):"]
        for item in items:
            if search_type == "tracks":
                artist = item.get("performer", {}).get("name", "Unknown")
                album = item.get("album", {}).get("title", "")
                lines.append(
                    f"  ID: {item['id']} | {item.get('title', '?')} — {artist}"
                    + (f" [{album}]" if album else "")
                )
            elif search_type == "albums":
                artist = item.get("artist", {}).get("name", "Unknown")
                lines.append(
                    f"  ID: {item['id']} | {item.get('title', '?')} — {artist} "
                    f"({item.get('released_at', '')[:4] if item.get('released_at') else ''})"
                )
            elif search_type == "artists":
                lines.append(f"  ID: {item['id']} | {item.get('name', '?')}")
            elif search_type == "playlists":
                owner = item.get("owner", {}).get("name", "?")
                count = item.get("tracks_count", 0)
                lines.append(
                    f"  ID: {item['id']} | {item.get('name', '?')} by {owner} ({count} tracks)"
                )
        return text("\n".join(lines))

    if name == "get_user_playlists":
        limit = int(arguments.get("limit", 20))
        ok, err = await _ensure_auth()
        if not ok:
            return text(f"Auth error: {err}")
        data = await _get(
            "playlist/getUserPlaylists",
            {"user_id": _user_id, "limit": limit, "offset": 0, "extra": "tracks"},
        )
        if "error" in data:
            return text(f"Error: {data['error']}")
        playlists = data.get("playlists", {}).get("items", [])
        if not playlists:
            return text("No playlists found.")
        lines = [f"Your Qobuz playlists ({len(playlists)}):"]
        for pl in playlists:
            count = pl.get("tracks_count", 0)
            pub = "public" if pl.get("is_public") else "private"
            lines.append(f"  ID: {pl['id']} | {pl.get('name', '?')} ({count} tracks, {pub})")
        return text("\n".join(lines))

    if name == "create_playlist":
        name_ = arguments.get("name", "").strip()
        description = arguments.get("description", "")
        is_public = arguments.get("is_public", False)
        if not name_:
            return text("Error: name is required.")
        data = await _post(
            "playlist/create",
            {
                "name": name_,
                "description": description,
                "is_public": "1" if is_public else "0",
                "is_collaborative": "0",
            },
        )
        if "error" in data:
            return text(f"Error: {data['error']}")
        pl_id = data.get("id") or data.get("playlist", {}).get("id")
        if pl_id:
            return text(f"Playlist '{name_}' created successfully. ID: {pl_id}")
        return text(f"Unexpected response: {data}")

    if name == "add_tracks_to_playlist":
        playlist_id = str(arguments.get("playlist_id", "")).strip()
        track_ids = arguments.get("track_ids", [])
        if not playlist_id:
            return text("Error: playlist_id is required.")
        if not track_ids:
            return text("Error: track_ids list is required.")
        ids_str = ",".join(str(tid) for tid in track_ids)
        data = await _get(
            "playlist/addTracks",
            {"playlist_id": playlist_id, "track_ids": ids_str},
        )
        if "error" in data:
            return text(f"Error: {data['error']}")
        added = data.get("tracks_added", len(track_ids))
        return text(f"Added {added} track(s) to playlist {playlist_id}.")

    if name == "get_playlist":
        playlist_id = str(arguments.get("playlist_id", "")).strip()
        limit = int(arguments.get("limit", 50))
        if not playlist_id:
            return text("Error: playlist_id is required.")
        data = await _get(
            "playlist/get",
            {"playlist_id": playlist_id, "limit": limit, "offset": 0, "extra": "tracks"},
        )
        if "error" in data:
            return text(f"Error: {data['error']}")
        pl_name = data.get("name", "?")
        tracks = data.get("tracks", {}).get("items", [])
        lines = [f"Playlist: {pl_name} (ID: {playlist_id}, {len(tracks)} tracks shown)"]
        for i, tr in enumerate(tracks, 1):
            artist = tr.get("performer", {}).get("name", "?")
            lines.append(f"  {i}. {tr.get('title', '?')} — {artist} [ID: {tr.get('id')}]")
        return text("\n".join(lines))

    if name == "get_track":
        track_id = str(arguments.get("track_id", "")).strip()
        if not track_id:
            return text("Error: track_id is required.")
        data = await _get("track/get", {"track_id": track_id})
        if "error" in data:
            return text(f"Error: {data['error']}")
        artist = data.get("performer", {}).get("name", "?")
        album = data.get("album", {}).get("title", "?")
        dur = data.get("duration", 0)
        mins, secs = divmod(dur, 60)
        return text(
            f"Track: {data.get('title', '?')}\n"
            f"Artist: {artist}\n"
            f"Album: {album}\n"
            f"Duration: {mins}:{secs:02d}\n"
            f"ID: {data.get('id')}\n"
            f"ISRC: {data.get('isrc', 'N/A')}"
        )

    return text(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
