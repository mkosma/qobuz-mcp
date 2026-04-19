# qobuz-mcp

A lightweight MCP server for searching and managing playlists on [Qobuz](https://www.qobuz.com). Designed for use with Claude (Desktop, Code, Cowork).

## Status

Qobuz killed their `/user/login` API endpoint around 2026-04-03 during a backend cloud migration, replacing it with OAuth + reCAPTCHA that blocks all third-party clients. Affected projects include streamrip ([#954](https://github.com/nathom/streamrip/issues/954)), qobuz-dl ([#329](https://github.com/vitiko98/qobuz-dl/issues/329)), and this server.

**Workaround:** browser-based token capture. A persistent Playwright browser profile holds your Qobuz session; when the API returns 401, the server auto-launches a headless browser to capture a fresh `X-User-Auth-Token` and retries.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- Playwright Chromium: `uv run --with playwright playwright install chromium`

### One-time manual login

```bash
uv run refresh_token.py --login
```

This opens a Chromium window. Log in to Qobuz (handle reCAPTCHA). The script captures the token and saves the browser session to `~/.qobuz-mcp/browser-profile/` so future refreshes are headless.

The token is written to `~/.qobuz-mcp/token.json`. The MCP server reads it on startup.

### MCP config

Only `QOBUZ_APP_ID` and `QOBUZ_APP_SECRET` are needed in env vars now — auth comes from the token file.

#### Claude Code

```bash
claude mcp add \
  -e QOBUZ_APP_ID=YOUR_APP_ID \
  -e QOBUZ_APP_SECRET=YOUR_SECRET \
  -s user qobuz -- /opt/homebrew/bin/uv run /path/to/qobuz-mcp/server.py
```

#### Claude Desktop

`~/.claude/mcp-servers.json`:

```json
{
  "qobuz": {
    "type": "stdio",
    "command": "/opt/homebrew/bin/uv",
    "args": ["run", "/path/to/qobuz-mcp/server.py"],
    "env": {
      "QOBUZ_APP_ID": "...",
      "QOBUZ_APP_SECRET": "..."
    }
  }
}
```

## How auto-refresh works

1. Server starts, loads token from `~/.qobuz-mcp/token.json`.
2. On any API call returning 401, server runs `uv run refresh_token.py` (headless).
3. Refresh script launches Chromium with the saved profile, navigates to play.qobuz.com, intercepts the `X-User-Auth-Token` header from the player's API requests, and writes it to `token.json`.
4. Server reloads the token and retries the original request.

If the saved browser session itself has expired (likely months), the headless refresh fails — re-run `uv run refresh_token.py --login` to log in again.

## Available tools

- `qobuz_search` — search for tracks, albums, artists, or playlists
- `get_user_playlists` — list your playlists
- `create_playlist` — create a new playlist
- `add_tracks_to_playlist` — add tracks to a playlist by ID
- `get_playlist` — get playlist details and track listing
- `get_track` — get detailed track metadata
- `qobuz_login` — test/initialize auth
- `qobuz_refresh_token` — force a token refresh

## App credentials

Extract `QOBUZ_APP_ID` and `QOBUZ_APP_SECRET` from [Qobuz's web player](https://play.qobuz.com) `bundle.js`. The [Qobuz-AppID-Secret-Tool](https://github.com/QobuzDL/Qobuz-AppID-Secret-Tool) automates this. They rotate occasionally.

## Files

- `server.py` — the MCP server
- `refresh_token.py` — Playwright-based token refresh
- `~/.qobuz-mcp/token.json` — captured token (chmod 600)
- `~/.qobuz-mcp/browser-profile/` — persistent Chromium profile

## License

MIT
