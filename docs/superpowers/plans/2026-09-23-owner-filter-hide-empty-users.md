# 「归属人」下拉只列出有账户的用户 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 账户面板的「归属人」下拉不再列出「在该平台一个户都没有」的用户（户管豁免）。

**Architecture:** 纯后端单点改动。`/api/platform/users` 的 WHERE 上加一条 `role = 'huguan' OR EXISTS(该平台账户表里 owner_id=u.id AND deleted_at IS NULL)`。之所以单点够用：前端 `client.js` 的请求拦截器已按 `window.location.hash` 给这个接口注入 `platform`（`/tt`→tt、`/fb`→fb、其余 gg），后端因此**本来就知道是哪个面板在问**，可以直接按白名单映射选表。前端一行不动。

**Tech Stack:** Flask + SQLite（`py/`）；pytest（现有套件 `py/tests/`）。前端 Vue 3 + Element Plus —— 本次零改动。

**Spec:** `docs/superpowers/specs/2026-09-23-owner-filter-hide-empty-users-design.md`

## Global Constraints

- **纯增量**：不改动 `/api/platform/users` 已有的两个条件（平台隔离、排除 `hidden`），只在其结果集上「减人」。返回字段、返回结构、`owner_id` 语义（空 = 全部）全部不变。
- **户管豁免**：`role = 'huguan'` 无论有无账户恒列出（用户裁定：「户管就是管理所有户的」「其他角色都一样」—— 不为 developer / admin 开特例）。
- **「有账户」口径**：该平台账户表里 `deleted_at IS NULL` 的行（与仓库既有口径一致，见 `main.py:3752`、`main.py:6122-6124`）。
- **前端零改动**：不改 `OwnerFilterSelect.vue` / `ownerScope.js`；0 户用户默认选中自己时显示裸 id 属**已裁定接受**的已知现象。
- **不动的接口**：`/api/tt/users`、`/api/fb/users`（那是产品面板选「跑手」用的）。
- 测试命令必须在 `py/` 目录下跑：`cd py && python -m pytest ...`（仓库根的 `py/` 会遮蔽 pytest 自身的 `py` 依赖）。
- 提交信息按仓库既有约定使用中文 `feat:` / `fix:` / `test:` 前缀。

---

### Task 1: 后端接口加「有账户」约束与户管豁免

**Files:**
- Modify: `py/main.py:6016-6032`（`platform_users()` 及其上方新增常量）

**Interfaces:**
- Consumes: 既有 `_get_effective_platform()`（`py/main.py:6005`）、`_yt_db()`
- Produces: `GET /api/platform/users` 返回体结构不变（`{"success": true, "users": [{id, username, display_name, platform}]}`），仅结果集收窄。无新增参数、无新增字段。

- [x] **Step 1: 新增平台→账户表白名单常量**

在 `py/main.py` 的 `platform_users()` 定义**上方**（即 `py/main.py:6015` 那个空行处，`_get_effective_platform()` 之后）插入：

```python
# 有效平台 → 该平台的账户表。表名无法用占位符参数化，故走白名单映射：
# 用户输入进不了这个字典的键，拼接出来的表名只可能是这三个之一。
ACCOUNT_TABLE_BY_PLATFORM = {"gg": "accounts", "fb": "fb_accounts", "tt": "tt_accounts"}
```

- [x] **Step 2: 改写 `platform_users()` 的查询**

把 `py/main.py:6019-6032` 的 docstring 与查询体替换为：

