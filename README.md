# Flow2API Token Updater v3.3

Flow2API Token Updater 是一个轻量级的多账号令牌刷新工具。
它使用 Playwright 的持久化浏览器 Profile 来保持 Google Labs 登录会话存活，
在需要时提取会话令牌（session token），并将其推送到 Flow2API。

当前版本重点解决三件事：

- 多账号管理
- 单账号级别的 Flow2API 目标覆盖
- 带图表和近期活动的实时仪表盘（Dashboard）

## 亮点

- 运行时轻量：只有在需要登录时才会启动 VNC / Xvfb / noVNC
- 智能同步：按最终生效的 Flow2API 地址和令牌分组
- 单账号覆盖：每个 Profile 都可以覆盖目标地址和连接令牌
- 代理支持：每个 Profile 都可以使用独立代理
- Cookie 导入：无需打开浏览器也能恢复登录状态
- 实时仪表盘：优先使用 SSE，失败时自动回退到轮询
- 图表范围切换：6 小时 / 24 小时 / 72 小时 / 7 天
- 内置分析：同步活动、失败原因、目标实例分布

## 工作原理

1. 每个账号都作为独立的 Profile 保存。
2. 浏览器状态持久化存储在 `profiles/` 中。
3. 同步时，最终生效目标按以下顺序计算：
   - `profile.flow2api_url`，否则使用全局 `FLOW2API_URL`
   - `profile.connection_token_override`，否则使用全局 `CONNECTION_TOKEN`
4. 所有启用中的 Profile 会按“最终生效目标地址 + 最终生效令牌”分组。
5. 每个分组会先调用 Flow2API 的 `check-tokens` 接口。
6. 只有确实需要刷新的 Profile 才会执行同步。
7. 如果目标端检查失败，该分组会回退到强制同步。
8. 每次同步结果都会写入历史记录，供仪表盘展示。

## 快速开始

### 1. 克隆并配置

```bash
git clone https://github.com/genz27/flow2api_tupdater.git
cd flow2api_tupdater
cp .env.example .env
```

至少需要在 `.env` 中设置以下变量：

- `ADMIN_PASSWORD`
- `FLOW2API_URL`
- `CONNECTION_TOKEN`

### 2. 启动服务

```bash
docker compose up -d --build
```

### 3. 访问应用

- 管理界面（Admin UI）：`http://localhost:8002`
- noVNC：`http://localhost:6080/vnc.html`

> 只有在启用并实际使用 VNC 登录时，端口 `6080` 才有意义。

## 常见使用流程

### 流程 A：通过 VNC 登录

1. 打开管理界面。
2. 配置全局默认的 Flow2API 地址和连接令牌。
3. 创建一个 Profile。
4. 点击 `Login` 启动浏览器。
5. 在 noVNC 中完成 Google 登录。
6. 点击 `Close Browser` 保存当前登录状态。
7. 手动执行一次同步，确认账号可用。
8. 后续刷新交给定时任务处理。

### 流程 B：导入 Cookie

1. 创建一个 Profile。
2. 打开 `Cookie` 对话框。
3. 粘贴 `labs.google` 域名下的 Cookie JSON。
4. 执行 `Check Login` 或 `Sync`，验证导入后的登录状态。

### 多实例 Flow2API 配置

如果某个账号需要同步到另一套 Flow2API 实例：

1. 打开该 Profile 的编辑对话框。
2. 设置 `Flow2API URL override`。
3. 如果目标实例使用不同令牌，再设置 `Connection Token override`。
4. 保存后，这个 Profile 会优先使用覆盖值。

## 仪表盘

管理仪表盘包含以下内容：

- 概览指标
- 可切换时间范围的同步活动图表
- 状态分布和账号排行
- 失败原因聚合
- 目标实例分布
- 近期活动流
- 实时连接状态

前端默认优先使用 SSE 获取实时更新；
如果实时流不可用，会自动回退到轻量轮询。

## 持久化

默认的 `docker-compose.yml` 会挂载以下目录：

- `./data` -> `/app/data`
  - `profiles.db`：账号数据和同步历史
  - `config.json`：持久化的全局默认配置
