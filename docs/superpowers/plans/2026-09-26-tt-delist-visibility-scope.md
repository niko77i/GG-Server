# TT 掉包可见性收窄 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 去掉 TT 掉包两个查询接口中的 `developer/admin` 特权分支，使可见性只由「产品归属人 ∪ 在跑人员」决定。

**Architecture:** 纯删减 —— 把两处 `if role in ('developer', 'admin')` / `else` 的二分结构，压成只保留 `else` 那条路径。SQL 与参数不变，仅去掉特权捷径；顺带删除因此变成死变量的 `role`。

**Tech Stack:** Flask + Blueprint（`py/routes/tt_routes.py`）、SQLite、pytest + Flask test client。

**Spec:** [2026-09-26-tt-delist-visibility-scope-design.md](../specs/2026-09-26-tt-delist-visibility-scope-design.md)

## Global Constraints

- **最终口径**：TT 掉包可见性 = 产品归属人（`tt_products.owner_id`）**∪** 在跑人员（`tt_product_runners`）。**无 developer/admin 特权。**
- **两条轴都保留**：owner 轴**不得**去掉（设计文档 `:159` 明文需求，有具名测试钉住；用户 2026-09-26 复查后裁定保留）。
- **平台闸门不得动**：`@tt_required`（`delist_status`）与 `require_platform('tt')`（`delist_pending`）原样保留。
- **API 契约不变**：路由、HTTP 方法、响应结构（含 `platform: "tt"` 标记）全部不动，仅返回集合收窄。
- **前端一行不改**：`frontend/src/App.vue` 无角色过滤，纯渲染后端返回 —— **本次改动本身不需要 `npm run build`**（仅限本设计范围；工作区若另有并行会话在途的前端改动，仍需另行构建）。
- **禁止外发真实通知**：测试中 Telegram / 邮件一律 monkeypatch。
- **禁止 `git add -A`**：本仓库有并行会话在途改文件，只按路径精确提交。
- **不得自行启动/重启进程**：改完只提醒用户重启 Flask，不代为执行。
- 改完测试**必须真跑**，未跑过的测试不得计入交付。

---

## File Structure

| 文件 | 职责 | 本次改动 |
|------|------|---------|
| `py/routes/tt_routes.py` | TT 平台全部 Blueprint 路由 | `delist_status`（:729）与 `delist_pending`（:762）各删一支特权分支 + 删死变量 `role` + 改 2 处注释/docstring |
| `py/tests/test_tt_delist_notification.py` | TT 掉包通知测试（pending / dismiss / 定时 / Telegram） | 新增 `TestTtDelistStatusScope` 类；改写 `test_developer_sees_all`；新增 2 条 pending 用例 |
| `docs/superpowers/specs/2026-09-24-tt-delist-notification-design.md` | TT 掉包通知设计 | 修正 `:93` / `:159` 两处与本次裁定相反的表述 |
| `AGENTS.md` | 项目主文档 | TT 掉包通知段补「可见性无角色特权」口径 |

---

### Task 1: `delist_status` 去掉特权分支

**Files:**
- Modify: `py/routes/tt_routes.py:729-756`（`delist_status` 函数体）
- Test: `py/tests/test_tt_delist_notification.py`（在 `TestTtDelistPending` 类之后、`# ==================== dismiss 接口 ====================` 之前插入新类）

**Interfaces:**
- Consumes: 测试文件模块级辅助 `_make_tt_user(client, username) -> (headers, uid)`、`_mk_product(db, owner_id, name="TT产品", status="active") -> pid`、`_mk_package(db, product_id, series="系列A", status="", pkg_type="package") -> pkg_id`、`_mark_delisted(db, package_id, is_delisted=1)`（均已存在，无需新建）
- Consumes: conftest 夹具 `client`、`tt_headers`（ttuser，platform=tt）、`dev_headers`（devuser，role=developer，platform=gg，走 `PLATFORM_SWITCH_ROLES` 放行 `@tt_required`）
- Produces: 无新符号对外暴露；仅改变 `GET /api/tt/products/delist-status` 的返回集合

- [ ] **Step 1: 写失败测试**

在 `py/tests/test_tt_delist_notification.py` 的 `TestTtDelistPending` 类结束之后（即 `# ==================== dismiss 接口 ====================` 那一行之前）插入：

