# 掉包检测 — Telegram 群组通知 设计文档

## 1. 需求描述

在现有掉包检测系统的邮件通知基础上，增加 Telegram 群组通知能力。当检测到包掉包后，通过 Telegram Bot 向指定群组发送通知消息，并在消息中 @提及该产品的在跑人员，使群组成员能实时看到并快速响应。

### 核心功能

1. **群组通知（仅首次）**：定时检测或手动检测**首次**发现掉包后，自动发一条 Telegram 消息到配置的群组。后续重复检测到同一掉包不再重复发送
2. **@在跑人员**：消息中 @提及产品对应的在跑人员（需用户预先绑定 Telegram 用户名）
3. **用户绑定**：每个系统用户可配置自己的 Telegram 用户名，管理员可协助配置
4. **未配置提醒**：当前端检测到掉包时，若用户未绑定 Telegram 用户名，弹窗提醒其配置

## 2. 技术方案

### 2.1 数据库变更（database.py）

`users` 表新增字段：

```sql
ALTER TABLE users ADD COLUMN telegram_username TEXT DEFAULT '';
```

通过 `_ensure_schema()` 迁移自动执行。

### 2.2 新增模块：`py/telegram_sender.py`

参考 `py/email_sender.py` 的设计模式。核心要素：

- `_TelegramConfig` dataclass：bot_token、chat_id、parse_mode（默认 `"HTML"`）
- `_escape_html(text)`：转义 `&` `<` `>`，防止无效 HTML 导致 API 400
- `_build_mentions(usernames)`：构建 `@user1 @user2` 字符串
- `_build_message(pkg_info, usernames)`：构建 HTML 格式消息
- `send_delist_notification(config, pkg_info, usernames) -> bool`：通过 `requests.post` 调用 `https://api.telegram.org/bot{token}/sendMessage`

**消息格式示例：**

```
【GG-Server 掉包通知】

@carl567 @zhangsan
产品：某游戏
系列：东南亚
包名：com.example.game
链接：Google Play

该包已被下架，请尽快将包状态设置为"掉包"。
```

**API 参数：**
- `parse_mode: "HTML"`
- `disable_web_page_preview: true`
- 超时 10 秒

**错误处理：**
- 配置为空 → 静默跳过
- API 返回非 200 → `print()` 错误信息，返回 False
- 超时/网络错误 → `print()` 错误信息，返回 False
- 任何错误均不影响邮件通知和检测流程

### 2.3 配置变更（config.json）

```json
"telegram": {
    "bot_token": "8705623419:AAHTV7MUQ9xlYe2FGzwgJFJI6AI_afeu07Y",
    "chat_id": "7381484473"
}
```

部署时填入实际值即可。

### 2.4 后端 API 变更（main.py）

#### 新增端点

**1. 当前用户修改自己的 Telegram 用户名**
```
PUT /auth/telegram-username
Body: { "telegram_username": "carl567" }
```
- 权限：登录用户
- 注意：无需 `@` 前缀，存储时自动去除

**2. 管理员修改他人 Telegram 用户名**
```
PUT /admin/users/<uid>/telegram-username
Body: { "telegram_username": "carl567" }
```
- 权限：admin/developer（复用现有权限控制）

#### `_run_delist_check_once()` 修改

在第 5016 行邮件通知代码之后追加 Telegram 通知逻辑。

**关键约束：Telegram 只发一次。** 与邮件不同（每次定时检测都对所有掉包发邮件），Telegram 群组消息在聊天记录中持续可见，不需要重复发送。只有**本轮新检测到的掉包**才发 Telegram 消息。

实现方式：在检测循环中，写 `delist_checks` 之前先查询该 package 是否已有 `is_delisted=1` 的记录：
- 已有 → 不是新掉包，本轮不发 Telegram
- 没有或 `is_delisted=0` → 本轮新掉包，记录到 `newly_delisted` 列表

然后在邮件通知之后对 `newly_delisted` 列表单独处理：

1. 从 `APP_CONFIG` 读取 `telegram` 配置
2. 若 `bot_token` 和 `chat_id` 均非空：
   - 对 `newly_delisted` 中每个包，解析 `runner_ids`，查询 `users.telegram_username`（非空）
   - 构建 `pkg_info` 和 `usernames` 列表
   - 调用 `telegram_sender.send_delist_notification()`
   - 失败打印错误信息，继续下一个

### 2.5 前端变更

#### 2.5.1 用户个人信息页（UserProfileView.vue）

路径：`/profile`

在现有邮箱配置区域旁新增 Telegram 用户名输入框：

```
Telegram 用户名: [@carl567        ]  💡 用于掉包时在群组中 @ 通知你
```

- 失焦自动保存
- 调用 `PUT /auth/telegram-username`
- 遵循现有页面布局风格（`el-descriptions` + `el-input`）

#### 2.5.2 管理员用户管理页（UserManageView.vue）

路径：`/admin/users`

在编辑用户弹窗中新增 `telegram_username` 字段，管理员可协助填写。

#### 2.5.3 未配置提醒（App.vue）

在 `checkDelistNotifications()` 中，当有 pending 通知时，额外检查当前用户是否已配置 `telegram_username`。若未配置，弹出 `ElMessage.warning`：

> "检测到包掉包！请在个人信息页配置 Telegram 用户名以接收群组通知"

此检查需依赖 `/auth/me` 返回的数据中包含 `telegram_username` 字段。

#### 2.5.4 API 客户端

`frontend/src/api/auth.js` 新增：
```javascript
updateTelegramUsername: (username) => api.put('/auth/telegram-username', { telegram_username: username }),
```

`frontend/src/api/admin.js` 新增：
```javascript
updateUserTelegram: (uid, username) => api.put(`/admin/users/${uid}/telegram-username`, { telegram_username: username }),
```

## 3. 涉及的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `py/database.py` | 修改 | `users` 表加 `telegram_username` 列 |
| `py/telegram_sender.py` | **新建** | Telegram 通知模块 |
| `py/main.py` | 修改 | 新增 2 个 API + `_run_delist_check_once()` 追加通知 |
| `config/config.json` | 修改 | 新增 `telegram` 配置块 |
| `frontend/src/views/UserProfileView.vue` | 修改 | 个人设置加 telegram_username 输入框 |
| `frontend/src/views/UserManageView.vue` | 修改 | 管理员编辑弹窗加 telegram_username |
| `frontend/src/api/auth.js` | 修改 | 新增 `updateTelegramUsername` |
| `frontend/src/api/admin.js` | 修改 | 新增 `updateUserTelegram` |
| `frontend/src/App.vue` | 修改 | 未配置 telegram_username 时弹提醒 |

## 4. 边界情况

1. **未配置 Telegram**：`bot_token` 或 `chat_id` 为空 → 跳过所有 Telegram 逻辑
2. **用户未绑定 username**：发消息时跳过该用户不 @，其他已绑定的正常 @
3. **产品无在跑人员**：只发通知消息不加 @提及
4. **全部在跑人员都未绑定**：消息照发但不含 @提及行
5. **Bot 被踢出群组**：API 返回 403，打印日志静默失败
6. **Token 过期失效**：API 返回 401，打印日志静默失败
7. **部署配置**：打包为 exe 后 config.json 在 exe 同级目录，修改配置需重启服务
8. **重复检测**：定时任务每小时运行，已掉包的包再次被检测到时不再重复发 Telegram（通过 `delist_checks` 表中已有记录判断）
9. **不参与提醒循环**：Telegram 通知只在后端检测到掉包时发一次，不参与前端的 3 分钟重复提醒机制（邮件也不参与，但邮件的逻辑是每次定时检测都会发）
