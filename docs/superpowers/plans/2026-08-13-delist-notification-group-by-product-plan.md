# 掉包通知按产品聚合 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将掉包检测的弹窗与 Telegram 通知从「按包」聚合为「按产品」，一个产品一条通知。

**Architecture:** 底层 `delist_notifications` 仍按包维护（不改表结构），仅在上层（`delist/pending` 接口输出、`delist/dismiss` 入参、Telegram 发送、前端弹窗）按产品聚合。纯增量，不重构检测/去重/提醒核心逻辑。

**Tech Stack:** Python Flask + SQLite（后端）、Vue 3 + Element Plus（前端）、Markdown 文档。

## Global Constraints

- 语言：代码注释与文档用中文；回复用户用中文。
- 纯增量原则：只新增/局部修改，不重构原有检测、去重、邮件逻辑；邮件通知保持「按包」不变。
- 弹窗文案：产品名 + 换行系列名（去重）+ `请将包状态设置为"掉包"（点击跳转到对应包）`，不展示包名。
- Telegram 消息：产品名 + 系列名列表，不展示包名与链接。
- 前端标红逻辑（`ProductCard.vue` `pkg-row--delisted`）**不改动**。
- 测试运行方式：`cd py && python -m pytest tests/ -v`。

---

### Task 1: Telegram 产品级消息构建 + 发送函数（`py/telegram_sender.py`）

**Files:**
- Modify: `py/telegram_sender.py`（在文件末尾追加两个新函数，保留现有 `_build_message` / `send_delist_notification` 不动）
- Test: `py/tests/test_telegram_sender.py`（新建）

**Interfaces:**
- Produces:
  - `_build_product_message(product_name: str, series_names: list[str], usernames: list[str]) -> str`
  - `send_product_delist_notification(config: _TelegramConfig, product_name: str, series_names: list[str], usernames: list[str]) -> bool`

- [ ] **Step 1: 写失败测试**

新建 `py/tests/test_telegram_sender.py`：

```python
"""Telegram 通知模块测试。"""
import pytest
from unittest.mock import patch, MagicMock


class TestBuildProductMessage:
    """测试产品级掉包消息构建。"""

    def test_builds_message_with_product_and_series(self):
        from telegram_sender import _build_product_message
        msg = _build_product_message("某游戏", ["东南亚", "巴西"], ["carl567"])
        assert "【GG-Server 掉包通知】" in msg
        assert "产品：" in msg and "某游戏" in msg
        assert "东南亚" in msg
        assert "巴西" in msg
        assert "@carl567" in msg
        assert "com.example" not in msg  # 不展示包名

    def test_escapes_html_special_chars(self):
        from telegram_sender import _build_product_message
        msg = _build_product_message("<游戏>&", ["<系列>"], [])
        assert "&lt;" in msg and "&amp;" in msg

    def test_no_mentions_when_usernames_empty(self):
        from telegram_sender import _build_product_message
        msg = _build_product_message("P1", ["S1"], [])
        assert "@" not in msg


class TestSendProductDelistNotification:
    """测试产品级掉包通知发送。"""

    def test_sends_message(self):
        from telegram_sender import send_product_delist_notification, _TelegramConfig
        config = _TelegramConfig(bot_token="token123", chat_id="chat123")
        with patch("telegram_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {}
            mock_post.return_value = mock_resp
            result = send_product_delist_notification(config, "P1", ["S1"], ["u1"])
        assert result is True
        mock_post.assert_called_once()

    def test_returns_false_without_config(self):
        from telegram_sender import send_product_delist_notification, _TelegramConfig
        config = _TelegramConfig(bot_token="", chat_id="")
        result = send_product_delist_notification(config, "P1", ["S1"], [])
        assert result is False

    def test_returns_false_on_error(self):
        from telegram_sender import send_product_delist_notification, _TelegramConfig
        config = _TelegramConfig(bot_token="t", chat_id="c")
        with patch("telegram_sender.requests.post", side_effect=Exception("boom")):
            result = send_product_delist_notification(config, "P1", ["S1"], [])
        assert result is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd py && python -m pytest tests/test_telegram_sender.py -v`
Expected: FAIL（`ModuleNotFoundError` / `ImportError`，函数未定义）

- [ ] **Step 3: 实现两个新函数**

在 `py/telegram_sender.py` 文件末尾追加：

