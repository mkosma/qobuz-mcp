# qobuz-mcp

A lightweight MCP server for searching and managing playlists on [Qobuz](https://www.qobuz.com). Designed for use with Claude (Desktop, Code, Cowork).

## Status

**Login is currently broken** (since ~2026-04-03). Qobuz is migrating their backend infrastructure and the `/user/login` API endpoint returns 401 for all third-party clients. This affects every project that uses the Qobuz API — streamrip, qobuz-dl, etc.

Tracking issues:
- [nathom/streamrip#954](https://github.com/nathom/streamrip/issues/954)
- [nathom/streamrip#956](https://github.com/nathom/streamrip/issues/956)
- [vitiko98/qobuz-dl#329](https://github.com/vitiko98/qobuz-dl/issues/329)

Once Qobuz restores API access, this server should work without changes.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

### Environment variables

| Variable | Description |
|---|---|
| `QOBUZ_APP_ID` | Qobuz application ID (from web player bundle) |
| `QOBUZ_APP_SECRET` | Qobuz application secret |
| `QOBUZ_USERNAME` | Your Qobuz account email |
| `QOBUZ_PASSWORD` | Your Qobuz account password |

### Claude Code

```bash
claude mcp add \
  -e QOBUZ_APP_ID=YOUR_APP_ID \
  -e QOBUZ_APP_SECRET=YOUR_SECRET \
  -e QOBUZ_USERNAME=you@example.com \
  -e "QOBUZ_PASSWORD=yourpassword" \
  -s user qobuz -- /opt/homebrew/bin/uv run /path/to/qobuz-mcp/server.py
```

### Claude Desktop

Add to `~/.claude/mcp-servers.json`:

```json
{
  "qobuz": {
    "type": "stdio",
    "command": "/opt/homebrew/bin/uv",
    "args": ["run", "/path/to/qobuz-mcp/server.py"],
    "env": {
      "QOBUZ_APP_ID": "...",
      "QOBUZ_APP_SECRET": "...",
      "QOBUZ_USERNAME": "...",
      "QOBUZ_PASSWORD": "..."
    }
  }
}
```

## Available tools

- `qobuz_search` — search for tracks, albums, artists, or playlists
- `get_user_playlists` — list your playlists
- `create_playlist` — create a new playlist
- `add_tracks_to_playlist` — add tracks to a playlist by ID
- `get_playlist` — get playlist details and track listing
- `get_track` — get detailed track metadata
- `qobuz_login` — explicitly test credentials

## App credentials

The app ID and secret can be extracted from [Qobuz's web player](https://play.qobuz.com) bundle.js. The [Qobuz-AppID-Secret-Tool](https://github.com/QobuzDL/Qobuz-AppID-Secret-Tool) automates this. These rotate periodically.

## License

MIT