- `./profiles` -> `/app/profiles`
  - Playwright 持久化浏览器 Profile 数据
- `./logs` -> `/app/logs`
  - 运行日志

## 环境变量

应用当前实际使用的环境变量如下：

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `ADMIN_PASSWORD` | 管理界面密码 | 空 |
| `API_KEY` | 对外 API 的访问密钥 | 空 |
| `FLOW2API_URL` | 全局默认 Flow2API 地址 | `http://host.docker.internal:8000` |
| `CONNECTION_TOKEN` | 全局默认 Flow2API 连接令牌 | 空 |
| `REFRESH_INTERVAL` | 定时刷新间隔，单位分钟 | `60` |
| `SESSION_TTL_MINUTES` | 管理端会话 TTL，`0` 表示永不过期 | `1440` |
| `CONFIG_FILE` | 持久化全局配置文件路径 | `/app/data/config.json` |
| `API_PORT` | HTTP 监听端口 | `8002` |
| `ENABLE_VNC` | 是否启用 VNC 登录入口，`1/0` | `1` |
| `VNC_PASSWORD` | noVNC / x11vnc 密码 | `flow2api` |

### 配置优先级

最终生效目标按以下顺序决定：

1. Profile 级别的 `flow2api_url`
2. 全局 `FLOW2API_URL`

连接令牌按以下顺序决定：

1. Profile 级别的 `connection_token_override`
2. 全局 `CONNECTION_TOKEN`

## API 参考

### 管理端 API

以下接口由 Web 仪表盘使用：

- `POST /api/login`
- `POST /api/logout`
- `GET /api/auth/check`
- `GET /api/status`
- `GET /api/dashboard?hours=6|24|72|168`
- `GET /api/dashboard/stream?session_token=...`
- `GET /api/config`
- `POST /api/config`
- `GET /api/profiles`
- `POST /api/profiles`
- `GET /api/profiles/{id}`
- `PUT /api/profiles/{id}`
- `DELETE /api/profiles/{id}`
- `POST /api/profiles/{id}/launch`
- `POST /api/profiles/{id}/close`
- `POST /api/profiles/{id}/check-login`
- `POST /api/profiles/{id}/import-cookies`
- `POST /api/profiles/{id}/extract`
- `POST /api/profiles/{id}/sync`
- `POST /api/sync-all`

### 对外 API

以下接口需要在请求头中携带 `X-API-Key`：

- `GET /v1/profiles`
- `GET /v1/profiles/{id}/token`
- `POST /v1/profiles/{id}/sync`
- `GET /health`

## 升级说明

### 升级到 v3.3

v3.3 新增了以下能力：

- Profile 级目标地址覆盖
- Profile 级连接令牌覆盖
- 同步历史存储
- 实时仪表盘和 SSE 流
- 失败原因聚合
- 目标实例分布
- 仪表盘时间范围筛选

建议按以下步骤升级：

1. 备份 `data/` 和 `profiles/`。
2. 拉取最新代码。
3. 重新构建并重启容器。
4. 应用会在需要时自动创建新字段和历史表。
5. 重新检查管理界面中的全局默认配置。
6. 如果你使用多套 Flow2API 目标，再检查一次各 Profile 的覆盖配置。

## 故障排查

### 同步提示：Flow2API URL 或令牌不完整

说明最终生效的目标配置不完整。请检查：

- 全局默认目标配置
- Profile 级地址覆盖
- Profile 级令牌覆盖

如果某个 Profile 指向另一套 Flow2API 实例，通常也需要为它配置匹配的令牌覆盖。

### 同步提示：提取令牌失败

说明当前保存的浏览器会话已经不可用。可以尝试：

- 通过 VNC 重新登录
- 导入新的 Cookie
- 在再次同步前先执行一次 `Check Login`

### noVNC 无法使用

请检查：

- `ENABLE_VNC=1`
- 端口 `6080` 已正确映射
- 你确实点击了对应 Profile 的 `Login` 按钮

### 修改了 `API_PORT` 但无法访问应用

如果你修改了应用监听端口，也要同时更新 `docker-compose.yml` 中的端口映射。

## 许可证

MIT