```python
def _build_product_message(product_name: str, series_names: list[str], usernames: list[str]) -> str:
    """构建产品级掉包通知消息正文（HTML 格式）。

    Args:
        product_name: 产品名称
        series_names: 掉包系列名列表（已去重）
        usernames: Telegram 用户名列表（不带 @ 前缀）

    Returns:
        HTML 格式的通知消息
    """
    product_name = _escape_html(product_name or "-")
    mentions = _build_mentions(usernames)

    lines = [
        "<b>【GG-Server 掉包通知】</b>",
    ]
    if mentions:
        lines.append("")
        lines.append(mentions)

    lines.append("")
    lines.append(f"<b>产品：</b>{product_name}")
    lines.append("<b>掉包系列：</b>")
    for sn in series_names:
        lines.append(f"· {_escape_html(sn or '-')}")

    lines.extend([
        "",
        '该产品的多个包已被下架，请尽快将包状态设置为"掉包"。',
    ])

    return "\n".join(lines)


def send_product_delist_notification(
    config: _TelegramConfig,
    product_name: str,
    series_names: list[str],
    usernames: list[str],
) -> bool:
    """发送产品级掉包通知到 Telegram 群组。

    Args:
        config: Telegram Bot 配置
        product_name: 产品名称
        series_names: 掉包系列名列表
        usernames: Telegram 用户名列表（不带 @ 前缀），空列表表示不 @任何人

    Returns:
        True 表示发送成功，False 表示失败
    """
    if not config.bot_token or not config.chat_id:
        return False

    text = _build_product_message(product_name, series_names, usernames)

    payload = {
        "chat_id": config.chat_id,
        "text": text,
        "parse_mode": config.parse_mode,
        "disable_web_page_preview": True,
    }

    url = _BASE_URL.format(token=config.bot_token)

    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        data = resp.json()
        if not resp.ok:
            description = data.get("description", resp.text)
            print(f"[Telegram] 发送失败: {description}")
            return False
        return True
    except requests.Timeout:
        print("[Telegram] 发送超时")
        return False
    except requests.ConnectionError:
        print("[Telegram] 网络连接失败")
        return False
    except Exception as e:
        print(f"[Telegram] 发送异常: {e}")
        return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd py && python -m pytest tests/test_telegram_sender.py -v`
Expected: PASS（6 个测试全部通过）

- [ ] **Step 5: Commit**

```bash
git add py/telegram_sender.py py/tests/test_telegram_sender.py
git commit -m "feat: 掉包 Telegram 通知按产品聚合（新增产品级消息构建/发送）"
```

---

### Task 2: `_send_telegram_notifications` 按产品分组 + 更新两个调用方（`py/main.py`）

**Files:**
- Modify: `py/main.py:7705-7739`（`_send_telegram_notifications`）
- Modify: `py/main.py:7846-7853`（`_run_delist_check_once` 内 Telegram 段）
- Modify: `py/main.py:3224-3240`（`products_check_delist` 内 Telegram 段）

**Interfaces:**
- Consumes: `telegram_sender.send_product_delist_notification(config, product_name, series_names, usernames)`
- Produces: `_send_telegram_notifications(db, pkgs)`，`pkgs` 每项含 `product_id/product_name/series_name/runner_ids`（`runner_ids` 为 JSON 字符串）

- [ ] **Step 1: 重写 `_send_telegram_notifications`（L7705-7739 整体替换）**

