"""路由层公共工具函数 — 减少 main.py 中的样板代码。"""
HUGUAN_ROLE = "huguan"

# 可跨用户查看/编辑账户类数据的角色（账户、MCC、BC、BM、像素）
CROSS_USER_ROLES = ("developer", "admin", HUGUAN_ROLE)

# 报表类资源（ad_reports / fb_ad_reports）：
# ⚠️ 这两张表**没有 owner_id 列**，归属轴是 **user_id（谁保存的这条）** ——
#    与账户类的 owner_id 不是一回事，**不能**套用本文件按 owner 的 scope_where / can_modify。
# 可跨用户查看报表数据的角色（与账户类同集合）。
REPORT_VIEW_ALL_ROLES = CROSS_USER_ROLES

# 在数据管理页**只能改「消耗」一个字段**的角色。
# ⚠️ admin **不在**其中 ⇒ 管理员只读（本设计最核心的一条，改动前请先读设计 §3）。
REPORT_COST_ONLY_ROLES = (HUGUAN_ROLE,)

# 可编辑平台级下拉选项的角色（代理名、账户状态、MCC等级、地区时区、商务人员）
GLOBAL_OPTION_ROLES = ("developer", "admin", HUGUAN_ROLE)

# 可在 GG / FB / TT 之间切换平台的角色（跨平台路由放行 + 平台选项解析）
# 注意：admin 不在其中 —— 管理员本身按平台隔离（见用户角色平台隔离设计）。
PLATFORM_SWITCH_ROLES = ("developer", HUGUAN_ROLE)

# 页号上限。端点把 (page - 1) * size 绑进 SQL 的 OFFSET，SQLite 的整数是
# int64；page 无上界时该值会溢出，抛 OverflowError 把接口打成 500。
# 10 万页在 500 行/页下是 5000 万行，远超任何真实数据量，但让 OFFSET 稳稳
# 落在 int64 内（10 万 * 500 = 5*10^7）。
PAGE_MAX = 100_000

from flask import request, jsonify, g
from flask_jwt_extended import get_jwt_identity
import database
import auth


def ok(data=None) -> tuple:
    """成功响应 (200)。data 为 dict 时平铺到响应中，为 list 时包装为 {"data": [...]}。"""
    resp = {"success": True}
    if isinstance(data, list):
        resp["data"] = data
    elif isinstance(data, dict):
        resp.update(data)
    elif data is not None:
        resp["data"] = data
    return jsonify(resp)


def err(msg: str, code: int = 400) -> tuple:
    """错误响应。"""
    return jsonify({"success": False, "error": msg}), code


def parse_body() -> dict:
    """解析 JSON 请求体，失败返回空字典。"""
    return request.get_json(silent=True) or {}


def get_uid() -> int | None:
    """获取当前 JWT 用户 ID，未认证则返回 None。"""
    try:
        return int(get_jwt_identity())
    except Exception:
        return None


def get_db():
    """获取请求级共享数据库连接。"""
    db_conn = getattr(g, "db", None)
    if db_conn is None:
        db_conn = database.get_db()
        g.db = db_conn
    return db_conn


def get_current_user() -> dict | None:
    """获取当前认证用户信息。"""
    uid = get_uid()
    if uid is None:
        return None
    return auth.get_user_by_id(uid)


def get_user_display(user: dict | None, uid: int = None) -> str:
    """获取用户显示名（用于目录路径等）。"""
    if user:
        return (user.get("display_name") or user.get("username") or f"user_{user.get('id', uid or 0)}").strip()
    return f"user_{uid or 0}"


