# 账户面板「归属人」下拉只列出有账户的用户 设计

- 日期：2026-09-23
- 状态：待确认
- 类型：后端接口口径变更（`/api/platform/users` 结果集收窄）
- 关联：本需求是 `2026-09-23-owner-filter-default-scope-design.md`（默认作用域）的后续修正

---

## 1. 需求背景

「账户管理」各面板的「归属人」下拉，列出的是**当前平台的全部用户**，完全不看他们名下有没有账户。其中一部分人在该平台一个户都没有 —— 选中他们必然得到空表，这些选项没有筛选价值，只是噪音。

**用户原话**：「账户管理筛选用户的下拉框，用户没有账户，不用展示在这里」。

---

## 2. 需求描述（用户裁定）

| 角色 | 是否受「有无账户」过滤 |
|---|---|
| `huguan`（户管） | **豁免** —— 户管管理所有户，始终列出 |
| `developer` / `admin` / `user` / `viewer` | **一律过滤** —— 在该平台 0 户即不列出 |

用户原话：「户管就是管理所有户的，户管必须豁免，户管登陆上来就展示直接所有户，**其他角色都一样**」——即不为 developer / admin 开特例。

「有没有账户」的口径 = 在该平台账户表里有 **`deleted_at IS NULL`** 的行（软删除的户不算，与仓库既有口径一致，见 `main.py:3752`、`main.py:6122-6124`）。

---

## 3. 现状与落点

### 3.1 下拉的唯一数据源

`/api/platform/users`（`py/main.py:6016-6032`），被 8 个面板共用的 `frontend/src/components/OwnerFilterSelect.vue:53` 调用。现有口径：

```sql
SELECT id, username, display_name, platform FROM users
WHERE (platform = ? OR role = 'developer') AND role != 'hidden'
ORDER BY display_name, username
```

`platform` 取自 `_get_effective_platform()`（`main.py:6005-6013`）：developer / 户管 可跨平台（读 `?platform=`，缺省 `gg`），其余角色恒取自己的 `users.platform`。

### 3.2 该接口天然是「按面板平台分别调用」的

`frontend/src/api/client.js` 的请求拦截器会按 `window.location.hash` 给 developer / 户管 注入 `platform`（`/tt`→tt、`/fb`→fb、其余 gg）。因此**后端在这个接口里就已经知道是哪个面板在问**，可以直接按平台选择要查的账户表 —— 这是本方案能收敛成单点后端改动的前提。

### 3.3 三张平台账户表

| 平台 | 表 | owner 列 | 软删除列 |
|---|---|---|---|
| gg | `accounts` | `owner_id` | `deleted_at` |
| fb | `fb_accounts` | `owner_id` | `deleted_at` |
| tt | `tt_accounts` | `owner_id` | `deleted_at` |

（已用 `PRAGMA table_info` 逐一核实。）

### 3.4 明确不在范围内

`/api/tt/users`、`/api/fb/users`（前端 `listTtUsers` / `listFbUsers`）被 `FbProductPanel.vue:305`、`TtProductPanel.vue:144` 用于产品面板选「跑手」，**与账户归属无关，本次不动**。

---

## 4. 技术方案

**单点后端改动**：在 `/api/platform/users` 的 WHERE 上再加一条「户管豁免 OR 名下有未删除账户」的约束。