```python
def _send_telegram_notifications(db, pkgs):
    """按产品分组发送 Telegram 群组掉包通知。

    Args:
        db: 数据库连接
        pkgs: 掉包字典列表，每项含 product_id, product_name, series_name, runner_ids(JSON字符串)
    """
    tg_cfg = APP_CONFIG.get("telegram", {})
    if not (tg_cfg.get("bot_token") and tg_cfg.get("chat_id") and pkgs):
        return

    import telegram_sender as _tg_sender
    tg_config = _tg_sender._TelegramConfig(
        bot_token=tg_cfg.get("bot_token", ""),
        chat_id=tg_cfg.get("chat_id", ""),
        parse_mode=tg_cfg.get("parse_mode", "HTML"),
    )

    # 按 product_id 分组（dict 保持插入顺序）
    groups = {}
    for pkg in pkgs:
        pid = pkg.get("product_id")
        groups.setdefault(pid, []).append(pkg)

    for pid, group_pkgs in groups.items():
        product_name = group_pkgs[0].get("product_name", "") if group_pkgs else ""
        series_names = []
        runner_ids = []
        for pkg in group_pkgs:
            sn = (pkg.get("series_name") or "").strip()
            if sn and sn not in series_names:
                series_names.append(sn)
            try:
                rids = _json.loads(pkg.get("runner_ids", "[]"))
            except Exception:
                rids = []
            for rid in rids:
                if rid not in runner_ids:
                    runner_ids.append(rid)

        usernames = []
        if runner_ids:
            rows = db.execute(
                f"SELECT telegram_username FROM users WHERE id IN ({','.join('?'*len(runner_ids))}) AND telegram_username != ''",
                runner_ids
            ).fetchall()
            usernames = [r["telegram_username"] for r in rows]

        _tg_sender.send_product_delist_notification(tg_config, product_name, series_names, usernames)
```

- [ ] **Step 2: 更新 `_run_delist_check_once` 内 Telegram 段（L7846-7853）**

将：

```python
            # --- Telegram 群组通知（仅发本轮新掉包的包，不重复发送）---
            if newly_delisted_list:
                for pkg in newly_delisted_list:
                    try:
                        rids = _json.loads(pkg.get("runner_ids", "[]"))
                    except Exception:
                        rids = []
                    _send_telegram_notifications(db, [pkg], rids)
```

替换为：

```python
            # --- Telegram 群组通知（按产品聚合，仅发本轮新掉包，不重复发送）---
            if newly_delisted_list:
                _send_telegram_notifications(db, newly_delisted_list)
```

- [ ] **Step 3: 更新 `products_check_delist` 内 Telegram 段（L3224-3240）**

将：

```python
    # 新掉包 → Telegram 群组通知
    if newly_delisted:
        try:
            rids = _json.loads(runner_ids_raw)
        except Exception:
            rids = []
        # 补齐包详情字段
        tg_pkgs = []
        for r in newly_delisted:
            orig = pkg_map.get(r["package_id"], {})
            tg_pkgs.append({
                "product_name": product_name,
                "series_name": orig.get("series_name", ""),
                "package_name": orig.get("package_name", ""),
                "url": orig.get("url", ""),
            })
        _send_telegram_notifications(db, tg_pkgs, rids)
```

替换为：

```python
    # 新掉包 → Telegram 群组通知（按产品聚合）
    if newly_delisted:
        tg_pkgs = []
        for r in newly_delisted:
            orig = pkg_map.get(r["package_id"], {})
            tg_pkgs.append({
                "product_id": pid,
                "product_name": product_name,
                "series_name": orig.get("series_name", ""),
                "runner_ids": runner_ids_raw,
            })
        _send_telegram_notifications(db, tg_pkgs)
```

- [ ] **Step 4: 回归测试**

Run: `cd py && python -m pytest tests/ -v`
Expected: 现有测试全部通过（无回归；`_send_telegram_notifications` 仅在检测到掉包时被调用，测试中 Telegram 配置为空会静默跳过）

- [ ] **Step 5: Commit**

```bash
git add py/main.py
git commit -m "feat: 掉包 Telegram 通知按产品分组发送"
```

---

### Task 3: `delist/pending` 聚合 + `delist/dismiss` 批量（`py/main.py`）

**Files:**
- Modify: `py/main.py:3280-3311`（`delist_dismiss`）
- Modify: `py/main.py:3314-3388`（`delist_pending`）

**Interfaces:**
- Produces:
  - `POST /api/delist/dismiss` 入参 `{ "package_ids": [int, ...] }`（兼容旧 `{ "package_id": int }`）
  - `GET /api/delist/pending` 返回 `notifications[]`，每项 `{ product_id, product_name, series_names[], package_ids[], type, reminder_count }`

- [ ] **Step 1: 重写 `delist_dismiss`（L3280-3311）**

将整个函数体替换为：

