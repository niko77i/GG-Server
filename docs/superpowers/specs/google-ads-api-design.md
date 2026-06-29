# Google Ads API 直连 — 独立页面方案

## Context

用户目前手动从 Google Ads 后台下载 Excel/CSV 报告，然后粘贴到做表工具解析。希望直接对接 Google Ads API 自动拉取数据，省去手动下载步骤。

## 前端条件（用户需在 Google 后台完成）

Google Ads API 需要以下凭据，已全部获取：

- **Google Cloud 项目** — `golden-hologram-499109-d8`
- **OAuth 2.0 凭据** — Web 应用类型，重定向 URI `https://developers.google.com/oauthplayground`
- **开发者令牌** — 基本访问权限
- **刷新令牌** — 通过 OAuth Playground 获取
- **经理账户 ID** — `230-247-9968`（下有子账户 `208-320-2792`）

## 架构

独立页面 `google-ads.html` + 后端 API 路由，与主项目物理隔离：

- `google-ads.html` — 独立的 Google Ads 报告页面
- `py/google_ads_service.py` — Google Ads API 客户端封装
- `py/main.py` — 新增 API 路由
- `requirements.txt` — 添加 `google-ads` 库

**访问方式**：`http://localhost:5000/google-ads.html`

## 不涉及

- 不改动 index.html 任何代码
- 不改动 js/、css/ 任何文件
- 不打包进 EXE（除非用户明确要求）
- 不影响主项目任何功能

## 页面功能

1. 凭据配置区（已预填，可修改）
2. 选择账号 + 日期范围
3. 拉取广告系列级别报告（费用、展示、点击、点击率、转化）
4. 表格展示结果
5. 一键复制 / 导出 Excel

## 新增 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/google-ads/accounts` | 获取子账户列表 |
| POST | `/api/google-ads/report` | 拉取报告 |

## 验证

1. 启动 `python main.py`
2. 浏览器打开 `http://localhost:5000/google-ads.html`
3. 选择账号 + 日期，点拉取报告
4. 确认数据显示正常