```python
    """当前有效平台下的用户列表，供账户面板的「归属人」筛选下拉使用。

    只列出**在该平台有未删除账户**的用户 —— 选中一个名下无户的人必然得到空表，
    这种选项没有筛选价值。

    户管（huguan）豁免：户管管理所有户，本人在该平台可能一个户都没有，仍恒列出。

    「有无账户」口径 = 该平台账户表里 `deleted_at IS NULL` 的行，与
    /api/accounts/list 等既有查询一致；软删除的户不算数。
    """
    platform = _get_effective_platform()
    table = ACCOUNT_TABLE_BY_PLATFORM.get(platform, "accounts")  # 未知平台回退 gg，与 _get_effective_platform 的缺省一致
    db = _yt_db()
    rows = db.execute(
        "SELECT u.id, u.username, u.display_name, u.platform FROM users u "
        "WHERE (u.platform = ? OR u.role = 'developer') AND u.role != 'hidden' "
        "  AND (u.role = 'huguan' OR EXISTS ("
        f"      SELECT 1 FROM {table} a WHERE a.owner_id = u.id AND a.deleted_at IS NULL)) "
        "ORDER BY u.display_name, u.username",
        (platform,)
    ).fetchall()
    return jsonify({"success": True, "users": [dict(r) for r in rows]})
```

- [x] **Step 3: 直连接口验证（不依赖测试套件，确认新口径生效）**

创建临时脚本 `D:/server/cc/_gghist/verify_platform_users.py`（仓库外，不进版本库）：

```python
"""直连真库跑一遍新口径，绕过 Flask 请求层。"""
import sqlite3, sys
sys.stdout.reconfigure(encoding="utf-8")

ACCOUNT_TABLE_BY_PLATFORM = {"gg": "accounts", "fb": "fb_accounts", "tt": "tt_accounts"}
con = sqlite3.connect(r"D:/server/cc/GG-Server/temp/app.db")
con.row_factory = sqlite3.Row

def platform_users(platform):
    table = ACCOUNT_TABLE_BY_PLATFORM.get(platform, "accounts")
    return [dict(r) for r in con.execute(
        "SELECT u.id, u.username, u.display_name, u.platform FROM users u "
        "WHERE (u.platform = ? OR u.role = 'developer') AND u.role != 'hidden' "
        "  AND (u.role = 'huguan' OR EXISTS ("
        f"      SELECT 1 FROM {table} a WHERE a.owner_id = u.id AND a.deleted_at IS NULL)) "
        "ORDER BY u.display_name, u.username",
        (platform,))]

for p in ("gg", "fb", "tt"):
    us = platform_users(p)
    print(f"{p.upper()}: {len(us)} 人 -> " + (", ".join(f"{u['display_name'] or u['username']}({u['role']})" for u in us) or "（空）"))

gg = {u["username"] for u in platform_users("gg")}
assert "户部尚书" in gg, "户管必须豁免"
assert "阿信" not in gg and "柠檬" not in gg and "蜻蜓" not in gg, "0 户 admin 必须被剔除"
assert "Developer" not in gg, "0 户 developer 必须被剔除"
assert "卡尔" in gg, "有户的 developer 必须保留"
print("\n断言全部通过")
```

Run: `python D:/server/cc/_gghist/verify_platform_users.py`

Expected（与设计文档 §5 一致）：

```
GG: 5 人 -> 卡尔(developer), 大盗(admin), 户部尚书(huguan), 拉菲(admin), 阿伟(admin)
FB: 0 人 -> （空）
TT: 1 人 -> 黎明(admin)

断言全部通过
```

（顺序按 `display_name` 排，中文排序可能与上面不同，**人数与集合**才是断言点。）

- [x] **Step 4: 提交**

```bash
cd /d/server/cc/GG-Server
git add py/main.py
git commit -m "feat: 「归属人」下拉只列出有账户的用户（户管豁免）"
```

---

### Task 2: 修复 3 个既有用例 + 新增 4 个用例

**背景（务必读）：** Task 1 会让 `TestPlatformUsersEndpoint` 的 **3 个用例全部红灯** —— 它们插入的夹具用户都是 0 账户，会被新过滤整批剔掉。

**修法是给夹具补账户行，不是改断言。** 尤其两处负面断言（`_hgpu_gg not in names`、`_hgpu_leak not in names`）必须让对应夹具**确实持有该平台账户**，否则新过滤会代为满足它们 —— 平台隔离一旦被破坏也不会红，断言就成了空的。测试文件里已两次强调这个陷阱（见 `test_huguan_role.py:362-364`、`test_huguan_role.py:412-413`）。