```python
@app.route("/api/delist/dismiss", methods=["POST"])
@jwt_required()
def delist_dismiss():
    """记录用户关闭掉包通知的时间（支持批量 package_ids）。"""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    package_ids = data.get("package_ids")
    if not package_ids:
        # 兼容旧的单包字段
        package_id = data.get("package_id")
        if package_id:
            package_ids = [package_id]
    if not package_ids:
        return jsonify({"success": False, "error": "缺少 package_ids"}), 400

    db = _yt_db()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for package_id in package_ids:
        existing = db.execute(
            "SELECT id, first_notified FROM delist_notifications WHERE package_id=? AND user_id=?",
            (package_id, user_id)
        ).fetchone()

        if existing:
            db.execute(
                "UPDATE delist_notifications SET dismissed_at=?, reminder_count=reminder_count+1 WHERE package_id=? AND user_id=?",
                (now, package_id, user_id)
            )
        else:
            db.execute(
                "INSERT INTO delist_notifications(package_id, user_id, first_notified, dismissed_at, reminder_count) "
                "VALUES(?, ?, 1, ?, 0)",
                (package_id, user_id, now)
            )

    db.commit(); db.close()
    return jsonify({"success": True})
```

- [ ] **Step 2: 重写 `delist_pending`（L3314-3388）**

将整个函数体替换为：

```python
@app.route("/api/delist/pending", methods=["GET"])
@jwt_required()
def delist_pending():
    """获取当前用户待处理的掉包通知列表（按产品聚合）。

    返回两种类型的通知：
    - type='first': 首次通知（组内任一包尚未弹出过）
    - type='reminder': 提醒通知（组内任一包已关闭超过 3 分钟，且未 dropped）
    """
    user_id = int(get_jwt_identity())
    db = _yt_db()
    uid_s = str(user_id)

    rows = db.execute(
        "SELECT dc.package_id, dc.product_id, dc.is_delisted, dc.checked_at, "
        "pkg.package_name, pkg.series_name, pkg.url, pkg.status AS pkg_status, "
        "prod.product_name, "
        "dn.first_notified, dn.dismissed_at, dn.reminder_count "
        "FROM delist_checks dc "
        "JOIN packages pkg ON dc.package_id = pkg.id "
        "JOIN products prod ON dc.product_id = prod.id "
        "LEFT JOIN delist_notifications dn ON dc.package_id = dn.package_id AND dn.user_id = ? "
        "WHERE dc.is_delisted = 1 "
        "AND (pkg.status IS NULL OR pkg.status = '' OR pkg.status = '0' OR pkg.status NOT IN ('dropped', 'paused')) "
        "AND (prod.runner_ids = ? OR prod.runner_ids LIKE ? OR prod.runner_ids LIKE ? OR prod.runner_ids LIKE ?) "
        "AND (prod.is_archived IS NULL OR prod.is_archived = 0) "
        "ORDER BY dc.checked_at DESC",
        (user_id, f"[{uid_s}]", f"[{uid_s},%", f"%, {uid_s},%", f"%, {uid_s}]")
    ).fetchall()

    now = datetime.datetime.now(datetime.timezone.utc)
    # 先按包计算 first/reminder
    pkg_notifications = []
    for r in rows:
        d = dict(r)
        pkg_status = (d.get("pkg_status") or "").strip()
        if pkg_status == "dropped":
            continue  # 已标记为掉包的不需要通知

        first_notified = d.get("first_notified") or 0
        dismissed_at = d.get("dismissed_at")

        if not first_notified:
            pkg_notifications.append({
                "product_id": d["product_id"],
                "product_name": d["product_name"],
                "series_name": d["series_name"] or "",
                "package_id": d["package_id"],
                "type": "first",
                "reminder_count": 0,
            })
        elif dismissed_at:
            try:
                dismissed_dt = datetime.datetime.fromisoformat(dismissed_at)
                if dismissed_dt.tzinfo is None:
                    dismissed_dt = dismissed_dt.replace(tzinfo=datetime.timezone.utc)
                elapsed = (now - dismissed_dt).total_seconds()
                if elapsed >= 180:  # 3 分钟 = 180 秒
                    pkg_notifications.append({
                        "product_id": d["product_id"],
                        "product_name": d["product_name"],
                        "series_name": d["series_name"] or "",
                        "package_id": d["package_id"],
                        "type": "reminder",
                        "reminder_count": d.get("reminder_count", 0),
                    })
            except (ValueError, TypeError):
                pass

    # 按 product_id 聚合（dict 保持插入顺序）
    groups = {}
    for n in pkg_notifications:
        pid = n["product_id"]
        g = groups.setdefault(pid, {
            "product_id": pid,
            "product_name": n["product_name"],
            "series_names": [],
            "package_ids": [],
            "type": n["type"],
            "reminder_count": 0,
        })
        sn = (n["series_name"] or "").strip()
        if sn and sn not in g["series_names"]:
            g["series_names"].append(sn)
        if n["package_id"] not in g["package_ids"]:
            g["package_ids"].append(n["package_id"])
        if n["type"] == "first":
            g["type"] = "first"  # first 优先于 reminder
        if n["reminder_count"] > g["reminder_count"]:
            g["reminder_count"] = n["reminder_count"]

    notifications = list(groups.values())

    db.close()
    return jsonify({"success": True, "notifications": notifications})
```

