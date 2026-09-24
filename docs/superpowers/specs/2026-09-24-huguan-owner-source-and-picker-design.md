# 户管看板：归属变更「来源」标注 + 户管专用归属人列表 设计文档

> 父设计：`docs/superpowers/specs/2026-09-23-huguan-sheet-design.md`（子项目 B：户管看板 Google Sheet 双向同步）
> 前端视觉设计：`docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md`
> 状态：**待用户确认**（确认后才动手写代码）
> 日期：2026-09-24

---

## 0. 这两项是怎么来的

`2026-09-24-huguan-frontend-visual-design.md` §9 列了 11 项需要裁定的问题。其中 9 项已按设计者建议拍定并落入计划；剩下 2 项是**后端增量**，2026-09-24 用户逐项裁定：

| # | 问题 | 用户裁定 |
|---|---|---|
| §9-3 | 差异报告的归属变更要不要显示「来源」列 | **加 `via` 字段** |
| §9-4 | 「改归属」用户下拉的 `GET /platform/users` 语义不匹配 | **在户管蓝图里加专用端点** |

两项都是**纯增量**（不改既有键、不改既有端点行为），符合全局「纯增量原则」。

---

## 1. 增量一：归属变更项增加 `via` 字段

### 1.1 需求

户管在差异报告里看到「账户 X：归属由 张三 改为 李四」时，**看不出这次变更是因为表里哪一列触发的**。而这恰恰是用户定的核心规则（原话）：

> 「同步的时候表里运营列和重新分配列不一致，就以表里的重新分配为准」

不标出来，户管就无法把这个规则和眼前这条变更对上——尤其是当他们自己只在「运营」列改了人、却因为「重新分配」列有残留值而被判成别人时。

### 1.2 技术方案

`build_diff` 里归属变更项（`py/huguan_dashboard.py:397-404`）新增一个 `via` 键，取值是**该平台下那一列的真实表头文字**：

- 触发列是归属变更通道 → GG `"重新分配"` / TT `"换绑情况"`
- 否则（走当前归属列）→ GG `"运营"` / TT `"接户运营"`

判定依据是已有的合成字段 `p["_owner_channel"]`（`parse_row` 产出，`:33`/`:53` 定义，`effective_owner_name` 在 `:125` 就是这么用的）——**空串即未触发通道**。

**不硬编码中文列头**：新增一个按平台查列头的小工具，从 `COLUMNS` 表（`:25-56`）反查，避免列头改名时两处不同步。

```python
def column_header(platform: str, field: str) -> str:
    """按平台反查某字段对应的表头文字（列头改名时只改 COLUMNS 一处）。"""
    for _col, header, f, _writable, _syncable in COLUMNS[platform]:
        if f == field:
            return header
    return field
```

`build_diff` 内：

```python
            owner_changes.append({
                "row": row_no,
                "account_id": aid,
                "existing_id": existing["id"],
                "from": ...,
                "to": want_owner_name,
                "to_owner_id": want_owner_id,
                # 规格 §7.2 规则 1：通道列非空时压过当前归属列。`via` 让户管看见
                # 「为什么这个人被改了」——否则规则与眼前这条变更对不上。
                "via": (column_header(platform, "_owner_channel")
                        if (p.get("_owner_channel") or "").strip()
                        else column_header(platform, "owner_name")),
            })
```

### 1.3 数据结构

`diff.owner_changes[i]` 新增一个键（**不改既有键**）：

| 键 | 类型 | 说明 | 新增？ |
|---|---|---|---|
| `row` | int | 表里的**绝对行号**（表头 = 1，首条数据行 = 2） | 否 |
| `account_id` | str | 账户ID | 否 |
| `existing_id` | int | 系统内主键 | 否 |
| `from` / `to` | str | 变更前后归属人名 | 否 |
| `to_owner_id` | int | 变更后归属人 id | 否 |
| **`via`** | str | **触发列的表头文字**：`重新分配`/`换绑情况`/`运营`/`接户运营` | **是** |

### 1.4 UI 改动

前端在差异报告的「归属变更」区块（设计文档 §4.x 的 ① 区块）显示 `via` 列。设计者已按此设计好 `来源` 列；本增量后它变成 5 列。

### 1.5 涉及文件与测试

- 改：`py/huguan_dashboard.py`（新增 `column_header`；`build_diff` 的 `owner_changes.append` 加一个键）
- 测：`py/tests/test_huguan_dashboard.py`

测试（4 条）：

1. GG：表里只有「运营」(G) 有值 → `via == "运营"`
2. GG：表里「重新分配」(H) 有值 → `via == "重新分配"`
3. TT：`via` 分别为 `"接户运营"` / `"换绑情况"`
4. 回归：`owner_changes[i]` 的既有 6 个键仍在、且值不变

---

## 2. 增量二：户管专用的归属人列表端点

### 2.1 需求（含实测证据）

`GET /api/platform/users`（`py/main.py:6280-6305`）是**为「筛选」设计的**——它的 docstring 明写：

> 只列出**在该平台有未删除账户**的用户 —— 选中一个名下无户的人必然得到空表，这种选项没有筛选价值。
> 户管（huguan）豁免：户管管理所有户，本人在该平台可能一个户都没有，仍恒列出。

而「改归属」需要的是**全量用户**。后果（实测确认）：**户管无法把一个 GG 账户转给一个只在 TT 有账户的合法用户**——那个人不出现在下拉里。

这违反用户的原始要求「户管随时可以更改运营归属」。父设计 §9.2 写「复用 `/platform/users`」是**错的**，本设计予以更正。

