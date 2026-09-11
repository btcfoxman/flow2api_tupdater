# Flow 新站迁移补漏（2026-09-11）

适用默认 Flow 会话同步，不修改独立的 Gemini `gcu:` 同步分支。源 Profile 与目标 native Profile 继续分离，已有账号、代理和连接设置保留，无数据库迁移。

## 已修复

- 浏览器默认入口、登录完成判定和纯 HTTP 协议检查使用 `https://flow.google.com/`；验证 bootstrap 与准确邮箱，再要求完整 Google SID / Flow OSID Cookie，不依赖 Labs ST/AT。
- 协议登录管理接口不再把内部 `flow:邮箱` 处理为 Labs NextAuth Cookie。缺少新站身份、完整 Cookie 或邮箱不一致时，不向源浏览器导入。
- 新站同步发送 `auth_mode=flow`、`email`、`google_cookies`、`captcha_proxy_url`；不发送 ST/AT。Cookie 保留域名、根路径、有效期、HttpOnly / SameSite / Secure 元数据；支持 `expires` / `expirationDate` / `expiry`，过滤分区 Cookie、非法域边界及过期项。
- 协议检查保留 Cookie 的 host-only 属性与到期时间，不把 host-only Cookie 扩展到其他子域。
- 同步成功要求目标完整确认 Cookie、代理、同一邮箱、`flow_identity_verified`、`native_session_verified`、`account_active`。不再从英文成功消息提取邮箱，缺少邮箱的非原生响应也不会清空已有 Profile 邮箱。
- 新版错误码区分服务端版本、认证模式、账号忙、身份不符、验证未完成及独立登录保护。普通 HTTP 409 不再一律标为独立登录，不因目标端异常反复授权或清空源 Cookie。

## 对外接口变化

`GET /v1/profiles/{id}/token`（`X-API-Key` 鉴权）现在返回：

```json
{
  "success": true,
  "profile_id": 1,
  "profile_name": "example",
  "email": "example@example.com",
  "auth_mode": "flow",
  "session_token": null,
  "google_cookies": ["此处为实际结构化 Cookie 对象，示意中省略"],
  "captcha_proxy_url": "socks5://host.docker.internal:20001"
}
```

这属于响应契约变更：旧调用方读取 `session_token` 的代码必须升级。真正的登录凭据是 Cookie，而不是内部身份标识。接口禁止缓存，普通列表不返回 Cookie。协议登录管理接口只返回验证结果，不返回原始凭据。

## 升级与验证

1. 备份并保留原 `data/`、`profiles/`；先升级支持 native Flow 的 Flow2API，再升级本项目。
2. 目标使用 `native_cdp`，每个 Profile 的 `captcha_proxy_url` 必须在目标可访问且与源代理同公网出口。不能根据两台机器的 localhost 地址自行推断出口。
3. 默认保持 `FLOW_PROTOCOL_REFRESH_ENABLED=false`。先单账号同步，检查完整确认，再做真实生成验收；不要直接批量重放失败会话。
4. 独立登录目标不允许外部覆盖；目标仍禁用、预检失败、账号忙均不计为恢复成功。

本次本地完整 Python 测试 160 项通过，前端脚本语法检查通过。另使用两个项目真实 HTTP 路由、同步器、TokenManager 与临时 SQLite 做跨项目契约测试，仅替换上游浏览器/Google 边界。该测试不证明真实 Cookie 在另一台服务器可用，也不证明上游 429 已消失。本轮未部署、未批量同步、未提交计费任务。