- [ ] **Step 3: 回归测试**

Run: `cd py && python -m pytest tests/test_delist_api.py -v`
Expected: `TestDismissDelist` 现有测试仍通过（`test_records_dismissal` 用旧 `package_id` 字段，兼容逻辑应使其通过）

- [ ] **Step 4: Commit**

```bash
git add py/main.py
git commit -m "feat: delist/pending 按产品聚合、delist/dismiss 支持批量"
```

---

### Task 4: 前端弹窗聚合 + 批量 dismiss + 多包跳转高亮

**Files:**
- Modify: `frontend/src/App.vue:49`（`_notifiedPkgIds` → `_notifiedProductIds`，仅改名）
- Modify: `frontend/src/App.vue:66-87`（`onMessage` + `_dismissRemotePkg`）
- Modify: `frontend/src/App.vue:99-156`（`checkDelistNotifications`）
- Modify: `frontend/src/api/products.js:21`（`dismissDelist`）
- Modify: `frontend/src/views/ProductPanel.vue:182-196`（watcher + `scrollToHighlightedPackage`）

**Interfaces:**
- Consumes: `productsApi.getPendingDelist()` 返回 `notifications[]`（产品聚合结构）；`productsApi.dismissDelist(packageIds)`
- Produces: 跳转 URL `/accounts/products?highlight_pkgs=<逗号分隔 pkgId>`

- [ ] **Step 1: `App.vue` 改名去重集合（L49）**

将 `const _notifiedPkgIds = new Set()` 改为 `const _notifiedProductIds = new Set()`。

- [ ] **Step 2: `App.vue` 更新 `onMessage`（L66-80）**

将：

```js
onMessage((msg) => {
  if (msg.type === MSG.DELIST_NOTIFIED) {
    const { package_id, type, reminder_count } = msg.payload
    // 与 checkDelistNotifications 中保持一致的 key 计算逻辑
    const key = type === 'reminder'
      ? `${package_id}-reminder-${reminder_count || 0}`
      : `${package_id}-first`
    _notifiedPkgIds.add(key)
  }
  if (msg.type === MSG.DELIST_DISMISSED) {
    const pkgId = msg.payload?.package_id
    if (pkgId) _dismissRemotePkg(pkgId)
  }
```

替换为：

```js
onMessage((msg) => {
  if (msg.type === MSG.DELIST_NOTIFIED) {
    const { product_id, type, reminder_count } = msg.payload
    // 与 checkDelistNotifications 中保持一致的 key 计算逻辑
    const key = type === 'reminder'
      ? `${product_id}-reminder-${reminder_count || 0}`
      : `${product_id}-first`
    _notifiedProductIds.add(key)
  }
  if (msg.type === MSG.DELIST_DISMISSED) {
    const productId = msg.payload?.product_id
    if (productId) _dismissRemotePkg(productId)
  }
```

- [ ] **Step 3: `App.vue` 更新 `_dismissRemotePkg`（L83-87）**

将：

```js
// 远程 dismiss：关闭本地同名 ElNotification（需持有引用）
const _notifRefs = {}
function _dismissRemotePkg(pkgId) {
  const ref = _notifRefs[pkgId]
  if (ref) { ref.close(); delete _notifRefs[pkgId] }
}
```

替换为：

```js
// 远程 dismiss：关闭本地同名 ElNotification（需持有引用，key 为 product_id）
const _notifRefs = {}
function _dismissRemotePkg(productId) {
  const ref = _notifRefs[productId]
  if (ref) { ref.close(); delete _notifRefs[productId] }
}
```

- [ ] **Step 4: `App.vue` 重写 `checkDelistNotifications`（L99-156）**