```python
# 平台 → 账户表 的白名单映射（表名无法参数化，故走映射而非字符串拼接）
ACCOUNT_TABLE_BY_PLATFORM = {"gg": "accounts", "fb": "fb_accounts", "tt": "tt_accounts"}


@app.route("/api/platform/users", methods=["GET"])
@jwt_required()
def platform_users():
    """当前有效平台下的用户列表，供账户面板的「归属人」筛选下拉使用。

    只列出**在该平台有未删除账户**的用户（户管豁免 —— 户管管理所有户，恒列出）。
    「有无账户」与仓库既有口径一致：deleted_at IS NULL。
    """
    platform = _get_effective_platform()
    table = ACCOUNT_TABLE_BY_PLATFORM.get(platform, "accounts")  # 未知平台回退 gg，与 _get_effective_platform 缺省一致
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

要点：

- **无注入面**：`platform` 走占位符参数化；`table` 只能取白名单字典的值，用户输入进不了它。
- **纯增量**：不改动已有的两条件（平台隔离、排除 hidden），只在其结果集上「减人」。返回字段、返回结构、`owner_id` 语义（空 = 全部）全部不变。
- **前端零改动**：见 §5.1.2 的用户裁定。

### 4.1 为什么选后端而不是前端过滤

前端过滤需要额外拉一次「各人户数」聚合请求，且要 8 个面板口径一致（其中 GG 走 Pinia、TT/FB 走本地 ref，分散实现易漏改）。后端一处 `EXISTS` 天然按平台选表，且下拉的首次渲染就是对的（不会出现「先列出全部人、再闪一下变少」）。

---

## 5. 影响面（实测 `temp/app.db`）

| 面板 | 现在 | 筛后 | 去掉的人 |
|---|---|---|---|
| GG | 9 人 | **5 人** | Developer、柠檬、蜻蜓、阿信（均 0 户） |
| FB | 8 人 | **0 人** | 全部 —— `fb_accounts` 表 0 行，无人有 FB 户 |
| TT | 4 人 | **1 人** | Developer、卡尔、哈兰德（均 0 户） |

保留清单 —— GG：卡尔(263 户)、大盗(4)、**户部尚书（户管，0 户，豁免）**、拉菲(14)、阿伟(58)；TT：黎明(49)。

### 5.1 三个已知副作用

#### 5.1.1 FB 下拉会彻底变空

`fb_accounts` 实测 **0 行**（不是「owner 全为空」，是整张表没有数据），所以「有 FB 户的人」= 空集。逻辑上自洽 —— FB 账户表本来就是空的，那个下拉本来也筛不出任何东西。**不做「本平台无任何账户则整体豁免」的特例**：那会引入一条说不清的规则，且平台一旦有数据该特例就失效。

#### 5.1.2 0 户用户进自己平台面板会显示裸 id（用户已裁定接受）

刚上线的「默认选自己」（`frontend/src/utils/ownerScope.js`）会让阿信/柠檬/蜻蜓（GG）、白白（FB）这类 0 户用户默认选中自己，而**自己已被本次改动筛出列表** → Element Plus `el-select` 找不到匹配项，会直接把数字渲染出来（如「2」）而不是名字。

**用户裁定：接受，前端不动。** 理由：这类用户名下本就无户，表格本来就是空的，影响面极小。

#### 5.1.3 有 4 个面板的「归属人」筛选域不是平台账户表（潜伏，今日零损失）

代码审查发现：`OwnerFilterSelect` 被 8 个面板共用，但其中 4 个面板把这个下拉选中的 id 用作**另一个所有权域**的过滤条件：

| 面板 | 实际筛选的表 | 后端位置 |
|---|---|---|
| MCC 管理 | `mcc.owner_id` | `py/main.py:5467` 起 |
| FB BM | `fb_bms.owner_id` | `py/routes/fb_routes.py:14` |
| FB 像素 / 像素-BM | `fb_pixel_bms.owner_id` | `py/routes/fb_routes.py:923` 起 |
| TT BC | `tt_bcs.owner_id` | `py/routes/tt_routes.py:15` |

而本次的判据挂在**平台账户表**上。因此理论上存在一个反向的错杀：某人拥有 BM/像素/BC/MCC 但在该平台 0 个账户时，会从这个面板的下拉里消失 —— 而选中他其实**能**筛出非空结果。

**今日实测影响 = 0**（在 `temp/app.db` 独立复核）：

- `mcc`：3 个 owner（卡尔 73 行、阿伟 3 行、拉菲 2 行）**全部**仍在新下拉里；
- `tt_bcs`：唯一 owner 黎明（5 行）仍在下拉里；
- `fb_bms` / `fb_pixel_bms`：**0 行**，无人可丢。

**潜伏点**：FB 的 BM / 像素 / 像素-BM 三个面板的下拉会**一并恒空**（判据挂在永远为空的 `fb_accounts` 上）。今日无损失（那两张表本来也是空的），但将来 `fb_bms` 有了带 owner 的数据后，这三个面板的归属人筛选依然不可用。

**未修的理由**：收口需要「按面板选择判据」，即让 `/api/platform/users` 知道调用方是哪个面板 —— 那会破坏本次「单点后端改动」的前提，代价远大于今日收益。**故本次只记录不处理**，留待该场景真正出现时再议。

#### 5.1.4 户管豁免只免「账户过滤」，平台条件照旧

实现是 `(platform = ? OR developer) AND (huguan OR EXISTS(...))`，所以 `users.platform='gg'` 的户管不会出现在 TT/FB 面板的下拉里（即使他可能是某 TT 户的 owner）。这属**改动前的既有行为**（改动前 TT 下拉也没有户管），与 §2「户管恒列出」的字面措辞有落差，但若一并豁免平台条件，就会重新引入「选了必得空表」的噪声 —— 与本次目标相悖。**维持现状。**

---

## 6. 对现有测试的冲击（必须处理，否则必然红灯）

`py/tests/test_huguan_role.py::TestPlatformUsersEndpoint` 的 **3 个用例全部会失败** —— 它们插入的夹具用户都是 0 账户，会被新过滤整批剔除，断言随之失效：

| 用例 | 会失效的断言 | 原因 |
|---|---|---|
| `test_huguan_sees_only_current_platform:375` | `_hgpu_tt in names` | `_hgpu_tt` 是 `user` / 0 户 → 被剔除 |
| `test_includes_developer_excludes_hidden:394` | `_hgpu_dev in names` | `_hgpu_dev` 是 `developer` / 0 户 → 被剔除 |
| `test_non_switch_role_cannot_pick_platform:414` | `_hgpu_plain in names` | `_hgpu_plain` 是 `user` / 0 户 → 被剔除 |

**修法：给夹具补上账户行，而不是改断言。** 这 3 个用例各自的守卫意图（平台隔离 / developer 分支 / hidden 排除）必须原样保留 —— 尤其两处负面断言（`_hgpu_gg not in names`、`_hgpu_leak not in names`）需要对应夹具**确实有该平台账户**，否则新过滤会让它们变成「恒真的空断言」（测试注释里已两次强调过这个陷阱）。

另外**新增 2 个用例**覆盖本次新口径：0 户非户管用户被排除、0 户户管被保留（豁免）。

---

## 7. 涉及文件

| 文件 | 改动 |
|---|---|
| `py/main.py` | 新增平台→表白名单常量；`platform_users()` 加 `EXISTS` 约束与户管豁免 |
| `py/tests/test_huguan_role.py` | 3 个既有用例补账户夹具；新增 2 个用例覆盖新口径 |

**不改动**：全部前端文件（`OwnerFilterSelect.vue`、`ownerScope.js` 等）、`/api/tt/users`、`/api/fb/users`、任何 DB schema。

---

## 8. 测试

### 8.1 单元/接口测试

`cd py && python -m pytest tests/ -q` 全绿。新增用例：

- `test_excludes_users_without_accounts`：0 户的 `user` 不出现在结果里；
- `test_huguan_exempt_even_without_accounts`：0 户的 `huguan` 仍出现。

### 8.2 手工验收

| # | 身份 | 面板 | 期望 |
|---|---|---|---|
| 1 | 卡尔 / developer / gg | GG 广告账户 → 展开归属人下拉 | **不出现** 阿信、柠檬、蜻蜓、Developer；**出现** 户部尚书、阿伟、拉菲、大盗、卡尔 |
| 2 | 卡尔 / developer / gg | 切到 TT 广告账户 | 下拉**只剩「黎明」**（户部尚书 platform=gg 不在此面板范围内） |
| 3 | 卡尔 / developer / gg | 切到 FB 广告账户 | 下拉为空（`fb_accounts` 0 行，已知副作用 §5.1.1） |
| 4 | 户部尚书 / huguan / gg | GG 广告账户 | 下拉**包含户部尚书自己**（0 户仍豁免） |
| 5 | 阿信 / admin / gg | GG 广告账户 | 下拉默认值是自己但已被筛出 → 显示裸 id（已知，接受）；表格为空 |

---

## 9. 不做的事（YAGNI）

- 不改前端做「孤儿默认值回退」（用户裁定接受裸 id）；
- 不做「本平台无账户则整体豁免」特例；
- 不改产品面板的「跑手」下拉（`/api/tt/users`、`/api/fb/users`）；
- 不顺手处理 69 户 `status_id` 悬空的数据订正议题（独立议题，已有取证与恢复方案，另行裁定）。

---

## 10. 已确认决议（2026-09-23）

1. **户管（huguan）豁免** —— 无论有无账户恒列出；developer / admin / user / viewer 一律按有无账户过滤。
2. **孤儿默认值接受裸 id** —— 前端不改。
