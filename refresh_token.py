#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "playwright>=1.40.0",
# ]
# ///
"""
Qobuz token refresher.

Uses a persistent Playwright browser profile to capture the X-User-Auth-Token
from qobuz.com network requests. The session cookie set by manual login persists
between runs, so subsequent refreshes are headless and unattended.

Usage:
  # First-time setup — opens browser visibly so you can log in (handles reCAPTCHA)
  uv run refresh_token.py --login

  # Subsequent refreshes — headless, uses saved session
  uv run refresh_token.py

Writes token + user_id to ~/.qobuz-mcp/token.json. Exits non-zero on failure.

Profile location: ~/.qobuz-mcp/browser-profile/
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

CONFIG_DIR = Path.home() / ".qobuz-mcp"
PROFILE_DIR = CONFIG_DIR / "browser-profile"
TOKEN_FILE = CONFIG_DIR / "token.json"

QOBUZ_PLAYER = "https://play.qobuz.com"
QOBUZ_LOGIN = "https://play.qobuz.com/login"


async def capture_token(headless: bool, timeout_s: int) -> tuple[str, str, str]:
    """Launch browser, capture token + user_id + app_id. Returns (token, user_id, app_id)."""
    CONFIG_DIR.mkdir(exist_ok=True)
    PROFILE_DIR.mkdir(exist_ok=True)

    captured: dict[str, str] = {}

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def on_request(req):
            tok = req.headers.get("x-user-auth-token")
            if tok and "token" not in captured:
                captured["token"] = tok
                captured["app_id"] = req.headers.get("x-app-id", "")

        async def on_response(resp):
            # Look for user_id in API responses
            if "user_id" in captured:
                return
            url = resp.url
            if "qobuz.com/api" not in url:
                return
            try:
                # Check URL params first (some endpoints include user_id=)
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(url).query)
                if "user_id" in qs and qs["user_id"][0]:
                    captured["user_id"] = qs["user_id"][0]
                    return
                # Otherwise look in JSON body
                ct = resp.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = await resp.json()
                # Common shapes: {user: {id: ...}}, {id: ...}, etc.
                if isinstance(body, dict):
                    if isinstance(body.get("user"), dict) and body["user"].get("id"):
                        captured["user_id"] = str(body["user"]["id"])
                    elif body.get("user_id"):
                        captured["user_id"] = str(body["user_id"])
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        if not headless:
            print("Opening Qobuz login page. Please log in manually...", file=sys.stderr)
            await page.goto(QOBUZ_LOGIN, wait_until="domcontentloaded")
            print("Waiting for token (max 5 min)...", file=sys.stderr)
            deadline = time.time() + 300
        else:
            await page.goto(QOBUZ_PLAYER, wait_until="domcontentloaded")
            deadline = time.time() + timeout_s

        # Wait until both token and user_id captured (or timeout)
        while time.time() < deadline:
            if "token" in captured and "user_id" in captured:
                break
            await asyncio.sleep(1)

        # If we got token but not user_id, navigate to player to trigger more API calls
        if "token" in captured and "user_id" not in captured:
            await page.goto(QOBUZ_PLAYER, wait_until="domcontentloaded")
            extra_deadline = time.time() + 15
            while time.time() < extra_deadline and "user_id" not in captured:
                await asyncio.sleep(1)

        await ctx.close()

        if "token" not in captured:
            raise RuntimeError(
                "Did not capture auth token. "
                + ("Login may have failed or session expired." if headless
                   else "Login did not complete in time.")
            )
        if "user_id" not in captured:
            raise RuntimeError("Captured token but could not resolve user_id from network traffic")

        return captured["token"], captured["user_id"], captured["app_id"]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Qobuz auth token")
    parser.add_argument(
        "--login", action="store_true",
        help="Open visible browser for manual login (first-time setup)"
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="Seconds to wait for token capture in headless mode (default 30)"
    )
    args = parser.parse_args()

    try:
        token, user_id, app_id = await capture_token(
            headless=not args.login,
            timeout_s=args.timeout,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    payload = {
        "user_auth_token": token,
        "user_id": user_id,
        "app_id": app_id,
        "refreshed_at": int(time.time()),
    }
    TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    TOKEN_FILE.chmod(0o600)
    print(f"OK: wrote token to {TOKEN_FILE} (user_id={user_id})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