```python
# ==================== delist-status 接口（可见性） ====================

class TestTtDelistStatusScope:
    """delist-status 可见性：归属人 ∪ 在跑人员，无 developer/admin 特权。"""

    def test_developer_no_longer_sees_others(self, client, dev_headers):
        """根因回归：developer 非 owner 非在跑 → 看不到他人产品的掉包。

        改动前本接口对 developer 返回全部（carl567 误收弹窗即此因），故本用例先红后绿。
        """
        _, uid = _make_tt_user(client, "tt_dl_dev_a")
        db = database.get_db()
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        resp = client.get("/api/tt/products/delist-status", headers=dev_headers)
        assert resp.status_code == 200
        assert resp.get_json()["delisted_packages"] == []

    def test_developer_sees_when_runner(self, client, dev_headers):
        """正向对照：developer 被列为在跑人员时确实能看到。

        防「接口对 developer 整体返空」的假绿 —— 上一条用例单独存在时，
        把函数写成 `return ok({'delisted_packages': []})` 也能骗过它。
        """
        _, uid = _make_tt_user(client, "tt_dl_dev_b")
        db = database.get_db()
        dev_uid = db.execute("SELECT id FROM users WHERE username='devuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        db.execute("INSERT INTO tt_product_runners(product_id, user_id) VALUES(?,?)", (pid, dev_uid))
        _mark_delisted(db, _mk_package(db, pid))
        db.commit()
        db.close()

        resp = client.get("/api/tt/products/delist-status", headers=dev_headers)
        assert resp.status_code == 200
        assert len(resp.get_json()["delisted_packages"]) == 1

    def test_owner_axis_kept(self, client, tt_headers):
        """owner 轴保留（用户 2026-09-26 复查裁定）：归属人无在跑人员时仍可见。"""
        db = database.get_db()
        uid = db.execute("SELECT id FROM users WHERE username='ttuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        resp = client.get("/api/tt/products/delist-status", headers=tt_headers)
        assert resp.status_code == 200
        assert len(resp.get_json()["delisted_packages"]) == 1

    def test_other_user_cannot_see(self, client, tt_headers):
        """补 test_tt_routes.py 注释段留下的越权回归缺口：非 owner/runner 看不到他人掉包。"""
        _, uid = _make_tt_user(client, "tt_dl_other_d")
        db = database.get_db()
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        resp = client.get("/api/tt/products/delist-status", headers=tt_headers)
        assert resp.status_code == 200
        assert resp.get_json()["delisted_packages"] == []
```

- [ ] **Step 2: 跑测试确认按预期失败**

Run: `cd py && python -m pytest tests/test_tt_delist_notification.py::TestTtDelistStatusScope -v`

Expected: `test_developer_no_longer_sees_others` **FAIL**（断言 `[...] == []` 失败，实际有 1 条 —— 特权分支放行）。
其余 3 条 **PASS**（它们是钉子与对照，改动前后都应绿）。这一红一绿正是根因的证明。

- [ ] **Step 3: 实现 —— 删除特权分支**

把 `py/routes/tt_routes.py` 的 `delist_status`（`:729` 起）函数体改成：

```python
@tt_bp.route('/api/tt/products/delist-status', methods=['GET'])
@jwt_required()
@tt_required
def delist_status():
    """获取当前用户可见的掉包检测状态（按归属/在跑人员，无角色特权）。"""
    db = get_db()
    uid = get_uid()

    base_sql = (
        "SELECT dc.package_id, dc.is_delisted, dc.checked_at, "
        "pkg.series_name, pkg.package_name, pkg.url, pkg.status AS pkg_status, "
        "prod.product_name "
        "FROM tt_delist_checks dc "
        "JOIN tt_packages pkg ON dc.package_id = pkg.id "
        "JOIN tt_products prod ON pkg.product_id = prod.id "
    )
    where = (
        "WHERE dc.is_delisted = 1 AND prod.is_archived = 0 AND "
        "(prod.owner_id = ? OR pkg.product_id IN "
        "(SELECT product_id FROM tt_product_runners WHERE user_id=?)) "
    )

    rows = db.execute(base_sql + where + "ORDER BY dc.checked_at DESC", [uid, uid]).fetchall()
    delisted = [dict(r) for r in rows]
    return ok({'delisted_packages': delisted})
```

