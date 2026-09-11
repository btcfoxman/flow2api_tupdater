"""Shared, credential-safe validation for the two independent Flow sessions."""
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

LABS_SESSION_URL = "https://labs.google/fx/api/auth/session"
LABS_CSRF_URL = "https://labs.google/fx/api/auth/csrf"
LABS_SIGNIN_URL = "https://labs.google/fx/api/auth/signin/google"
CREDITS_URL = "https://aisandbox-pa.googleapis.com/v1/credits"
FLOW_IDENTITY_EXPRESSION = """() => {
  const w = window.WIZ_global_data || {};
  return {origin: location.origin, path: location.pathname,
    ready: !!(w.SNlM0e && w.cfb2h && w.FdrFJe), email: w.oPEP7c || ''};
}"""


def validate_flow_identity(data, expected_email=""):
    import re
    if (not isinstance(data, dict) or data.get("origin") != "https://flow.google.com"
            or str(data.get("path", "")).startswith("/about") or not data.get("ready")):
        return failure("flow_login_required", "请在源 Profile 完成 flow.google.com 登录，无需 Labs 授权")
    email = str(data.get("email") or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 320:
        return failure("identity_unavailable", "尚未确认新站账号身份，请完成 Flow 登录")
    if expected_email and email != expected_email.strip().lower():
        return failure("identity_mismatch", "Flow 登录账号与当前 Profile 不一致")
    return {"success": True, "email": email, "auth_mode": "flow"}


def flow_receipt_email(receipt, expected_email="") -> str:
    """A local extraction receipt identifies an account; it is not a credential."""
    if not isinstance(receipt, str) or not receipt.startswith("flow:"):
        return ""
    email = receipt[5:].strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 320:
        return ""
    if expected_email and email != str(expected_email).strip().lower():
        return ""
    return email


def failure(code: str, message: str) -> dict:
    return {"success": False, "error_code": code, "error": message}


def validate_labs_session(data: Any, expected_email: str = "", *, now=None) -> dict:
    invalid = failure("auth_required", "Labs 授权缺失或已过期，请在源 Profile 重新完成 Labs 授权；仅登录 Flow 新站不足以续期")
    if not isinstance(data, dict) or data.get("error"):
        return invalid
    at = data.get("access_token") or data.get("accessToken")
    if not isinstance(at, str) or not at.strip():
        return invalid
    try:
        expires = datetime.fromisoformat(data["expires"].replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= (now or datetime.now(timezone.utc)) + timedelta(seconds=60):
            return invalid
    except (KeyError, TypeError, ValueError, AttributeError):
        return invalid
    user = data.get("user")
    email = str(user.get("email") or "").strip().lower() if isinstance(user, dict) else ""
    if not email or "@" not in email:
        return invalid
    if expected_email and email != expected_email.strip().lower():
        return failure("identity_mismatch", "Labs 授权账号与当前 Profile 不一致，请在源浏览器选择正确账号")
    return {"success": True, "access_token": at, "email": email, "expires": expires.isoformat()}


def validate_credits(status: int, data: Any) -> dict:
    if status == 401:
        return failure("auth_required", "Labs access token 已失效，请在源 Profile 重新授权")
    if status == 200 and isinstance(data, dict) and "error" not in data:
        credits = data.get("credits")
        # Observed HTTP 200 for exhausted accounts omits the zero protobuf scalar.
        # Require the complete authenticated tier response, not an arbitrary {}.
        if ("credits" not in data and isinstance(data.get("serviceTier"), str)
                and data["serviceTier"].startswith("SERVICE_TIER_")
                and isinstance(data.get("userPaygateTier"), str)
                and data["userPaygateTier"].startswith("PAYGATE_TIER_")
                and isinstance(data.get("sku"), str) and data["sku"].strip()):
            credits = 0
        if isinstance(credits, (int, float)) and not isinstance(credits, bool) and math.isfinite(credits) and credits >= 0:
            return {"success": True}
    return failure("verification_unavailable", "账号鉴权暂时无法确认，请检查源代理或稍后重试；未清除 Cookie")


def cookie_is_live(cookie: dict, *, now=None) -> bool:
    expires = cookie.get("expires", cookie.get("expirationDate", cookie.get("expiry")))
    if expires is None:
        return True
    try:
        expires = float(expires)
        return math.isfinite(expires) and (expires == -1 or expires > (now if now is not None else time.time()))
    except (TypeError, ValueError):
        return False


def scoped_google_cookies(raw: Any) -> list:
    if isinstance(raw, str) and len(raw.encode("utf-8")) > 300_000:
        return []
    try:
        raw = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("cookies")
    if not isinstance(raw, list) or len(raw) > 256:
        return []
    cookies = {}
    for cookie in raw:
        if not isinstance(cookie, dict):
            continue
        name, domain = cookie.get("name"), cookie.get("domain")
        path = cookie.get("path", "/")
        if not all(isinstance(v, str) and v for v in (name, domain, path, cookie.get("value"))):
            continue
        domain = domain.lower()
        if domain.startswith("..") or domain.lstrip(".") not in {"google.com", "www.google.com", "accounts.google.com", "flow.google.com"}:
            continue
        if (not path.startswith("/") or len(path) > 2048 or re.search(r"[\x00-\x1f\x7f]", path)
                or cookie.get("partitionKey") or cookie.get("partitioned") or not cookie_is_live(cookie)
                or not re.fullmatch(r"[^\s=;,\x00-\x1f\x7f]{1,256}", name)
                or len(cookie["value"]) > 16384 or re.search(r"[\x00-\x1f\x7f;]", cookie["value"])):
            continue
        if name.startswith("__Host-") and (domain.startswith(".") or path != "/"):
            continue
        normalized = {"name": name, "value": cookie["value"], "domain": domain, "path": path}
        for flag in ("secure", "httpOnly"):
            if flag in cookie:
                normalized[flag] = bool(cookie[flag])
        if name.startswith(("__Secure-", "__Host-")):
            normalized["secure"] = True
        same_site = {"lax":"Lax", "strict":"Strict", "none":"None", "no_restriction":"None"}.get(str(cookie.get("sameSite", "")).lower())
        if same_site:
            normalized["sameSite"] = same_site
        expires = cookie.get("expires", cookie.get("expirationDate", cookie.get("expiry")))
        if expires is not None:
            normalized["expires"] = float(expires)
        cookies[(name, domain, path)] = normalized
    return list(cookies.values())


def validate_google_cookies(cookies: list) -> dict:
    root = any(c.get("domain") == ".google.com" and c.get("path", "/") == "/"
               and c.get("name") == "SID" and c.get("value") and cookie_is_live(c) for c in cookies)
    flow = any(c.get("domain", "").lstrip(".") == "flow.google.com" and c.get("path", "/") == "/"
               and c.get("name") in {"OSID", "__Secure-OSID"} and c.get("value") and cookie_is_live(c) for c in cookies)
    if not root or not flow:
        return failure("cookies_incomplete", "Google/Flow 登录 Cookie 不完整或已过期，请在源 Profile 完成 Google 和 Flow 登录后同步")
    return {"success": True}
