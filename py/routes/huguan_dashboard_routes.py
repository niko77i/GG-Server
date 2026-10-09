"""户管看板（Google Sheet）配置与双向同步的 HTTP 入口。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。
本文件只做取参/鉴权/调逻辑层，双向同步的实际判断都在 huguan_dashboard.py，
Sheets I/O 在 google_sheets_service.py。
"""
import logging

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

import database
import huguan_dashboard as hd
from cache import cache as _app_cache

from .helpers import ok, err, get_uid, PLATFORM_SWITCH_ROLES
from .decorators import huguan_required

huguan_dashboard_bp = Blueprint("huguan_dashboard", __name__)

log = logging.getLogger("gg-server")


@huguan_dashboard_bp.route("/api/huguan/dashboard", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_config_get():
    """返回当前户管的看板配置（GG 与 TT 两份）。

    两份都经 `get_platform_config` 归一化后再返回：`config` 表是全仓共用的，
    平台条目可能是「真值非 dict」，直接透传会让 `config.gg` 变成字符串/数字，
    破坏 `{"spreadsheet_id","sheet_name"}` 这个响应契约。
    """
    db = database.get_db()
    try:
        uid = get_uid()
        conf = {}
        for p in hd.PLATFORMS:
            entry = hd.get_platform_config(db, uid, p)
            if p == "tt":
                # tt 额外带 tables，但**保留 sheet_name**（= tables[0].sheet_name）——
                # 老前端只认 sheet_name，去掉它等于把它们打成空配置。
                # get_platform_config 自身的签名/返回值不动（gg/fb 与既有测试依赖它）。
                tables = hd.get_platform_tables(db, uid, "tt")
                entry["tables"] = tables
                if tables and tables[0]["sheet_name"]:
                    entry["sheet_name"] = tables[0]["sheet_name"]
            conf[p] = entry
    finally:
        db.close()
    return ok({"config": conf})


@huguan_dashboard_bp.route("/api/huguan/dashboard", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_config_save():
    """保存某平台的看板配置。表格 ID 接受裸 ID 或完整 URL。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    # 字段一律先 str() 兜底：给个数字或 null 不该炸成 500，按取不到值处理
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg、tt 或 fb", 400)

    from main import _parse_sheet_id
    ss_id = _parse_sheet_id(str(data.get("spreadsheet_id") or "").strip())
    sheet_name = str(data.get("sheet_name") or "").strip()

    # tables 可选：给了就走多表（仅 tt），没给走旧单表路径（gg/fb 与老前端）。
    raw_tables = data.get("tables")
    tables = None
    if raw_tables is not None:
        if platform != "tt":
            return err("多账户表只支持 tt", 400)
        if not isinstance(raw_tables, list) or not raw_tables:
            return err("tables 必须是非空数组", 400)
        tables = []
        seen_names, seen_sheets = set(), set()
        for t in raw_tables:
            if not isinstance(t, dict):
                return err("tables 的每一项必须是对象", 400)
            name = str(t.get("name") or "").strip()
            sheet = str(t.get("sheet_name") or "").strip()
            if not name:
                return err("每个户类型都需要「类型名」", 400)
            if not sheet:
                return err(f"户类型「{name}」缺少工作表名", 400)
            # 重名会让按钮和回写路由产生歧义；同一 worksheet 挂两个类型则回写会打两次架。
            if name in seen_names:
                return err(f"户类型「{name}」重复", 400)
            if sheet in seen_sheets:
                return err(f"工作表「{sheet}」被两个户类型共用", 400)
            seen_names.add(name)
            seen_sheets.add(sheet)
            # `columns` 可选的**手工覆盖** `{表头名: 字段key}`（设计 §4.2）。校验口径
            # 必须与 `resolve_column_map` 一致（可覆盖目标 = 真字段，不含空串哨兵），
            # 否则存进去的覆盖到读/写时会静默失效（resolve_column_map 当它是未采集）。
            cols = t.get("columns")
            if cols is not None:
                if not isinstance(cols, dict):
                    return err(f"户类型「{name}」的 columns 必须是对象", 400)
                seen_fields = set()
                for header, field in cols.items():
                    # 空串 = 用户显式「刻意不采集」（设计 §3.3）：合法，且**允许多列同时指定** ——
                    # 所以它既不查目录，也不进 seen_fields 去重。
                    if isinstance(field, str) and field == "":
                        continue
                    # 非字符串字段key 一律按未知处理（否则下面 `not in set` 对 list/dict
                    # 等不可哈希值会抛 TypeError → 500；本层契约是畸形输入 400 而非 500）。
                    if not isinstance(field, str) or field not in hd._TT_CATALOG_FIELDS:
                        return err(f"列「{header}」指向了未知字段「{field}」", 400)
                    if field in seen_fields:
                        return err(f"字段「{field}」被两列同时指定", 400)
                    seen_fields.add(field)
            item = {"name": name, "sheet_name": sheet}
            if isinstance(cols, dict) and cols:
                item["columns"] = cols
            tables.append(item)

    db = database.get_db()
    try:
        hd.save_config(db, get_uid(), platform, ss_id, sheet_name, tables=tables)
    finally:
        db.close()
    return ok({"message": "配置已保存"})


def _spreadsheet_id(db, uid: int, platform: str) -> str:
    """该户管该平台的表格 ID（未配置时空串）。

    单拎出来只为让「有没有配表」的校验与「逐表读」循环共用同一次取值口径，
    免得两处各自 `get_platform_config(...)` 后改一处漏一处。
    """
    return hd.get_platform_config(db, uid, platform)["spreadsheet_id"]


@huguan_dashboard_bp.route("/api/huguan/dashboard/sync", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_sync():
    """表 → 系统：先出差异报告（dry_run=true），户管确认后再落库。

    归属门禁（规格 §8.2）：表地址一律取自该户管自己的配置，请求体不接受表地址，
    因此不存在「对着别人的表发起同步」这条路。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg、tt 或 fb", 400)

    uid = get_uid()
    db = database.get_db()
    try:
        if not _spreadsheet_id(db, uid, platform):
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)

        tables = hd.get_platform_tables(db, uid, platform)
        tables = [t for t in tables if t["sheet_name"]]
        if not tables:
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])

        # 逐张表各读一次，再**合并成一个列表**进 build_diff —— 跨表去重、冲突检测、
        # 归属变更全部沿用既有逻辑，不另写一套。
        # 顺序即优先级：同一账户出现在两张表时，靠前的那张表先出现 ⇒ 现有
        # 「首次出现生效 + warning」规则自然让靠前的表胜出（规格 §4.3 跨表重复）。
        parsed_rows, unmatched_columns = [], []
        # {sheet_name: col_map}：逐表按表头解析出的映射，供下面的撤回快照按行回查
        # 自己那张表的列字母。工作表名在同一份配置里互不重复（POST 层校验），但仍用
        # setdefault 钉「首次出现」—— 与 `sheet_from` / `build_diff` 的去重口径一致。
        sheet_col_maps = {}
        spreadsheet_id = _spreadsheet_id(db, uid, platform)
        for t in tables:
            grid = gs.read_sheet_values(service, spreadsheet_id,
                                        t["sheet_name"], hd.READ_RANGE[platform])
            # tt 改按**表头名**解析列（户管每加一张表表头都不同，固定列字母会静默串列）；
            # gg/fb 仍走合成 map（`col_map=None` ⇒ `COLUMN_SPEC` 固定列，逐字节不变）。
            col_map = None
            if platform == "tt":
                headers = grid[0] if grid else []
                col_map, unmatched = hd.resolve_column_map(
                    headers, t.get("columns") or {})
                # 定位键认不出 ⇒ 整批拒同步（设计 §4.3 第 2 条）：没有账户ID 列，
                # 读出来的每一行都无法与系统里的账户对应，继续跑只会产出垃圾差异。
                if not (col_map.get("advertiser_id") or col_map.get("account_id")):
                    return err(f"工作表「{t['sheet_name']}」里找不到「账户ID」列，无法同步")
                if unmatched:
                    unmatched_columns.append({"sheet": t["sheet_name"],
                                              "headers": unmatched})
                sheet_col_maps.setdefault(t["sheet_name"], col_map)
            # 第 1 行是表头；不跳任何数据行（户管看板没有「是否解绑」列可用作跳过标记）
            for i, values in enumerate(grid[1:], start=2):
                parsed = hd.parse_row(values, platform, col_map)
                parsed["row"] = i
                # 多表后「第 N 行」会撞：带上表名，前端按表分组展示（规格 §4.3 的坑）
                parsed["_sheet"] = t["sheet_name"]
                if platform == "tt":
                    # 户类型的来源：这一行是从哪张表读出来的。表名即类型名。
                    # **无条件赋值**：`_collect_updates` 对 tt 无条件产出
                    # `_account_type`，缺键（→ 空串）会让「加白户」的既有账户被判成
                    # 「变了」⇒ 整行虚报「将更新」（见 `_same_as_existing`）。
                    parsed["_account_type"] = t["name"]
                parsed_rows.append(parsed)

        diff = hd.build_diff(db, parsed_rows, platform)
        # 未采集列逐表上报（设计 §4.3）：**空列表也要带** —— 前端据它的存在与否渲染
        # 「N 列未采集」提示。gg/fb 无表头映射 ⇒ 恒为空（行为与改动前一致）。
        diff["unmatched_columns"] = unmatched_columns

        # fail-safe：只有**显式布尔 False** 才落库。缺省 / true / null / "false"
        # (字符串) / 0 全部走只读 dry_run —— 少了这个 is not False，JSON null 会因
        # `None` 为假值而掉进落库分支，等于「传了个空值就把库改了」。
        if data.get("dry_run") is not False:
            return ok({"diff": diff})

        # confirmed 期望 {"create": [账户ID...], "update": [账户ID...], "owner": [账户ID...]}。
        # `or {}` 兜不住真值非 dict（[1,2] / "abc"）→ apply_diff 里 conf.get 炸 500；
        # 值不是数组同样炸（`2 not in 2` → TypeError）。两层都在这里挡住。
        confirmed = data.get("confirmed")
        if not isinstance(confirmed, dict):
            return err("confirmed 必须是对象", 400)
        for k in ("create", "update", "owner"):
            v = confirmed.get(k)
            if v is not None and not isinstance(v, list):
                return err(f"confirmed.{k} 必须是账户ID数组", 400)

        # 撤回快照（子项目 ③，spec §5.2）：`sheet_from` 是「归属变更会碰的那几列在
        # 表里的原值」，而表侧原值只有 `parse_row` 的结果里才有 ⇒ 由本层按账户ID 算好
        # 传进 apply_diff（`build_diff` 的返回值是前端契约，不许为它加键）。
        # **必须传**：不传则快照的 `sheet_back` 全空 ⇒ 表侧撤回静默失效（不报错、
        # 不抛异常）。键按 `account_id`、**不按行号** —— 行号在重新拉表后会整体位移。
        #
        # ⚠️ 必须是**首次出现生效**（与 `build_diff` 的去重口径逐字对齐）：同一账户同时
        # 出现在两张表时（多表后成为可能），`build_diff` 保留的是**靠前**那张表的行，
        # 而字典推导是「后出现覆盖」—— 两者方向相反 ⇒ 快照里的表侧原值会取自**后**
        # 那张表，撤回时把后表的运营名写进前表（串表）。用 setdefault 钉住首次。
        sheet_from = {}
        # 审查修复轮 1 · Finding 1：同时记下**每个账户来自哪张表**，作为快照的**新增键**
        # `sheet_back_sheets`（`{account_id: sheet_name}`）。`undo_sync` 的表侧回退据此
        # 按表分组写回 —— tt 多表下 `conf["sheet_name"]` 恒为空串，没有这个映射，表侧那步
        # 就静默不写（库侧照退、表侧不动，下次同步把撤回重做一遍）。
        # ⚠️ **不改 `sheet_back` 的既有形状**：下游 `undo_sync` 与多条用例都消费它。
        # 同样钉「首次出现生效」（与 `sheet_from` / `build_diff` 去重口径一致）：跨表重复
        # 时撤回必须写回**胜出**的那张表，不是后表。
        sheet_back_sheets = {}
        for p in parsed_rows:
            aid = p.get("account_id")
            if aid:
                # 表侧原值必须按**该行那张表**的表头映射取列 —— 与上面的读路径同源。
                # 若这里还用合成 map（固定列），tt 表列序不同时快照会记错列字母，
                # 撤回便把运营名写进别的列（本批次新引入的串列）。gg/fb 的
                # `sheet_col_maps` 为空 ⇒ 查到 None ⇒ 仍走合成 map，行为不变。
                cm = sheet_col_maps.get(p.get("_sheet"))
                sheet_from.setdefault(aid, hd._owner_sheet_from(p, platform, cm))
                sheet_back_sheets.setdefault(aid, hd._conf_text(p.get("_sheet")))
        # 账户 → 该账户所在表的 col_map（tt）。下面的归属/备注回写要按它取**列身份**
        # （目标列 + 分桶），与读路径/写表器**同源**。gg/fb 的 sheet_col_maps 为空 ⇒ 恒空
        # ⇒ `.get(...)` 得 None ⇒ 分桶与取列仍走固定字母（逐字节不变）。
        col_map_by_account = {aid: sheet_col_maps[sheet]
                              for aid, sheet in sheet_back_sheets.items()
                              if sheet in sheet_col_maps}
        # 逐表记下**定位键列**（新增键 `sheet_key_cols`）：撤回的表侧回退据此按
        # 「当初同步用的同一列」找行，且不受此后表头漂移影响；账户ID 经手工覆盖映射时，
        # 撤回若按别名重解析会认不出（本批终审 Important #1）。gg/fb 的 sheet_col_maps
        # 为空 ⇒ 该键也空 ⇒ `undo_sync` 回落既有解析（逐字节不变）。
        sheet_key_cols = {sheet: hd.key_col_of_col_map(cm, platform)
                          for sheet, cm in sheet_col_maps.items()}
        try:
            result = hd.apply_diff(db, diff, platform, confirmed, user_id=uid,
                                   collect_undo=True, sheet_from=sheet_from)
        except Exception:
            # apply_diff 抛异常（中途失败）⇒ 部分落库的库状态无法用一份残缺快照安全
            # 反向（spec §5.3）⇒ 作废快照后原样抛出，维持既有的 500 行为。
            _discard_undo(uid, platform, "sync")
            raise
        # apply_diff 正常返回 ⇒ 本次同步完整成功，快照才有撤回资格。
        # 先摘出 "undo"：它是内部凭据，不随响应体发给前端。
        undo = result.pop("undo")
        # 审查修复轮 1 · Finding 1：把「账户 → 来源表」映射并进快照（新增键，旧快照没有）。
        # 缺这个键时 `undo_sync` 回落到 `conf["sheet_name"]`（gg/fb 与旧单表 tt 的旧行为）。
        undo["sheet_back_sheets"] = sheet_back_sheets
        # 同批：逐表定位键列（新增键，旧快照没有 ⇒ 撤回回落既有解析）。
        undo["sheet_key_cols"] = sheet_key_cols
        hd.save_undo(db, uid, platform, "sync", undo)
        db.commit()

        # 规格 §8.3 步骤 8：落库后清缓存（账户写入了，代理/列表下拉必须立即刷新）。
        # 只放在路由层 —— 纯逻辑的 apply_diff 不该依赖 cache。
        _app_cache.clear_prefix("accounts:agents:")
        if any(item.get("pending_status")
               for item in diff.get("to_create", []) + diff.get("to_update", [])):
            # 本次可能新建了状态行（build_diff 只读，状态行是在 apply_diff 里建的）
            _app_cache.delete(f"accounts:statuses:{uid}")

        # 规格 §7.2 规则 3② + 规则 4：应用了归属变更的行，回写运营列并清空变更通道列
        applied = result.pop("applied_owner_rows", [])
        if applied:
            # 新归属名直接取 item["to"]（apply_diff 已经带上），不再靠行号反查 ——
            # 行号在重新拉表后可能已经位移到别人身上。
            # 目标列取**该账户那张表**的「接户运营」映射列（tt 表头顺序不同时不在固定
            # G）；该表没有这一列（未采集）⇒ 跳过，一个字不碰。
            rows = []
            for item in applied:
                cm = col_map_by_account.get(item["account_id"])
                col = (hd.owner_role_col(platform, "owner", cm) if cm is not None
                       else hd.OWNER_COL[platform])
                if col is None:
                    continue
                rows.append({"account_id": item["account_id"], "cells": {col: item["to"]}})
            # 定向回写一律经 `_write_background_tables`（沿用 master 侧的入口）。
            # 「按户类型落到各自 worksheet」由 target 的 rebuild 负责（见该函数），
            # gg / fb 只有一张表，退化回单次写入（行为不变）。
            # 传入 per-account col_map：分桶也要按**同一份**映射认列，否则映射列归属行
            # 会被当成「其余」→ 整行重建 → 冲掉户管在别的列的手工内容。
            _write_background_tables(db, uid, platform, rows, col_map_by_account)
            # 规则 3② 只对 GG 生效（2026-10-06 规格）：TT 的 L 列已是换绑记录，
            # 同步时清空会抹掉记录，且因读回按表覆盖会连带清掉系统里的值。
            # FB 同理、且更彻底：它根本没有通道列（OWNER_CHANNEL_COL 无 fb 键），
            # 对 fb 硬调 owner_channel_cells 会 KeyError —— 换成下面的 I 列定向写。
            if platform not in ("tt", "fb"):
                _write_background_tables(db, uid, platform,
                                         hd.owner_channel_cells(applied, platform, ""))
            if platform == "fb":
                # FB 没有通道列可清；改为把换绑记录定向写进 I 列。
                # 注意 _fb_acceptor_cells 的签名是 (rows, value)，value 是**同一个串**
                # 写给所有行 —— 而这里每行的串不同，所以不能用它，直接构造 rows。
                _write_background_tables(db, uid, platform, [
                    {"account_id": r["account_id"],
                     "cells": {"I": hd._fb_owner_transition(r.get("from", ""), r["to"])}}
                    for r in applied])

        # TT 备注首次对齐的两个写回（2026-10-06 规格）。与 applied_owner_rows 同法：
        # 先从 result 摘掉，再发起后台写回。三期起，备注列经 `huguan_dashboard` target
        # **整行重建**写回（不再只写单格）；备注是可写列、值已在 apply_diff 里落库，
        # 故整行重建写出的备注与这里的 r["value"] 一致。
        # cells 的列字母取**该账户那张表**的「产品信息」映射列（tt 表头顺序不同时不在
        # 固定 M）；该表没有这一列（未采集）⇒ 跳过，一个字不碰。
        m_writeback = result.pop("remark_m_writeback", [])
        if m_writeback:
            rows = []
            for r in m_writeback:
                cm = col_map_by_account.get(r["account_id"])
                col = (cm or {}).get("remark")
                if col is None:
                    continue
                rows.append({"account_id": r["account_id"], "cells": {col: r["value"]}})
            if rows:
                _write_background_tables(db, uid, platform, rows, col_map_by_account)
        for r in result.pop("remark_operator_push", []):
            hd.push_remark_to_operator_dashboard(r["owner_id"], r["account_id"], r["value"])
    finally:
        db.close()

    return ok({"result": result, "diff": diff})