**Files:**
- Modify: `py/tests/test_huguan_role.py:359-414`（`TestPlatformUsersEndpoint` 三个用例）
- Modify: `py/tests/test_huguan_role.py`（在同一类内**新增** 3 个用例）

**Interfaces:**
- Consumes: 既有夹具 `_create_user(client, username, role="user", platform="gg") -> (headers, user_id)`（`test_huguan_role.py:9`）、`_huguan(client, username, platform="gg") -> (headers, user_id)`（`:23`）、`database.get_db()`。
- Produces: 无（仅测试）。

参考的三平台插法（均已在同文件用过）：
- `accounts`：`INSERT INTO accounts(name, account_id, owner_id) VALUES(?,?,?)`（`:418`）
- `tt_accounts`：`INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES(?,?,?)`（`:986`）
- `fb_accounts`：`INSERT INTO fb_accounts(name, account_id, owner_id) VALUES(?,?,?)`（`:1120`）

- [x] **Step 1: 先跑一遍，确认这 3 个用例确实红了**

Run: `cd py && python -m pytest tests/test_huguan_role.py::TestPlatformUsersEndpoint -q`

Expected: `3 failed`（三条失败都应落在 `... in names` 那类断言上）。**若此时是全绿，说明 Task 1 的改动没生效，先回去查 Task 1。**

- [x] **Step 2: 修 `test_huguan_sees_only_current_platform`**

把 `py/tests/test_huguan_role.py:360-376` 整段替换为：

```python
    def test_huguan_sees_only_current_platform(self, client):
        """户管切到 TT 时只应看到 TT + developer，不该看到 GG 行。

        注意这里用 `?platform=tt` 而**不是**调用者自身的 gg —— 否则即使
        `_get_effective_platform()` 完全忽略查询参数，本用例也会通过。

        两个夹具各配一个**本平台**账户：接口只列「名下有未删除账户」的人。
        若给 `_hgpu_gg` 不配账户（或配成 TT 账户），`_hgpu_gg not in names` 就会被
        账户过滤代为满足 —— 平台隔离一旦被破坏也不会红，那就成了空断言。
        """
        hg, _ = _huguan(client, "_hgpu_hg")  # users.platform == 'gg'
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_gg','x','user','gg')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_tt','x','user','tt')")
        gg_id = db.execute("SELECT id FROM users WHERE username='_hgpu_gg'").fetchone()["id"]
        tt_id = db.execute("SELECT id FROM users WHERE username='_hgpu_tt'").fetchone()["id"]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('GG夹具户','_hgpu_gg_acc',?)", (gg_id,))
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES('TT夹具户','_hgpu_tt_acc',?)", (tt_id,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=tt", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_tt" in names
        assert "_hgpu_gg" not in names
```

- [x] **Step 3: 修 `test_includes_developer_excludes_hidden`**

把 `py/tests/test_huguan_role.py:378-395` 整段替换为：

```python
    def test_includes_developer_excludes_hidden(self, client):
        """developer 行必须经 `OR role = 'developer'` 命中，hidden 行必须被排除。

        `_hgpu_dev` 故意插成 platform='tt'：调用者只查 platform='gg'，因此该行
        **只能**经 developer 分支出现。若把它插成 'gg'，它会被 `platform = ?`
        命中，删掉 `OR role = 'developer'` 断言也不会红 —— 那就成了空断言。

        两个夹具都配 **GG**（`accounts`）账户 —— 查的是 gg 面板，接口按有效平台选表，
        配错表或干脆不配，两条断言都会被账户过滤代为满足，同样失去守卫力。
        """
        hg, _ = _huguan(client, "_hgpu_hg2")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_dev','x','developer','tt')")
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_hid','x','hidden','gg')")
        dev_id = db.execute("SELECT id FROM users WHERE username='_hgpu_dev'").fetchone()["id"]
        hid_id = db.execute("SELECT id FROM users WHERE username='_hgpu_hid'").fetchone()["id"]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('dev夹具户','_hgpu_dev_acc',?)", (dev_id,))
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('hid夹具户','_hgpu_hid_acc',?)", (hid_id,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_dev" in names
        assert "_hgpu_hid" not in names
```

