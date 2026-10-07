"""户管看板（Google Sheet）双向同步的纯逻辑层。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。

本模块刻意不 import flask、不碰网络：列规格、双向映射、差异比对都放在这里，
单测可直接调用。真正的 Sheets I/O 在 google_sheets_service，HTTP 入口在
routes/huguan_dashboard_routes.py。
"""
import json
import logging

from google_sheets_service import col_index, read_sheet_values

log = logging.getLogger("gg-server")

PLATFORMS = ("gg", "tt", "fb")

DEAD_STATUS = "死亡"
ALIVE_STATUS = "存活"

# 列规格：每项 (列字母, 表头, 系统字段名, 可写, 可读)
# 字段名为 None → 该列系统不映射，户管自己用公式维护，读写都不碰。
#
# 字段名里以 "_" 开头的三个是合成字段，不对应数据库列：
#   _dead_flag      ← death_date 是否非空，写"是"/空
#   _owner_channel  ← 重新分配 / 换绑情况，归属变更通道（规格 §7）
COLUMN_SPEC = {
    "gg": [
        ("A", "日期",     "acquired_date",   True,  True),
        ("B", "是否封户", "_dead_flag",      True,  True),
        ("C", "账户ID",   "account_id",      True,  False),  # 定位键
        ("D", "MCC",      "mcc_name",        True,  True),
        ("E", "国家",     None,              False, False),
        ("F", "所属渠道", "agent_name",      True,  True),
        ("G", "运营",     "owner_name",      True,  True),
        ("H", "重新分配", "_owner_channel",  True,  True),
        ("I", "时区",     "timezone",        True,  True),
        ("J", "大MCC",    "parent_mcc_name", True,  False),  # 派生列，读回会与 D 打架
        ("K", "状态",     "status_name",     True,  True),
        ("L", "位置",     None,              False, False),
        ("M", "消耗",     None,              False, False),
        ("N", "产品信息", None,              False, False),
    ],
    "tt": [
        ("A", "入库时间",  "acquired_date",   True,  True),
        ("B", "是否回收",  "_dead_flag",      True,  True),
        ("C", "账户ID",    "account_id",      True,  False),  # 定位键（取自 advertiser_id）
        ("D", "BC",        "bc_name",         True,  True),
        ("E", "国家",      "country",         True,  True),
        ("F", "所属渠道",  "agent_name",      True,  True),
        ("G", "接户运营",  "owner_name",      True,  True),
        ("H", "时区",      "timezone",        True,  True),
        ("I", "状态",      "status_name",     True,  True),
        ("J", "消耗",      "consumption",     True,  True),
        ("K", "位置",      None,              False, False),
        # L 只读回、不回写：这一列是系统生成的换绑记录，只由 reassign 端点单点写入，
        # 不参与任何全量/单行回写（否则自动回写会静默吞掉刚记下的换绑）。
        ("L", "换绑情况",  "owner_change_note", False, True),
        ("M", "产品信息",  "remark",          True,  True),
    ],
    "fb": [
        ("A", "日期",     "acquired_date",   True,  True),
        ("B", "操作人",   "operator",        True,  False),  # 冻结字段，系统写、绝不读回
        ("C", "账户名称", "name",            True,  True),
        ("D", "资产UID",  "account_id",      True,  False),  # 定位键
        ("E", "所属渠道", "channel_name",    True,  True),
        ("F", "资产类型", "asset_type_name", True,  True),
        ("G", "单价",     "unit_price",      True,  True),
        ("H", "入库",     "inbound_qty",     True,  True),
        # I 只读回、不参与批量回写：它是系统生成的换绑记录，由三个定向写点维护
        # （建号 / reassign / apply_diff 收尾）。与 TT 的 L 列同形。
        ("I", "接户运营", "acceptor",        False, True),
        ("J", "在用运营", "owner_name",      True,  True),
        ("K", "出库时间", "outbound_date",   True,  True),
        ("L", "出库",     "outbound_qty",    True,  True),
        ("M", "时区",     "timezone",        True,  True),
        ("N", "消耗",     "consumption",     True,  True),
        ("O", "状态",     "status_name",     True,  True),
        ("P", "位置",     "primary_bm_name", True,  True),
        ("Q", "产品信息", "remark",          True,  True),
    ],
}

KEY_COL = {"gg": "C", "tt": "C", "fb": "D"}
OWNER_COL = {"gg": "G", "tt": "G", "fb": "J"}
OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}      # 刻意不含 fb，见 spec §6.5
READ_RANGE = {"gg": "A:N", "tt": "A:M", "fb": "A:Q"}

# 系统里「账户ID」列在两张表下的实际字段名
ACCOUNT_KEY_FIELD = {"gg": "account_id", "tt": "advertiser_id", "fb": "account_id"}


def _text(value) -> str:
    """账户ID 等长数字强制文本，避免 Sheets 按数字处理丢精度。

    对照 append_recycle（google_sheets_service.py:450）的既有做法。
    """
    s = "" if value is None else str(value).strip()
    if s and s.isdigit():
        return "'" + s
    return s


def cells_for_row(row: dict, platform: str) -> dict:
    """系统 → 表：把一行账户数据转成 {列字母: 待写值}。

    只产出可写列，且**绝不产出归属变更通道列**（规格 §7.2 规则 2）——
    自动回写若顺手把户管刚填的重新分配清掉，那个变更就被静默吞了。
    """
    cells = {}
    for col, _header, field, writable, _readable in COLUMN_SPEC[platform]:
        if not writable or field is None or field == "_owner_channel":
            continue
        if field == "_dead_flag":
            cells[col] = "是" if (row.get("death_date") or "").strip() else ""
        elif field == "account_id":
            cells[col] = _text(row.get("account_id", ""))
        else:
            cells[col] = "" if row.get(field) is None else str(row.get(field)).strip()
    return cells


def parse_row(values: list, platform: str) -> dict:
    """表 → 系统：把一行原始单元格值转成 {字段名: 字符串值}。

    不可读列（定位键 C、派生列、未映射列）一律不出现在结果里，
    `_owner_channel` 与 `_dead_flag` 是合成字段，供上层判归属与生死。
    """
    out = {}
    for col, _header, field, _writable, readable in COLUMN_SPEC[platform]:
        if not readable or field is None:
            continue
        i = col_index(col)
        raw = values[i] if len(values) > i else ""
        out[field] = ("" if raw is None else str(raw)).strip()
    # C 列是定位键，单独取。统一键名恒为 "account_id"（GG 与 TT 一致），
    # 与 ACCOUNT_KEY_FIELD 里的 DB 列名是两个命名空间：消费解析结果用
    # account_id，拼 SQL / 写库用 ACCOUNT_KEY_FIELD[platform]，勿混用。
    # lstrip("'") 假定该值只带 _text() 加的那一个前缀。
    key_i = col_index(KEY_COL[platform])
    raw_key = values[key_i] if len(values) > key_i else ""
    out["account_id"] = ("" if raw_key is None else str(raw_key)).strip().lstrip("'").strip()
    return out


def effective_owner_name(parsed: dict, platform: str) -> str:
    """有效归属判定，按平台分叉。

    TT（2026-10-06 规格）：归属**恒取**「接户运营」列。原「换绑情况」列的变更通道语义已取消，
    该列改作换绑记录文本（`owner_change_note`），不参与归属判定。

    GG：维持 2026-09-23 规格 §7.1 —— 「重新分配」列非空时压过「运营」列。
    「表里运营列和重新分配列不一致，就以表里的重新分配为准」（用户原话）。

    platform 是**必填位置参数**，刻意不给默认值：漏传的 TT 调用方会静默拿到 GG 语义，
    那正是本次要消除的 bug。
    """
    if platform == "tt":
        return (parsed.get("owner_name") or "").strip()
    channel = (parsed.get("_owner_channel") or "").strip()
    if channel:
        return channel
    return (parsed.get("owner_name") or "").strip()


def is_dead(parsed: dict) -> bool:
    """该行是否应判为死亡。

    状态列（GG K / TT I）比 是否封户 / 是否回收 更具体，有值时以它为准。
    """
    status = (parsed.get("status_name") or "").strip()
    if status:
        return status == DEAD_STATUS
    return (parsed.get("_dead_flag") or "").strip() == "是"


# ---------- 每户管的看板配置 ----------

CONFIG_KEY = "huguan_dashboard_{uid}"


def load_config(db, user_id: int) -> dict:
    """读取该户管的看板配置：{"gg": {...}, "tt": {...}}，未配置时为空 dict。"""
    row = db.execute("SELECT value FROM config WHERE key=?",
                     (CONFIG_KEY.format(uid=user_id),)).fetchone()
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {}


