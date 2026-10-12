# MCC 等级留空落到 id=1（修「建不了 MCC」）（设计）

> 起因：2026-10-12 在 `2026-10-12-open-account-area-to-normal-users-design.md` 的
> 真机验收中，用户以**普通用户**身份点「➕ 新增 MCC」保存，得到
> `POST /api/mcc/create → 409`，据此怀疑是权限没放开。
> 结论：**与权限无关**，是一条所有角色（含 admin / developer）都会踩的既有 bug。

## 一、根因（已在内存 SQLite 中实测复现）

三段各自都"讲得通"的代码叠在一起，把一条外键错误伪装成了重名冲突：

1. **前端初值是空串而不是 null** —— `MccModal.vue:41`
   ```js
   const form = reactive({ name: '', mcc_id: '', level_id: '', parent_mcc_id: '' })
   ```
   未选等级就 `store.createMcc(form)`，`level_id` 原样送成 `''`。

2. **`mcc.level_id` 是带外键的 INTEGER 列** —— `database.py:348`
   ```python
   _add_column_if_missing(conn, "mcc", "level_id", "level_id INTEGER REFERENCES mcc_levels(id)")
   ```
   连接开着 `PRAGMA foreign_keys=ON`，空串插进去直接
   `IntegrityError: FOREIGN KEY constraint failed`。

   实测（全新内存库，两条语句只差一个值）：

   | 送入 | 结果 |
   |---|---|
   | `level_id=''` | ❌ `IntegrityError: FOREIGN KEY constraint failed` |
   | `level_id=None` | ✅ INSERT 成功 |

3. **一句把所有完整性错误都说成重名的 except** —— `main.py` `mcc_create`
   ```python
   except _sqlite3.IntegrityError:
       return jsonify({"success": False, "error": f"MCC ID '{mcc_id}' 已存在"}), 409
   ```
   外键失败被盖在这条文案底下 ⇒ 用户看到「已存在」，自然怀疑是权限/重名。

**且与角色无关**：本机 `mcc_levels` **一行都没有**（全新库，`agents` / `account_statuses`
同样为空），等级下拉对 admin / developer / user 全是空的 —— 谁点谁 409。用户恰好在用普通
用户测，纯属巧合。

> 同类前科：AGENTS.md 记的 GG 状态字典 409（写成 `INSERT` 撞 UNIQUE，异常被通用分支
> 误报成「账户 ID 已存在」）。**本项目第二次栽在"IntegrityError 一律当成重名"上。**

## 二、用户裁定（2026-10-12）

| 问题 | 裁定 |
|---|---|
| 用不用 git worktree | **不用，直接在 master 改** |
| 等级留空怎么处理 | **空就默认为 1** |
| 但全新库里 id=1 也不存在 | **写死 id=1，并补建 id=1** |

## 三、技术方案

### 3.1 新增归一函数 `_resolve_mcc_level_id(db, raw, owner_id)`

放在 `main.py` 中 `mcc_create` 之前，四条分支：

| 输入 | 处理 | 理由 |
|---|---|---|
| 指向**真实存在**的等级（含 `"43"` 这种字符串数字） | **原样返回** | 不许无脑改成 1 —— 否则等级功能等于废掉。有对照腿钉住 |
| 空缺 / 非数字 / 悬空 id | 落 **id=1** | 用户裁定 |
| id=1 不存在 | **补建** `mcc_levels(id=1, name=?, owner_id=?)` | 用户裁定；顺带让下拉第一次就有内容 |
| 连后备名都被占（极端） | 退回本人已有的任一等级；再没有就返回 `None` | 写 NULL（列可空）仍好过抛 FK → 409 |

补建时的**后备名循环**：`一级` → `默认等级` → `默认等级-{owner_id}`，
因为 `mcc_levels` 是 `UNIQUE(name, owner_id)`（`database.py:762`），
本人可能已有一个叫「一级」但 id≠1 的等级。