@huguan_dashboard_bp.route("/api/huguan/dashboard/push", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_push():
    """系统 → 表：全量刷新。同步执行，返回实际写入行数。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg、tt 或 fb", 400)

    uid = get_uid()
    db = database.get_db()
    try:
        conf = {p: hd.get_platform_config(db, uid, p) for p in (platform,)}
        c = conf[platform]
        tables = hd.get_platform_tables(db, uid, platform)
        # gg/fb：判据里必须留着 `c["sheet_name"]` —— 「有表格ID 但工作表名为空」的半截
        # 配置是 POST 端点允许存下的（它不校验非空），改动前会在这里 400。
        # tt：工作表名在 `tables` 里（多表配置的 `conf["sheet_name"]` 恒为空串），
        # 沿用旧判据会把已配好的多表看板当成「未配置」。
        if (not c["spreadsheet_id"] or not tables
                or (platform != "tt" and not c["sheet_name"])):
            return err("请先在设置页配置户管看板的表格 ID 与工作表名", 400)

        import google_sheets_service as gs
        from main import _GOOGLE_SHEETS_CONFIG
        service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
        # collect / 快照 / 写表三者必须用**同一份**每表 col_map：tt 表头顺序不同时，
        # 固定列字母会把 cells 产出到错列、定位也会落错列 ⇒ 快照记的行集合与真正被写的
        # 行集合对不上（静默串列 + 整批落空）。gg/fb 走合成 map、零额外读，行为逐字节不变。
        col_maps_by_sheet = {
            t["sheet_name"]: hd.resolve_table_col_map(
                service, c["spreadsheet_id"], t["sheet_name"], platform,
                t.get("columns") or {})
            for t in tables
        }
        col_maps_by_type = {t["name"]: col_maps_by_sheet[t["sheet_name"]]
                            for t in tables}
        rows = hd.collect_rows_for_push(db, platform, col_maps_by_type=col_maps_by_type)
        groups, skipped = hd.group_rows_by_sheet(db, uid, platform, rows)
    finally:
        db.close()
    for name in skipped:
        log.warning("全量刷新跳过：户类型「%s」查不到工作表", name)

    # 撤回快照（子项目 ③，规格 §6.1）：**写表之前**先把「本次将写到的每个格」的原值
    # 读下来存好 —— 写完原值就没了。上面那条连接已在 finally 里关闭，不可复用；写表是
    # 网络调用，快照事务不能挂在它上面等（会长时间持写锁），故单独开一条短连接。
    # 读表失败就照常抛（与其它 Sheets 调用同口径）：此时快照没 commit ⇒ 一行都没写，
    # 上一份快照原封不动，仍可撤回上一次真正成功的同步。
    # 多表后快照是**每张表一份**（Task 7）：逐表读、逐表记，撤回才能逐表还原。
    undo_db = database.get_db()
    try:
        hd.save_undo(undo_db, uid, platform, "push",
                     hd.snapshot_push_targets(service, c, platform, groups,
                                              col_maps_by_sheet))
        undo_db.commit()
    finally:
        undo_db.close()

    total_updated, total_not_found = 0, []
    try:
        # 定位列必须与快照用的同一列（快照由 `snapshot_push_targets` 按该表 col_map 记）：
        # 写表按它找行，快照也按它找行，两边不一致时快照记的行集合与真正被写的行就对不上。
        # 写入器的默认值是 "C"（GG/TT 的账户ID列），但 **FB 的账户ID在 D 列**
        # （C 是「账户名称」）⇒ 不显式传就按错误的列定位、写空。tt 表头顺序不同时账户ID
        # 也不在 C 列 ⇒ 逐表取该表 col_map 的定位键（gg/fb 合成 map ⇒ 仍是 C / D）。
        for sheet_name, sheet_rows in groups:
            res = gs.update_rows_by_account_id(
                service, c["spreadsheet_id"], sheet_name, sheet_rows,
                key_col=hd.key_col_of_col_map(col_maps_by_sheet[sheet_name], platform))
            total_updated += res["updated"]
            total_not_found.extend(res["not_found"])
    except Exception:
        # 多表之后**不再整批原子**：`groups` 里可能「表 1 已写成功、表 2 抛异常」——
        # `update_rows_by_account_id` 只保证**单次** batchUpdate 原子，不是整轮循环原子。
        # 若无条件作废整份快照，已写成功的表的撤回入口会被**永久丢掉**（按钮消失），而那张
        # 表已经被改了，户管再也退不回去。故失败时**不再一律丢弃**，改用与成功路径同一口径：
        # 本次**一个字都没写**（表没变，撤回没有意义，spec §十 第 1 条）才作废；有写就**保留**
        # —— 对未写的表而言，后续撤回把旧值写回去是**幂等无操作**（写回原值），安全。
        # 原样抛出，维持既有的 500 行为。
        if not total_updated and not total_not_found:
            _discard_push_undo(uid, platform)
        raise

    if not total_updated and not total_not_found:
        # 一个字都没写 ⇒ 没有可撤回的东西，作废快照
        _discard_push_undo(uid, platform)

    return ok({"result": {"rows": len(rows), "updated": total_updated,
                          "not_found": total_not_found}})


def _discard_undo(uid: int, platform: str, direction: str) -> None:
    """作废某户管某平台某方向的撤回快照（空写 / 写失败时调用）。

    自己开连接：调用点的 `db` 要么已经关闭，要么正处在异常处理里，都不能复用。
    **绝不抛异常** —— 它在 except 分支里也会被调用，抛出去会顶掉原始的错误。
    """
    try:
        db = database.get_db()
        try:
            hd.delete_undo(db, uid, platform, direction)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log.warning("作废 %s 撤回快照失败: %s", direction, e)


def _discard_push_undo(uid: int, platform: str) -> None:
    """作废 push 快照（dashboard_push 的两个调用点保持原样）。"""
    _discard_undo(uid, platform, "push")


@huguan_dashboard_bp.route("/api/huguan/dashboard/undo", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_undo_status():
    """两个方向各有没有可撤的快照（spec §7）。

    响应形状 `{"success": true, "push": {...}|null, "sync": {...}|null}`：平铺，
    不套一层 "undo" —— 与 spec §7 的接口表、以及本任务 brief 的 Produces 契约行一致
    （brief Step 3 的示例代码写的是 `ok({"undo": out})`，那是计划快照里的笔误）。

    push 的 count 是「快照覆盖的行数」；sync 的 count 是快照里**要撤的项**之和
    （updates + owner_changes + created + created_statuses），与 `undo_sync` 的 `reverted`
    及前端要显示的规模口径一致（spec §八 的「影响 N 行」）。`sheet_back` 是表侧原值、
    不作为独立的「要撤的项」计数 —— 它的改动已经体现在其它几类里。

    created_at 取自快照行（「上一次：10-06 14:32」），行不存在或 payload 坏掉 → null，
    与「没有快照」同形。
    """
    platform = str(request.args.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg、tt 或 fb", 400)
    uid = get_uid()
    db = database.get_db()
    try:
        out = {}
        for direction in hd.UNDO_DIRECTIONS:
            meta = hd.load_undo_meta(db, uid, platform, direction)
            if not meta:
                out[direction] = None
            elif direction == "push":
                # 口径 = 快照覆盖的行数。多表后快照是「每张表一份」（Task 7）：
                # 直接取顶层 `cells` 会恒为 0（新形状没有这个键）⇒ 按钮亮着却显示
                # 「影响 0 行」。`push_undo_row_count` 两种形状都数得对。
                out[direction] = {"count": hd.push_undo_row_count(meta["payload"]),
                                  "created_at": meta["created_at"]}
            else:
                out[direction] = {"count": len(meta["payload"].get("updates", []))
                                           + len(meta["payload"].get("owner_changes", []))
                                           + len(meta["payload"].get("created", []))
                                           + len(meta["payload"].get("created_statuses", [])),
                                  "created_at": meta["created_at"]}
    finally:
        db.close()
    return ok(out)


@huguan_dashboard_bp.route("/api/huguan/dashboard/undo", methods=["POST"])
@jwt_required()
@huguan_required
def dashboard_undo_apply():
    """执行一次撤回（spec §7）。body `{"platform": …, "direction": …}`。

    只撤自己的：uid 一律取自 JWT，**请求体不接受 uid** —— 与「表地址一律取自自己的
    配置」同一口径（spec §7 / 2026-09-23 设计 §8.2）。

    `hd.undo_push` / `hd.undo_sync` **有意不吞异常**（写表失败、库事务失败都必须
    可见）。路由层在这里定错误码：500 + 中文说明，并落日志 —— 绝不「吞掉却不说」。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    if platform not in hd.PLATFORMS:
        return err("platform 必须是 gg、tt 或 fb", 400)
    direction = str(data.get("direction") or "").strip()
    if direction not in hd.UNDO_DIRECTIONS:
        return err("direction 必须是 push 或 sync", 400)

    uid = get_uid()
    try:
        if direction == "push":
            out = hd.undo_push(uid, platform)
        else:
            out = hd.undo_sync(uid, platform)
    except Exception:
        # 异常详情只落日志：**绝不**把原始异常文本内插进响应体 —— 可能含文件路径 /
        # SQL 片段等内部信息（既有 sync / push 端点靠 Flask 的泛化 500，不内插）。
        log.exception("撤回失败: platform=%s direction=%s", platform, direction)
        return err("撤回失败，请重试", 500)
    return ok(out)


def _owner_option_platform():
    """owner-options 要按哪个平台隔离。

    户管是 PLATFORM_SWITCH_ROLES 成员，其「有效平台」在 GG/TT 两份看板上就等于
    ?platform=（缺省 gg）—— 与 main._get_effective_platform 对户管的取值相同。
    本模块不 import main（main 注册本 blueprint，反向 import 会循环），故就地实现。

    ⚠️ 与 `_get_effective_platform` 有一处**有意**的差异：那个函数对 `?platform=fb`
    原样返回 'fb'（账户表随之切到 `fb_accounts`），本函数却回落 'gg' —— 因为本端点
    只服务 GG/TT 两份看板（`hd.PLATFORMS`），FB 没有看板表配置。**将来若给 FB 面板
    接上归属下拉，必须先扩展 `hd.PLATFORMS`**，否则会出现「列表是 FB 户、改归属
    下拉是 GG 人」的错配（`fb_routes` 的 reassign 只校验目标用户存在）。

    白名单的方向也要看清：白名单外的值必须回落 gg，而不是「不过滤」—— 后者会把
    FB/TT 的人漏回名单里，正好抵消本次隔离。
    """
    p = request.args.get("platform", "gg")
    return p if p in hd.PLATFORMS else "gg"


@huguan_dashboard_bp.route("/api/huguan/dashboard/owner-options", methods=["GET"])
@jwt_required()
@huguan_required
def dashboard_owner_options():
    """「户归属」下拉的数据源：可以直接把户转给他的**本平台**用户。

    与 `/api/platform/users` 的分工（父设计 §9.2 的更正）：
    - `/api/platform/users` 服务**筛选**（「归属人」筛选器）——只列该平台有未删除
      账户的人，选中一个名下无户的人必然得到空表，这种选项没有筛选价值；
    - 本端点服务**编辑**（改归属）——不要求名下已有账户，否则户管没法把户转给一个
      刚建号、还没分到户的新人。
    两者都保留，各有各的用途，不要互相替代。

    排除 `viewer`（只读角色，转给它在业务上无意义，用户已裁定）与 `hidden`
    （被停用、无法登录）。**按当前看板平台过滤**（`?platform=`，白名单外回落 gg）：
    GG 看板只列 gg 平台用户，TT 看板只列 tt 平台用户。

    但 `PLATFORM_SWITCH_ROLES`（developer / 户管）**无条件保留**，不随平台过滤 ——
    他们的 `users.platform` 是 `gg`，却能在 TT 看板建户：「新增账户 / 批量导入 /
    从表格同步」三条路径都把 `owner_id` 设成操作者自己，而 `require_platform` 对这两个
    角色直接放行。名单里没有他们，这些行的归属格就退化成禁用的「用户 #N」，且
    `TtAccountModal` 没有归属字段 ⇒ 户管没有任何 UI 能把这一列改回来（改归属正是该列
    存在的唯一目的）。存量 0 例，但 developer 点一次「同步」就会批量产生。
    GG 看板名单因此**逐字不变**（生产里这两个角色全是 `platform='gg'`，本就在名单内），
    只有 TT 看板多出他们 3 人。**别把这个 OR 去掉**。
    `developer` 在 GG 看板上靠的也是这个 OR（265 户挂他名下，缺了他那些行会退化成
    禁用态）—— 别在这里加「显式排除 developer」。

    本端点此前**不**按平台过滤，理由是「户管可能要把 GG 户转给只在 TT 有户的合法
    用户」。2026-09-28 用生产数据核销了这条理由（GG 275 户 / TT 403 户的归属人 100%
    是本平台用户，跨平台持有 0 例），而代价是 GG 看板混入 FB 6 人 + TT 8 人。见
    docs/superpowers/specs/2026-09-28-huguan-owner-options-platform-isolation-design.md。
    """
    platform = _owner_option_platform()
    # SQL 里只拼接「? 的个数」，角色名仍走参数位 —— 不是把用户输入拼进 SQL。
    switch_roles = ", ".join("?" for _ in PLATFORM_SWITCH_ROLES)
    db = database.get_db()
    try:
        rows = db.execute(
            "SELECT id, username, display_name, platform FROM users "
            "WHERE role NOT IN ('viewer', 'hidden') "
            f"AND (platform = ? OR role IN ({switch_roles})) "
            "ORDER BY display_name, username",
            (platform, *PLATFORM_SWITCH_ROLES)
        ).fetchall()
    finally:
        db.close()
    return ok({"users": [dict(r) for r in rows]})


def _write_background_tables(db, uid: int, platform: str, rows,
                             col_map_by_account=None) -> None:
    """定向写回（归属变更 / 备注 / 清空通道列）：登记 + 后台写 + 失败可查可重试。

    签名与四个调用点沿用 master 侧（它取代了旧的 `_write_background(conf, rows, platform)`）。

    ⚠️ **「按户类型落到各自 worksheet」不在这里做，而是下沉到 target 的 rebuild。**
    本函数只负责按**列身份**分派 target、并在请求线程登记日志。选表由
    `huguan_*_sync` 写表时用 `get_platform_tables` + 该账户的 `account_type` 现解析 ——
    重试路径同样需要它，放在那里才不会出现「首次写对、重试写错表」。

    为什么不能沿用 master 那版「先 group_rows_by_sheet、再逐组直调
    `_sync_sheets_background`」：那是直调、绕开 `run_write` ⇒ 回写失败退回
    「只落日志」，用户看不见也重试不了（正是三期要消灭的形态，且不会有测试变红）。

    四向分派（按 cells 的键身份，勿并成一组）：
      - 归属变更通道列（`OWNER_CHANNEL_COL`，GG=H / TT=L）→ `huguan_owner_channel`
        （该列被 `cells_for_row` 刻意排除，整行重建碰不到它）
      - FB 的接户运营列（I）→ `huguan_fb_acceptor`
        （fb 规格里该列 `writable=False`，同样被整行重建排除 —— 计划书曾误称
         该分支由整行重建覆盖，实为静默丢弃，T3 审查时回归修复）
      - 归属/运营列（`OWNER_COL`，gg/tt=G、fb=J）→ **也走 `huguan_owner_channel`**
        的**单格定向写**（`col_role="owner"`）。理由：它若并进整行重建，这一行
        其他列会被按 DB 值覆盖 —— 户管在表里改过、还没同步回来的内容就没了。
        这是与 master 语义对齐的修正（master 原先就是定向单格写；
        T3 把它并进了「其余」桶，T3 报告当时就标注「与 item["to"] 是否等价未验证」）。
      - 其余（TT 备注列 …）→ `huguan_dashboard`（整行重建）

    `col_map_by_account`（可选）是 `{account_id: 该账户所在表的 col_map}`：给了就按该表
    col_map 取**映射后**的通道/归属列来分桶（tt 表头顺序不同时角色列不在固定字母上 ——
    固定字母会把映射列归属行当「其余」→ 整行重建）；没给（None）⇒ 既有固定字母路径，
    逐字节不变（gg/fb 与直接调本函数的既有用例都走这条）。

    划分**按身份**逐行归桶，不得用 `r not in channel_rows` 这类写法 ——
    dict 的 `in` / `==` 是**按值比较**，两行内容相同会被一起划进/划出。
    这里的 `in` 是判 **cells 的键**，不是判行相等，故安全。

    `db` 由调用方传入（master 侧签名）。四个调用点都在 `db.commit()` **之后**才走到
    这里（`dashboard_sync` 的 commit 在函数中段），故 `run_write` 内部的
    `record_pending(db, …)` 不会撞上未提交的写事务 —— 那会等满 `timeout=30` 抛
    database is locked（见 tt_accounts_routes 里同族缺陷的修复）。
    """
    import sheet_write
    import routes.huguan_sheet_targets as _hst

    channel_rows, owner_rows, acceptor_rows, other_rows = [], [], [], []
    for r in rows:
        cells = r.get("cells") or {}
        cm = (col_map_by_account or {}).get(r.get("account_id"))
        if cm is not None:
            # 该表按表头映射：角色列也必须从**同一份** col_map 取（与写表器同一列），
            # 否则映射列归属行会被当成「其余」→ 整行重建 → 冲掉户管手工内容。
            # 该表没有这一列（未采集）⇒ 返回 None ⇒ 这一行不落进该桶。
            channel_col = hd.owner_role_col(platform, "channel", cm)
            owner_col = hd.owner_role_col(platform, "owner", cm)
        else:
            # gg/fb（或调用方未提供映射）：既有固定字母路径，逐字节不变。
            channel_col = hd.OWNER_CHANNEL_COL.get(platform)
            owner_col = hd.OWNER_COL.get(platform)
        if channel_col and channel_col in cells:
            channel_rows.append((r, channel_col))
        elif platform == "fb" and "I" in cells:
            acceptor_rows.append(r)
        elif owner_col and owner_col in cells:
            owner_rows.append((r, owner_col))
        else:
            other_rows.append(r)

    if other_rows:
        keys = [r["account_id"] for r in other_rows]
        _payload = {"platform": platform}
        sheet_write.run_write_many(
            db, user_id=uid, platform=platform, target="huguan_dashboard",
            business_keys=keys,
            sync_fn=_hst.huguan_dashboard_many_sync(uid, platform, keys),
            payload=_payload)
    if owner_rows:
        # 归属/运营列：**单格定向写**，与通道列同理 —— 若并进上面的整行重建，
        # 这一行的其他列会被按 DB 值覆盖，户管在表里改过、还没同步回来的内容就没了。
        # 值取 `apply_diff` 已落库的 `item["to"]`，随 payload 携带（重试可复现）。
        for r, owner_col in owner_rows:
            value = (r["cells"] or {}).get(owner_col, "")
            _payload = {"platform": platform, "mode": "owner",
                        "col_role": "owner", "value": value}
            sheet_write.run_write(
                db, user_id=uid, platform=platform, target="huguan_owner_channel",
                business_key=r["account_id"],
                sync_fn=sheet_write.build_sync("huguan_owner_channel", uid,
                                               r["account_id"], _payload),
                payload=_payload)
    if acceptor_rows:
        # FB 接户运营列：走自己的 target（该列被 cells_for_row 排除）。
        # 其 rebuild 从 `fb_accounts.acceptor` 读回 —— apply_diff 已把本次的
        # 「旧转新」串落库，故读回即本次要写的值。
        _payload = {"platform": platform}
        for r in acceptor_rows:
            sheet_write.run_write(
                db, user_id=uid, platform=platform, target="huguan_fb_acceptor",
                business_key=r["account_id"],
                sync_fn=sheet_write.build_sync("huguan_fb_acceptor", uid,
                                               r["account_id"], _payload),
                payload=_payload)
    if channel_rows:
        # 通道列：走自己的 target（该列被 cells_for_row 排除）
        for r, channel_col in channel_rows:
            value = (r["cells"] or {}).get(channel_col, "")
            _payload = {"platform": platform, "mode": "clear" if value == "" else "owner"}
            sheet_write.run_write(
                db, user_id=uid, platform=platform, target="huguan_owner_channel",
                business_key=r["account_id"],
                sync_fn=sheet_write.build_sync("huguan_owner_channel", uid,
                                               r["account_id"], _payload),
                payload=_payload)
