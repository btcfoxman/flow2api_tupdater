"""Classify destination failures without storing response bodies/secrets in logs."""
from .session_validation import failure


def destination_error(response, *, endpoint: str = "") -> dict:
    status = response.status_code
    # Endpoint is a call-site constant, never an arbitrary server URL or response body.
    route = f"/api/plugin/{endpoint}" if endpoint in {"check-tokens", "update-token"} else "插件接口"
    try:
        data = response.json()
        code = data.get("detail", {}).get("code", "") if isinstance(data, dict) and isinstance(data.get("detail"), dict) else ""
        code = code if isinstance(code, str) else ""
        detail = str(data.get("detail") or data.get("error") or "").lower() if isinstance(data, dict) else ""
    except (ValueError, TypeError):
        detail = ""
        code = ""
    flow_errors = {
        "flow_auth_mode_required": ("destination_version", "该账号已迁移新站，请升级同步器并使用 auth_mode=flow"),
        "unsupported_auth_mode": ("destination_version", "目标尚不支持 Flow 新站认证，请先升级 Flow2API"),
        "flow_verification_unavailable": ("destination_unavailable", "目标新站会话验证未完成，请先核查账号状态；保留源 Cookie"),
        "native_cdp_required": ("destination_mode", "目标必须使用 native_cdp 才能同步 Flow 新站会话"),
        "flow_session_fields_required": ("destination_proxy", "新站同步需提供完整 Cookie 和目标可访问的同出口代理"),
        "flow_account_busy": ("destination_busy", "目标账号正在执行任务，请等待完成后同步"),
        "flow_identity_mismatch": ("identity_mismatch", "目标验证的 Flow 账号与源 Profile 不一致"),
        "flow_identity_unavailable": ("flow_login_required", "目标无法确认 Flow 身份，请检查源新站登录态及同出口代理"),
        "flow_login_unavailable": ("flow_login_required", "目标 Flow 登录态不可用，请检查源新站登录态及同出口代理"),
        "project_context_unavailable": ("flow_login_required", "目标 Flow 登录态不可用，请检查源新站登录态及同出口代理"),
        "local_session_external_sync_forbidden": ("independent_login", "目标账号使用独立登录，外部同步不能覆盖"),
    }
    if code in flow_errors:
        error_code, message = flow_errors[code]
        return {**failure(error_code, f"{message}（HTTP {status}）"), "status_code": status}
    if status in (401, 403):
        result = failure("destination_auth", "目标拒绝同步连接，请检查 CONNECTION_TOKEN 和插件接口是否启用；无需重新登录源账号")
    elif status in (404, 405):
        result = failure("destination_endpoint", f"目标接口 {route} 不存在或不支持 POST，请核对服务基础地址（不要填写完整插件接口路径）并升级目标服务；无需重新登录源账号")
    elif 300 <= status < 400:
        result = failure("destination_redirect", f"目标接口 {route} 返回跳转，请配置最终服务基础地址；未跟随跳转或转发连接 Token")
    elif status == 409:
        result = failure("destination_conflict", "目标同步存在冲突，请核对账号任务占用、登录保护及服务端版本；未覆盖源 Cookie")
    elif status == 400 and "captcha_proxy_url" in detail:
        result = failure("destination_proxy", "请配置目标 Flow2API 可访问、与源 Profile 同出口的 captcha_proxy_url；新站同步必须提供")
    elif status == 400 and "proxy" in detail:
        result = failure("verification_unavailable", "目标无法确认会话或账号代理，请先检查两端代理出口和 Flow 新站登录态；未触发重复登录")
    elif status == 400 and any(word in detail for word in ("expired labs", "invalid session token", "labs access token", "missing labs", "renew labs")):
        result = failure("auth_required", "目标拒绝过期或失效的 Labs 授权，请在源 Profile 重新授权后同步")
    elif status == 400 and any(word in detail for word in ("cookie", "google session")):
        result = failure("cookies_incomplete", "目标拒绝不完整的 Google/Flow Cookie，请在源 Profile 完成登录后重新同步")
    elif status == 429 or status >= 500:
        result = failure("destination_unavailable", "目标服务或账号校验暂不可用，请稍后重试；源 Cookie 保留，不重复登录")
    else:
        result = failure("destination_rejected", "目标拒绝同步请求，请核对接口地址、配置及服务端版本")
    return {**result, "error": f"{result['error']}（HTTP {status}）", "status_code": status}
