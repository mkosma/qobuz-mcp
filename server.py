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
  QOBUZ_USERNAME    - Your Qobuz account email
  QOBUZ_PASSWORD    - Your Qobuz account password

To get app credentials, you can use credentials from open-source projects
like streamrip, or register at https://www.qobuz.com/us-en/application/form
"""

import asyncio
import hashlib
import os
import time

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

# Cached auth token and user id
_auth_token: str = ""
_user_id: str = ""


def text(s: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=s)]


def _request_sig(endpoint_path: str, params: dict, ts: int) -> str:
    """
    Build the HMAC-style request signature Qobuz needs for some endpoints.
    sig = md5(endpoint_path_no_slashes + sorted_params_values + ts + app_secret)
    """
    # Strip leading slash and replace remaining with empty
    path = endpoint_path.lstrip("/").replace("/", "")
    sorted_vals = "".join(str(v) for _, v in sorted(params.items()) if v)
    raw = f"{path}{sorted_vals}{ts}{APP_SECRET}"
    return hashlib.md5(raw.encode()).hexdigest()


async def _login() -> tuple[bool, str]:
    """Authenticate and cache the token. Returns (success, error_msg)."""
    global _auth_token, _user_id
    if not all([APP_ID, APP_SECRET, USERNAME, PASSWORD]):
        return False, (
            "Missing credentials. Set QOBUZ_APP_ID, QOBUZ_APP_SECRET, "
            "QOBUZ_USERNAME, QOBUZ_PASSWORD environment variables."
        )
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
                msg = data.get("message", str(data))
                return False, f"Login failed: {msg}"
            _auth_token = data["user_auth_token"]
            _user_id = str(data["user"]["id"])
            return True, ""
        except Exception as e:
            return False, f"Login error: {e}"


async def _ensure_auth() -> tuple[bool, str]:
    """Ensure we have a valid auth token, logging in if needed."""
    global _auth_token
    if _auth_token:
        return True, ""
    return await _login()


async def _get(endpoint: str, params: dict | None = None, signed: bool = False) -> dict:
    """Make an authenticated GET request to the Qobuz API."""
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
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{QOBUZ_BASE}/{endpoint.lstrip('/')}",
                params=p,
                headers=headers,
                timeout=20,
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


async def _post(endpoint: str, data: dict | None = None) -> dict:
    """Make an authenticated POST request to the Qobuz API."""
    ok, err = await _ensure_auth()
    if not ok:
        return {"error": err}
    d = dict(data or {})
    d["app_id"] = APP_ID
    headers = {"X-User-Auth-Token": _auth_token, "X-App-Id": APP_ID}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{QOBUZ_BASE}/{endpoint.lstrip('/')}",
                data=d,
                headers=headers,
                timeout=20,
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


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
                "Authenticate with Qobuz and cache the session token. "
                "Called automatically on first use, but you can call this "
                "explicitly to test credentials."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    if name == "qobuz_login":
        ok, err = await _login()
        if ok:
            return text(f"Logged in successfully. User ID: {_user_id}")
        return text(f"Login failed: {err}")

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