将整个函数替换为：

```js
async function checkDelistNotifications() {
  if (_checking) return  // 上一次检查未完成，跳过
  _checking = true
  try {
    const res = await productsApi.getPendingDelist()
    const notifications = res.notifications || []

    // 有掉包通知但未配置 Telegram 用户名时，提醒一次
    if (notifications.length > 0 && !_tgWarned && !auth.user?.telegram_username) {
      _tgWarned = true
      ElMessage.warning({
        message: '检测到包掉包！请在个人信息页配置 Telegram 用户名以接收群组 @ 通知',
        duration: 8000,
        showClose: true,
      })
    }

    for (const n of notifications) {
      // reminder 用 reminder_count 区分，避免重复提醒被去重；key 为产品级
      const key = n.type === 'reminder'
        ? `${n.product_id}-reminder-${n.reminder_count || 0}`
        : `${n.product_id}-first`
      if (_notifiedProductIds.has(key)) continue
      _notifiedProductIds.add(key)
      // 通知其他 Tab 同步跳过此通知
      broadcast(MSG.DELIST_NOTIFIED, {
        product_id: n.product_id,
        type: n.type,
        reminder_count: n.reminder_count || 0,
      })

      const title = n.type === 'first' ? '⚠️ 检测到包已掉包' : '⏰ 掉包提醒'
      const lines = []
      if (n.product_name) lines.push(`【${n.product_name}】`)
      for (const s of (n.series_names || [])) lines.push(s)
      lines.push('请将包状态设置为"掉包"（点击跳转到对应包）')

      const notifInst = ElNotification({
        title,
        message: lines.join('\n'),
        type: 'warning',
        duration: 0,
        position: 'top-right',
        showClose: true,
        onClick: () => {
          router.push(`/accounts/products?highlight_pkgs=${(n.package_ids || []).join(',')}`)
        },
        onClose: async () => {
          try { await productsApi.dismissDelist(n.package_ids || []) } catch {}
          delete _notifRefs[n.product_id]
          broadcast(MSG.DELIST_DISMISSED, { product_id: n.product_id, package_ids: n.package_ids })
        }
      })
      // 持有引用以便远程 dismiss
      if (notifInst) _notifRefs[n.product_id] = notifInst
    }
  } catch {} finally {
    _checking = false
  }
}
```

- [ ] **Step 5: `api/products.js` 更新 `dismissDelist`（L21）**

将：

```js
dismissDelist: (pkgId) => api.post('/delist/dismiss', { package_id: pkgId }),
```

替换为：

```js
dismissDelist: (packageIds) => api.post('/delist/dismiss', { package_ids: packageIds }),
```

- [ ] **Step 6: `ProductPanel.vue` 更新 watcher + `scrollToHighlightedPackage`（L182-196）**

将 watcher（L182）替换为：

```js
watch(() => route.query.highlight_pkgs, () => { scrollToHighlightedPackage() })
```

将函数（L184-196）替换为：

```js
async function scrollToHighlightedPackage() {
  const raw = route.query.highlight_pkgs || route.query.highlight_pkg || ''
  const pkgIds = String(raw).split(',').filter(Boolean)
  if (!pkgIds.length) return
  router.replace({ query: {} })  // 清除 query，避免后续重复滚动
  await nextTick()
  let scrolled = false
  for (const pkgId of pkgIds) {
    const el = document.getElementById('pkg-' + pkgId)
    if (!el) continue
    if (!scrolled) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      scrolled = true
    }
    el.style.boxShadow = '0 0 0 3px #ef4444'
    el.style.transition = 'box-shadow 0.3s'
    setTimeout(() => { el.style.boxShadow = '' }, 2000)
  }
}
```

- [ ] **Step 7: 前端构建校验**

Run: `cd frontend && npm run build`
Expected: 构建成功无报错（若项目无 build 脚本，改用 `npx vite build` 或跳过，人工确认语法）

- [ ] **Step 8: Commit**

```bash
git add frontend/src/App.vue frontend/src/api/products.js frontend/src/views/ProductPanel.vue
git commit -m "feat: 前端掉包弹窗按产品聚合、批量 dismiss、多包跳转高亮"
```

---

### Task 5: 迁移设计文档更新 v1.10