> 注意 `_hgpu_hid` **也要**配账户：否则删掉 `role != 'hidden'` 这条约束，它仍会被账户过滤挡住，本用例不会红。

- [x] **Step 4: 修 `test_non_switch_role_cannot_pick_platform`**

把 `py/tests/test_huguan_role.py:397-414` 整段替换为：

```python
    def test_non_switch_role_cannot_pick_platform(self, client):
        """非切换角色传 ?platform= 必须被忽略，只能拿到自己平台的数据。

        本接口只挂 @jwt_required()，不像 /api/tt/users、/api/fb/users 那样挂平台
        装饰器，因此这条隔离属性只能靠本用例守护。

        两个夹具各配**本平台**账户（plain 配 GG、leak 配 TT）：接口只列「名下有未删除
        账户」的人，不配的话 `_hgpu_leak not in names` 会被账户过滤代为满足。
        """
        u, plain_id = _create_user(client, "_hgpu_plain", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO users(username, password, role, platform) VALUES('_hgpu_leak','x','user','tt')")
        leak_id = db.execute("SELECT id FROM users WHERE username='_hgpu_leak'").fetchone()["id"]
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('plain夹具户','_hgpu_plain_acc',?)", (plain_id,))
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES('leak夹具户','_hgpu_leak_acc',?)", (leak_id,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=tt", headers=u)
        assert resp.status_code == 200
        names = {x["username"] for x in resp.get_json()["users"]}
        assert "_hgpu_leak" not in names
        # 正向断言：调用者自己（platform='gg'）必须在结果里。否则若接口返回空列表，
        # 上面那条负面断言也会通过 —— 那就成了空断言。
        assert "_hgpu_plain" in names
```

- [x] **Step 5: 跑一遍，确认 3 个用例恢复绿**

Run: `cd py && python -m pytest tests/test_huguan_role.py::TestPlatformUsersEndpoint -q`

Expected: `3 passed`

- [x] **Step 6: 新增 3 个用例覆盖新口径**

在 `TestPlatformUsersEndpoint` 类末尾（`test_non_switch_role_cannot_pick_platform` 之后、`def _mk_account` 之前）追加：

```python
    def test_excludes_users_without_accounts(self, client):
        """新口径：非户管用户在该平台 0 户时，不出现在下拉里。"""
        hg, _ = _huguan(client, "_hgpu_hg3")
        _, with_acc = _create_user(client, "_hgpu_with", role="user", platform="gg")
        _, without_acc = _create_user(client, "_hgpu_without", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO accounts(name, account_id, owner_id) VALUES('有户','_hgpu_with_acc',?)", (with_acc,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_with" in names
        assert "_hgpu_without" not in names

    def test_deleted_account_does_not_count(self, client):
        """新口径：「有账户」看的是**未删除**的户 —— 只剩软删除户的人同样被排除。

        守卫 `a.deleted_at IS NULL`：把它删掉，本用例必红。
        """
        hg, _ = _huguan(client, "_hgpu_hg4")
        _, uid = _create_user(client, "_hgpu_deleted", role="user", platform="gg")
        db = database.get_db()
        db.execute("INSERT INTO accounts(name, account_id, owner_id, deleted_at) "
                   "VALUES('已删除户','_hgpu_del_acc',?, datetime('now','localtime'))", (uid,))
        db.commit()
        db.close()
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_deleted" not in names

    def test_huguan_exempt_even_without_accounts(self, client):
        """新口径：户管豁免 —— 自己在该平台 0 户也仍列出（户管管理所有户）。

        守卫 `u.role = 'huguan' OR ...`：把它删掉，本用例必红。
        """
        hg, _ = _huguan(client, "_hgpu_hg_exempt")
        resp = client.get("/api/platform/users?platform=gg", headers=hg)
        assert resp.status_code == 200
        names = {u["username"] for u in resp.get_json()["users"]}
        assert "_hgpu_hg_exempt" in names

    def test_account_table_follows_effective_platform(self, client):
        """新口径：账户表按**有效平台**选 —— 持有 TT 户的人在 gg 面板下拉里不出现。

        守卫 `ACCOUNT_TABLE_BY_PLATFORM` 的平台→表映射：若把 tt 面板也错查成
        `accounts`，本用例必红。
        """
        hg, _ = _huguan(client, "_hgpu_hg5")
        _, uid = _create_user(client, "_hgpu_ttonly", role="user", platform="tt")
        db = database.get_db()
        db.execute("INSERT INTO tt_accounts(name, advertiser_id, owner_id) VALUES('只TT户','_hgpu_ttonly_acc',?)", (uid,))
        db.commit()
        db.close()
        gg = {u["username"] for u in client.get("/api/platform/users?platform=gg", headers=hg).get_json()["users"]}
        tt = {u["username"] for u in client.get("/api/platform/users?platform=tt", headers=hg).get_json()["users"]}
        assert "_hgpu_ttonly" not in gg
        assert "_hgpu_ttonly" in tt
```