要点：
- 删掉 `if role in ('developer', 'admin'): ... else: ...` 整个二分，只留 `else` 的 where/params。
- **同时删掉** `role = _get_role(db, uid)`（原 `:736`）—— 删分支后它成为死变量。
- `base_sql` 逐字不变。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_delist_notification.py::TestTtDelistStatusScope -v`

Expected: 4 passed。

- [ ] **Step 5: 确认死变量已清净**

Run: `cd py && grep -n "role" routes/tt_routes.py | sed -n '1,40p'`

Expected: `delist_status` 函数体内**不再出现** `role`。若仍有 `_get_role` 残留，说明 Step 3 漏删。

- [ ] **Step 6: 提交**

```bash
cd /d/server/cc/GG-Server
git add py/routes/tt_routes.py py/tests/test_tt_delist_notification.py
git commit -m "fix(tt): delist-status 去掉 developer/admin 特权，只按归属∪在跑人员"
```

---

### Task 2: `delist_pending` 去掉特权分支

**Files:**
- Modify: `py/routes/tt_routes.py:762-807`（`delist_pending` 函数体）
- Test: `py/tests/test_tt_delist_notification.py:116`（改写 `test_developer_sees_all`）+ 同文件新增 1 条对照用例

**Interfaces:**
- Consumes: Task 1 已确立的口径（同一可见性规则，两个接口必须一致）
- Consumes: 同 Task 1 的模块级辅助与夹具
- Produces: 无新符号；仅改变 `GET /api/tt/delist/pending` 的返回集合

- [ ] **Step 1: 改写既有失败测试 + 新增对照测试**

在 `py/tests/test_tt_delist_notification.py` 中，把 `TestTtDelistPending` 类的
`test_developer_sees_all`（`:116`，原为断言 developer 看到全部）整段替换为下面两条：

```python
    def test_developer_no_longer_sees_all(self, client, dev_headers):
        """改自 test_developer_sees_all：developer 不再因角色看到全部。

        收窄后与普通用户同口径 —— developer 非 owner、非在跑人员 → 空。
        """
        _, uid = _make_tt_user(client, "ttuser_dev")
        db = database.get_db()
        pid = _mk_product(db, uid)
        _mark_delisted(db, _mk_package(db, pid))
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=dev_headers)
        assert resp.status_code == 200
        assert resp.get_json()["notifications"] == []

    def test_developer_sees_when_runner(self, client, dev_headers):
        """正向对照：developer 作为在跑人员时确实收到通知。

        防「接口对 developer 整体返空」的假绿。
        """
        _, uid = _make_tt_user(client, "ttuser_dev_runner")
        db = database.get_db()
        dev_uid = db.execute("SELECT id FROM users WHERE username='devuser'").fetchone()["id"]
        pid = _mk_product(db, uid)
        db.execute("INSERT INTO tt_product_runners(product_id, user_id) VALUES(?,?)", (pid, dev_uid))
        _mark_delisted(db, _mk_package(db, pid))
        db.commit()
        db.close()

        resp = client.get("/api/tt/delist/pending", headers=dev_headers)
        notifs = resp.get_json()["notifications"]
        assert len(notifs) == 1
        assert notifs[0]["product_id"] == pid
```

> 注意：`_make_tt_user` 会把新用户 platform 置为 `tt`；`dev_headers` 的 devuser 是
> role=developer / platform=gg，经 `PLATFORM_SWITCH_ROLES` 放行平台闸门。

- [ ] **Step 2: 跑测试确认按预期失败**

Run: `cd py && python -m pytest tests/test_tt_delist_notification.py::TestTtDelistPending -v`

Expected: `test_developer_no_longer_sees_all` **FAIL**（旧代码下 developer 命中特权分支，返回 1 条而非 0）；
`test_developer_sees_when_runner` **PASS**（在跑人员本就在两种实现下都可见）。

- [ ] **Step 3: 实现 —— 删除特权分支**

把 `py/routes/tt_routes.py` 的 `delist_pending` 中这两段：

```python
    role = _get_role(db, uid)
```

（原 `:785`，整行删除）

以及原 `:803-804`：

```python
    if role in ('developer', 'admin'):
        params = [uid]
    else:
        base_sql += (
            "AND (prod.owner_id = ? OR pkg.product_id IN "
            "(SELECT product_id FROM tt_product_runners WHERE user_id=?)) "
        )
        params = [uid, uid, uid]