def _conf_text(value) -> str:
    """配置值一律转成去空白的字符串。

    不能写 `(value or "").strip()` —— `config` 表是全仓共用的，里面存的可能是数字或
    列表（真值非 str），`.strip()` 会直接 `AttributeError` 炸成 500。同类兜底先例见
    本模块 `_text()`。
    """
    return "" if value is None else str(value).strip()


def get_platform_config(db, user_id: int, platform: str) -> dict:
    """取某平台的看板配置，永远返回两项（未配置时为空串，调用方无需判 None）。"""
    entry = load_config(db, user_id).get(platform)
    # config 表被其它功能共用，平台条目可能是「真值非 dict」；不判类型会 AttributeError
    if not isinstance(entry, dict):
        entry = {}
    return {
        # 内层值同样不能假设是 str —— 外层判了 dict 不代表里面存的是字符串
        "spreadsheet_id": _conf_text(entry.get("spreadsheet_id")),
        "sheet_name": _conf_text(entry.get("sheet_name")),
    }


def save_config(db, user_id: int, platform: str, spreadsheet_id: str, sheet_name: str) -> None:
    """写入某平台的看板配置，另一个平台的配置保持不变。"""
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")
    conf = load_config(db, user_id)
    conf[platform] = {
        "spreadsheet_id": _conf_text(spreadsheet_id),
        "sheet_name": _conf_text(sheet_name),
    }
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (CONFIG_KEY.format(uid=user_id), json.dumps(conf, ensure_ascii=False)))
    db.commit()


# ---------- 子项目 ③：同步撤回的快照原语 ----------

UNDO_DIRECTIONS = ("push", "sync")


def save_undo(db, user_id: int, platform: str, direction: str, payload: dict) -> None:
    """写入/覆盖某户管某平台某方向的撤回快照。

    `UNIQUE(user_id, platform, direction)` + `INSERT OR REPLACE` ⇒ 天然「只留最近一条」。
    **不 commit**：与调用方共用事务（快照必须与它描述的那次写入同生共死）。
    """
    if direction not in UNDO_DIRECTIONS:
        raise ValueError(f"不支持的撤回方向: {direction}")
    db.execute("INSERT OR REPLACE INTO huguan_sync_undo(user_id, platform, direction, payload) "
               "VALUES(?,?,?,?)",
               (user_id, platform, direction, json.dumps(payload, ensure_ascii=False)))


def load_undo(db, user_id: int, platform: str, direction: str) -> dict | None:
    """读某方向的快照；没有或 JSON 坏掉都返回 None（撤回入口据此禁用）。"""
    row = db.execute("SELECT payload FROM huguan_sync_undo "
                     "WHERE user_id=? AND platform=? AND direction=?",
                     (user_id, platform, direction)).fetchone()
    if not row or not row["payload"]:
        return None
    try:
        loaded = json.loads(row["payload"])
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def delete_undo(db, user_id: int, platform: str, direction: str) -> None:
    """作废某方向的快照。**不 commit**。"""
    db.execute("DELETE FROM huguan_sync_undo "
               "WHERE user_id=? AND platform=? AND direction=?", (user_id, platform, direction))


def resolve_named_id(db, sql: str, params: tuple = ()) -> int | None:
    """按名称查唯一主键。命中 0 条或 ≥2 条都返回 None（规格 §8.4）。

    重名时不猜 —— 猜错就是把账户挂到了错误的 MCC / BC / 渠道上。
    """
    rows = db.execute(sql, params).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def resolve_owner_id(db, name: str):
    """归属名 → users.id。空 display_name 回退 username，唯一命中才返回。

    必须用**单条** COALESCE(NULLIF(display_name,''), username) 查询，不能拆成
    「先查 display_name，查不到再查 username」两条：后者会在
    「甲的 display_name 与乙的 username 同名」时静默返回甲 —— 而写表方向
    （`_GG_ROW_SQL` / `_TT_ROW_SQL`）产出的正是这一个合成名字空间，两边不对称
    就会把账户挂到错误的人名下。规格 §8.4 的统一口径是「唯一命中才落库」，
    跨命名空间撞名属 ≥2 条命中，应出警告而不是猜。
    """
    name = (name or "").strip()
    if not name:
        return None
    return resolve_named_id(
        db,
        "SELECT id FROM users WHERE COALESCE(NULLIF(display_name, ''), username) = ?",
        (name,))


def resolve_status_id(db, name: str, owner_id, platform: str, *, create_missing: bool = True):
    """状态名 → account_statuses.id。

    **查重键是 (name, platform)，不含 owner_id。** 真实唯一约束就是这两个列
    （database.py:1225 的迁移重建；database.py:505 的原始建表 UNIQUE(name, owner_id)
    已被覆盖，PRAGMA 实测 sqlite_autoindex_account_statuses_1 = ['name','platform']）。
    带上 owner_id 查重会让「甲已有『待优化』(gg)、乙的账户也写『待优化』」查不中而
    重复 INSERT，直接 sqlite3.IntegrityError —— 该异常从 _resolve_field 穿到
    build_diff，**把整份差异报告带崩**（同 sheet 其它行的结果也拿不到）。
    owner_id 只是「谁先建的」这个记账，不参与查重。
    既有正确对照：main.py:6102（/api/statuses/list 的创建）、routes/tt_accounts_routes.py:65。

    **必须带 platform**：account_statuses.platform 默认 'gg'（database.py:153），
    而状态下拉按平台过滤（main.py:6059 `/api/statuses/list`）。不写平台会让 TT 同步
    新建的状态落进 gg 命名空间 —— TT 下拉里看不见，反而出现在 GG 下拉里。
    既有代码的两种写法可对照：GG 侧靠默认值吃 'gg'（main.py:4042/4184/4944/5068），
    TT 侧显式写 'tt'（main.py:6085、tt_accounts_routes.py:69）。

    因为唯一约束成立，(name, platform) **至多命中 1 行**，所以状态解析没有
    规格 §8.4 的「命中 ≥2 条」歧义档 —— 只有 id / None 两种结果。

    create_missing=False 时只查不建（规格 §8.3 步骤 7：dry_run 不改库），
    查不到返回 None，由调用方按 pending 处理（不是 warning）。
    """
    name = (name or "").strip()
    if not name:
        return None
    row = db.execute("SELECT id FROM account_statuses WHERE name=? AND platform=?",
                     (name, platform)).fetchone()
    if row:
        return row["id"]
    if not create_missing:
        return None
    db.execute("INSERT INTO account_statuses(name, owner_id, platform) VALUES(?,?,?)",
               (name, owner_id, platform))
    return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# 各可读列 → (解析器种类, 查名 SQL 模板)
_SQL_MCC = "SELECT id FROM mcc WHERE name=?"
_SQL_AGENT_GG = "SELECT id FROM agents WHERE name=? AND (platform='gg' OR platform IS NULL)"
_SQL_AGENT_TT = "SELECT id FROM agents WHERE name=? AND platform='tt'"
# tt_bcs 有 deleted_at（database.py），必须过滤软删：否则一个已删的 BC 若恰好是
# 唯一同名行，会被「唯一命中才落库」放行，把账户挂到已删的 BC 上。仓库既有口径一致
# （tt_routes.py:133/198/1054/1058 全部带 deleted_at IS NULL）。
# mcc / agents 无 deleted_at，不加；users 也无。
_SQL_BC = "SELECT id FROM tt_bcs WHERE name=? AND deleted_at IS NULL"

# 平台 → 「所属渠道」的查名 SQL。FB 为 None：它不走 agents，由 Task 2 单独处理。
_AGENT_SQL = {"gg": _SQL_AGENT_GG, "tt": _SQL_AGENT_TT, "fb": None}

# FB 的两个公用词表（子项目 ① §4.2）。唯一约束都是 (name, platform)，
# 因此**至多命中 1 行**，不存在「命中 ≥2 条」的歧义档 —— 与 status_name 同档。
_SQL_CHANNEL = "SELECT id FROM fb_channels WHERE name=? AND platform='fb'"
_SQL_ASSET_TYPE = "SELECT id FROM fb_asset_types WHERE name=? AND platform='fb'"


def _resolve_field(db, platform: str, field: str, value: str):
    """把表里的一个名称解析成系统主键；不认识的字段返回 (True, None) 表示无需解析。

    返回 (ok, resolved)：ok=False 表示该列要记 warning 且不落库。

    **status_name 刻意不在这里。** 状态有三档而其它名称只有两档：其它名称是
    「唯一命中 / 歧义（0 或 ≥2 条）」，状态是「已有 id / 系统里还没有（pending）」
    —— 因为唯一约束 (name, platform) 让状态至多命中 1 行，不存在歧义档。
    混进本函数会让「查不到」被误判成歧义而记 warning、把该列丢弃，正是规格
    §8.3 步骤 7 要避免的。状态的解析在 `_collect_updates` 里单独走。
    """
    if field == "mcc_name":
        return True, resolve_named_id(db, _SQL_MCC, (value,))
    if field == "agent_name":
        sql = _AGENT_SQL[platform]
        if sql is None:
            # FB 的「所属渠道」不在 agents 表里，走 fb_channels（见下方独立分支）
            return False, None
        return True, resolve_named_id(db, sql, (value,))
    if field == "bc_name":
        return True, resolve_named_id(db, _SQL_BC, (value,))
    # FB 专有：所属渠道 / 资产类型
    if field == "channel_name":
        return True, resolve_named_id(db, _SQL_CHANNEL, (value,))
    if field == "asset_type_name":
        return True, resolve_named_id(db, _SQL_ASSET_TYPE, (value,))
    return False, None


