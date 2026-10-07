"""Connect a LinkedIn account without giving the app your password.

"Connect LinkedIn" opens a real browser window with a dedicated profile stored in
data/linkedin-browser-profile. You sign in there yourself (2FA and checks work as
usual). The app only watches for the session cookie to appear, then closes the
window. Later collections reuse that saved browser profile.
"""
from __future__ import annotations

import shutil
import threading
import time
from typing import Optional

from .. import config, db

_state_lock = threading.Lock()
_login_state = {"status": "idle", "message": ""}   # idle | waiting | connected | failed | cancelled

LOGIN_TIMEOUT_SECONDS = 300
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def is_connected() -> bool:
    if not config.LINKEDIN_PROFILE_DIR.exists():
        return False
    with db.session() as conn:
        return db.get_settings(conn).get("linkedin_connected") == "1"


def connection_info() -> dict:
    with db.session() as conn:
        s = db.get_settings(conn)
    with _state_lock:
        state = dict(_login_state)
    return {
        "connected": is_connected(),
        "connected_at": s.get("linkedin_connected_at") or "",
        "note": s.get("linkedin_note") or "",
        "login": state,
    }


def _set_state(status: str, message: str = "") -> None:
    with _state_lock:
        _login_state.update(status=status, message=message)


def mark_connected() -> None:
    with db.session() as conn:
        db.set_setting(conn, "linkedin_connected", "1")
        db.set_setting(conn, "linkedin_connected_at", db.now_iso())
        db.set_setting(conn, "linkedin_note", "")


def mark_disconnected(note: str = "") -> None:
    with db.session() as conn:
        db.set_setting(conn, "linkedin_connected", "0")
        db.set_setting(conn, "linkedin_note", note)
        if db.get_settings(conn).get("linkedin_mode") == "logged_in":
            db.set_setting(conn, "linkedin_mode", "public")


def disconnect() -> None:
    mark_disconnected("")
    shutil.rmtree(config.LINKEDIN_PROFILE_DIR, ignore_errors=True)


def _launch_sync(p, headless: bool):
    config.LINKEDIN_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kwargs = dict(user_data_dir=str(config.LINKEDIN_PROFILE_DIR), headless=headless, args=LAUNCH_ARGS, viewport=None)
    try:
        # Prefer the user's installed Google Chrome: it looks like a normal browser to LinkedIn.
        return p.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception:
        return p.chromium.launch_persistent_context(**kwargs)


async def launch_async(p, headless: bool):
    config.LINKEDIN_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    kwargs = dict(user_data_dir=str(config.LINKEDIN_PROFILE_DIR), headless=headless, args=LAUNCH_ARGS, viewport=None)
    try:
        return await p.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception:
        return await p.chromium.launch_persistent_context(**kwargs)


def _has_session_cookie(context) -> bool:
    return any(c.get("name") == "li_at" and c.get("value") for c in context.cookies("https://www.linkedin.com"))


def _login_worker() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _set_state("failed", "Playwright is not installed. Run ./run.sh again to install it.")
        return
    try:
        with sync_playwright() as p:
            context = _launch_sync(p, headless=False)
            closed = {"v": False}
            context.on("close", lambda *_: closed.__setitem__("v", True))
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.linkedin.com/login")
            deadline = time.time() + LOGIN_TIMEOUT_SECONDS
            while time.time() < deadline:
                if closed["v"]:
                    _set_state("cancelled", "The browser window was closed before sign-in finished.")
                    return
                try:
                    if _has_session_cookie(context) and "/login" not in page.url and "/checkpoint" not in page.url:
                        mark_connected()
                        _set_state("connected", "LinkedIn connected.")
                        time.sleep(1.5)
                        context.close()
                        return
                except Exception:
                    if closed["v"]:
                        _set_state("cancelled", "The browser window was closed before sign-in finished.")
                        return
                time.sleep(1)
            _set_state("failed", "Timed out waiting for sign-in (5 minutes).")
            context.close()
    except Exception as exc:  # pragma: no cover - depends on local browser
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            msg = "The browser for LinkedIn sign-in isn't installed. Run ./run.sh again (it installs it)."
        _set_state("failed", msg[:500])


def start_login() -> dict:
    with _state_lock:
        if _login_state["status"] == "waiting":
            return dict(_login_state)
        _login_state.update(status="waiting", message="A browser window opened. Sign in to LinkedIn there.")
    threading.Thread(target=_login_worker, name="linkedin-login", daemon=True).start()
    with _state_lock:
        return dict(_login_state)


def login_state() -> dict:
    with _state_lock:
        return dict(_login_state)


def playwright_available() -> Optional[str]:
    try:
        import playwright  # noqa: F401
        return None
    except ImportError:
        return "Playwright is not installed."
