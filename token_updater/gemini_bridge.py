"""Gemini cookie bridge for plugin sync payloads."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from typing import Any, Dict, Optional

from playwright.async_api import BrowserContext, async_playwright

from .browser import BROWSER_ARGS, browser_manager
from .config import config
from .logger import logger
from .proxy_utils import format_proxy_for_playwright, parse_proxy

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _is_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(value.strip()))


def _resolve_profile_dir(profile_id: int) -> str:
    return os.path.join(os.path.abspath(config.profiles_dir), f"profile_{profile_id}")


def _clean_locks(profile_dir: str) -> None:
    for lock_name in LOCK_FILES:
        lock_path = os.path.join(profile_dir, lock_name)
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except Exception:
                pass


def _build_proxy(profile: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not profile.get("proxy_enabled"):
        return None
    proxy_url = str(profile.get("proxy_url") or "").strip()
    if not proxy_url:
        return None
    parsed = parse_proxy(proxy_url)
    return format_proxy_for_playwright(parsed) if parsed else None


def _resolve_client_id(profile: Dict[str, Any]) -> str:
    profile_id = profile.get("id")
    if isinstance(profile_id, int):
        return f"profile-{profile_id}"
    return f"profile-{str(profile_id or 'unknown').strip()}"


def _resolve_identity_email(profile: Dict[str, Any], client_id: str) -> str:
    profile_email = str(profile.get("email") or "").strip().lower()
    if profile_email and _is_email(profile_email):
        return profile_email

    login_account = str(profile.get("login_account") or "").strip().lower()
    if login_account and _is_email(login_account):
        return login_account

    return client_id


def _encode_payload(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return f"gcu:v1:{encoded}"


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:1]}..."
    return f"{value[:4]}...{value[-4:]}"


class GeminiCookieBridge:
    """Extract Gemini cookies and convert them to plugin payload."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def build_plugin_session_token(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            cookies = await self._extract_cookie_pair(profile)
            secure_1psid = cookies.get("__Secure-1PSID")
            secure_1psidts = cookies.get("__Secure-1PSIDTS")
            if not secure_1psid or not secure_1psidts:
                return {
                    "success": False,
                    "error": "未提取到 __Secure-1PSID 或 __Secure-1PSIDTS，请先完成 Gemini 登录。",
                }

            client_id = _resolve_client_id(profile)
            email = _resolve_identity_email(profile, client_id)
            proxy = str(profile.get("proxy_url") or "").strip() if profile.get("proxy_enabled") else None

            payload = {
                "client_id": client_id,
                "email": email,
                "secure_1psid": secure_1psid,
                "secure_1psidts": secure_1psidts,
                "proxy": proxy or None,
            }
            session_token = _encode_payload(payload)
            logger.info(
                "[%s] Gemini 凭据提取成功: client_id=%s, email=%s, 1psid=%s, 1psidts=%s",
                profile.get("name"),
                client_id,
                email,
                _mask(secure_1psid),
                _mask(secure_1psidts),
            )
            return {
                "success": True,
                "session_token": session_token,
                "client_id": client_id,
                "email": email,
            }

    async def _extract_cookie_pair(self, profile: Dict[str, Any]) -> Dict[str, str]:
        active_profile_id = browser_manager.get_active_profile_id()
        profile_id = int(profile.get("id"))
        if active_profile_id == profile_id:
            active_context = getattr(browser_manager, "_active_context", None)
            if active_context is not None:
                return await self._read_cookie_pair_from_context(active_context)

        profile_dir = _resolve_profile_dir(profile_id)
        if not os.path.exists(profile_dir):
            return {}

        _clean_locks(profile_dir)
        proxy = _build_proxy(profile)

        playwright = await async_playwright().start()
        context: Optional[BrowserContext] = None
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=True,
                viewport={"width": 1024, "height": 768},
                locale="en-US",
                timezone_id="America/New_York",
                proxy=proxy,
                args=BROWSER_ARGS,
                ignore_default_args=["--enable-automation"],
            )

            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(config.labs_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                # Cookie may still be available even if navigation fails.
                pass

            return await self._read_cookie_pair_from_context(context)
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            try:
                await playwright.stop()
            except Exception:
                pass

    async def _read_cookie_pair_from_context(self, context: BrowserContext) -> Dict[str, str]:
        cookie_sources = [
            "https://labs.google",
            "https://accounts.google.com",
            "https://google.com",
        ]
        try:
            cookies = await context.cookies(cookie_sources)
        except Exception:
            cookies = await context.cookies()

        cookie_map: Dict[str, str] = {}
        for cookie in cookies:
            name = str(cookie.get("name") or "")
            if name in {"__Secure-1PSID", "__Secure-1PSIDTS"}:
                cookie_map[name] = str(cookie.get("value") or "")

        return cookie_map


gemini_cookie_bridge = GeminiCookieBridge()