# 可直接覆盖的文本列（不需要名称解析）
_PLAIN_TEXT_FIELDS = {
    "gg": ("acquired_date", "timezone"),
    "tt": ("acquired_date", "country", "timezone", "consumption", "remark",
           "owner_change_note"),
    # FB 的文本列。acceptor（I 列「接户运营」）**在这里** —— 它是**双向**列：户管
    # 在表里手填的串原样读回落进 `acceptor`（设计 §3.1），空值照常走「文本列空着=清空」。
    # 它之所以还特殊，只是**批量回写**（系统→表）不写这一列 —— 那是 `COLUMN_SPEC`
    # 里 `writable=False` 管的（设计 §4.1），与本读回口径是两个正交的旋钮。
    "fb": ("acquired_date", "name", "unit_price", "inbound_qty", "outbound_date",
           "outbound_qty", "timezone", "consumption", "remark", "acceptor"),
}


# 各平台可读且需要名称解析的字段。FB 没有 MCC / BC，改为两个公用词表。
_PARSEABLE_FIELDS = {
    "gg": ("mcc_name", "agent_name", "bc_name", "status_name"),
    "tt": ("mcc_name", "agent_name", "bc_name", "status_name"),
    "fb": ("channel_name", "asset_type_name", "status_name"),
}


def _parseable_fields(platform: str) -> tuple:
    """该平台可读且需要名称解析的字段（值非空时才解析）。"""
    return _PARSEABLE_FIELDS[platform]


def build_diff(db, parsed_rows: list, platform: str) -> dict:
    """表 → 系统 的逐行比对，产出五类差异（规格 §8.3）。

    parsed_rows: [{"row": 表里行号, **parse_row(...)}]
    每个产出项都带 "row"，供前端回传确认。
    """
    key_field = ACCOUNT_KEY_FIELD[platform]
    sheet_rows = len(parsed_rows)   # 表里数据行总数（**去重前**），供 summary 用

    # 四个产出列表必须在去重循环**之前**建好：去重本身会往 warnings 里塞一条
    to_create, to_update, owner_changes, to_skip = [], [], [], []
    warnings = []

    # 按账户ID 去重：同一 ID 在表里出现两行时，若两行都进 to_create，落库阶段第二行
    # 会撞唯一约束。取**首次出现**的那行生效，后续行记 warning（户管要能看到并去改表）。
    # 账户ID 为空的行不在这里拦 —— 它们要按原有路径记「账户ID为空，跳过」。
    seen_rows, deduped = {}, []
    for p in parsed_rows:
        aid = (p.get("account_id") or "").strip()
        if not aid:
            deduped.append(p)
            continue
        if aid in seen_rows:
            warnings.append({"row": p.get("row"),
                             "message": f"账户ID「{aid}」已在第 {seen_rows[aid]} 行出现，本行跳过"})
            continue
        seen_rows[aid] = p.get("row")
        deduped.append(p)
    parsed_rows = deduped

    ids = [p.get("account_id") for p in parsed_rows if p.get("account_id")]

    existing_map = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        table = _TABLE_FOR_PLATFORM[platform]
        rows = db.execute(
            f"""SELECT a.*, u.display_name AS owner_display, u.username AS owner_username
                FROM {table} a LEFT JOIN users u ON a.owner_id = u.id
                WHERE a.{key_field} IN ({marks})""",
            ids,
        ).fetchall()
        for r in rows:
            existing_map[r[key_field]] = dict(r)

    for p in parsed_rows:
        row_no = p.get("row")
        aid = p.get("account_id", "")
        if not aid:
            warnings.append({"row": row_no, "message": "账户ID为空，跳过"})
            continue

        want_owner_name = effective_owner_name(p, platform)
        want_owner_id = None
        if want_owner_name:
            want_owner_id = resolve_owner_id(db, want_owner_name)
            if want_owner_id is None:
                warnings.append({"row": row_no,
                                 "message": f"运营「{want_owner_name}」无法识别，已跳过归属变更"})

        existing = existing_map.get(aid)
        if existing is None:
            db_values = _collect_updates(db, platform, p, want_owner_id, row_no, warnings,
                                         create_missing=False)
            # 只摘 `_pending_status` 这一个合成键（它由报告层的 `pending_status` 字段承载）。
            # `_is_dead` **故意保留在 db_values 里**，别顺手一起 pop —— apply_diff 会
            # 自己 pop 它去同步 death_date；在这里摘掉会让新建账户的死亡标记静默丢失。
            pending = db_values.pop("_pending_status", None)
            to_create.append({
                "row": row_no,
                "account_id": aid,
                "owner_id": want_owner_id,
                "owner_name": want_owner_name,
                # 键名刻意不叫 "cells"：本模块里 "cells" 一律指「表列字母 → 单元格值」
                # （Task 4 的 update_rows_by_account_id 契约），这里装的是
                # 「数据库列名 → 值」，供 apply_diff 拼 INSERT。两者同名会被误用。
                "db_values": db_values,
                # 系统里还没有的状态名；apply_diff 落库前才 INSERT（build_diff 只读）
                "pending_status": pending,
            })
            continue

        if existing.get("deleted_at"):
            to_skip.append({"row": row_no, "account_id": aid,
                            "reason": "系统中已逻辑删除，不动"})
            continue

        cur_owner = existing.get("owner_id")
        if want_owner_id is not None and int(cur_owner or 0) != int(want_owner_id):
            owner_changes.append({
                "row": row_no,
                "account_id": aid,
                "existing_id": existing["id"],
                "from": existing.get("owner_display") or existing.get("owner_username") or "",
                "to": want_owner_name,
                "to_owner_id": want_owner_id,
                # 规格 §7.2 规则 1：通道列非空时压过当前归属列。`via` 让户管看见
                # 「为什么这个人被改了」——否则规则与眼前这条变更对不上。
                # 稳定 token（不是中文列头）：列头改名/加平台都不影响接口契约，
                # 中文文字由前端按平台映射（GG 重新分配 / TT 换绑情况）。
                "via": ("owner_channel"
                        if (p.get("_owner_channel") or "").strip()
                        else "owner_name"),
            })

        # 归属变更后，状态/渠道等要按新 owner 作用域解析
        scope_owner = want_owner_id if want_owner_id is not None else cur_owner
        fields = _collect_updates(db, platform, p, scope_owner, row_no, warnings,
                                  create_missing=False)
        pending = fields.pop("_pending_status", None)
        # TT 的 remark 不走「按表覆盖」（2026-10-06 规格）：投手权威永久，
        # 户管看板 M 列的改动不再进系统。空值也因此不会进 clears，
        # 根治了原先「户管 M 列空着就清掉投手备注」的隐患。
        # 注意：只剔 to_update —— to_create（首次入库）仍要用户管 M 列的值。
        changed = {k: v for k, v in fields.items()
                   if not _same_as_existing(db, platform, existing, k, v)
                   and not (platform == "tt" and k == "remark")}
        # pending 也算真实变更：系统里没这个状态名，建出来必然与现状不同。
        # 只比 `changed` 会让「这一行只改了状态」被整行漏掉。
        if changed or pending:
            to_update.append({"row": row_no, "account_id": aid,
                              "existing_id": existing["id"], "fields": changed,
                              "pending_status": pending,
                              # apply_diff 建缺失状态行时用它记 owner（谁先建的）
                              "scope_owner_id": scope_owner,
                              # 新值为空串的文本列：清空是不可逆的，必须让前端显式标注
                              "clears": _blank_columns(platform, changed)})

    return {
        "to_create": to_create,
        "to_update": to_update,
        "owner_changes": owner_changes,
        "to_skip": to_skip,
        "warnings": warnings,
        "summary": {
            "total_in_sheet": sheet_rows,
            "new_accounts": len(to_create),
            "updates": len(to_update),
            "owner_changes": len(owner_changes),
            "skipped": len(to_skip),
            "warnings": len(warnings),
            # 只统计 to_update：新建账户的空列是「不填」，不是「清空已有值」。
            # 首次正式同步前先跑 dry_run 看这个数，是这次「空值=清空」口径的
            # 唯一量化手段（规格 §8.3）。
            "clears": sum(len(i.get("clears") or []) for i in to_update),
        },
    }