**这不是推翻既有决策，而是补上另一半**：`2026-09-23-owner-filter-hide-empty-users-design.md`（账户面板「归属人」下拉只列出有账户的用户）是**为筛选**有意做的取舍，那个决策在筛选场景下依然正确。出错的是父设计把它**顺手套用**到了编辑场景。⇒ 两个端点各服务一个场景，都保留。

### 2.2 技术方案

在**户管看板自己的蓝图**里新增一个端点，**完全不碰 `py/main.py`**（该文件有并行会话在途迭代，冲突风险高）。

- 路径：`GET /api/huguan/dashboard/owner-options`
- 装饰器：`@jwt_required()` + `@huguan_required`（与蓝图里既有 4 个端点同款，`decorators.py:38-50` 实测为严格 `role == "huguan"`，否则 403）
- 语义：列出**全部非 `hidden` 用户**（不限平台、不限有无账户）
- 返回形状：与既有 `/api/platform/users` **逐字段一致**（`id` / `username` / `display_name` / `platform`），前端可无缝换源

```python
@huguan_dashboard_bp.route("/api/huguan/dashboard/owner-options", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_owner_options():
    """「户归属」下拉的数据源：可以直接把户转给他的**全部**用户。

    与 `/api/platform/users` 的分工（父设计 §9.2 的更正）：
    - `/api/platform/users` 服务**筛选**（「归属人」筛选器）——只列该平台有未删除
      账户的人，选项才有筛选价值；
    - 本端点服务**编辑**（改归属）——必须全量，否则户管没法把 GG 账户转给一个
      只在 TT 有户的合法用户（实测缺口）。
    两者都保留，各有各的用途，不要互相替代。

    只排 `role='hidden'`（被停用、无法登录），与既有端点同口径。
    """
    db = database.get_db()
    try:
        rows = db.execute(
            "SELECT id, username, display_name, platform FROM users "
            "WHERE role != 'hidden' ORDER BY display_name, username"
        ).fetchall()
    finally:
        db.close()
    return ok({"users": [dict(r) for r in rows]})
```

> **实现时须核**：（a）本蓝图文件的既有 import 与 `ok(...)` 用法；（b）`database.get_db()` 的取用方式以本文件既有写法为准；（c）`users.platform` 允许 `'gg'|'tt'|'fb'`，developer 为双平台——本端点**不按平台过滤**，这是有意的。

### 2.3 数据结构

`{"success": true, "users": [{"id": int, "username": str, "display_name": str, "platform": str}, ...]}`

### 2.4 UI 改动

前端 Task 11 的「户归属」列下拉（仅户管可见）改从本端点取数；**「归属人」筛选器继续用 `/api/platform/users`**。计划 Task 11 里 `loadOwnerOptions()` 现在是 `api.get('/platform/users')`，需改路径并为两个用途分别命名（如 `loadOwnerFilterOptions()` / `loadOwnerPickerOptions()`），避免后人又合并回去。

### 2.5 涉及文件与测试

- 改：`py/routes/huguan_dashboard_routes.py`（新增 1 个端点）
- 测：`py/tests/test_huguan_dashboard.py`

测试（3 条）：

1. 户管调用 → 200，且列表里**包含一个在该平台没有任何账户的用户**（这条正是缺口的回归钉）
2. 非户管（`user` 角色）调用 → 403
3. `role='hidden'` 的用户**不出现**在结果里

---

## 3. 不做的事（YAGNI）

- **不改 `GET /api/platform/users`**（不加 `?scope=all`）：用户已裁定走户管专用端点，`py/main.py` 不动。
- **不让 `reassign` 返回「是否回写了看板」的布尔**：那要动 `py/main.py` 与 `py/routes/tt_accounts_routes.py`。前端继续用条件句兜底文案（计划 Task 11 已落文）。
- **不做「来源」列的前端筛选/排序**：只是标注，不引入交互。
- **本设计不含前端实现**：前端按 `2026-09-24-huguan-frontend-visual-design.md` 走，本设计只补它需要的两个后端事实。

## 4. 风险与已知代价

| 项 | 说明 |
|---|---|
| `via` 是展示用文字而非稳定枚举 | 若将来前端要按 `via` 做逻辑判断，需改为稳定 token（如 `owner_channel`/`owner_name`）再由前端映射。**当前只有展示用途，故直接给列头文字**（这也是户管在表里实际看到的名字）。 |
| 新端点列出全部非 hidden 用户 | 含 `viewer` 角色与无账户用户。这是「转给谁」的**真实全集**；是否允许转给 viewer 由既有 reassign 逻辑决定（TT 侧只校验目标存在），本端点不额外设限。 |
| 端点未做分页 | 本部署为局域网 20 人以下（AGENTS.md），用户量极小，下拉一次性拉全量即可。 |

## 5. 门禁

- 聚焦：`cd py && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_huguan_dashboard.py -q`
  —— 基线 **138 passed**（`204687f` 实测），本设计新增 7 条（4 + 3）⇒ 预期 **145 passed**
- 全量：`cd py && PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/ -q`
  —— 基线 **693 passed**（2026-09-24 实测），**不得低于当次实测基线**（并行会话在同时加测试，数字只会涨）
- `PYTHONDONTWRITEBYTECODE=1` 不能省：同秒内生成的同字节数变异体不会让 `.pyc` 失效，会得到假 GREEN
- 完成后按 CLAUDE.md 调用 `/code-review`，修复后重跑门禁

## 6. 待确认问题

1. `via` 给**列头文字**（本设计的选择）还是稳定 token？——本设计选列头文字，理由是只有展示用途，且它就是户管在表里看到的名字。
2. 新端点是否需要**排除 `viewer`**？——本设计不排除（保持「转给谁」的全集），若你认为不该转给只读角色，我改为排除。