- [x] **Step 7: 跑这一类，确认 7 个用例全绿**

Run: `cd py && python -m pytest tests/test_huguan_role.py::TestPlatformUsersEndpoint -q`

Expected: `7 passed`

- [x] **Step 8: 提交**

```bash
cd /d/server/cc/GG-Server
git add py/tests/test_huguan_role.py
git commit -m "test: 补账户夹具并覆盖「归属人」下拉的新口径（3 改 4 增）"
```

---

### Task 3: 回归、验收与代码审查

**Files:**
- Verify only（无代码改动，除非验收发现问题）

**Interfaces:**
- Consumes: Task 1 + Task 2 的成果
- Produces: 验收结论

- [x] **Step 1: 后端全量回归**

Run: `cd py && python -m pytest tests/ -q`

Expected: 全绿。基线为 `420 passed` + 本次新增 4 例 = **`424 passed`**。
（若数字不符，先确认没有别处因本改动而红灯 —— 尤其 `test_user_platform_isolation.py`、`test_tt_platform.py`、`test_fb_platform.py`。）

- [x] **Step 2: 手工验收**

启动后端与前端，按矩阵核对（前端本次**零改动**，故重点是下拉内容）：

| # | 身份 | 面板 | 期望 |
|---|---|---|---|
| 1 | 卡尔 / developer / gg | GG 广告账户 → 展开归属人下拉 | **不出现** 阿信、柠檬、蜻蜓、Developer；**出现** 户部尚书、阿伟、拉菲、大盗、卡尔 |
| 2 | 卡尔 / developer / gg | 切到 TT 广告账户 | 下拉**只剩「黎明」** |
| 3 | 卡尔 / developer / gg | 切到 FB 广告账户 | 下拉为空（`fb_accounts` 0 行，已知副作用，设计文档 §5.1.1） |
| 4 | 户部尚书 / huguan / gg | GG 广告账户 | 下拉**包含户部尚书自己**（0 户仍豁免） |
| 5 | 阿信 / admin / gg | GG 广告账户 | 下拉默认值是自己但已被筛出 → 显示裸 id（已知且已裁定接受，设计文档 §5.1.2）；表格为空 |

> 验收第 5 条若确认到裸 id，**不算缺陷** —— 那是用户明确裁定接受的行为，不要顺手去修。

- [x] **Step 3: 若验收发现问题 → 修复后重跑 Step 1、Step 2**

- [x] **Step 4: 代码审查**

按 CLAUDE.md 要求，调用 `/code-review` 对本次改动做审查，修复发现的问题。

审查时请重点核对两件事：
1. **白色名单映射是否真的无注入面**（`platform` 必须走占位符，`table` 只能取字典值）；
2. **测试断言是否仍非空**（新增的账户过滤会不会把某条负面断言变成恒真）。

- [x] **Step 5: 收尾提交（仅当有修复或文档更新时）**

