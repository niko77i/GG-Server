"""户管看板（Google Sheet）双向同步的纯逻辑层。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。

本模块刻意不 import flask、不碰网络：列规格、双向映射、差异比对都放在这里，
单测可直接调用。真正的 Sheets I/O 在 google_sheets_service，HTTP 入口在
routes/huguan_dashboard_routes.py。
"""
import json

from google_sheets_service import col_index

PLATFORMS = ("gg", "tt")

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
        ("L", "换绑情况",  "_owner_channel",  True,  True),
        ("M", "产品信息",  "remark",          True,  True),
    ],
}

KEY_COL = {"gg": "C", "tt": "C"}
OWNER_COL = {"gg": "G", "tt": "G"}
OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}
READ_RANGE = {"gg": "A:N", "tt": "A:M"}

# 系统里「账户ID」列在两张表下的实际字段名
ACCOUNT_KEY_FIELD = {"gg": "account_id", "tt": "advertiser_id"}


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


def effective_owner_name(parsed: dict) -> str:
    """规格 §7.1：归属变更通道非空时压过当前归属列。

    「表里运营列和重新分配列不一致，就以表里的重新分配为准」（用户原话）。
    """
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
        sql = _SQL_AGENT_TT if platform == "tt" else _SQL_AGENT_GG
        return True, resolve_named_id(db, sql, (value,))
    if field == "bc_name":
        return True, resolve_named_id(db, _SQL_BC, (value,))
    return False, None


# 可直接覆盖的文本列（不需要名称解析）
_PLAIN_TEXT_FIELDS = {
    "gg": ("acquired_date", "timezone"),
    "tt": ("acquired_date", "country", "timezone", "consumption", "remark"),
}


def _parseable_fields(platform: str) -> tuple:
    """该平台可读且需要名称解析的字段（值非空时才解析）。"""
    return ("mcc_name", "agent_name", "bc_name", "status_name")


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
        table = "tt_accounts" if platform == "tt" else "accounts"
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

        want_owner_name = effective_owner_name(p)
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
            })

        # 归属变更后，状态/渠道等要按新 owner 作用域解析
        scope_owner = want_owner_id if want_owner_id is not None else cur_owner
        fields = _collect_updates(db, platform, p, scope_owner, row_no, warnings,
                                  create_missing=False)
        pending = fields.pop("_pending_status", None)
        changed = {k: v for k, v in fields.items()
                   if not _same_as_existing(db, platform, existing, k, v)}
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

    产出里可能带两个**下划线开头的合成键**（不是数据库列，调用方必须先摘掉）：
    `_is_dead` 死亡标记、`_pending_status` 系统里还没有的状态名。

    create_missing 由 build_diff 传 False（dry_run 只读），落库阶段才用默认 True。
    """
    out = {}
    for f in _PLAIN_TEXT_FIELDS[platform]:
        # `_conf_text` 兜底是因为 p 未必全是 str（同 `_conf_text` 的既有理由）
        out[f] = _conf_text(p.get(f))
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
    }[field]


def _same_as_existing(db, platform, existing: dict, key: str, value) -> bool:
    """比较待写值与库里当前值，决定是否真的需要更新（避免无意义写入）。"""
    if key == "_is_dead":
        cur_dead = bool((existing.get("death_date") or "").strip())
        return cur_dead == bool(value)
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
    applied_owner_rows = []
    hit = {"create": set(), "update": set(), "owner": set()}

    table = "tt_accounts" if platform == "tt" else "accounts"
    key_field = ACCOUNT_KEY_FIELD[platform]

    for item in diff.get("to_create", []):
        if item["account_id"] not in conf.get("create", []):
            continue
        hit["create"].add(item["account_id"])
        try:
            # db_values 装的是「数据库列名 → 值」（见 build_diff 的 to_create），
            # 与表列字母的 cells 不是一回事，切勿混用。
            src = dict(item.get("db_values") or {})
            # _is_dead 是合成标记，不是数据库列，必须先摘掉再拼 INSERT
            want_dead = bool(src.pop("_is_dead", False))
            # 系统里还没有的状态名，到这一步才建行（build_diff 全程只读）
            pending = item.get("pending_status")
            if pending:
                src[_target_column(platform, "status_name")] = resolve_status_id(
                    db, pending, item.get("owner_id"), platform)
            src[key_field] = item["account_id"]
            src["name"] = item["account_id"]
            src["owner_id"] = item.get("owner_id")
            src["death_date"] = ""
            cols = ", ".join(src)
            marks = ", ".join("?" for _ in src)
            db.execute(f"INSERT INTO {table}({cols}) VALUES({marks})", tuple(src.values()))
            new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
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
            owner_changed += 1
            # 带上 "to"（新归属名）：路由收尾直接用它回写运营列，不必再拿行号反查
            applied_owner_rows.append({"account_id": item["account_id"],
                                       "to": item["to"]})
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
            "errors": errors}


def _apply_death(db, platform: str, account_pk: int, want_dead: bool) -> None:
    """按死亡标记同步 death_date（对照 main.py:4638 的既有语义）。"""
    table = "tt_accounts" if platform == "tt" else "accounts"
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


def collect_rows_for_push(db, platform: str, account_ids=None) -> list:
    """系统 → 表：查出待写账户并转成 update_rows_by_account_id 的入参。

    产出里刻意不含归属变更通道列（规格 §7.2 规则 2）。
    account_ids=None 表示全部；给了具体 ID 时只取这些。
    """
    sql = _TT_ROW_SQL if platform == "tt" else _GG_ROW_SQL
    params = ()
    if account_ids is not None:
        if not account_ids:
            return []
        marks = ",".join("?" for _ in account_ids)
        sql += f" WHERE a.{ACCOUNT_KEY_FIELD[platform]} IN ({marks})"
        params = tuple(account_ids)

    out = []
    for r in db.execute(sql, params).fetchall():
        row = dict(r)
        out.append({"account_id": str(row.get("account_id") or "").strip(),
                    "cells": cells_for_row(row, platform)})
    return [o for o in out if o["account_id"]]


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


def _open_db():
    """惰性取库连接（避免本模块在 import 期依赖 database）。"""
    import database
    return database.get_db()
