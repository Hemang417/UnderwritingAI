"""Manages the MAHARERA live session token: obtaining it (via a human
solving a CAPTCHA in a real browser) and reading it back at request time.

This is deliberately NOT automated end-to-end. MAHARERA's detail API is
behind a CAPTCHA, and solving or bypassing CAPTCHAs is never something this
codebase does programmatically, under any circumstances. `setup_session()`
opens a real, visible browser window and waits for a human to solve it
exactly like any real site visitor would; it never attempts the CAPTCHA
itself. See scripts/setup_maharera_session.py for the one-off operational
entry point a human runs directly.

Ported from REDO_Platform/src/scraper/browser_client.py, adapted to this
project's own token storage location and read-fresh-every-time semantics
(see load_token) so a re-run of setup_session() takes effect on the very
next live lookup with no app restart or .env edit needed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_CAPTCHA_URL = "https://maharerait.maharashtra.gov.in/public/project/view/1"
_AUTH_ENDPOINT = "/api/maha-rera-login-service/login/authenticatePublic"
_CAPTCHA_TIMEOUT_MS = 90_000


class SessionSetupError(Exception):
    """Raised when the browser session cannot be established."""


def _token_path() -> Path:
    return Path(get_settings().maharera_token_file_path)


def setup_session() -> str:
    """Open a visible Chrome window, wait for a human to solve MAHARERA's
    CAPTCHA, capture the resulting JWT, and save it to disk.

    Requires `playwright install chromium` to have been run once on this
    machine (a one-time browser-binary download, separate from `pip
    install`).

    Returns:
        The JWT access token string.

    Raises:
        SessionSetupError: if playwright isn't installed, the CAPTCHA
            isn't solved in time, or the token can't be captured.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SessionSetupError(
            "playwright is not installed -- run: pip install playwright && playwright install chromium"
        ) from exc

    logger.info("Opening browser for MAHARERA CAPTCHA setup. A human must solve it within 90 seconds.")
    captured: dict = {}

    def on_response(response) -> None:
        if _AUTH_ENDPOINT in response.url and response.status == 200:
            try:
                data = response.json()
                token = data.get("responseObject", {}).get("accessToken")
                if token:
                    captured["token"] = token
                    captured["full_response"] = data
                    logger.info("JWT captured from authenticatePublic response")
            except Exception as exc:
                logger.debug("Could not parse auth response: %s", exc)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.on("response", on_response)

        page.goto(_CAPTCHA_URL, timeout=60_000)
        logger.info("Browser open. Solve the CAPTCHA now...")

        try:
            page.wait_for_selector("button:has-text('Submit')", state="hidden", timeout=_CAPTCHA_TIMEOUT_MS)
            logger.info("CAPTCHA solved. Waiting for page load...")
            page.wait_for_timeout(5_000)
        except Exception:
            logger.warning("CAPTCHA solve timeout. Proceeding with whatever was captured.")

        browser.close()

    if "token" not in captured:
        raise SessionSetupError(
            "JWT was not captured -- the CAPTCHA may not have been solved in time, or the "
            "authenticatePublic call did not complete."
        )

    _save_token(captured["full_response"])
    return captured["token"]


def _save_token(auth_response: dict) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(auth_response, fh, indent=2, default=str)
    logger.info("MAHARERA token saved to %s", path)


def load_token() -> str | None:
    """Read the current token fresh from disk on every call -- deliberately
    not cached alongside the rest of Settings, so a re-run of
    setup_session() takes effect immediately, not after a restart."""
    path = _token_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("responseObject", {}).get("accessToken")
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        logger.warning("Could not load MAHARERA token from %s: %s", path, exc)
        return None
