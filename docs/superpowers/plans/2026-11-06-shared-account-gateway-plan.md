# 共享账号网关 · 实施计划

> 依据：[设计文档](../specs/2026-11-06-shared-account-gateway-design.md)（2026-11-06 已确认）
> 目标：把「登录态共享」从扩展方案搬进 GG-Server，同事零安装直接浏览原站。

## 已确认的四项

| 项 | 决定 |
|---|---|
| 入口 | 一级菜单「🔗 共享账号」（GG/FB/TT 三平台可见；户管不显示） |
| 权限 | 所有登录用户可打开；配置/清空/日志仅 developer |
| 端口 | 8901（广大大）、8902（有米云） |
| 续期 | 会话失效时管理员在网关页面里手动登录一次 |

## 步骤

### 第 1 步 · 后端骨架（不接真实站点）

1. `py/database.py`：新增 `share_sites` / `share_sessions` / `share_access_log` 三张表（`CREATE TABLE IF NOT EXISTS`）。
2. `py/share_gateway/ticket.py`：票据签发/校验 + 一次性 nonce。
3. `py/share_gateway/jar.py`：Set-Cookie 解析、合并、筛选、AES-GCM 加解密。
4. `py/share_gateway/store.py`：站点/会话/日志读写。
5. `py/share_gateway/runtime.py`：每站点内存会话罐（启动加载、变更落库）。
6. `py/share_gateway/proxy.py`：WSGI 代理 + 响应重写。
7. `py/share_gateway/app.py`：票据入口 + 网关 cookie 校验 + 401 页。
8. `py/share_gateway/runner.py`：waitress 线程 + 心跳线程 + 运行时注册表。

**验收**：`py/tests/test_share_gateway.py` 全绿（jar、ticket、重写、假上游代理）。

### 第 2 步 · 接口

1. `py/routes/share_routes.py`：`GET /api/share/sites`、`POST .../enter`、`GET .../logs`、`POST .../reset`、`POST .../check`、`PUT .../<id>`。
2. `py/main.py`：注册 blueprint；`__main__` 里启动网关（失败只打日志，不影响主服务）。
3. `config/config.json`：加 `share_gateway` 节点（默认广大大 8901 启用，有米云 8902 停用）。

**验收**：测试客户端可列出站点；未登录 401；非 developer 调管理接口 403。

### 第 3 步 · 前端

1. `frontend/src/api/share.js`。
2. `frontend/src/views/ShareView.vue`（卡片 + 状态徽标 + 管理抽屉）。
3. `router/index.js` 加 `/share`；`AppSidebar.vue` 三套菜单加「共享账号」。

**验收**：`npm run build` 通过；页面能列出站点、点「打开」新标签打开网关。

### 第 4 步 · 真实联调（需用户配合）

1. 启动服务，放行 8901。
2. 管理员在网关页面登录广大大（滑块）。
3. 6 人并发浏览 30 分钟，确认无跳登录、无 401。
4. 记录问题（CDN 403、iframe、Copilot 等）并归入二期。

**验收**：6 人可直接用；卡片显示「可用」；清空会话后变「需重新登录」。

### 第 5 步 · 收尾

1. 独立代码审查（subagent）。
2. 更新 `AGENTS.md`（模块说明 + 设计索引）。
3. 提醒提交 git。

## 实际落地与计划偏差（2026-11-06 联调记录）

计划外的两个关键修复（联调时才暴露，已写进设计文档 §3/§5.4）：

1. **CDN Referer 防盗链 → 白屏**：`nbs-bj-global.zingfront.com` 对 Referer 为网关地址的请求返回 403，
   Chrome 以 `ERR_BLOCKED_BY_ORB` 丢掉 main.js。修复：HTML 注入
   `<meta name="referrer" content="no-referrer">` + `Referrer-Policy: no-referrer`。
2. **`user-token` 引导**：它是 SPA 用 `document.cookie` 写的，不在上游 Set-Cookie 里；不学习它，
   换主机/端口打开会一直停在登录页。修复：网关从请求 Cookie 头学习（白名单，72h 到期），
   再在 HTML 响应里下发。原计划里的「ZFSESSID 是必需锚点」被实测推翻：罐里只有 `user-token`
   时 `/napi/v1/creative/list` 仍返回 200。

其它偏差：
- 密码登录改为「管理员在网关页面手动登录」，且**只需一次**；同事不再需要任何账号密码。
- 落地页从 `/` 改为 `/modules/creative/display-ads`（原站 `/` 是营销首页）。
- 有米云实际域名是 `youcloud.com` 系（`auth.youcloud.com` / `appgrowing-global.youcloud.com`），
  二期接入时改 `upstream`，不是 `appgrowing.cn`。
- P2 的访问日志/管理操作随 P0 一起落地；P1 核心链路已验证（全新 origin 直接进工作台）。

## 验收结果（2026-11-06）

- `python -m pytest tests/test_share_gateway.py -q` → 29 passed。
- 全新 origin（`172.30.3.237:8901`，无 cookie/localStorage）→ 直接进「工作台」，
  `/napi/v1/creative/list`、`/creative/count` 200。
- 同事用自己的 GG-Server 账号点「打开」→ 成功（用户实测）。
- 已知不覆盖：`agent.guangdada.net`（Copilot）跨域被 CORS 拦。

## 风险与回滚

- 网关是**纯增量**：不启动就不影响任何现有功能；`main.py` 的启动钩子包在 try/except 里。
- 端口冲突：启动日志会打印失败原因，HTTP 侧显示「网关未启动」。
- 若平台强校验导致不可用：保留扩展方案作为兜底，网关可随时 `enabled: false`。
- 数据库三张表为新增，无迁移风险。