def _collect_updates(db, platform, p, owner_id, row_no, warnings, *, create_missing=True) -> dict:
    """把一行解析结果里「要写进系统」的字段收集成 {字段名: 值}。

    名称类字段先解析成主键，解析不唯一则记 warning 并丢弃该字段。

    **文本列的空值照常落库，不得写成 `if not value: continue`。** 规格 §8.3 对
    `to_update` 的口径是「**按表覆盖该列**」——表里空着就是把系统里该列清空，
    否则户管永远无法从表里清掉一个值（B 列「是否封户」清空即撤销死亡，同理）。
    §7.4「不因表里空着就把 owner_id 清空」是**归属专属例外**，不能推广到文本列。
    与下方名称类字段的 `if not value: continue` 不对称是**刻意的**：空串在名称
    命名空间里根本没有可解析的候选，属规格 §8.4 的「命中 0 条」。

    产出里可能带三个**下划线开头的合成键**（不是数据库列，调用方必须先摘掉）：
    `_is_dead` 死亡标记、`_pending_status` 系统里还没有的状态名、
    `_primary_bm_name`（FB 专有，表里填的主 BM 名）。

    create_missing 由 build_diff 传 False（dry_run 只读），落库阶段才用默认 True。
    """
    out = {}
    for f in _PLAIN_TEXT_FIELDS[platform]:
        # `_conf_text` 兜底是因为 p 未必全是 str（同 `_conf_text` 的既有理由）
        out[f] = _conf_text(p.get(f))
    # FB 的「位置」列：BM 名 → 主 BM。它不是普通外键列（主 BM 存在中间表
    # fb_account_bm 上，见 _set_primary_bm），所以不能走 _resolve_field /
    # _target_column 那条通用路径，改为在这里产出 `_primary_bm_name` 合成键，
    # 由 apply_diff 的 to_create / to_update 分支消费。
    # 注意**不判空**：表里「位置」空着时也要产出空串，交给 apply_diff 的 to_update
    # 走「只清 is_primary 标记、不删关联行」那条分支（设计 §6.3）。若在这里用
    # `if bm_name:` 把空值丢掉，户管就永远无法从表里撤销主 BM。
    if platform == "fb":
        out["_primary_bm_name"] = (p.get("primary_bm_name") or "").strip()
    for f in _parseable_fields(platform):
        value = (p.get(f) or "").strip()
        if not value:
            continue
        if f == "status_name":
            # 状态单独走：它没有「歧义」档（唯一约束 (name, platform) 至多命中 1 行），
            # 所以查不到**不是**警告，而是「系统里还没有」——create_missing=False 时
            # 记成 pending，落库阶段再 INSERT。走下面的通用分支会被误判成歧义而丢弃。
            sid = resolve_status_id(db, value, owner_id, platform,
                                    create_missing=create_missing)
            if sid is None:
                out["_pending_status"] = value
            else:
                out["status_id"] = sid
            continue
        _known, resolved = _resolve_field(db, platform, f, value)
        if not _known:
            continue
        if resolved is None:
            warnings.append({"row": row_no,
                             "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
            continue
        out[_target_column(platform, f)] = resolved
    out["_is_dead"] = is_dead(p)
    return out


def _blank_columns(platform: str, fields: dict) -> list:
    """fields 里新值为空串的文本列（下划线开头的合成键不算）。

    规格 §8.3：文本列空着 = 清空系统里该列。这是不可逆的批量动作，所以单独列出来
    让前端显式标注「将清空」——不能让「几百行的 acquired_date 被悄悄清掉」藏在差异
    报告里。只认文本列：`_is_dead`（合成键）与主键列（`mcc_id` 等）不在此列。
    """
    return sorted(k for k, v in fields.items()
                  if k in _PLAIN_TEXT_FIELDS[platform] and v == "")


def _target_column(platform: str, field: str) -> str:
    """解析后的字段名 → 真实数据库列名。

    `status_name` 这条**不**经 `_collect_updates` 的通用分支（状态走 pending 档），
    但 apply_diff 落库时要靠它把 pending 状态名映射到 `status_id` 列，所以保留。
    """
    return {
        "mcc_name": "mcc_id",
        "agent_name": "agent_id",
        "bc_name": "bc_id",
        "status_name": "status_id",
        "channel_name": "channel_id",
        "asset_type_name": "asset_type_id",
    }[field]


def _same_as_existing(db, platform, existing: dict, key: str, value) -> bool:
    """比较待写值与库里当前值，决定是否真的需要更新（避免无意义写入）。"""
    if key == "_is_dead":
        cur_dead = bool((existing.get("death_date") or "").strip())
        return cur_dead == bool(value)
    if key == "_primary_bm_name":
        # 合成键：当前主 BM 名不在业务表行上（挂在中间表 fb_account_bm），
        # existing 里取不到，必须现查 —— 否则「表里清空位置」会被误判成「没变」
        # 而被 build_diff 滤掉，主 BM 永远清不掉（设计 §6.3）。
        row = db.execute(
            "SELECT b.name AS n FROM fb_account_bm ab JOIN fb_bms b ON ab.bm_id=b.id "
            "WHERE ab.account_id=? AND ab.is_primary=1", (existing["id"],)).fetchone()
        return (row["n"] if row else "") == (value if value is not None else "")
    cur = existing.get(key)
    if cur is None and value in (None, ""):
        return True
    return str(cur if cur is not None else "") == str(value if value is not None else "")

def owner_channel_cells(rows: list, platform: str, value: str) -> list:
    """构造只写归属变更通道列的 rows（规格 §7.2 规则 3②）。

    刻意只含这一列 —— 收尾写入若顺手带上别的列，就会把户管在表里的
    其他手工改动一起冲掉。
    """
    col = OWNER_CHANNEL_COL[platform]
    return [{"account_id": r["account_id"], "cells": {col: value}} for r in rows]


# MCC / BC 变更历史的分平台落库规格：
# (业务表, 业务列, 历史表, 旧值列, 新值列)
_CHANNEL_HISTORY_SPEC = {
    "gg": ("accounts", "mcc_id", "account_mcc_history", "old_mcc_id", "new_mcc_id"),
    "tt": ("tt_accounts", "bc_id", "tt_account_bc_history", "old_bc_id", "new_bc_id"),
}

# 户管同步造成的 MCC / BC 变更的 change_type，**按语义分成两个**：
#   create —— 建号时的首次分配（to_create 分支），面板显示「新建账户」，
#             与仓库既有建号路径取同一个值（main.py:4333）。
#   batch  —— 改**既存**账户的 MCC/BC（to_update 分支），面板显示「批量修改」，
#             表驱动的一批账户批量改列，与仓库既有的批量修改同档（main.py:4943）。
# 两者都取既有取值、不新增 —— 新增取值会让 GG 的 `_MCC_CHANGE_TYPE_LABELS`
# （main.py:1957）与 TT 的 `changeTypeLabel`（TtAccountDetailModal.vue:150）
# 双双回落成英文原值（两处映射都没有中文兜底）。
_CHANNEL_HISTORY_CHANGE_TYPE_CREATE = "create"
_CHANNEL_HISTORY_CHANGE_TYPE_UPDATE = "batch"


def _norm_ref_id(value):
    """外键列的空值归一：0 / "0" / 空串 / None 一律算「没挂」。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if value == 0 or value == "0":
        return None
    return value


def _record_channel_change(db, platform: str, account_pk: int, fields: dict,
                           changed_by: int) -> None:
    """同步改了 MCC（GG）/ BC（TT）时补写变更历史，值没真变则不写。

    仓库既有契约是**任何** mcc_id 变更都要写 `account_mcc_history`
    （main.py:4339 / :4479 / :4539 / :4729 / :4943，TT 侧同构走
    `tt_account_bc_history`）。户管同步此前直接 UPDATE 而不留痕，MCC 变更历史
    面板会整批漏掉这类变更 —— 谁在什么时候把账户挂到了哪个 MCC 上再也查不回来。

    `account_id` 列存的是**业务表行主键**（`account_mcc_history.account_id
    REFERENCES accounts(id)`，database.py:334；TT 同构），不是表里的文本账户ID
    —— 历史面板正是按行主键查的（main.py:5749 的 `<int:aid>`）。

    changed_by 取发起本次同步的户管 uid（调用方传入的 user_id）。
    本函数不 commit：与调用方共用同一个事务，历史行与业务行同生共死。
    """
    table, col, _hist_table, _old_col, _new_col = _CHANNEL_HISTORY_SPEC[platform]
    if col not in fields:
        return
    new_val = _norm_ref_id(fields[col])
    old = db.execute(f"SELECT {col} AS v FROM {table} WHERE id=?", (account_pk,)).fetchone()
    if not old:
        return
    old_val = _norm_ref_id(old["v"])
    # 必须与**库里的当前值**比，而不是只看 fields 里有没有这个键：
    # 值没变时写历史会凭空多出一条「A → A」的变更，历史面板上真变更被淹没。
    # （NULL → 某值是真变更：NULL 表示原本没挂 MCC/BC。）
    if old_val == new_val:
        return
    _insert_channel_history(db, platform, account_pk, old_val, new_val, changed_by,
                            _CHANNEL_HISTORY_CHANGE_TYPE_UPDATE)


def _record_channel_assign(db, platform: str, account_pk: int, fields: dict,
                           changed_by: int) -> None:
    """同步**新建**的账户带了 MCC / BC 时补写「首次分配」历史（旧值恒为 NULL）。

    与仓库既有建号路径同契约：main.py:4333（`create`）/ :4479（`import`）在
    INSERT 账户之后同样紧接着补一条 old=NULL 的历史 —— 首次分配也是变更，
    否则新账户的 MCC 挂载在历史面板上凭空出现、事后无从追溯。

    值没落地就不写：表里那一列空着是「不填」，压根没有可记的首次分配。
    change_type 取 `create`（与仓库既有建号路径 main.py:4333 同值）。
    """
    col = _CHANNEL_HISTORY_SPEC[platform][1]
    new_val = _norm_ref_id(fields.get(col))
    if new_val is None:
        return
    _insert_channel_history(db, platform, account_pk, None, new_val, changed_by,
                            _CHANNEL_HISTORY_CHANGE_TYPE_CREATE)


def _insert_channel_history(db, platform: str, account_pk: int, old_val, new_val,
                           changed_by, change_type: str) -> None:
    """写一行 MCC / BC 变更历史。**调用方负责判定「这确实是一次变更」与取值。**"""
    if not changed_by:
        # changed_by REFERENCES users(id)：写 None/0 会撞 FK 或记出一行无主历史。
        # 真出现（调用方没传 uid）时宁可漏记也不能写坏。
        log.warning("户管同步改 MCC/BC 但缺少 changed_by，跳过历史记录 platform=%s id=%s",
                    platform, account_pk)
        return
    _table, _col, hist_table, old_col, new_col = _CHANNEL_HISTORY_SPEC[platform]
    db.execute(
        f"INSERT INTO {hist_table}(account_id, {old_col}, {new_col}, changed_by, change_type) "
        "VALUES(?,?,?,?,?)",
        (account_pk, old_val, new_val, changed_by, change_type))


def apply_diff(db, diff: dict, platform: str, confirmed: dict, user_id: int) -> dict:
    """执行户管确认过的差异（规格 §8.3 步骤 8）。

    confirmed: {"create": [账户ID...], "update": [账户ID...], "owner": [账户ID...]}
               缺哪个键就完全不执行该类别。

    **匹配键一律是 `account_id`，不是行号。** 落库时是重新拉表重算 diff 的，
    行号会因表里插行/删行而整体位移 —— 按行号匹配会把「勾了账户甲」静默作用到
    另一个账户上（diff 各项里仍保留 "row"，但只用于在 errors 里报「第几行出错」）。
    返回里的 "not_applied" 收集「confirmed 勾了、当前 diff 里却没有任何一项
    account_id 命中」的账户 —— 确认被静默丢弃比报错更危险：户管会以为改过了。
    """
    conf = confirmed or {}
    created = updated = owner_changed = 0
    errors = []
    # 行级「非致命、但户管要知道」的提示（与 build_diff 的 warnings 同形：row + message）。
    # 落库阶段唯一的此类情形是 FB「位置」列的 BM 名无法唯一匹配 —— 该列被跳过，
    # 但不该让整行失败。errors 装的是异常，语义不同，故单列一个列表。
    warnings = []
    applied_owner_rows = []
    hit = {"create": set(), "update": set(), "owner": set()}

    # TT 备注首次对齐的产物（2026-10-06 规格）：由路由层 pop 后消费。
    remark_m_writeback = []
    remark_operator_push = []
    # 本次调用内的投手看板备注缓存 {owner_id: {aid: remark}}。
    # 局部而非模块级 —— 表内容随时可变，跨请求缓存会让户管看到过期值。
    _operator_remark_cache = {}

    table = _TABLE_FOR_PLATFORM[platform]
    key_field = ACCOUNT_KEY_FIELD[platform]

    for item in diff.get("to_create", []):
        if item["account_id"] not in conf.get("create", []):
            continue
        hit["create"].add(item["account_id"])
        try:
            # db_values 装的是「数据库列名 → 值」（见 build_diff 的 to_create），
            # 与表列字母的 cells 不是一回事，切勿混用。
            src = dict(item.get("db_values") or {})
            if platform == "tt" and "remark" in src:
                _op_id = item.get("owner_id")
                if _op_id is not None and _op_id not in _operator_remark_cache:
                    _operator_remark_cache[_op_id] = read_operator_remark_map(db, _op_id)
                _op_value = (_operator_remark_cache.get(_op_id) or {}).get(
                    item["account_id"], "").strip() if _op_id is not None else ""
                if _op_value:
                    src["remark"] = _op_value            # 投手赢
                    remark_m_writeback.append({"account_id": item["account_id"],
                                               "value": _op_value})
                elif _op_id is not None:
                    # 归属解析不到的账户没有投手看板可推（build_diff 对这类行只 warning
                    # 不拦，仍会进 to_create）——不发出记录，保持本键 owner_id 恒为 int。
                    remark_operator_push.append({"owner_id": _op_id,
                                                 "account_id": item["account_id"],
                                                 "value": (src.get("remark") or "").strip()})
            # _is_dead 是合成标记，不是数据库列，必须先摘掉再拼 INSERT
            want_dead = bool(src.pop("_is_dead", False))
            # FB 的「位置」列同样是合成键：主 BM 挂在中间表 fb_account_bm 上，不是
            # fb_accounts 的列。**必须在下面 `cols = ", ".join(src)` 之前摘掉**，
            # 否则会拼出 `INSERT INTO fb_accounts(..., _primary_bm_name)` 直接报错。
            fb_bm_name = src.pop("_primary_bm_name", None) if platform == "fb" else None
            # 系统里还没有的状态名，到这一步才建行（build_diff 全程只读）
            pending = item.get("pending_status")
            if pending:
                src[_target_column(platform, "status_name")] = resolve_status_id(
                    db, pending, item.get("owner_id"), platform)
            src[key_field] = item["account_id"]
            src["name"] = item["account_id"]
            src["owner_id"] = item.get("owner_id")
            # FB 无 death_date 列（子项目 ① 已确认，设计 §6.1）：生死只由状态列承载，
            # 「apply_diff 不据此写 death_date」。无条件写会让 FB 的 INSERT 直接
            # `no column named death_date` —— 整条 to_create 失败，主 BM（位置列）也就挂不上。
            if platform != "fb":
                src["death_date"] = ""
            cols = ", ".join(src)
            marks = ", ".join("?" for _ in src)
            db.execute(f"INSERT INTO {table}({cols}) VALUES({marks})", tuple(src.values()))
            new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            # 首次分配也要留痕（与 main.py:4333 的 create / :4479 的 import 同契约）。
            # new_id 是刚 INSERT 出来的**行主键**，历史表的外键列要的正是它。
            # MCC / BC 首次分配留痕。FB 无 MCC / BC —— `_CHANNEL_HISTORY_SPEC` 没有
            # "fb" 键，直接调用会 KeyError。调用点按平台分流（设计 §5：FB 绝不走到
            # 那两个函数）；FB 自己的留痕是下面的主 BM（_record_bm_change）。
            if platform != "fb":
                _record_channel_assign(db, platform, new_id, src, user_id)
            # FB 的「位置」列：把主 BM 挂到刚建出的账户上（bm_name 在上方已从 src 摘出）。
            if platform == "fb" and fb_bm_name:
                bid = resolve_named_id(
                    db, "SELECT id FROM fb_bms WHERE name=? AND deleted_at IS NULL",
                    (fb_bm_name,))
                if bid:
                    _set_primary_bm(db, new_id, bid)
                    _record_bm_change(db, new_id, None, bid, user_id)
            _apply_death(db, platform, new_id, want_dead)
            created += 1
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    for item in diff.get("to_update", []):
        if item["account_id"] not in conf.get("update", []):
            continue
        hit["update"].add(item["account_id"])
        try:
            fields = dict(item.get("fields") or {})
            is_dead_val = fields.pop("_is_dead", None)
            # 「位置」列是合成键（主 BM 挂在中间表上，不是 fb_accounts 的列）：
            # **必须在下面 `sets = [f"{k}=?" for k in fields]` 之前摘掉**，否则会拼出
            # `UPDATE fb_accounts SET _primary_bm_name=?` 直接报错。
            # 注意空值语义：表里「位置」空着 → 这里是空串（不是 None），
            # 要落到下面的 else 分支「只清主 BM 标记、不删关联行」（设计 §6.3）。
            new_bm_name = fields.pop("_primary_bm_name", None) if platform == "fb" else None
            # 系统里还没有的状态名，到这一步才建行（build_diff 全程只读，规格 §8.3
            # 步骤 7/8）。owner 取该行作用域归属，只记「谁先建的」——不参与查重。
            pending = item.get("pending_status")
            if pending:
                fields[_target_column(platform, "status_name")] = resolve_status_id(
                    db, pending, item.get("scope_owner_id"), platform)
            # 状态真的变了（build_diff 只在状态真变了才把它放进 fields）⇒
            # 「状态变更时间」必须跟着刷新，否则前端显示的永远是旧值。
            # 注意 `datetime('now','localtime')` 是 SQL 表达式不是值：只能作为
            # SET 子句里的**字面量**拼进去，塞进 fields.values() 走占位符会被当成
            # 普通字符串写进该列。
            sets = [f"{k}=?" for k in fields]
            if "status_id" in fields:
                sets.append("status_changed_date=datetime('now','localtime')")
            # MCC / BC 变更必须留痕（历史面板按行主键查）。放在 UPDATE **之前**：
            # 旧值要从库里读，写完这一行就读不到了。
            # FB 无 MCC / BC —— `_CHANNEL_HISTORY_SPEC` 没有 "fb" 键，调用点按平台
            # 分流（设计 §5）。FB 的留痕是下面的主 BM（_record_bm_change）。
            if platform != "fb":
                _record_channel_change(db, platform, item["existing_id"], fields, user_id)
            # FB 的「位置」列：BM 名 → 换主 BM。必须放在 UPDATE **之前** —— 旧主 BM
            # 要从库里读，写完这行业务表就读不到了。
            if platform == "fb" and new_bm_name is not None:
                # `ab.bm_id` 就是 fb_bms 的**行主键**（中间表的外键），正是
                # fb_account_bm_history.old_bm_id 需要的值。**不能取 `b.bm_id`**
                # —— 那是 fb_bms 的业务文本 ID（如 'b1'），拿它写历史会撞 FK。
                old = db.execute(
                    "SELECT ab.bm_id AS bm_id FROM fb_account_bm ab "
                    "WHERE ab.account_id=? AND ab.is_primary=1",
                    (item["existing_id"],)).fetchone()
                bid = resolve_named_id(
                    db, "SELECT id FROM fb_bms WHERE name=? AND deleted_at IS NULL",
                    (new_bm_name,)) if new_bm_name else None
                if new_bm_name and bid is None:
                    warnings.append({"row": item["row"],
                                     "message": f"位置「{new_bm_name}」无法唯一匹配，已跳过"})
                else:
                    _set_primary_bm(db, item["existing_id"], bid) if bid else \
                        db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?",
                                   (item["existing_id"],))
                    _record_bm_change(db, item["existing_id"],
                                      old["bm_id"] if old else None, bid, user_id)
            if sets:
                db.execute(f"UPDATE {table} SET {', '.join(sets)}, "
                           "updated_at=datetime('now','localtime') WHERE id=?",
                           tuple(fields.values()) + (item["existing_id"],))
            if is_dead_val is not None:
                _apply_death(db, platform, item["existing_id"], bool(is_dead_val))
            updated += 1
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    for item in diff.get("owner_changes", []):
        if item["account_id"] not in conf.get("owner", []):
            continue
        hit["owner"].add(item["account_id"])
        try:
            db.execute(f"UPDATE {table} SET owner_id=?, "
                       "updated_at=datetime('now','localtime') WHERE id=?",
                       (item["to_owner_id"], item["existing_id"]))
            if platform == "fb":
                # 换绑记录：旧名 → 新名（spec §6.4 写点 3）
                old_name = item.get("from") or ""
                new_name = item.get("to") or ""
                db.execute("UPDATE fb_accounts SET acceptor=? WHERE id=?",
                           (_fb_owner_transition(old_name, new_name), item["existing_id"]))
            owner_changed += 1
            # 带上 "to"（新归属名）：路由收尾直接用它回写运营列，不必再拿行号反查。
            # "from" 一并带上：路由收尾的 FB 定向回写要用它拼「旧转新」。
            applied_owner_rows.append({"account_id": item["account_id"],
                                       "to": item["to"],
                                       "from": item.get("from", "")})
        except Exception as e:
            errors.append({"row": item["row"], "error": str(e)})

    # 「勾了却没作用上」是独立信号，不进 errors —— 差异报告变了不是出错，
    # 但户管必须知道自己的勾选没生效。
    not_applied = []
    for cat in ("create", "update", "owner"):
        picked = conf.get(cat)
        if not isinstance(picked, list):
            continue
        for aid in picked:
            if aid not in hit[cat]:
                not_applied.append({"account_id": aid, "category": cat})

    db.commit()
    return {"created": created, "updated": updated, "owner_changed": owner_changed,
            "applied_owner_rows": applied_owner_rows, "not_applied": not_applied,
            "remark_m_writeback": remark_m_writeback,
            "remark_operator_push": remark_operator_push,
            "errors": errors, "warnings": warnings}


def _fb_owner_transition(old_name: str, new_name: str) -> str:
    """拼 FB 的换绑记录：`"{旧}转{新}"`。

    两个方向都要挡半截串，否则户管在表里读到的是断句：
    - **没有旧归属**（首任）时只返回新名 —— 否则会拼出「转李四」这种半截串，
      户管在表里读不出是谁转给李四的。
    - **没有新归属**时只返回旧名 —— 否则会拼出「张三转」。接线之后才可能遇到：
      写点的目标用户查不到、或 `apply_diff` 的行少了 `to` 时新名会是空串。
    两者皆空 → 空串（调用方据此不写这列）。
    """
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not new_name:
        return old_name
    if not old_name:
        return new_name
    return f"{old_name}转{new_name}"


def _fb_acceptor_cells(rows: list, value: str) -> list:
    """构造只写 I 列（接户运营）的 rows。

    刻意只含这一列 —— 与 `owner_channel_cells` 同一理由：收尾写入若顺手带上别的列，
    就会把户管在表里的其他手工改动一起冲掉。
    """
    return [{"account_id": r["account_id"], "cells": {"I": value}} for r in rows]


def _set_primary_bm(db, acc_pk: int, bm_id: int) -> None:
    """把某账户的主 BM 换成 bm_id。**不 commit**，事务边界由调用方负责。

    ⚠️ **必须先清后设，顺序不能反。** `idx_fb_account_bm_primary` 是
    `WHERE is_primary = 1` 的部分唯一索引（子项目 ① §4.3）。SQLite 的唯一索引是
    **逐语句**检查的，先设新的（此刻旧的主 BM 还是 1）会立刻 UNIQUE constraint failed。

    与 `py/routes/fb_routes.py::_set_primary_bm` 同一契约（逻辑层刻意不 import
    flask / routes，故不能复用那个）。BM 存在中间表 `fb_account_bm` 上，不是
    `fb_accounts` 的外键列 —— 所以它走不了 `_resolve_field` / `_target_column`
    那条通用路径。
    """
    db.execute("UPDATE fb_account_bm SET is_primary=0 WHERE account_id=?", (acc_pk,))
    cur = db.execute("UPDATE fb_account_bm SET is_primary=1 WHERE account_id=? AND bm_id=?",
                     (acc_pk, bm_id))
    if cur.rowcount == 0:
        db.execute("INSERT INTO fb_account_bm(account_id, bm_id, is_primary) VALUES(?,?,1)",
                   (acc_pk, bm_id))


def _record_bm_change(db, acc_pk: int, old_bm_id, new_bm_id, changed_by: int) -> None:
    """主 BM 真变了才写一行 `fb_account_bm_history`。**不 commit**。

    与 GG 的 `account_mcc_history` / TT 的 `tt_account_bc_history` 同契约：
    任何 MCC / BC 变更都要留痕，FB 的对应物是 BM。`change_type` 取既有的 `batch`
    （表驱动的一批账户改列，与 main.py 的批量修改同档）。

    changed_by 为假值时不写：该列 `REFERENCES users(id)`，写 None/0 会撞 FK 或
    记出一行无主历史，宁可漏记也不能写坏（同 `_insert_channel_history` 的口径）。

    本函数刻意不复用 `_CHANNEL_HISTORY_SPEC` / `_insert_channel_history`：FB 的历史
    表 `fb_account_bm_history` 挂在**中间表**上、不是业务表的外键列，那个形状装不下
    （设计 §5）。
    """
    old_val = _norm_ref_id(old_bm_id)
    new_val = _norm_ref_id(new_bm_id)
    if old_val == new_val:
        return
    if not changed_by:
        log.warning("FB 主 BM 变更但缺少 changed_by，跳过历史记录 acc=%s", acc_pk)
        return
    db.execute("INSERT INTO fb_account_bm_history"
               "(account_id, old_bm_id, new_bm_id, changed_by, change_type) "
               "VALUES(?,?,?,?,?)", (acc_pk, old_val, new_val, changed_by, "batch"))


def _apply_death(db, platform: str, account_pk: int, want_dead: bool) -> None:
    """按死亡标记同步 death_date（对照 main.py:4638 的既有语义）。"""
    # FB 没有 death_date 列（子项目 ① 已确认），生死完全由状态列承载 ——
    # is_dead() 对 FB 只看 status_name == "死亡"，落库时已经通过 status_id 表达。
    # 这里必须直接返回：继续走下去会 UPDATE 一个不存在的列，整批同步报错。
    if platform == "fb":
        return
    table = _TABLE_FOR_PLATFORM[platform]
    if want_dead:
        db.execute(f"UPDATE {table} SET death_date=date('now','localtime'), "
                   "status_changed_date=datetime('now','localtime') WHERE id=?", (account_pk,))
    else:
        # 撤销死亡同样是「状态变更」：status_changed_date 必须一起刷新，否则前端
        # 「状态变更时间」还停在上次封户的时刻上（与真值分支对称）。
        db.execute(f"UPDATE {table} SET death_date='', "
                   "status_changed_date=datetime('now','localtime') WHERE id=?",
                   (account_pk,))


# ---------- Task 8: 系统 → 表 全量刷新 ----------

# 系统 → 表 的行查询语句。owner_name 取 display_name（回退 username）。
#
# 大MCC（J 列，parent_mcc_name）取自**该账户所属 MCC 的父级**：`mcc.parent_mcc_id`
# 指向父 MCC 行。注意这条 join 的条件是 `m.parent_mcc_id = pm.id`，**不是**
# `a.parent_mcc_id` —— `accounts` 表根本没有 parent_mcc_id 列（全仓只在 `mcc`
# 上有，database.py:221），写成账户列名会让整条 SQL 直接 OperationalError。
_GG_ROW_SQL = """
SELECT a.account_id, a.acquired_date, a.death_date, a.timezone,
       m.name AS mcc_name, pm.name AS parent_mcc_name,
       ag.name AS agent_name, COALESCE(NULLIF(u.display_name, ''), u.username, '') AS owner_name,
       s.name AS status_name
FROM accounts a
LEFT JOIN mcc m ON a.mcc_id = m.id
LEFT JOIN mcc pm ON m.parent_mcc_id = pm.id
LEFT JOIN agents ag ON a.agent_id = ag.id
LEFT JOIN users u ON a.owner_id = u.id
LEFT JOIN account_statuses s ON a.status_id = s.id
"""

_TT_ROW_SQL = """
SELECT a.advertiser_id AS account_id, a.acquired_date, a.death_date, a.country,
       a.timezone, a.consumption, a.remark,
       b.name AS bc_name, ag.name AS agent_name,
       COALESCE(NULLIF(u.display_name, ''), u.username, '') AS owner_name,
       s.name AS status_name
FROM tt_accounts a
LEFT JOIN tt_bcs b ON a.bc_id = b.id
LEFT JOIN agents ag ON a.agent_id = ag.id
LEFT JOIN users u ON a.owner_id = u.id
LEFT JOIN account_statuses s ON a.status_id = s.id
"""

_FB_ROW_SQL = """
SELECT a.account_id, a.acquired_date, a.name, a.timezone, a.operator, a.acceptor,
       a.unit_price, a.inbound_qty, a.outbound_date, a.outbound_qty, a.consumption, a.remark,
       ch.name AS channel_name, at.name AS asset_type_name,
       bm.name AS primary_bm_name,
       COALESCE(NULLIF(u.display_name, ''), u.username, '') AS owner_name,
       s.name AS status_name
FROM fb_accounts a
LEFT JOIN fb_channels ch ON a.channel_id = ch.id
LEFT JOIN fb_asset_types at ON a.asset_type_id = at.id
LEFT JOIN fb_account_bm ab ON ab.account_id = a.id AND ab.is_primary = 1
LEFT JOIN fb_bms bm ON ab.bm_id = bm.id
LEFT JOIN users u ON a.owner_id = u.id
LEFT JOIN account_statuses s ON a.status_id = s.id
"""
# 主 BM 的 join **必须带 ab.is_primary = 1**：一个账户可挂多个 BM，
# 不加这个条件会让同一个账户产出多行，而 collect_rows_for_push 按行产 cells。

# 平台 → 业务表名。**刻意用字典查表而不是 `if platform == "tt" else ...`**：
# 后者的 else 会把未知平台静默导向 GG 表（accounts），是本子项目最大的回归风险。
_TABLE_FOR_PLATFORM = {"gg": "accounts", "tt": "tt_accounts", "fb": "fb_accounts"}

# 平台 → 系统→表 的行查询语句
_ROW_SQL = {"gg": _GG_ROW_SQL, "tt": _TT_ROW_SQL, "fb": _FB_ROW_SQL}


def collect_rows_for_push(db, platform: str, account_ids=None) -> list:
    """系统 → 表：查出待写账户并转成 update_rows_by_account_id 的入参。

    产出里刻意不含归属变更通道列（规格 §7.2 规则 2）。
    account_ids=None 表示全部；给了具体 ID 时只取这些。
    两条路径都排除软删账户（`a.deleted_at IS NULL`）：与「从表同步」对软删做
    to_skip 的口径对称，也符合规格 §6.2「软删不触发回写」的意图 —— 软删是用户
    主动从看板撤下的意图，刷新不该把它复活。
    """
    sql = _ROW_SQL[platform]
    params = ()
    # 两个基语句都没有 WHERE 子句，故条件先累积成 list 再统一拼 —— 避免
    # 「先拼 WHERE 再找地方插 AND」那种在无 WHERE 时静默拼错条件的写法。
    conds = ["a.deleted_at IS NULL"]
    if account_ids is not None:
        if not account_ids:
            return []
        marks = ",".join("?" for _ in account_ids)
        conds.append(f"a.{ACCOUNT_KEY_FIELD[platform]} IN ({marks})")
        params = tuple(account_ids)
    sql += " WHERE " + " AND ".join(conds)

    out = []
    for r in db.execute(sql, params).fetchall():
        row = dict(r)
        out.append({"account_id": str(row.get("account_id") or "").strip(),
                    "cells": cells_for_row(row, platform)})
    return [o for o in out if o["account_id"]]


def _operator_dashboard_name(db, owner_id: int) -> str:
    """解析某投手「我的看板」的 sheet 名。

    与 tt_accounts_routes.sync_from_sheet() 同源：先取全局 tags 兜底，
    再被 config 表里的投手私有配置覆盖。两处必须保持一致，否则读与写会对着
    不同的 tab 操作。
    """
    name = ""
    row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_mappings'").fetchone()
    if row and row["value"]:
        try:
            loaded = json.loads(row["value"])
            if isinstance(loaded, dict):
                name = (loaded.get("my_dashboard") or "").strip()
        except Exception:
            pass
    if not name:
        name = "我的看板"
    priv = db.execute("SELECT value FROM config WHERE key=?",
                      (f"tt_sheet_mappings_{owner_id}",)).fetchone()
    if priv and priv["value"]:
        try:
            loaded_priv = json.loads(priv["value"])
            # 必须与 tt_accounts_routes.sync_from_sheet() 的私有覆盖分支**逐字一致**
            # （真值判断、赋原值，两侧都不 strip）——否则「读」与「写」会对着
            # 不同的 sheet tab 操作：配置值带首尾空白时写入用 " 看板A " 而这里读
            # "看板A"；纯空白值写入侧接受、这里却当成「未配置」回退到全局名。
            if isinstance(loaded_priv, dict) and loaded_priv.get("my_dashboard"):
                name = loaded_priv["my_dashboard"]
        except Exception:
            pass
    return name


def read_operator_remark_map(db, owner_id: int) -> dict:
    """读该投手「我的看板」的 广告账户ID → J 列备注 映射。

    投手未配看板、全局未配 tt_sheet_id、或读表失败 —— 一律返回空 dict，
    由调用方按「户管赢」降级。读不到投手看板不应阻断户管同步，故本函数**绝不抛异常**。
    """
    import logging
    log = logging.getLogger("gg-server")
    try:
        row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
        sheet_id = (row["value"] if row and row["value"] else "").strip()
        if not sheet_id:
            return {}
        sheet_name = _operator_dashboard_name(db, owner_id)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        rows = gs.read_sheet_values(service, sheet_id, sheet_name, "A:J")
        if not rows:
            return {}
        rows = rows[1:]   # 跳过表头

        # 单元格取值的 None 守卫（同 parse_row）：Sheets API 对空值可能返回 null，
        # 直接 .strip() 会 AttributeError —— 被外层 catch 吞成 {} 后**一个坏格
        # 就把整张映射全丢了**。
        def _cell(r, i):
            raw = r[i] if len(r) > i else ""
            return ("" if raw is None else str(raw)).strip()

        out = {}
        for r in rows:
            # D 列（下标 3）是账户ID，J 列（下标 9）是备注
            # D 列剥 Sheets 文本前缀 '，J 列不需要。末尾必须再 .strip() ——
            # 与 parse_row / update_rows_by_account_id 的两段式解析对齐：
            # 对 "' 123" 这类格，少了这次 strip 会得到键 " 123"，而那边得到
            # "123"，apply_diff 的 .get(account_id) 静默 miss 后降级为「户管赢」。
            aid = _cell(r, 3).lstrip("'").strip()
            if not aid or aid in out:
                continue
            out[aid] = _cell(r, 9)
        return out
    except Exception as e:
        log.warning("读投手看板备注失败（按户管赢降级）: %s", e)
        return {}


def snapshot_push_targets(service, conf: dict, platform: str, rows: list) -> dict:
    """读整片表，记下「本次刷新将会写到的每个格子」的当前值。

    只覆盖**真正会被写**的行与列：
      - 行：`rows` 里在表中命中定位键的那些（表里没有的账户 update_rows_by_account_id
        会进 not_found、一个字都不写）
      - 列：该行 `cells_for_row` 会产出的列（即 COLUMN_SPEC 里 writable=True 的）

    ⚠️ 必须在**写表之前**调用 —— 写完之后原值就没了。
    """
    sheet_name = conf["sheet_name"]
    grid = read_sheet_values(service, conf["spreadsheet_id"], sheet_name, READ_RANGE[platform])
    key_i = col_index(KEY_COL[platform])

    where = {}
    for i, values in enumerate(grid[1:], start=2):
        if len(values) <= key_i:
            continue
        raw = ("" if values[key_i] is None else str(values[key_i])).strip().lstrip("'").strip()
        if raw and raw not in where:
            where[raw] = values

    out = []
    for r in rows:
        aid = r["account_id"]
        values = where.get(aid)
        if values is None:
            continue
        cells = {}
        for col in r["cells"]:
            i = col_index(col)
            cells[col] = ("" if len(values) <= i or values[i] is None
                          else str(values[i])).strip()
        if cells:
            out.append({"account_id": aid, "cells": cells})
    return {"spreadsheet_id": conf["spreadsheet_id"],
            "sheet_name": sheet_name,
            "cells": out}


def push_undo_cells(payload: dict) -> list:
    """把 push 快照转成 `update_rows_by_account_id` 的入参形状。"""
    return [{"account_id": c["account_id"], "cells": dict(c["cells"])}
            for c in (payload or {}).get("cells", [])]


def push_rows(user_id: int, platform: str, account_ids=None) -> None:
    """把账户当前值写进该户管自己的看板表。

    未配置看板 → 静默返回（不是每个用户都是户管，这不是错误）。
    后台线程写，失败只记日志，不影响调用方的接口返回。
    """
    import logging
    log = logging.getLogger("gg-server")

    db = _open_db()
    try:
        conf = get_platform_config(db, user_id, platform)
        if not conf["spreadsheet_id"] or not conf["sheet_name"]:
            return
        rows = collect_rows_for_push(db, platform, account_ids)
    finally:
        db.close()

    if not rows:
        return

    def _do():
        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                     conf["sheet_name"], rows)

    from main import _sync_sheets_background
    _sync_sheets_background(_do, lambda s, e: log.warning("户管看板回写失败: %s", e) if e else None)


def push_remark_to_operator_dashboard(owner_id: int, account_id: str, value: str) -> None:
    """把备注写进该投手「我的看板」的 J 列（按 D 列定位行）。

    与 push_rows 的区别：push_rows 面向**户管看板**（配置来自 huguan_dashboard_{uid}），
    本函数面向**投手看板**（配置来自 tags.tt_sheet_id + tt_sheet_mappings）。

    投手未配看板 / 全局未配 tt_sheet_id → 静默返回。
    绝不抛异常（与 writeback_rows 同契约：回写失败不得影响主流程）。
    """
    try:
        db = _open_db()
        try:
            row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
            sheet_id = (row["value"] if row and row["value"] else "").strip()
            if not sheet_id:
                return
            sheet_name = _operator_dashboard_name(db, owner_id)
        finally:
            db.close()

        rows = [{"account_id": account_id, "cells": {"J": value}}]

        def _do():
            import google_sheets_service as gs
            from main import _GOOGLE_SHEETS_CONFIG
            service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            # 投手看板的账户ID在 D 列（户管看板在 C 列），故必须显式传 key_col。
            gs.update_rows_by_account_id(service, sheet_id, sheet_name, rows, key_col="D")

        from main import _sync_sheets_background
        _sync_sheets_background(
            _do, lambda s, e: log.warning("投手看板备注回写失败: %s", e) if e else None)
    except Exception as e:
        log.warning("投手看板备注回写触发失败: %s", e)


def _open_db():
    """惰性取库连接（避免本模块在 import 期依赖 database）。"""
    import database
    return database.get_db()


def writeback_rows(user_id, platform, account_ids=None):
    """触发户管看板的单行/多行回写（规格 §6.2）。未配置看板时静默跳过。

    回写是业务端点的副作用，任何失败都不得影响主流程，故本函数绝不抛异常。
    """
    try:
        push_rows(user_id, platform, account_ids)
    except Exception as e:
        log.warning("户管看板回写触发失败: %s", e)


def writeback_owner_channel(user_id, platform, account_id, new_owner_id, text=None):
    """户管在系统里改了归属 → 把新归属写进表里的变更通道列（规格 §7.2 规则 3①）。

    GG 写 H「重新分配」，TT 写 L「换绑情况」。绝不抛异常（理由同 writeback_rows）。
    """
    try:
        db = _open_db()
        try:
            conf = get_platform_config(db, user_id, platform)
            if not conf["spreadsheet_id"] or not conf["sheet_name"]:
                return
            r = db.execute("SELECT COALESCE(NULLIF(display_name, ''), username, '') AS n "
                           "FROM users WHERE id=?", (new_owner_id,)).fetchone()
            name = (r["n"] if r else "").strip()
        finally:
            db.close()
        # text 非 None 时值就是 text，写不写与「归属人名能否解析」无关 ——
        # 否则换绑记录会在归属人名为空时被静默丢弃（2026-10-06 审查裁定）。
        if not name and text is None:
            return
        # text 为 None 时写解析出的新归属名 —— GG 走这条路，行为与改动前逐字节一致。
        # TT 由调用方传入完整的换绑记录文本（「旧转新月.日」）：文本里含「变更前归属人」，
        # 那是 reassign 端点才知道的信息，在本函数里重新推断会引入第二次查询与不一致风险。
        value = text if text is not None else name
        rows = owner_channel_cells([{"account_id": account_id}], platform, value)

        def _do():
            import google_sheets_service as gs
            from main import _GOOGLE_SHEETS_CONFIG
            service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                         conf["sheet_name"], rows)

        from main import _sync_sheets_background
        _sync_sheets_background(
            _do, lambda s, e: log.warning("归属变更通道列回写失败: %s", e) if e else None)
    except Exception as e:
        log.warning("归属变更通道列回写触发失败: %s", e)


def writeback_fb_acceptor(user_id, platform, account_id, note):
    """把 FB 的换绑记录（"{旧}转{新}"）定向写进表里的 I 列。

    与 `writeback_owner_channel` 同形但**语义不同**：那个写的是「新归属名」，
    这个写的是「旧转新」整串（spec §6.5）。因此刻意不复用 `OWNER_CHANNEL_COL`
    （它不含 fb 键，硬塞会 KeyError）。

    绝不抛异常（理由同 `writeback_rows`）。
    """
    try:
        db = _open_db()
        try:
            conf = get_platform_config(db, user_id, platform)
            if not conf["spreadsheet_id"] or not conf["sheet_name"]:
                return
        finally:
            db.close()
        if not (note or "").strip():
            return
        rows = _fb_acceptor_cells([{"account_id": account_id}], note)

        def _do():
            import google_sheets_service as gs
            from main import _GOOGLE_SHEETS_CONFIG
            service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            # 定位列必须按平台取：写入器默认 "C"（GG/TT 的账户ID列），而 FB 的
            # 账户ID在 **D** 列（C 是「账户名称」）—— 不传就按错误的列定位、写空。
            gs.update_rows_by_account_id(service, conf["spreadsheet_id"],
                                         conf["sheet_name"], rows,
                                         key_col=KEY_COL[platform])

        from main import _sync_sheets_background
        _sync_sheets_background(
            _do, lambda s, e: log.warning("FB 接户运营回写失败: %s", e) if e else None)
    except Exception as e:
        log.warning("FB 接户运营回写触发失败: %s", e)