def _safe_int(raw, default: int) -> int:
    """安全整数解析：非数字一律回落默认值，不抛异常。

    现状的裸 `int(request.args.get("size", 20) or 20)` 遇到 `size=abc`
    会 ValueError ⇒ 500。分页参数是用户可以随便拼的，不该把接口打成 500。
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def parse_pagination(default: int = 20, maximum: int = 500,
                     name: str = "size") -> tuple[int, int]:
    """解析分页参数，返回 (page, size)。**越界一律钳制，不报错**。

    这是「不要全量返回、冲烂浏览器」的服务端总闸门：调用方前端的默认页尺寸
    都很小，但服务端此前没有任何上限，任何客户端传 `size=999999` 就能把整张
    表拉回去。

    page 也有上界（PAGE_MAX）：端点会把 `(page - 1) * size` 绑进 SQL 的
    OFFSET，page 无上界时该值可超过 2^63-1，SQLite 直接抛
    `OverflowError: Python int too large to convert to SQLite INTEGER` ⇒ 500。
    同样是「用户能随便拼的参数不得把接口打成 500」，故一并钳制。

    Args:
        default: 缺省页尺寸。**各调用点保持自己的原值**（GG 是 20，TT/FB 是 50），
                 迁移时不得统一成 20 —— 那会改变既有端点的行为。
        maximum: 页尺寸上限，默认 500（前端最大页尺寸是 200，留 2.5 倍余量）。
        name: 页尺寸的查询参数名，默认 "size"。`main.py:8423` 用的是 `page_size`。

    Returns:
        (page, size)，满足 `1 <= page <= PAGE_MAX` 且 `1 <= size <= maximum`。
    """
    page = max(1, min(PAGE_MAX, _safe_int(request.args.get("page"), 1)))
    size = max(1, min(maximum, _safe_int(request.args.get(name), default)))
    return page, size


# --- 从 main.py 迁移的公共辅助函数 ---

MCC_CHANGE_TYPE_LABELS = {
    "manual": "手动编辑", "batch": "批量修改", "reassign": "认领转移",
    "import": "批量导入", "create": "新建账户",
}


def runner_ids_where(alias: str, uid: int):
    """返回 (SQL 片段, 参数列表)，匹配 products 表中 runner_ids JSON 列含指定 uid。"""
    uid_s = str(uid)
    return (
        f"({alias}.runner_ids = ? OR {alias}.runner_ids LIKE ? "
        f"OR {alias}.runner_ids LIKE ? OR {alias}.runner_ids LIKE ?)",
        [f"[{uid_s}]", f"[{uid_s},%", f"%, {uid_s},%", f"%, {uid_s}]"]
    )


def scope_where(scope: str, user_id: int, alias: str = None):
    """返回 scope 过滤的 (SQL片段, 参数列表)。alias 可选，如 \"v\"、\"cw\"。"""
    col = f"{alias}." if alias else ""
    if scope == "public":
        return f"{col}is_public = 1", []
    elif scope == "private":
        return f"{col}owner_id = ?", [user_id]
    else:  # all
        return f"({col}is_public = 1 OR {col}owner_id = ?)", [user_id]


def can_modify(db, user_id, table, item_id):
    """检查用户是否有权编辑/删除某项。db 由调用方传入。
    返回 (can: bool, error: str|None)
    """
    user = auth.get_user_by_id(user_id)
    if user and user["role"] in ("developer", "admin"):
        return True, None
    try:
        row = db.execute(
            f"SELECT owner_id, is_public FROM {table} WHERE id=?", (item_id,)
        ).fetchone()
        if not row:
            return False, "记录不存在"
        if row["owner_id"] == user_id:
            return True, None
        if row["is_public"] == 1:
            return True, None
        return False, "无权限：仅可操作自己的或公开的内容"
    except Exception:
        return False, "查询出错"


def can_modify_user(actor: dict, target: dict) -> bool:
    """admin 只能操作 user/viewer/hidden，不能操作其他 admin。developer 不受限。"""
    if actor["role"] == "developer":
        return True
    return target["role"] in ("user", "viewer", "hidden")


def user_role(db, uid) -> str:
    """取用户角色，查不到回落 'user'（**不是 None** —— 调用方一律按"最低权限"处理）。

    FB 侧原有一个同义的 `_get_role`；本函数落地后它改为委派到这里，避免两份。
    """
    row = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return row["role"] if row else "user"


def report_scope_where(role, uid, owner_uid=None, alias=None):
    """报表类资源的可见作用域 → (SQL 片段, 参数列表)。

    - 非跨用户角色 → `user_id = ?` + [uid]（**与各端点原有写法语义等价**；
      端点原文是不带空格的 `"user_id=?"`，SQL 对 `=` 两侧空白不敏感，故可整段替换）
    - 跨用户角色   → 不加 user_id 限定（看全部）；owner_uid 非空时收窄到该人
      （前端「保存人」筛选）

    ⚠️ **非跨用户角色即使传了 owner_uid 也只返回自己的行** —— 该参数不得成为越权口。

    ⚠️ **契约：表示"不筛"必须传 `None`，不能传 `0`**。实现用 `0 is not None` 判定，
    故 `0` 会被当成一个真实（且不存在）的 owner ⇒ 结果集为空。
    调用方从 `request.args.get("user_id", type=int)` 取值时天然是 None（参数缺失），
    但**不要让任何路径把 0 当作"未选"的哨兵值**传进来。
    """
    col = f"{alias}." if alias else ""
    if role in REPORT_VIEW_ALL_ROLES:
        if owner_uid is not None:
            return f"{col}user_id = ?", [owner_uid]
        return "1=1", []
    return f"{col}user_id = ?", [uid]


def report_editable_fields(role):
    """该角色在数据管理页可改的字段集合。**None = 不设白名单（全字段可改）**。

    - developer → None
    - 户管      → {"cost"}
    - 其余（含 **admin**）→ set() ⇒ 空集 = **只读**
    """
    if role == "developer":
        return None
    if role in REPORT_COST_ONLY_ROLES:
        return {"cost"}
    return set()