```bash
cd /d/server/cc/GG-Server
git add -A
git commit -m "docs: 补充「归属人」下拉只列有户用户的设计与实现计划"
```

---

## 备注

- 临时验证脚本 `D:/server/cc/_gghist/verify_platform_users.py` 留在仓库外，不进版本库。
- 已知且已裁定接受的副作用：**FB 下拉彻底变空**（设计文档 §5.1.1）、**0 户用户默认选中自己时显示裸 id**（§5.1.2）。二者均**不在本次修复范围**。
- 本次**不含**：69 户 `status_id` 悬空的数据订正、`COALESCE(st.name,'存活')` 显示层掩盖问题。独立议题，另行裁定。

---

## 完成记录（2026-09-23）

全部 3 个 Task 完成，提交：`cd55dca`（后端）→ `f46007c`（测试）→ `6d957f5`（审查收口）。

**结果**：`cd py && python -m pytest tests/ -q` → **`424 passed`**，与计划预测的基线 420 + 新增 4 完全吻合。

### 执行中与计划的偏差（按实记载）

1. **计划 Step 3 的验证脚本断言字段写错了。** 计划里写 `assert "户部尚书" in gg`，但 `gg` 是 `username` 集合，而该账号的 `username` 是 `feifei`、`display_name` 才是「户部尚书」（卡尔同理：`carl567`）。脚本因此报 `AssertionError`。已把断言改为按 `display_name || username`（下拉 label 的口径）。**这是脚本自身的问题，不影响接口。**

2. **`test_account_table_follows_effective_platform` 初版是弱断言，靠变异测试才发现。** 初版夹具用普通 `user`/`tt`，查 gg 时会先被基础条件 `platform = ?` 挡掉，`not in gg` 恒真 —— 根本没验到表映射（变异 D 第一次跑时该用例没红）。改用 **developer** 做夹具（能穿透基础平台过滤）后，表的选择成为唯一变量，变异 D 即变红。

3. **变异验证扩到 4 条**（计划里只要求跑测试，未要求变异）。实际对 4 条约束各做了一次破坏，确认全部有守卫：

   | 变异 | 变红的用例 |
   |---|---|
   | A 去掉整条 EXISTS 约束 | `test_excludes_users_without_accounts`、`test_deleted_account_does_not_count`、`test_account_table_follows_effective_platform` |
   | B 去掉户管豁免 | `test_huguan_exempt_even_without_accounts` |
   | C 去掉 `deleted_at IS NULL` | `test_deleted_account_does_not_count` |
   | D 表映射 gg↔tt 弄反 | 5 个用例（含 `test_account_table_follows_effective_platform`） |

   脚本留在仓库外：`D:/server/cc/_gghist/mutation_check.py`。

   > 复现注意：`AND a.deleted_at IS NULL` 在 `main.py` 出现 3 次（3914 / 4084 / 6041），朴素 `replace(..., 1)` 会打到无关位置，必须用唯一锚点 `WHERE a.owner_id = u.id AND a.deleted_at IS NULL`。

4. **代码审查（`01216c6..f46007c`）结论：可以合并，0 阻塞。** 采纳并修复了 2 条 Minor：去掉 `test_excludes_users_without_accounts` 里一句恒真断言（`assert without_acc`）、修正 `main.py` 回退注释的措辞（回退的只是选表，`platform = ?` 仍用原样值）。

   审查发现的 **I-1（跨面板筛选域不一致）** 已独立复核并在设计文档 §5.1.3 记录：MCC / FB-BM / FB-像素 / TT-BC 四个面板的归属人筛选域不是平台账户表。**今日实测损失为零**（各 owner 全在新下拉里；FB 两张表本就 0 行），属潜伏问题，本次只记录不处理。

### 尚未完成

- **手工验收（Task 3 Step 2）**：需人工在浏览器核对 5 行矩阵，**待用户执行**。前端本次零改动，重点看下拉内容。
- **Task 3 Step 5 收尾提交**：本文档更新随之提交。