**Files:**
- Modify: `docs/superpowers/specs/2026-07-31-spring-boot-migration-design.md`

- [ ] **Step 1: 版本号与变更记录（L3-9 区域）**

将 L3-4 的版本号由 `v1.9` 改为 `v1.10`，日期补 `v1.10 更新于 2026-08-13`；并在 v1.9 变更行（L8）之上新增一行：

```markdown
> **v1.10 变更**: 掉包通知按产品聚合——`delist/pending` 返回产品聚合结构、`delist/dismiss` 接受 `package_ids[]`、Telegram 通知改为产品级（产品名 + 多系列名，不展示包名/链接）；前端弹窗按产品统一为一条（详见附录 G）
```

- [ ] **Step 2: 更新 9.6 Telegram 通知（L2726-2762）**

将 `TelegramSender.sendDelistNotification(PackageInfo pkgInfo, ...)` 代码块替换为产品级实现，并补消息格式说明：

```java
@Service
@Slf4j
public class TelegramSender {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${notification.telegram.bot-token}")
    private String botToken;

    @Value("${notification.telegram.chat-id}")
    private String chatId;

    // 产品级掉包通知：一个产品一条消息，展示产品名 + 多个系列名（不展示包名/链接）
    @Async
    public void sendProductDelistNotification(String productName,
            List<String> seriesNames, List<String> usernames) {
        String text = buildProductHtmlMessage(productName, seriesNames, usernames);
        String url = "https://api.telegram.org/bot" + botToken + "/sendMessage";

        Map<String, Object> body = Map.of(
            "chat_id", chatId,
            "text", text,
            "parse_mode", "HTML",
            "disable_web_page_preview", true
        );

        try {
            restTemplate.postForEntity(url, body, String.class);
            log.info("Telegram 产品级掉包通知已发送: {}", productName);
        } catch (Exception e) {
            log.error("Telegram 发送失败", e);
        }
    }

    private String buildProductHtmlMessage(String productName, List<String> seriesNames,
            List<String> usernames) {
        StringBuilder sb = new StringBuilder("<b>【GG-Server 掉包通知】</b>\n");
        if (!usernames.isEmpty()) {
            sb.append("\n").append(usernames.stream()
                .map(u -> "@" + u).collect(Collectors.joining(" ")));
        }
        sb.append("\n<b>产品：</b>").append(escapeHtml(productName)).append("\n");
        sb.append("<b>掉包系列：</b>\n");
        for (String sn : seriesNames) {
            sb.append("· ").append(escapeHtml(sn)).append("\n");
        }
        sb.append("\n该产品的多个包已被下架，请尽快将包状态设置为\"掉包\"。");
        return sb.toString();
    }
}
```

并在该代码块下补充说明：对应 Python `telegram_sender.py` 的 `send_product_delist_notification`，消息不再包含包名与链接。

- [ ] **Step 3: 补充 DelistController 说明（L1701 附近表格后）**

在 6.3 完整 Controller 清单表格后，追加一段说明：

```markdown
> **说明（v1.10 新增）**：`DelistController` 的 `delist/pending` 返回**产品聚合**结构
> （`{ product_id, product_name, series_names[], package_ids[], type, reminder_count }`），
> `delist/dismiss` 入参为 `package_ids[]`（批量）。对应 Python 端 `delist_pending` / `delist_dismiss`
> 已同步改造为按产品聚合/批量关闭；前端 `App.vue` 按产品统一弹窗、`ProductPanel.vue` 支持多包跳转高亮。
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-31-spring-boot-migration-design.md
git commit -m "docs: 迁移设计文档 v1.10 — 掉包通知按产品聚合"
```

---

## 自检（Self-Review）

- **Spec 覆盖**：弹窗聚合（Task 4）、Telegram 聚合（Task 1+2）、`pending` 聚合（Task 3）、`dismiss` 批量（Task 3）、标红不变（无改动）、跳转高亮（Task 4）、迁移文档（Task 5）——全部覆盖。
- **占位符**：无 TBD/TODO。
- **类型一致性**：`_send_telegram_notifications(db, pkgs)` 与 Task 2 两个调用方签名一致；`send_product_delist_notification(config, product_name, series_names, usernames)` 在 Task 1 定义、Task 2 调用一致；前端 `dismissDelist(packageIds)` 与 `product_id/package_ids` 字段跨 App.vue/api 一致。