⚠️ **这里 `INSERT OR IGNORE` 不管用**：它只吞 UNIQUE 冲突并且语义是"忽略插入"，
而我们要的是"换一个名字插成功"。（另：ON CONFLICT 算法本就不适用于 FOREIGN KEY。）

幂等性由分支 2 的前置查询保证：id=1 在就直接用，不会重复补建。

### 3.2 两条入口都接上

| 入口 | 改动 |
|---|---|
| `mcc_create` | 老的纯文本 `level` 入参（无 `level_id`）走原逻辑；其余走归一函数 |
| `mcc_update` | `if "level_id" in data:` 时先归一。**原实现完全没有 except** ⇒ 空等级抛 IntegrityError 变成 **500**（比 409 更难查） |

`mcc_update` 补建默认等级时用 `mcc_row["owner_id"]`（**不是当前用户**）：
developer/admin 可跨用户改 MCC，补建出来的等级要挂在 MCC 归属人名下，别污染操作者。

### 3.3 修正那句误导文案

```python
except _sqlite3.IntegrityError as e:
    if "mcc.mcc_id" in str(e):
        return jsonify({"success": False, "error": f"MCC ID '{mcc_id}' 已存在"}), 409
    return jsonify({"success": False, "error": f"保存失败：{e}"}), 400
```

只有真的撞 `idx_mcc_mcc_id_unique`（唯一索引在 `database.py:1286/1352`）才叫重名。
真重名仍是 409，有对照腿钉住。

## 四、验证（TDD，含变异实测）

`py/tests/test_mcc_level_default.py` —— **9 条**，`cd py && python -m pytest tests/ -v`：

| 用例 | 类型 |
|---|---|
| 空串 / 缺省 / 悬空 id 三种空值都落 1 | 红钉 ×3 |
| id=1 补建**幂等** | 红钉 |
| 本人已有同名「一级」（id≠1）时补建不撞 UNIQUE | 红钉 |
| 编辑路径空等级不 500 | 红钉 |
| 真重复 MCC ID 仍 409 | 红钉（旧代码在第一句 create 就挂） |
| **有效 id 原样保留** / **字符串数字 id 原样保留** | **对照腿 ×2** |

**变异实测**（`git stash push -- py/main.py` 后重跑）：
**7 红 / 2 绿** —— 两条对照腿在旧代码上保持绿，七条红钉全红。
这正是想要的剖面：如果哪天有人把 `level_id` 一律写死成 1，那两条会立刻变红。

**全量回归**（60 个测试文件逐个跑）：**2127 通过 / 1 失败**。

唯一失败是 `test_column_prefs.py::test_load_prefs_survives_deeply_nested_json`，**既有、环境相关、
与本次改动无关**，已用 `git stash push -- py/main.py`（把我的改动摘掉）复跑确认同样红：
该用例先钉「`json.loads('['*2000 + ']'*2000)` 必须爆 `RecursionError`」，而本机
Python 3.12.15 的 `json` **C 扫描器**不爆栈（`recursionlimit=1000` 但没走到），前提不成立 ⇒ 红在
`pytest.raises` 那一行。

> ⚠️ 本机 `pytest tests/`（一次跑全部）**极慢**（单文件合计约 26 分钟，`test_fb_platform` 172s /
> `test_huguan_dashboard` 142s / `test_tt_platform` 198s），建议逐文件跑：
> `for f in tests/test_*.py; do echo "=== $f"; python -m pytest "$f" -q | tail -2; done`
> （另：本机原先**没装 pytest**，本次 `pip install pytest` 才跑起来。）

## 五、遗留 / 范围外

- `MccModal.vue` **未改**：后端已把空串归一，前端再改成发 `null` 属冗余（且要多一次
  `npm run build`）。若日后要改，注意 `form.level_id || null` 会把合法的 `0` 也变成 null
  （id 从 1 起，实际不可达）。
- 默认等级名固定为「一级」（撞名时「默认等级」）。用户没要求可配置，未做。
- 未做存量数据回填：生产库 `mcc` 表为空，无悬空 `level_id` 可修。