```

改为（只保留原 `else` 的内容，取消缩进一层）：

```python
    base_sql += (
        "AND (prod.owner_id = ? OR pkg.product_id IN "
        "(SELECT product_id FROM tt_product_runners WHERE user_id=?)) "
    )
    params = [uid, uid, uid]
```

同时改两处文案：

(a) 函数 docstring（原 `:769`）最后一句：

```python
    可见性与 delist_status 一致：按 owner_id 或在跑人员，无 developer/admin 特权。
```

（原为「可见性与 delist_status 一致：跨用户角色看全部，其余按 owner_id 或在跑人员。」）

(b) 平台闸门注释（原 `:779-783`）末句：

```python
    # developer / 户管 属 PLATFORM_SWITCH_ROLES 直接放行；二者通常不命中任何
    # TT 产品（除非确为归属人或在跑人员）→ 天然返回空。闸门仍不可去掉：
    # 非 TT 且不可切平台的用户（如 GG 的 admin）必须在此被挡下。
```

**不得改动**：`if require_platform('tt') is not None: return ok({'notifications': []})` 这一整段；
`base_sql` 的 SELECT 与 WHERE 主体；`now` 之后的聚合逻辑。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd py && python -m pytest tests/test_tt_delist_notification.py -v`

Expected: 全绿（含 `TestTtDelistPending` 全部、`TestTtDelistDismiss`、`TestTtTelegramSender`、
`TestTtManualCheckNotify`、`TestTtDelistScheduler`、新增的 `TestTtDelistStatusScope`）。

- [ ] **Step 5: 确认死变量已清净**

Run: `cd py && awk 'NR>=760 && NR<=830 && /role/ {print NR": "$0}' routes/tt_routes.py`

Expected: 无输出（`delist_pending` 内不再引用 `role`）。

- [ ] **Step 6: 提交**

```bash
cd /d/server/cc/GG-Server
git add py/routes/tt_routes.py py/tests/test_tt_delist_notification.py
git commit -m "fix(tt): delist/pending 去掉 developer/admin 特权，与 delist-status 同口径"
```

---

### Task 3: 文档同步

**Files:**
- Modify: `docs/superpowers/specs/2026-09-24-tt-delist-notification-design.md:93` 与 `:159`
- Modify: `AGENTS.md`（TT 掉包通知段）
- Modify: `docs/superpowers/specs/2026-09-26-tt-delist-visibility-scope-design.md`（状态行）
- Modify: `AGENTS.md:866`（索引行的「待用户确认，未动代码」脚注）

**Interfaces:**
- Consumes: Task 1 / Task 2 已落地的口径
- Produces: 无代码符号

- [ ] **Step 1: 修正旧设计文档两处相反表述**

先看原文：

Run: `cd /d/server/cc/GG-Server && sed -n '93p;159p' docs/superpowers/specs/2026-09-24-tt-delist-notification-design.md`

把这两行里「developer/admin 全部」「developer/admin 看全部」的表述改为与本次裁定一致：

- `:93` 行内「…在 `tt_product_runners` 中；**developer/admin 全部**」
  → 「…在 `tt_product_runners` 中；**归属人（`owner_id`）或在跑人员**」
- `:159` 行内「TT 掉包 pending 沿用 `delist_status` 的角色过滤（**developer/admin 看全部**，其余按 `owner_id` 或在跑人员）」
  → 「TT 掉包 pending 与 `delist_status` 同口径（按 `owner_id` 或在跑人员，**无 developer/admin 特权**；
     该特权已于 2026-09-26 按用户裁定移除，详见
     `2026-09-26-tt-delist-visibility-scope-design.md`）」

- [ ] **Step 2: 在 AGENTS.md 的 TT 掉包通知段补口径**

在 `AGENTS.md`「### TT 掉包通知（独立机器人）」的「**核心逻辑**」列表中，
「**前端通知**」一条之后插入一条：

```markdown
- **可见性**：`delist/pending` 与 `delist-status` 均只按**产品归属人（`owner_id`）或在跑人员**过滤，
  **无 developer/admin 特权**（2026-09-26 按用户裁定移除该特权分支；起因是 developer 账号
  即使不在跑也收到掉包弹窗）。平台闸门 `require_platform('tt')` / `@tt_required` 不受影响。
```

- [ ] **Step 3: 更新本次设计文档的状态行与索引脚注**

- `docs/superpowers/specs/2026-09-26-tt-delist-visibility-scope-design.md` 顶部
  `> 状态：**已定稿并经用户确认，进入实现**` → `> 状态：**已实现（2026-09-26）**`
- `AGENTS.md:866` 索引行末尾的 `（**待用户确认，未动代码**）` → 删除该脚注

- [ ] **Step 4: 提交**

```bash
cd /d/server/cc/GG-Server
git add AGENTS.md docs/superpowers/specs/2026-09-24-tt-delist-notification-design.md docs/superpowers/specs/2026-09-26-tt-delist-visibility-scope-design.md
git commit -m "docs(tt): 同步掉包可见性收窄口径（旧 spec 两处相反表述 + AGENTS.md）"
```

---

### Task 4: 代码审查与收口

**Files:**
- 视审查结论而定（只改本次触及的文件）

- [ ] **Step 1: 调用 `/code-review`**

本次改动触及**权限 / 可见性**边界，按 CLAUDE.md 必须走 `/code-review`。

Run: `/code-review`

- [ ] **Step 2: 逐条处置审查发现**

对 Critical / Important 逐条修复，修复后重跑 Task 1 / Task 2 的测试并附上**真实输出**。
Minor 若判定为零影响，需在交付说明里写明理由，不得静默丢弃。

- [ ] **Step 3: 全量回归**

Run: `cd py && python -m pytest tests/test_tt_delist_notification.py tests/test_huguan_role.py tests/test_tt_appstore_package.py tests/test_delist_checker.py -v`

Expected: 全绿。任何红都必须先解释清楚再交付。

- [ ] **Step 4: 收尾提醒（**不代为执行**）**

向用户报告以下三条待办，**由用户自行执行**：
1. **重启 Flask 服务**（后端 `py/routes/tt_routes.py` 已改，不重启不生效）
2. **提交 git**（若尚有未提交改动）
3. 本次**不需要** `npm run build`（前端未改）—— 但若并行会话的前端改动尚未构建，另行提醒

---

## Self-Review

**1. Spec coverage**

| Spec 章节 | 覆盖任务 |
|-----------|---------|
| §1.3 裁定 1（去特权） | Task 1 Step 3、Task 2 Step 3 |
| §1.3 裁定 2（**保留** owner 轴） | Global Constraints + Task 1 `test_owner_axis_kept` + Task 2 未动 owner 分支 |
| §2 为何是对齐 GG | Task 3 Step 1/2（文档口径） |
| §3.1 `delist_status` | Task 1 Step 3 |
| §3.2 `delist_pending` | Task 2 Step 3 |
| §3.3 不动的部分（平台闸门 / Telegram / 前端） | Global Constraints；Task 2 Step 3 明确「不得改动」 |
| §5 涉及文件 | File Structure 表 |
| §7 测试影响（仅 1 条红） | Task 2 Step 1（改写）；Task 1 Step 1（补越权缺口） |
| §8 验证方式（含正向对照腿 + 真实 HTTP 入口） | Task 1 Step 1、Task 2 Step 1（均为 `client.get(...)` 端到端） |
| §9 边界与风险 | Global Constraints |

无遗漏。

**2. Placeholder scan**

无 TBD / TODO /「类似上文」/「自行处理错误情况」。所有代码步骤均给出完整可粘贴代码与确切命令。

**3. Type consistency**

- 两处接口的过滤条件逐字一致：`(prod.owner_id = ? OR pkg.product_id IN (SELECT product_id FROM tt_product_runners WHERE user_id=?))`
- 参数个数一致且与 SQL 占位符数相符：`delist_status` → `[uid, uid]`；`delist_pending` → `[uid, uid, uid]`
  （第三个差异来自 pending 的 `LEFT JOIN tt_delist_notifications ... AND dn.user_id = ?`，其占位符在 SQL 文本中更靠前）
- 测试辅助函数签名与既有定义一致：`_make_tt_user(client, username)`、`_mk_product(db, owner_id, name, status)`、
  `_mk_package(db, product_id, series, status, pkg_type)`、`_mark_delisted(db, package_id, is_delisted)`
- 新用例名在两处引用中一致：`TestTtDelistStatusScope`、`test_developer_no_longer_sees_all`、`test_developer_sees_when_runner`
