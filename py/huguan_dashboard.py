"""户管看板（Google Sheet）双向同步的纯逻辑层。

设计见 docs/superpowers/specs/2026-09-23-huguan-sheet-design.md。

本模块刻意不 import flask、不碰网络：列规格、双向映射、差异比对都放在这里，
单测可直接调用。真正的 Sheets I/O 在 google_sheets_service，HTTP 入口在
routes/huguan_dashboard_routes.py。
"""
import json
import logging

from google_sheets_service import col_index, read_sheet_values
from tt_master_data import ensure_agent, ensure_bc, strip_utc_prefix
from utils import chunk

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

# ---------- TT 表头映射（2026-10-09 设计 §4.1）----------
#
# 每项：(字段key, 中文名, 别名元组, 方向, 是否定位键, 空值是否跳过回写)
#   - 别名是「自动识别」的**全部**依据。目前只放**有实测依据**的叫法（`日期` 来自企业户表）；
#     以后遇到新叫法加一行即可 —— 因为配置里只存"手工覆盖"，别名表一改、所有表自动受益。
#   - 方向 "r" = 只读回（表→系统），永不回写。
#   - 空值跳过回写：见设计 §4.7，目前只有 landing_url（非必填的户管自有链接，不能被系统清掉）。
#   - 未列在这里的字段（如 fb 的 operator / asset_type_name）不参与 tt 的表头映射。
TT_FIELD_CATALOG = [
    ("acquired_date",     "入库时间", ("入库时间", "日期"), "rw", False, False),
    ("_dead_flag",        "是否回收", ("是否回收",),        "rw", False, False),
    ("advertiser_id",     "账户ID",   ("账户ID",),          "rw", True,  False),
    ("subject_name",      "主体名称", ("主体名称",),        "rw", False, False),
    ("name",              "账户名称", ("账户名称",),        "rw", False, False),
    ("bc_name",           "BC",       ("BC",),              "rw", False, False),
    ("country",           "国家",     ("国家",),            "rw", False, False),
    ("agent_name",        "所属渠道", ("所属渠道",),        "rw", False, False),
    ("owner_name",        "接户运营", ("接户运营",),        "rw", False, False),
    ("timezone",          "时区",     ("时区",),            "rw", False, False),
    ("landing_url",       "下户链接", ("下户链接",),        "rw", False, True),
    # 空串字段key = **认识这个表头、但刻意不采集**（legacy COLUMN_SPEC["tt"] 的 K「位置」
    # 就是 field=None 的同一语义）。它既不入映射、也不进 unmatched —— 否则加白户表每次
    # 同步都会报「1 列未采集 —— 位置」，把「未采集」这个信号淹成噪音。
    ("", "位置", ("位置",), "ignore", False, False),
    ("status_name",       "状态",     ("状态",),            "rw", False, False),
    ("consumption",       "消耗",     ("消耗",),            "rw", False, False),
    ("remark",            "产品信息", ("产品信息",),        "rw", False, False),
    ("owner_change_note", "换绑情况", ("换绑情况",),        "r",  False, False),
]

# TT 的定位键在**三个命名空间**里各有名字，勿混：
#   - 字段目录 / `resolve_column_map` 产出的 col_map 键名 → "advertiser_id"（TT_FIELD_CATALOG 里那个 key）
#   - **解析结果**（parse_row 的产出）的键名恒为 → TT_KEY_FIELD，即下面的 "account_id"
#   - 拼 SQL / 写库用的 DB 列名 → ACCOUNT_KEY_FIELD["tt"]（也是 "advertiser_id"）
# 注意：`col_map[TT_KEY_FIELD]` 对 tt 会 KeyError —— col_map 里没有 "account_id" 这个键。
TT_KEY_FIELD = "account_id"

# 别名 → 字段key（同名字段只取最先出现的那个别名条目）
_TT_ALIAS_TO_FIELD = {}
for _f, _label, _aliases, _dir, _key, _skip in TT_FIELD_CATALOG:
    for _a in _aliases:
        _TT_ALIAS_TO_FIELD.setdefault(_a, _f)


def resolve_column_map(headers: list, overrides: dict) -> tuple:
    """表头行 + 手工覆盖 → ({字段key: 列字母}, [未采集的表头名])。

    优先级：**手工覆盖 > 别名自动匹配 > 不采集**（设计 §4.2）。

    - 表头文本 strip() 后匹配；空表头跳过。
    - 多列命中同一字段 ⇒ 取**最左**那列。其余列**只有输给了别的名字**（真冲突，用户改指派
      就能解）才记入未采集；**同名表头的后一个不报** —— `columns` 按表头名存键，用户按名字
      指派也只能认领最左那列，报它＝每条同步报告都挂一行**永远解不掉**的未采集，把「未采集」
      这个信号训练成被忽略（与「位置」哨兵同款的永久噪音陷阱）。
    - 覆盖指向的字段key 非法 ⇒ 忽略该条并记入未采集（校验已在 HTTP 层拦，这里是纵深防御）。
    - **覆盖值可以是空串**：= 用户显式「刻意不采集」（设计 §3.3），占用该列但既不映射
      也不上报 —— 与目录里的空串哨兵同档，只是由覆盖手工指定。
    返回的未采集列表保留表头原文（strip 后），供前端逐条显示与指派。
    """
    # 只把**真正的字段**当合法覆盖目标：空串字段key 是「认识但刻意不采集」的哨兵
    # （见 TT_FIELD_CATALOG），不是字段，故不能作为覆盖**指向的字段**。
    # （覆盖**值**取空串是另一回事：那合法，见下方第一轮。）
    catalog_fields = {f for f, _l, _a, _d, _k, _s in TT_FIELD_CATALOG if f}
    out, unmatched, taken = {}, [], set()
    # 已被**成功认领**的表头名（跨两轮累计）：同名表头的后一个落选时不再报未采集。
    claimed_names = set()

    def _claim(field, col_letter):
        if field in out:
            return False
        out[field] = col_letter
        taken.add(col_letter)
        return True

    def _report(name):
        """记一条未采集 —— 只在「这个名字还没被认领过」且尚未报过时。

        报出来的都是**输给了别的名字**的真冲突（用户改指派就能解）；同名表头的后一个
        没输给任何**新**名字，报它只会产生永久噪音（见函数 docstring）。"""
        if name not in claimed_names and name not in unmatched:
            unmatched.append(name)

    # 第一轮：手工覆盖
    for i, raw in enumerate(headers):
        name = ("" if raw is None else str(raw)).strip()
        if not name or name not in (overrides or {}):
            continue
        field = (overrides or {})[name]
        # 覆盖值空串 = 用户显式「刻意不采集」（设计 §3.3）：占用该列，既不映射也不上报。
        # 与目录里空串哨兵（「位置」）同档 —— 等于「手工把任意列降级为 ignore」。
        # 必须在目录判定**之前**，因为空串本就不是目录里的字段。
        if field == "":
            taken.add(_col_letter(i))
            continue
        if field not in catalog_fields:
            _report(name)          # 指向的字段非法：报（这不是同名落选，用户能改）
            continue
        if _claim(field, _col_letter(i)):
            claimed_names.add(name)
        else:
            _report(name)

    # 第二轮：别名自动匹配（跳过已被覆盖占用的列）
    for i, raw in enumerate(headers):
        name = ("" if raw is None else str(raw)).strip()
        if not name or _col_letter(i) in taken:
            continue
        field = _TT_ALIAS_TO_FIELD.get(name)
        if field is None:
            # 完全不认识 ⇒ 报出来（设计 §4.3）；同一个未知表头只报一次
            if name not in (overrides or {}):
                _report(name)
            continue
        if field == "":
            # 认识、但刻意不采集（如「位置」）：既不映射也不上报
            taken.add(_col_letter(i))
            continue
        if _claim(field, _col_letter(i)):
            claimed_names.add(name)
        else:
            _report(name)
    return out, unmatched


def _col_letter(i: int) -> str:
    """0 → "A"。只支持到 ZZ（表头映射够用；超过 702 列的表不在本次范围）。"""
    if i < 0 or i > 701:
        raise ValueError(f"列索引超出 A:ZZ 范围: {i}")
    if i < 26:
        return chr(ord("A") + i)
    return chr(ord("A") + i // 26 - 1) + chr(ord("A") + i % 26)


def describe_header_columns(headers: list, overrides: dict,
                            col_map: dict, unmatched: list) -> list:
    """把一次表头解析的结果摊成「逐列一行」，供前端列映射 UI 显示（设计 §3.1）。

    每项：{"header": strip 后的表头原文, "field": 字段key | "" | None, "via": 四档,
           "alias_field": 字段key | "" | None}

      via = "override" 该表手工指派 / "alias" 别名自动认出 /
            "ignored" 认识但刻意不采集（目录哨兵「位置」，或覆盖值为空串）/
            "none" 该列没被采集到任何字段（完全不认识，**或同名表头的后一个**——同名只采集
                   最左那列，其余同名列不采集；这一档与 unmatched 无关，见下）
      field = "" 只与 "ignored" 同现；field = None 只与 "none" 同现。
      alias_field = **去掉手工覆盖后**这一列会被别名单独认成什么（同 field 的三值约定）：
        字段key 别名能认出 / "" 别名说刻意不采集（目录哨兵「位置」）/ None 别名不认识。
        前端「改回自动」的落点取它是**必要的**：override 行的 field 就是那条覆盖本身，
        若拿 field 当「自动值」，用户「改一下又改回原值」会被误判成「改回自动」而静默删掉覆盖（I1）。

    **不重新解析**：主结果全部从 resolve_column_map 的三个产出（col_map / unmatched / overrides）
    反推，避免第二套「认列」逻辑（那是本批最容易漂的地方）；alias_field 另调一次同一个
    `resolve_column_map(headers, {})`（＝「无覆盖」的解析），判据与主解析逐行同款
    （缺席 ⟺ 未识别 → None；在场且非空 ⟺ 别名档；在场且空 ⟺ 哨兵档）。
    空表头列不列出 —— 与 resolve_column_map 的跳过口径一致。
    """
    field_by_letter = {col: field for field, col in col_map.items()}
    ov = overrides or {}
    unknown = set(unmatched)
    # 别名单独（无覆盖）的解析：只回答「这列去掉覆盖会是什么」，不是第二套认列逻辑。
    alias_map, alias_unmatched = resolve_column_map(headers, {})
    alias_by_letter = {col: field for field, col in alias_map.items()}
    alias_unknown = set(alias_unmatched)

    def _alias_field(i: int, name: str):
        """这一列别名单独会认成什么：与主解析同款判据（不看 via）。"""
        f = alias_by_letter.get(_col_letter(i))
        if f is None:
            # 别名 col_map 里没有这一列：不认识 ⇒ None；否则是哨兵（刻意不采集）⇒ ""
            return None if name in alias_unknown else ""
        return f

    rows = []
    # 每个表头名**第一次出现**时的 alias_field：同名表头的后一个按**名字**共享它
    # （别名是按名字认列的，两个同名列的答案相同）。它的在场与否即「这一列是不是后一个」。
    first_alias_field = {}
    for i, raw in enumerate(headers):
        name = ("" if raw is None else str(raw)).strip()
        if not name:
            continue
        # 同名表头的**后一个**（落选列）：只采集最左那列 ⇒ 本列不采集、也不报未采集
        # （见 resolve_column_map 的同名口径）。这里**显式**落 none 档，且**不看 unmatched**
        # —— 它已不在 unmatched 里，若仍走下面的反推会被误判成 ignored（「（不采集）」这个假命题）。
        # alias_field 沿用同名第一列的值：前端「改回自动」要用它当落点，而别名按名字认列。
        if name in first_alias_field:
            rows.append({"header": name, "field": None, "via": "none",
                         "alias_field": first_alias_field[name]})
            continue
        alias_field = _alias_field(i, name)
        first_alias_field[name] = alias_field
        if name in ov and ov[name] == "":
            # 覆盖空串：认识但刻意不采集（占用该列，不在 col_map 里）
            rows.append({"header": name, "field": "", "via": "ignored",
                         "alias_field": alias_field})
            continue
        field = field_by_letter.get(_col_letter(i))
        if field is None:
            # 该列没进 col_map：要么根本不认识（在 unmatched 里），要么是目录哨兵那一档
            if name in unknown:
                rows.append({"header": name, "field": None, "via": "none",
                             "alias_field": alias_field})
            else:
                rows.append({"header": name, "field": "", "via": "ignored",
                             "alias_field": alias_field})
            continue
        via = "override" if ov.get(name) == field else "alias"
        rows.append({"header": name, "field": field, "via": via,
                     "alias_field": alias_field})
    return rows


def field_spec(platform: str) -> dict:
    """字段key → {writable, readable, key, skip_empty_write}。

    tt 来自 TT_FIELD_CATALOG；gg/fb 由既有 COLUMN_SPEC 推导（保证行为逐字不变）。
    `key` 对 gg/fb 恒为 `ACCOUNT_KEY_FIELD` 那个字段名。
    """
    spec = {}
    if platform == "tt":
        for f, _l, _a, d, is_key, skip in TT_FIELD_CATALOG:
            if not f:
                continue          # 「认识但刻意不采集」的条目不是字段
            spec[f] = {"writable": d == "rw", "readable": True,
                       "key": is_key, "skip_empty_write": skip}
        return spec
    key_field = ACCOUNT_KEY_FIELD[platform]
    for _col, _header, field, writable, readable in COLUMN_SPEC[platform]:
        if field is None:
            continue
        spec[field] = {"writable": writable, "readable": readable,
                       "key": field == key_field, "skip_empty_write": False}
    return spec


# 合法的**可手工覆盖字段**集合，供 POST 层校验 `tables[].columns`（设计 §4.2）。
# 必须与 `resolve_column_map` 认定的可覆盖目标**同一口径** —— 后者用
# `{f for f, ... in TT_FIELD_CATALOG if f}`（剔掉空串哨兵）。若这里直接
# `{f for f, *_ in TT_FIELD_CATALOG}`，就会把「认识但刻意不采集」的空串哨兵
# （中文名「位置」）**当成一个字段**混进来：用户把某列覆盖成这个字段会被放行，
# 而 `resolve_column_map` 里根本没有这个字段可认 —— 两边对「什么是字段」打架。
# 故取 `field_spec("tt")` 这个**终裁字段集**（哨兵已在函数内部排除）。
# 至于覆盖**值**取空串（= 刻意不采集），那是另一回事，合法且两层一致，不经本集合。
_TT_CATALOG_FIELDS = set(field_spec("tt"))


def spec_column_map(platform: str) -> dict:
    """由既有 COLUMN_SPEC 合成的 {字段key: 列字母}。**只用于 gg / fb** ——
    它们继续走固定列规格，结果与改动前逐字节相同（设计 §4.4 的等价性承诺）。"""
    return {field: col for col, _h, field, _w, _r in COLUMN_SPEC[platform] if field}


def tt_field_catalog() -> list:
    """TT 字段目录（供前端「列映射」下拉）：只含**真正的字段**，排除空串哨兵。

    与 POST 校验**同源**（都出自 TT_FIELD_CATALOG / field_spec("tt")）—— 否则会出现
    「下拉里能选、保存时被 400 拒」这种漂移。`key_col` 给前端把定位键标成必选；
    `direction == "r"` 的标「只读回」。
    """
    spec = field_spec("tt")
    return [{"key": f, "label": label, "direction": d,
             "writable": spec[f]["writable"], "readable": spec[f]["readable"],
             "key_col": spec[f]["key"]}
            for f, label, _aliases, d, _key, _skip in TT_FIELD_CATALOG if f]


def key_col_of_col_map(col_map: dict, platform: str) -> str:
    """从一张表的 col_map 里取**定位键**所在列字母。

    tt 的定位键在 col_map 里的字段名是 `advertiser_id`（`ACCOUNT_KEY_FIELD["tt"]`），
    而解析结果命名空间里叫 `account_id`（`TT_KEY_FIELD`）—— 两个名字都要查，
    否则漏掉整列。gg/fb 恒为 `account_id`（两名字同形）。
    两个都没有 ⇒ 抛错：**绝不退回默认列**，那会让整批静默写空。
    """
    col = col_map.get(TT_KEY_FIELD) or col_map.get(ACCOUNT_KEY_FIELD[platform])
    if not col:
        raise ValueError(f"平台 {platform} 的 col_map 里找不到定位键列: {col_map}")
    return col


def resolve_table_col_map(service, spreadsheet_id: str, sheet_name: str,
                          platform: str, overrides: dict | None = None) -> dict:
    """写表前解析**这张表**的 col_map（tt 读一次表头行）。

    - gg / fb：直接返回 `spec_column_map(platform)`，**零额外读**，行为与改动前
      逐字节相同（它们继续走固定列规格）。
    - tt：读一次表头行（`A1:ZZ1`）再 `resolve_column_map`。表头顺序与加白户不同
      （户管每加一张表表头都不同）⇒ 固定列字母会静默串列，必须按表头定位。
    - 定位键（账户ID）解析不到时**抛错** —— 绝不退回任何默认列：那会让整批
      静默写到错行（读路径同样拒同步，两侧口径一致）。

    `overrides` 是该表的手工覆盖 `{表头名: 字段key}`，必须与读路径
    （`dashboard_sync` 的 `t.get("columns")`）**同源** —— 否则同一次同步里读与写
    对「哪一列是定位键」的认识不一致，写就会落到错行。
    """
    if platform != "tt":
        return spec_column_map(platform)
    grid = read_sheet_values(service, spreadsheet_id, sheet_name, "A1:ZZ1")
    headers = grid[0] if grid else []
    col_map, _unmatched = resolve_column_map(headers, overrides or {})
    if not (col_map.get("advertiser_id") or col_map.get(TT_KEY_FIELD)):
        raise ValueError(f"工作表「{sheet_name}」里找不到「账户ID」列，无法写表")
    return col_map


KEY_COL = {"gg": "C", "tt": "C", "fb": "D"}
OWNER_COL = {"gg": "G", "tt": "G", "fb": "J"}
OWNER_CHANNEL_COL = {"gg": "H", "tt": "L"}      # 刻意不含 fb，见 spec §6.5
# tt 读 A:ZZ：表头映射后列数不定（户管每加一张表表头都不同，且「认识但刻意不采集」
# 的列也占位），固定 A:M 会读漏右侧列。gg/fb 仍走各自固定范围（逐字节不变）。
READ_RANGE = {"gg": "A:N", "tt": "A:ZZ", "fb": "A:Q"}

# 系统里「账户ID」列在两张表下的实际字段名
ACCOUNT_KEY_FIELD = {"gg": "account_id", "tt": "advertiser_id", "fb": "account_id"}

# 「归属相关的**单格定向写**」用到的列 —— 按**角色**取，不按调用点各自写死字母。
# 只有这一个解析点：后续「按表头识别 + 手工映射」改造（2026-10-08 另一方向）
# 落到这里换实现即可，写表目标与调用点都不用动。
_OWNER_ROLE_COL = {
    "channel": OWNER_CHANNEL_COL,   # 归属变更通道列（gg=H / tt=L）
    "owner": OWNER_COL,             # 归属/运营列（gg/tt=G），即 apply_diff 的 item["to"] 落点
}


# 角色 → 该角色在 col_map 里对应的字段名（按顺序取第一个命中的）。
# channel 有两个命名空间的名字：gg 合成 map 用 `_owner_channel`，tt 真实表头映射里
# 没有它、那一列叫 `owner_change_note`（与 owner_channel_cells 同款双命名）。
_OWNER_ROLE_FIELDS = {
    "channel": ("_owner_channel", "owner_change_note"),
    "owner": ("owner_name",),
}


def owner_role_col(platform: str, role: str, col_map: dict | None = None):
    """角色 → 户管看板上的列字母。未知角色/平台一律抛错 ——
    绝不静默落到别的列（写错列的后果是冲掉户管在表里的手工内容）。

    `col_map` 给了（这张表的 {字段key: 列字母}）就按其定位该角色应写的列；
    该表没有这一列（未采集）时返回 None，由调用方「一个字不碰」。没给（None）
    就走既有固定字母 —— 与改动前逐字节等价（gg/fb 与既有调用点零改动）。
    """
    table = _OWNER_ROLE_COL.get(role)
    if table is None:
        raise ValueError(f"未知的归属列角色: {role}")
    if col_map is not None:
        for field in _OWNER_ROLE_FIELDS[role]:
            if field in col_map:
                return col_map[field]
        return None
    col = table.get(platform)
    if not col:
        raise ValueError(f"平台 {platform} 没有角色 {role} 对应的列")
    return col


def _text(value) -> str:
    """账户ID 等长数字强制文本，避免 Sheets 按数字处理丢精度。

    对照 append_recycle（google_sheets_service.py:450）的既有做法。
    """
    s = "" if value is None else str(value).strip()
    if s and s.isdigit():
        return "'" + s
    return s


def cells_for_row(row: dict, platform: str, col_map: dict | None = None) -> dict:
    """系统 → 表：把一行账户数据转成 {列字母: 待写值}。

    `col_map` 是**这张表**的 {字段key: 列字母}；`None` ⇒ 用既有固定规格合成的
    （gg/fb 与既有调用点零改动，逐字节等价）。

    只产出「col_map 里映射到可写字段」的列，且**绝不产出归属变更通道列**
    （规格 §7.2 规则 2）—— 自动回写若顺手把户管刚填的重新分配清掉，那个变更就被静默吞了。
    **未采集的列一个字不碰**：它不在 col_map 里，自然不会出现在产出里（设计 §4.5）。
    """
    cm = spec_column_map(platform) if col_map is None else col_map
    spec = field_spec(platform)
    cells = {}
    for field, col in cm.items():
        s = spec.get(field)
        # 合成 map（`col_map=None` 的 None 路径）里账户ID 的字段key 恒为
        # **解析结果命名空间**（TT_KEY_FIELD == "account_id"），而 tt 的 `field_spec`
        # 用的是**字段目录命名**（ACCOUNT_KEY_FIELD["tt"] == "advertiser_id"）。
        # 两者对 tt 不一致，缺了这步会把 C 列（账户ID）整个漏掉 —— 只兜这一个字段，
        # 未知字段仍照旧跳过（绝不误落到别的列）。
        if s is None and field == TT_KEY_FIELD:
            s = spec.get(ACCOUNT_KEY_FIELD[platform])
        if not s or not s["writable"] or field == "_owner_channel":
            continue
        if field == "_dead_flag":
            value = "是" if (row.get("death_date") or "").strip() else ""
        elif s["key"]:
            # 定位键列按 spec 的 key 标志判定，**而非字段字面名** —— tt 真实 col_map 的
            # key 是 advertiser_id，而 row 用**解析结果**命名空间（account_id），字面比对
            # 会漏掉 `_text` 的 ' 前缀（长数字被 Sheets 按数值处理丢精度），并把该格写成空串。
            key_val = row.get(TT_KEY_FIELD)
            if key_val is None:
                key_val = row.get(ACCOUNT_KEY_FIELD[platform])
            value = _text("" if key_val is None else key_val)
        else:
            value = "" if row.get(field) is None else str(row.get(field)).strip()
        # 空值跳过回写（设计 §4.7）：非必填、由户管维护的字段，系统没填不代表要清掉表里那格。
        if not value and s["skip_empty_write"]:
            continue
        cells[col] = value
    return cells


def parse_row(values: list, platform: str, col_map: dict | None = None) -> dict:
    """表 → 系统：把一行原始单元格值转成 {字段名: 字符串值}。

    `col_map` 是**这张表**的 {字段key: 列字母}；`None` ⇒ 用既有固定规格合成的。

    不可读列（未映射列、派生列）一律不出现在结果里；`_owner_channel` 与 `_dead_flag`
    是合成字段，供上层判归属与生死。**未采集的列不产出任何字段**（设计 §4.4）。
    """
    cm = spec_column_map(platform) if col_map is None else col_map
    spec = field_spec(platform)
    out = {}
    for field, col in cm.items():
        s = spec.get(field)
        if not s or not s["readable"] or s["key"]:
            continue
        i = col_index(col)
        raw = values[i] if len(values) > i else ""
        out[field] = ("" if raw is None else str(raw)).strip()
    # 定位键单独取。统一键名恒为 "account_id"（GG 与 TT 一致），
    # 与 ACCOUNT_KEY_FIELD 里的 DB 列名是两个命名空间：消费解析结果用
    # account_id，拼 SQL / 写库用 ACCOUNT_KEY_FIELD[platform]，勿混用。
    # lstrip("'") 假定该值只带 _text() 加的那一个前缀。
    key_col = cm.get(TT_KEY_FIELD) or cm.get(ACCOUNT_KEY_FIELD[platform]) \
        or KEY_COL[platform]
    key_i = col_index(key_col)
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

# 默认户类型名（2026-10-08 规格 §5）。只在「新建账户却没指定类型」时兜底，
# 与 database.py 里 account_type 回填用的字面量必须一致。
TT_DEFAULT_ACCOUNT_TYPE = "加白户"


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


def get_platform_tables(db, user_id: int, platform: str) -> list:
    """取某平台的全部账户表：[{"name": 户类型名, "sheet_name": worksheet 名}]。

    - tt 配了 `tables` → 原样返回（保持配置顺序，顺序即按钮顺序与跨表去重的优先级）；
      每项**额外带 `columns`**（手工覆盖 `{表头名: 字段key}`，缺省 `{}`）—— 读路径
      （`dashboard_sync`）与写路径（`huguan_sheet_targets`）都按 `t.get("columns")`
      取它，前端也据此渲染，缺省 `{}` 让前端无需判 None。
    - tt 只有旧的 `sheet_name`（2026-10-08 之前的存量配置）→ 当成单条「加白户」。
      **只读不改写磁盘**：写回发生在用户下次点保存时，这样出问题能一眼看出是读的还是写的。
    - gg / fb → 单元素列表，`name` 为空串，**不带 `columns`**（columns 是 tt 专属概念，
      gg/fb 走固定列规格，载荷必须逐字节不变）。
    """
    entry = load_config(db, user_id).get(platform)
    if not isinstance(entry, dict):
        entry = {}
    if platform == "tt":
        tables = entry.get("tables")
        if isinstance(tables, list):
            out = []
            for t in tables:
                if not isinstance(t, dict):
                    continue
                name = _conf_text(t.get("name"))
                sheet_name = _conf_text(t.get("sheet_name"))
                if name and sheet_name:
                    # 原样透出配置里的覆盖，缺省 `{}`。**归一成 dict** 防手工改坏的配置
                    # （非 dict 真值会让下游 `t.get("columns") or {}` 原样透出、前端迭代炸）。
                    cols = t.get("columns")
                    out.append({"name": name, "sheet_name": sheet_name,
                                "columns": cols if isinstance(cols, dict) else {}})
            if out:
                return out
        legacy = _conf_text(entry.get("sheet_name"))
        return [{"name": TT_DEFAULT_ACCOUNT_TYPE, "sheet_name": legacy}] if legacy else []
    return [{"name": "", "sheet_name": _conf_text(entry.get("sheet_name"))}]


def _default_account_type(db, user_id: int) -> str:
    """新建账户未指定类型时的兜底：该用户自己配置里的第一条类型名，否则常量。

    取用户**自己的**配置而不是全局：类型清单本来就随户管看板配置私有存放（规格决策 2）。
    """
    tables = get_platform_tables(db, user_id, "tt")
    if tables and tables[0]["name"]:
        return tables[0]["name"]
    return TT_DEFAULT_ACCOUNT_TYPE


def save_config(db, user_id: int, platform: str, spreadsheet_id: str, sheet_name: str,
                *, tables=None) -> None:
    """写入某平台的看板配置，另一个平台的配置保持不变。

    `tables=None`（默认）→ 写旧格式 `{spreadsheet_id, sheet_name}`，行为与改动前**逐字节一致**
    （gg / fb 走这条路）。`tables` 非 None → 只允许 tt，写新格式
    `{spreadsheet_id, tables:[{name, sheet_name}]}`，并按类型名改名**级联**回填账户表。
    """
    if platform not in PLATFORMS:
        raise ValueError(f"不支持的平台: {platform}")
    if tables is not None and platform != "tt":
        raise ValueError(f"多账户表只支持 tt，收到: {platform}")
    conf = load_config(db, user_id)
    if tables is None:
        conf[platform] = {
            "spreadsheet_id": _conf_text(spreadsheet_id),
            "sheet_name": _conf_text(sheet_name),
        }
    else:
        clean = []
        for t in tables:
            name = _conf_text((t or {}).get("name"))
            sheet = _conf_text((t or {}).get("sheet_name"))
            if not name or not sheet:
                raise ValueError("每个户类型都需要「类型名」和「工作表名」")
            item = {"name": name, "sheet_name": sheet}
            # 手工覆盖 `columns`（`{表头名: 字段key}`）原样持久化：读路径
            # （`dashboard_sync`）与写路径（`huguan_sheet_targets`）都按同一份配置取它，
            # 少存一步就会让「保存后再读回」丢覆盖（读写对定位键认识不一致 → 落错列）。
            # 空 dict 不落盘（保持未配 columns 时的配置文本与改动前逐字节一致）。
            cols = (t or {}).get("columns")
            if isinstance(cols, dict) and cols:
                item["columns"] = cols
            clean.append(item)
        # 行身份 = worksheet 名，**不是下标**。下标在「删掉中间一行」时会整体错位：
        # 旧 [加白户→S1, 企业户→S2, 特批户→S3] → 新 [加白户→S1, 特批户→S3] 会把
        # 「企业户」的账户改名成「特批户」（静默并户），与规格 §5「删除类型保留原值」冲突。
        # worksheet 名可以作为身份，是因为路由层校验了同一次保存内它互不重复
        # （见 routes/huguan_dashboard_routes.py 的 POST 校验）。
        # 已知边界：用户同时改「类型名」和「worksheet」时会被当成删+增、不级联，
        # 该类型账户保留旧名（孤儿）。这是刻意接受的取舍 —— 宁可留孤儿，不可错并户。
        old_by_sheet = {t["sheet_name"]: t["name"] for t in get_platform_tables(db, user_id, "tt")}
        for new_t in clean:
            old_name = old_by_sheet.get(new_t["sheet_name"])
            if old_name and old_name != new_t["name"]:
                # 类型名字符串即标识（规格 §5）：不级联的话，存量账户会从按钮里凭空消失。
                db.execute("UPDATE tt_accounts SET account_type=? WHERE account_type=?",
                           (new_t["name"], old_name))
        conf[platform] = {
            "spreadsheet_id": _conf_text(spreadsheet_id),
            "tables": clean,
        }
    db.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)",
               (CONFIG_KEY.format(uid=user_id), json.dumps(conf, ensure_ascii=False)))
    db.commit()


def group_rows_by_sheet(db, user_id: int, platform: str, rows: list):
    """把待写行按「户类型 → worksheet」分组。

    返回 `(groups, skipped)`：`groups` 是 `[(sheet_name, rows)]`（按配置顺序），
    `skipped` 是「在配置里查不到工作表的类型名」列表。

    查不到就**跳过**，绝不退回写第一张表 —— 那正是多表之后要消除的「填错表」。
    gg/fb 的类型恒为空串且配置里恰好有一个空名条目 ⇒ 只有一组，与改动前等价。
    tt 的空类型（账户行没类型 / 查不到）**跳过**，不退回第一张表：宁可漏写
    （日志里看得见）也不能写错 —— 写错表会把甲类账户的内容覆盖进乙类的 worksheet。
    """
    tables = get_platform_tables(db, user_id, platform)
    buckets = {}
    for r in rows:
        buckets.setdefault(r.get("account_type") or "", []).append(r)
    groups, skipped = [], []
    for t in tables:
        name = t["name"]
        if name in buckets:
            groups.append((t["sheet_name"], buckets.pop(name)))
    for leftover, leftover_rows in buckets.items():
        if leftover:
            skipped.append(leftover)
        elif platform != "tt" and tables:
            # gg/fb 的类型恒为空串，其配置条目也恰好是空名 ⇒ 正常已被上面的循环取走。
            # 保留这一支只为兼容「配置条目缺失」这种历史态，行为与改动前等价。
            groups.append((tables[0]["sheet_name"], leftover_rows))
        else:
            # tt：类型为空 ⇒ 查不到对应工作表。**绝不退回写第一张表** —— 那正是本设计
            # 要消除的「填错表」。宁可漏写（日志里看得见）也不能写错：写错表会把甲类
            # 账户的内容覆盖进乙类的 worksheet，而漏写只是少刷新几行。
            skipped.append(leftover or "（未设置户类型）")
    return groups, skipped


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


def load_undo_meta(db, user_id: int, platform: str, direction: str) -> dict | None:
    """读某方向快照的 payload 与 created_at；无行 / 坏 payload 都是 None。

    `load_undo` 的契约是「返回 payload 本身」（Task 1 已交付，测试按此断言），
    改它会把契约撑破；而 GET 状态端点要报「上一次：10-06 14:32」（spec §7 / §八），
    需要 created_at。故单开本函数，两类信息一起给。

    坏 payload 与「无快照」同形（都 None），与 `load_undo` 的短路口径一致 ——
    撤回入口据此禁用，不会拿一份读不懂的快照去写表。
    """
    row = db.execute("SELECT payload, created_at FROM huguan_sync_undo "
                     "WHERE user_id=? AND platform=? AND direction=?",
                     (user_id, platform, direction)).fetchone()
    if not row or not row["payload"]:
        return None
    try:
        loaded = json.loads(row["payload"])
    except Exception:
        return None
    if not isinstance(loaded, dict):
        return None
    return {"payload": loaded, "created_at": row["created_at"]}


def resolve_named_id(db, sql: str, params: tuple = ()) -> int | None:
    """按名称查唯一主键。命中 0 条或 ≥2 条都返回 None（规格 §8.4）。

    重名时不猜 —— 猜错就是把账户挂到了错误的 MCC / BC / 渠道上。
    """
    rows = db.execute(sql, params).fetchall()
    return rows[0]["id"] if len(rows) == 1 else None


def _named_hits(db, platform: str, field: str, value: str) -> int:
    """该名称命中了**几条**（0 / 1 / ≥2）。只为区分「没有」与「歧义」，不参与取值。

    `resolve_named_id` 对 0 条与 ≥2 条都返回 None，两者的处理却**相反**：
    0 条 = 系统里没有 ⇒ 产 pending、落库补建；≥2 条 = 歧义 ⇒ 仍警告跳过。
    本函数只数命中行数，**不改变 `resolve_named_id` 的取值口径**。
    """
    if field == "bc_name":
        sql = _SQL_BC
    elif field == "agent_name":
        sql = _AGENT_SQL[platform]
        if sql is None:
            # fb 的「所属渠道」不在 agents 表里（走 fb_channels）⇒ 不走本 pending 分支
            return 0
    else:
        return 0
    return len(db.execute(sql, (value,)).fetchall())


def _region_exists(db, country: str) -> bool:
    """`regions` 里是否已有该国家（tt 命名空间）。只查库、不写。"""
    return db.execute("SELECT 1 FROM regions WHERE name=? AND platform='tt'",
                      (country,)).fetchone() is not None


def _ensure_region(db, name: str, timezone: str) -> None:
    """国家 → 时区：缺则补建（**已存在绝不覆盖** —— 字典是别的功能在用的权威值）。

    `regions` 有 UNIQUE(name, platform)：同一国家的多行同步会各自产一份 pending、
    落到这里各调一次 —— 少了 `_region_exists` 门，第二次 INSERT 直接撞唯一约束、
    把该行整条记进 errors。门同时兑现设计 §4.2「绝不覆盖已存在的国家」。

    name 或 timezone 为空一律 no-op：建出「有国家没时区」的残项会被后续
    `_region_exists` 当成已有、再也补不上（build_diff 的门同样要求两者都有）。
    """
    name = _conf_text(name)
    timezone = _conf_text(timezone)
    if not name or not timezone:
        return
    if _region_exists(db, name):
        return
    db.execute("INSERT INTO regions(name, timezone, platform) VALUES(?,?,'tt')",
               (name, timezone))


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
           "owner_change_note", "subject_name", "landing_url"),
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


# 按平台给出「归属变更会写到表侧的那几列」，用于把表里原值记进撤回快照。
# **必须按平台分流**（规格 §3.3）：
#   GG：运营列 G + 通道列 H（同步后 H 被清空）
#   TT：只有接户运营列 G（L「换绑情况」只读回不回写，没有通道列）
#   FB：在用运营列 J + 接户运营列 I（同步后 I 被写成「{旧}转{新}」）
# 与路由收尾回写（routes/huguan_dashboard_routes.py 的 dashboard_sync）实际会写的
# 列一一对应 —— 多记一列会让撤回写脏表侧，少记一列则漏撤回。
_OWNER_SHEET_COLS = {"gg": ("G", "H"), "tt": ("G",), "fb": ("J", "I")}


def _owner_sheet_from(parsed: dict, platform: str, col_map: dict | None = None) -> dict:
    """取「归属变更会碰的那几列」在**表里的原值**：{列字母: 单元格值}。

    撤回时要用它把表侧盖回原样（规格 §5.2 的 `sheet_back`）。记的是**真实原值**，
    不是「回退成旧归属名」—— 后者对 GG 的通道列是错的：通道列在同步前存的是户管
    填的**新**归属名，不是旧归属名。记原值对三个平台一致正确。

    值取自 `parse_row` 的结果：这几列在 `COLUMN_SPEC` 里都是 `readable=True`
    （GG 的 G/H = owner_name/_owner_channel，TT 的 G = owner_name，
    FB 的 J/I = owner_name/acceptor），解析结果里必然有对应字段，无需回读原始 values。

    `col_map` 是**这张表**的 {字段key: 列字母}；`None` ⇒ 用既有固定规格合成的
    （gg/fb 与既有调用点零改动，逐字节等价）。给了 col_map 时方向翻转：字段集合
    仍由既有来源（`_OWNER_SHEET_COLS` × `COLUMN_SPEC`）推导，但列字母改为到这张
    表的映射里查该字段的落点；**这张表没有该列（未采集）⇒ 跳过，一个字不碰**。
    """
    cm = spec_column_map(platform) if col_map is None else col_map
    field_by_col = {c[0]: c[2] for c in COLUMN_SPEC[platform]}
    out = {}
    for col in _OWNER_SHEET_COLS[platform]:
        field = field_by_col.get(col)
        if not field:
            continue
        target = cm.get(field)
        if target is None:
            continue
        out[target] = "" if parsed.get(field) is None else str(parsed.get(field))
    return out


def build_diff(db, parsed_rows: list, platform: str) -> dict:
    """表 → 系统 的逐行比对，产出五类差异（规格 §8.3）。

    parsed_rows: [{"row": 表里行号, **parse_row(...)}]
    每个产出项都带 "row"，供前端回传确认。
    """
    key_field = ACCOUNT_KEY_FIELD[platform]
    sheet_rows = len(parsed_rows)   # 表里数据行总数（**去重前**），供 summary 用

    # 多表同步后「第 N 行」在两张表里会撞（规格 §4.3 的坑）：每个产出项都带表名，
    # 前端按表分组展示，否则户管会去改错表。
    def _sheet_of(p):
        return _conf_text(p.get("_sheet"))

    # 四个产出列表必须在去重循环**之前**建好：去重本身会往 warnings 里塞一条
    to_create, to_update, owner_changes, to_skip = [], [], [], []
    warnings = []
    # 系统字典里缺的项（tt）：逐行收集（**每行都收**，不只收进 to_create/to_update 的行）——
    # 否则「已存账户、表里只写了个系统没有的 BC」这行（无字段变更、不进 to_update）
    # 的 pending 会丢失，违反设计 §4.3「dry_run 必须在差异报告里看得见」。
    pending_rows = []
    # 「孤儿行」：既存的账户，其表侧唯一变化是「系统字典里缺的 BC/渠道/国家」——
    # 其余列与库里逐字相同 ⇒ `changed` 为空、也没有待建状态 ⇒ **不进 to_update**，
    # apply_diff 的 create/update 两个分支都够不到它。但它的 pending 已被上面收进聚合
    # （dry_run 报告里看得见）—— 若不在这里单独记一份「按账户」的清单交给 apply_diff
    # 收尾补建并挂链，就会「报告说将新增、落库一个都不建」。**键名 `pending_master_rows`
    # 与展示键 `pending_master` 是两回事**：后者是给前端渲染的聚合，这里是内部载荷。
    pending_master_rows = []

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
            warnings.append({"row": p.get("row"), "sheet": _sheet_of(p),
                             "message": f"账户ID「{aid}」已在第 {seen_rows[aid]} 行出现，本行跳过"})
            continue
        seen_rows[aid] = p.get("row")
        deduped.append(p)
    parsed_rows = deduped

    ids = [p.get("account_id") for p in parsed_rows if p.get("account_id")]

    existing_map = {}
    if ids:
        table = _TABLE_FOR_PLATFORM[platform]
        # 分块绑定：上万账户时一次 IN 会超 SQLite 的 32766 变量上限。
        for part in chunk(ids):
            marks = ",".join("?" for _ in part)
            for r in db.execute(
                f"""SELECT a.*, u.display_name AS owner_display, u.username AS owner_username
                    FROM {table} a LEFT JOIN users u ON a.owner_id = u.id
                    WHERE a.{key_field} IN ({marks})""",
                tuple(part),
            ).fetchall():
                existing_map[r[key_field]] = dict(r)

    for p in parsed_rows:
        row_no = p.get("row")
        aid = p.get("account_id", "")
        if not aid:
            warnings.append({"row": row_no, "sheet": _sheet_of(p),
                             "message": "账户ID为空，跳过"})
            continue

        want_owner_name = effective_owner_name(p, platform)
        want_owner_id = None
        if want_owner_name:
            want_owner_id = resolve_owner_id(db, want_owner_name)
            if want_owner_id is None:
                warnings.append({"row": row_no, "sheet": _sheet_of(p),
                                 "message": f"运营「{want_owner_name}」无法识别，已跳过归属变更"})

        existing = existing_map.get(aid)
        if existing is None:
            db_values = _collect_updates(db, platform, p, want_owner_id, row_no, warnings,
                                         create_missing=False)
            # 只摘 `_pending_status` / `_pending_master` 这两个合成键（分别由报告层的
            # `pending_status` 与 `pending_master` 承载）。
            # `_is_dead` **故意保留在 db_values 里**，别顺手一起 pop —— apply_diff 会
            # 自己 pop 它去同步 death_date；在这里摘掉会让新建账户的死亡标记静默丢失。
            pending = db_values.pop("_pending_status", None)
            # 系统字典里缺的项（tt）：apply_diff 落库前才补建/挂链（build_diff 只读）。
            # **必须摘掉**：留着会穿过 `INSERT INTO ...(_pending_master)` 直接报错。
            pending_master = db_values.pop("_pending_master", None)
            pending_rows.extend(pending_master or [])
            to_create.append({
                "row": row_no,
                "sheet": _sheet_of(p),
                "account_id": aid,
                "owner_id": want_owner_id,
                "owner_name": want_owner_name,
                # 键名刻意不叫 "cells"：本模块里 "cells" 一律指「表列字母 → 单元格值」
                # （Task 4 的 update_rows_by_account_id 契约），这里装的是
                # 「数据库列名 → 值」，供 apply_diff 拼 INSERT。两者同名会被误用。
                "db_values": db_values,
                # 系统里还没有的状态名；apply_diff 落库前才 INSERT（build_diff 只读）
                "pending_status": pending,
                "pending_master": pending_master,
            })
            continue

        if existing.get("deleted_at"):
            to_skip.append({"row": row_no, "sheet": _sheet_of(p), "account_id": aid,
                            "reason": "系统中已逻辑删除，不动"})
            continue

        cur_owner = existing.get("owner_id")
        if want_owner_id is not None and int(cur_owner or 0) != int(want_owner_id):
            owner_changes.append({
                "row": row_no,
                "sheet": _sheet_of(p),
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
        # 系统字典里缺的项（tt）：**必须在 `changed = {...}` 推导之前摘掉**，
        # 否则它会穿过 `sets = [f"{k}=?" ...]` 拼出 `UPDATE tt_accounts SET _pending_master=?`
        # 直接报错（`_sheet_name` 踩过同款）。apply_diff 落库时才据它补建/挂链。
        pending_master = fields.pop("_pending_master", None)
        pending_rows.extend(pending_master or [])
        # `_sheet_name` 是 tt 合成键（表里「账户名称」，只给**新建**账户决定 name）。
        # **必须在这里摘掉**：update 路径不消费它，留着会（a）被 `_same_as_existing`
        # 拿去比库里的列 → 恒判「变了」→ 每行虚报「将更新」；（b）穿过下面
        # `sets = [f"{k}=?" ...]` 拼出 `UPDATE tt_accounts SET _sheet_name=?` 直接报错。
        fields.pop("_sheet_name", None)
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
            to_update.append({"row": row_no, "sheet": _sheet_of(p), "account_id": aid,
                              "existing_id": existing["id"], "fields": changed,
                              "pending_status": pending,
                              "pending_master": pending_master,
                              # apply_diff 建缺失状态行时用它记 owner（谁先建的）
                              "scope_owner_id": scope_owner,
                              # 新值为空串的文本列：清空是不可逆的，必须让前端显式标注
                              "clears": _blank_columns(platform, changed)})
        elif pending_master:
            # 孤儿行（见上方 `pending_master_rows` 的定义）：既不新建也不更新，
            # 但字典里缺了它要的项。单列一份交 apply_diff 收尾补建 + 定向挂链。
            pending_master_rows.append({
                "row": row_no, "sheet": _sheet_of(p), "account_id": aid,
                "existing_id": existing["id"], "scope_owner_id": scope_owner,
                "pending_master": pending_master})

    # 聚合「将新增的字典项」（设计 §4.3）：按 (kind, name) 去重、`rows` 计数、
    # 时区取**首次出现**（与既有「首次出现生效」惯例一致）。dry_run 与落库两条
    # 返回路径共用同一份 diff ⇒ 报告层据此渲染「将新增的字典项」一节。
    agg, order = {}, []
    for x in pending_rows:
        k = (x["kind"], x["name"])
        if k not in agg:
            agg[k] = {"kind": x["kind"], "name": x["name"],
                      "timezone": x.get("timezone"), "rows": 0}
            order.append(k)
        agg[k]["rows"] += 1

    return {
        "to_create": to_create,
        "to_update": to_update,
        "owner_changes": owner_changes,
        "to_skip": to_skip,
        "warnings": warnings,
        "pending_master": [agg[k] for k in order],
        # 内部载荷：孤儿行的「账户 → 缺失字典项」。apply_diff 收尾据此补建并挂链。
        # 前端渲染的展示键是上面的 `pending_master`（聚合），本键不参与渲染。
        "pending_master_rows": pending_master_rows,
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

    **但「该列被采集、且值为空」与「该列根本没被采集」是两回事**（本轮修复）：
    下面文本循环的门是 `if f not in p: continue` —— 判的是**这一列在不在该表的
    col_map 里**（`p` 是 `parse_row` 的产出，只有被映射的列才落键），**不是**值是否
    为空。二者混淆的后果是静默数据丢失：多表配置（企业户 + 加白户）里，加白户表没有
    「主体名称/下户链接」列 ⇒ 早先 `p.get(f)` 得 `None` → `""` → 被当成「表里空着」，
    于是同步加白户会把企业户先前落库的 `subject_name`/`landing_url` **无条件清掉**，
    违反本批次全局约束「未采集的列一个字不碰（读不取、写不写）」。所以：**被采集的
    列空着照样产出空串**（上面那段口径不变），**未采集的列一个字段都不产出**。

    产出里可能带五个**下划线开头的合成键**（不是数据库列，调用方必须先摘掉）：
    `_is_dead` 死亡标记、`_pending_status` 系统里还没有的状态名、
    `_primary_bm_name`（FB 专有，表里填的主 BM 名）、
    `_account_type`（TT 专有，由调用方按「这一行读自哪张表」注入的户类型）、
    `_sheet_name`（TT 专有，表里「账户名称」列的值，供新建账户决定 `name`）、
    `_pending_master`（系统字典里缺的 BC/渠道/国家时区，dry_run 只产不写，落库才补建）。

    create_missing 由 build_diff 传 False（dry_run 只读），落库阶段才用默认 True。
    """
    out = {}
    # 系统字典里缺的项（BC / 渠道 / 国家时区），**只产不写**：dry_run 只读，
    # 落库阶段（apply_diff）才据它补建。每行一份，见文件末尾 region 判定。
    pending_master = []
    for f in _PLAIN_TEXT_FIELDS[platform]:
        # **门在「这一列有没有被该表采集」上，不在值上**：`p` 是 `parse_row` 的产出，
        # `f in p` ⇔ 该表的 col_map 映射了这列。未采集的列（如加白户表没有
        # 主体名称/下户链接）不产出字段 ⇒ 不参与比对、不进 clears、不被清库
        #（全局约束「未采集的列一个字不碰」）。与下面的值判空**正交**：被采集但空着的
        # 列仍产出空串并照常清库。gg/fb 的合成 map 覆盖全部文本列 ⇒ 恒 `f in p` ⇒ 无操作。
        if f not in p:
            continue
        # `_conf_text` 兜底是因为 p 未必全是 str（同 `_conf_text` 的既有理由）
        out[f] = _conf_text(p[f])
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
            # 「查不到」与「重名多条」在 resolve_named_id 里都返回 None（0 或 ≥2 ⇒ 不猜）。
            # 但两者处理**相反**：0 条 = 系统里没有 ⇒ dry_run 产 pending、落库补建；
            # ≥2 条 = 歧义 ⇒ 仍然只警告跳过（多建一条只会更乱）。
            # **只 tt 产**（设计 §4.4）：本功能只落 tt 字典，gg/fb 行为逐字不变
            # （gg 的 0 命中仍记警告；fb 的 agent 查名 SQL 为 None、_named_hits 恒 0）。
            hits = _named_hits(db, platform, f, value)
            if hits == 0 and platform == "tt" and f in ("bc_name", "agent_name"):
                pending_master.append({"kind": "bc" if f == "bc_name" else "agent",
                                       "name": value, "timezone": None})
                continue
            warnings.append({"row": row_no, "sheet": _conf_text(p.get("_sheet")),
                             "message": f"{f}「{value}」无法唯一匹配，已跳过该列"})
            continue
        out[_target_column(platform, f)] = resolved
    # 只有该表**真的采集了**死亡判定列（是否回收 `_dead_flag` / 状态 `status_name`）才
    # 产出 `_is_dead`。两个判定列都未采集时 `is_dead(p)` 恒返回 False（见 `is_dead`），
    # 无条件产出会让「缺这两列的 tt 表」同步一个库里已死账户时判成「变了」→ 确认后
    # `apply_diff` 清空 `death_date`（**静默复活**），违反「未采集的列一个字不碰」——
    # 与 Task 7 文本列门控**同族**（这里载体是合成键而非文本列）。
    # gg/fb 的合成 map 恒含这两列（gg：B `_dead_flag` + K `status_name`；fb：O
    # `status_name`）⇒ 门控恒真、逐字节不变（见 `spec_column_map`）。
    # 缺键时的消费端已保证「什么都不做」：create 分支 `pop(..., False)` 默认存活、
    # update 分支 `pop(..., None)` 直接跳过死亡处理。
    if "_dead_flag" in p or "status_name" in p:
        out["_is_dead"] = is_dead(p)
    # 户类型的传递链第 ② 环（规格 §4.3）：`account_type` 不是表里的列，
    # 所以走合成键，与 `_primary_bm_name` 同形 —— 由调用方（同步路由）按
    # 「这一行是从哪张表读出来的」注入，这里原样搬运。
    # **不放进 _PLAIN_TEXT_FIELDS**：那个集合参与「文本列空着＝清空系统该列」的口径。
    if platform == "tt":
        out["_account_type"] = _conf_text(p.get("_account_type"))
        # 设计 §4.6：表里「账户名称」列（字段 key 恒为 "name"）的值搬成合成键。
        # **不能直接把 `name` 放进 `_PLAIN_TEXT_FIELDS["tt"]`** —— 那个集合参与
        # 「文本列空着＝清空系统该列」的口径，会让每次同步都把已存账户的 `name`
        # 按表覆盖（乃至用空值清掉）。本批次只让它在**新建**账户时决定 `name`。
        # 与 `_account_type` 同理无条件产出（未映射时 `p.get("name")` 为 None →
        # 空串），由 apply_diff 的 create 分支回落账户ID。
        out["_sheet_name"] = _conf_text(p.get("name"))
    # 国家 → 时区：表里两列都有、而 regions 里没有这个国家 ⇒ 记 pending（**只查库、不写**）。
    # 国家或时区缺一不建：建出「有国家没时区」的残项会被当成已有、再也补不上。
    # 只在 tt 产（gg/fb 的国家列本轮不映射、也不补建字典）。
    country = _conf_text(p.get("country"))
    tz = _conf_text(p.get("timezone"))
    if platform == "tt" and country and tz and not _region_exists(db, country):
        pending_master.append({"kind": "region", "name": country,
                               "timezone": strip_utc_prefix(tz)})
    if pending_master:
        out["_pending_master"] = pending_master
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
    if key == "_account_type":
        # 合成键：库里对应的是真实列 account_type。不加这一支会落到下面的通用比较，
        # 拿 existing["_account_type"]（不存在 → None）去比 → 恒判「变了」，
        # 于是每次同步都把每一行报成「将更新」。
        return _conf_text(existing.get("account_type")) == _conf_text(value)
    if key == "_primary_bm_name":
        # 合成键：当前主 BM 名不在业务表行上（挂在中间表 fb_account_bm），
        # existing 里取不到，必须现查 —— 否则「表里清空位置」会被误判成「没变」
        # 而被 build_diff 滤掉，主 BM 永远清不掉（设计 §6.3）。
        # `b.deleted_at IS NULL` 不能省（本文件解析 BM 名的两处、以及仓库其它查
        # fb_bms 的地方都带它）：少了它，一条**已软删**的同名 BM 会被读成「当前主 BM
        # 名」，于是「表里把位置改成这个名字」被判成「没变」而滤掉 —— 永远写不进去。
        row = db.execute(
            "SELECT b.name AS n FROM fb_account_bm ab JOIN fb_bms b ON ab.bm_id=b.id "
            "WHERE ab.account_id=? AND ab.is_primary=1 AND b.deleted_at IS NULL",
            (existing["id"],)).fetchone()
        return (row["n"] if row else "") == (value if value is not None else "")
    cur = existing.get(key)
    if cur is None and value in (None, ""):
        return True
    return str(cur if cur is not None else "") == str(value if value is not None else "")

def owner_channel_cells(rows: list, platform: str, value: str,
                        col_map: dict | None = None) -> list:
    """构造只写归属变更通道列的 rows（规格 §7.2 规则 3②）。

    刻意只含这一列 —— 收尾写入若顺手带上别的列，就会把户管在表里的
    其他手工改动一起冲掉。

    `col_map` 是**这张表**的 {字段key: 列字母}；`None` ⇒ 用既有固定规格合成的
    （gg/tt 与既有调用点零改动，逐字节等价）。

    通道列在**两个命名空间**里名字不同，两种都要查：
      - 合成 map（`col_map=None`）走的是既有 `COLUMN_SPEC`，字段名是 `_owner_channel`（gg H）；
      - tt 的真实表头映射（`resolve_column_map`）里没有 `_owner_channel`，那一列叫
        `owner_change_note`（tt L）。只查一个名字会在另一种来源下漏掉整列。
    两种都没有 ⇒ 这张表没这一列（未采集）⇒ 不产出该格的 cell，一个字不碰。
    """
    cm = spec_column_map(platform) if col_map is None else col_map
    col = cm.get("_owner_channel") or cm.get("owner_change_note")
    if col is None:
        return [{"account_id": r["account_id"], "cells": {}} for r in rows]
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


def _read_old_value(db, table: str, col: str, pk: int):
    """读某行某列的当前值（撤回快照要的「旧值」）。

    ⚠️ **必须在 UPDATE 之前调用** —— 写完就读不到了。与 `_record_channel_change`
    读旧 MCC/BC、FB 主 BM 分支读旧主 BM 是同一条纪律（三处都靠「写前读」）。
    """
    row = db.execute(f"SELECT {col} AS v FROM {table} WHERE id=?", (pk,)).fetchone()
    return row["v"] if row else None


def apply_diff(db, diff: dict, platform: str, confirmed: dict, user_id: int,
               *, collect_undo: bool = False, sheet_from: dict | None = None) -> dict:
    """执行户管确认过的差异（规格 §8.3 步骤 8）。

    confirmed: {"create": [账户ID...], "update": [账户ID...], "owner": [账户ID...]}
               缺哪个键就完全不执行该类别。

    **匹配键一律是 `account_id`，不是行号。** 落库时是重新拉表重算 diff 的，
    行号会因表里插行/删行而整体位移 —— 按行号匹配会把「勾了账户甲」静默作用到
    另一个账户上（diff 各项里仍保留 "row"，但只用于在 errors 里报「第几行出错」）。
    返回里的 "not_applied" 收集「confirmed 勾了、当前 diff 里却没有任何一项
    account_id 命中」的账户 —— 确认被静默丢弃比报错更危险：户管会以为改过了。

    `collect_undo=True` 时额外收集一份**撤回快照**放进返回的 "undo" 键（规格 §5.2），
    由路由层 `save_undo` 落库、Task 5 的 `undo_sync` 消费。**默认 False**：既有调用
    与既有测试的行为逐字节不变，且不产生任何多余的读。

    快照为什么必须在这里收集：updates / owner_changes 的**旧值必须在 UPDATE 之前**
    读到（写完就读不到了），而这个位置只有本函数内部有。

    `sheet_from`：`{账户ID: {列字母: 表里的原值}}`，只服务快照里的 `sheet_back`
    （「落库后回写表的那几列的原值」）。**表侧原值只有 `parse_row` 的结果里才有**，
    所以由调用方用 `_owner_sheet_from(parsed, platform)` 逐行算好后传进来 ——
    **键按账户ID、不按行号**（与函数内其它一切匹配同一个理由：行号会位移）。
    `collect_undo=False` 时本参数**完全不被读取**。
    """
    conf = confirmed or {}
    created = updated = owner_changed = 0
    errors = []
    # 撤回快照的四个收集容器（collect_undo=False 时全部为空、不进返回值）。
    # owner_changes 与 updates 项**刻意同形状**（{account_id, cols:{列:{old,new}}}）：
    # Task 5 的 CAS 循环拿同一个函数处理两者。
    undo_updates, undo_owner_changes = [], []
    undo_created, undo_statuses, undo_sheet_back = [], [], []
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

    def _ensure_status(name, owner_id):
        """建缺失的状态行，并在 collect_undo 时记下「这次真的新建了」。

        查重键必须是 **(name, platform)**，与 `resolve_status_id` 内部一致（不含
        owner_id）：带上 owner_id 会漏判「别人已建过同名同平台状态」，撤回时就会把
        别人的状态误删（spec §5.2 的 `created_statuses` 只该记**本次新建**的行）。

        刻意不改 `resolve_status_id` 的签名/返回值 —— 它另有本任务不该碰的调用方
        （`build_diff` 的 `_collect_updates` 等），加出参会把契约撑破。
        """
        name = (name or "").strip()
        if not collect_undo:
            # 纯增量：不收集时直调，连多出来的一次 SELECT 都不做
            return resolve_status_id(db, name, owner_id, platform)
        existed = db.execute("SELECT id FROM account_statuses WHERE name=? AND platform=?",
                             (name, platform)).fetchone()
        sid = resolve_status_id(db, name, owner_id, platform)
        if existed is None and sid is not None:
            undo_statuses.append({"name": name, "platform": platform})
        return sid

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
            # 户类型（规格 §4.3 第 ④ 环）：合成键必须在拼 SQL 之前摘掉，
            # 否则会拼出 `INSERT INTO tt_accounts(..., _account_type)` 直接报错。
            account_type = src.pop("_account_type", None) if platform == "tt" else None
            # 系统里还没有的状态名，到这一步才建行（build_diff 全程只读）
            pending = item.get("pending_status")
            if pending:
                src[_target_column(platform, "status_name")] = _ensure_status(
                    pending, item.get("owner_id"))
            # 系统字典里缺的 BC / 渠道 / 国家（build_diff 只在 tt 产，见设计 §4.4）：
            # 到这一步才补建。BC / 渠道把新建的 id 挂进 `src` ⇒ 随下面的 INSERT 一起写。
            # region 是纯 INSERT，没有 id 要挂（国家 → 时区字典）。
            for x in item.get("pending_master") or []:
                if x["kind"] == "bc":
                    src["bc_id"] = ensure_bc(db, x["name"], item.get("owner_id"))
                elif x["kind"] == "agent":
                    src["agent_id"] = ensure_agent(db, x["name"], item.get("owner_id"))
                else:
                    _ensure_region(db, x["name"], x.get("timezone"))
            src[key_field] = item["account_id"]
            # 设计 §4.6：表里有「账户名称」列就用它；没有（如加白户表）仍回落账户 ID。
            # `_sheet_name` 是合成键（不是数据库列），必须先 pop 再拼 INSERT；未映射时
            # 值为空串 → `or` 回落账户ID（gg/fb 从不产出该键 ⇒ 恒为账户ID，逐字节不变）。
            src["name"] = (src.pop("_sheet_name", None) or "").strip() or item["account_id"]
            src["owner_id"] = item.get("owner_id")
            if account_type is not None:
                src["account_type"] = account_type or TT_DEFAULT_ACCOUNT_TYPE
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
                else:
                    # 解析不到就跳过这一列（账户照建），但必须让户管看见 —— 否则他看到的
                    # 是「账户建好了、位置列空着」而没有任何原因说明。文案与 update 分支
                    # 逐字一致（同一个 `位置「X」无法唯一匹配，已跳过` 口径），前端渲染
                    # 无需为两处写分支。
                    warnings.append({"row": item["row"],
                                     "message": f"位置「{fb_bm_name}」无法唯一匹配，已跳过"})
            _apply_death(db, platform, new_id, want_dead)
            created += 1
            if collect_undo:
                # 只在建号成功之后记（上面任一步抛异常都跳到 except，不记）
                undo_created.append(item["account_id"])
        except Exception:
            # 逐行错误只回固定中文文案：本函数的返回 result 会被路由整体塞进
            # POST /api/huguan/dashboard/sync 的响应体（`errors` 不被 pop），
            # str(e) 会把英文 errno / sqlite 消息 / 源码绝对路径直接泄给客户端
            # （CWE-209，同族口径见 main.py 的「创建失败，详情见服务端日志」）。
            # 异常详情照旧进日志，排查线索不因脱敏而降级。
            log.exception("户管同步：新建账户落库失败 platform=%s row=%s",
                          platform, item["row"])
            errors.append({"row": item["row"], "sheet": item.get("sheet", ""),
                           "error": "创建失败，详情见服务端日志"})

    for item in diff.get("to_update", []):
        if item["account_id"] not in conf.get("update", []):
            continue
        hit["update"].add(item["account_id"])
        try:
            # 本行是否真的写了库（计数规则见下方 `if wrote: updated += 1`）
            wrote = False
            fields = dict(item.get("fields") or {})
            is_dead_val = fields.pop("_is_dead", None)
            # 「位置」列是合成键（主 BM 挂在中间表上，不是 fb_accounts 的列）：
            # **必须在下面 `sets = [f"{k}=?" for k in fields]` 之前摘掉**，否则会拼出
            # `UPDATE fb_accounts SET _primary_bm_name=?` 直接报错。
            # 注意空值语义：表里「位置」空着 → 这里是空串（不是 None），
            # 要落到下面的 else 分支「只清主 BM 标记、不删关联行」（设计 §6.3）。
            new_bm_name = fields.pop("_primary_bm_name", None) if platform == "fb" else None
            # 同 create：`sets = [f"{k}=?" for k in fields]` 会无条件把每个键拼进 SET，
            # 漏 pop 就是 `UPDATE tt_accounts SET _account_type=?` 直接报错。
            account_type = fields.pop("_account_type", None) if platform == "tt" else None
            if account_type:
                fields["account_type"] = account_type
            # 系统里还没有的状态名，到这一步才建行（build_diff 全程只读，规格 §8.3
            # 步骤 7/8）。owner 取该行作用域归属，只记「谁先建的」——不参与查重。
            pending = item.get("pending_status")
            if pending:
                fields[_target_column(platform, "status_name")] = _ensure_status(
                    pending, item.get("scope_owner_id"))
            # 系统字典里缺的 BC / 渠道 / 国家（build_diff 只在 tt 产）：补建并把新建的
            # id 放进 `fields` ⇒（a）进下面的 `sets` 子句写进账户；
            # （b）`_record_channel_change` 据 `bc_id` 记上 BC 变更留痕。
            # **必须在 `sets = [...]` 与历史留痕之前**，否则 id 落不进 SET。
            for x in item.get("pending_master") or []:
                if x["kind"] == "bc":
                    fields["bc_id"] = ensure_bc(db, x["name"], item.get("scope_owner_id"))
                elif x["kind"] == "agent":
                    fields["agent_id"] = ensure_agent(db, x["name"], item.get("scope_owner_id"))
                else:
                    _ensure_region(db, x["name"], x.get("timezone"))
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
                    wrote = True
            # 撤回快照：列级旧值必须在 UPDATE **之前**读 —— 写完就读不到了
            # （与上面 _record_channel_change / 主 BM 两处同一条纪律）。
            # 新值（fields[k]）一并记下：Task 5 的 CAS 要拿它与库里的当前值比，
            # 只有仍等于「本次写的那个值」才敢回滚。
            old_cols = {}
            if collect_undo and fields:
                for k in fields:
                    if k.startswith("_"):
                        # 合成键（_is_dead 等）不是数据库列，拼进 SELECT 会直接报错
                        continue
                    old_cols[k] = _read_old_value(db, table, k, item["existing_id"])
            if sets:
                db.execute(f"UPDATE {table} SET {', '.join(sets)}, "
                           "updated_at=datetime('now','localtime') WHERE id=?",
                           tuple(fields.values()) + (item["existing_id"],))
                wrote = True
            # 记在写**成功之后**：UPDATE 抛异常的行不该进快照（那些新值根本没落库，
            # Task 5 的 CAS 拿它去比只会误报冲突）。
            if old_cols:
                undo_updates.append({
                    "account_id": item["account_id"],
                    "cols": {k: {"old": v, "new": fields[k]}
                             for k, v in old_cols.items()}})
            if is_dead_val is not None:
                _apply_death(db, platform, item["existing_id"], bool(is_dead_val))
                # FB 没有 death_date 列，`_apply_death` 对 fb 直接返回 —— 生死由
                # status_id 承载（真变了会走上面的 sets 分支）。把这一路也算成
                # 「写了库」会让「已死亡账户、表里状态列仍写死亡」这种一行 sets 为空
                # 的行虚报成已更新。
                if platform != "fb":
                    wrote = True
            # 「updated」只统计**确实写了库**的行：业务行 UPDATE（sets）、
            # `_apply_death` 写 death_date（GG/TT）、FB 主 BM 的换 / 清 —— 三条写入
            # 路径任一发生才计数。三者皆无的行（如「位置」名解析不到、只剩一条 warning）
            # 一个字节都没写，计进「已更新」会让户管看到的条数虚高。
            if wrote:
                updated += 1
        except Exception:
            # 同 to_create 分支：固定文案回响应体，异常详情进日志（本函数返回
            # result 会被路由整体回出，str(e) 即 CWE-209 泄露）。
            log.exception("户管同步：更新账户落库失败 platform=%s row=%s",
                          platform, item["row"])
            errors.append({"row": item["row"], "sheet": item.get("sheet", ""),
                           "error": "更新失败，详情见服务端日志"})

    for item in diff.get("owner_changes", []):
        if item["account_id"] not in conf.get("owner", []):
            continue
        hit["owner"].add(item["account_id"])
        try:
            # 撤回快照：归属变更走的是**本分支**，不经过 to_update
            # （`_collect_updates` 不产出 owner_id）—— 旧值不在这里记，撤回时库里的
            # 归属纹丝不动。旧值同样必须在 UPDATE **之前**读。
            undo_oc = None
            if collect_undo:
                cols = {"owner_id": {
                    "old": _read_old_value(db, table, "owner_id", item["existing_id"]),
                    "new": item["to_owner_id"]}}
                if platform == "fb":
                    # acceptor 只对 fb 记：其它平台的表没有这一列，记了会让 Task 5
                    # 拼出 `UPDATE ... SET acceptor=?` 直接报错。
                    cols["acceptor"] = {
                        "old": _read_old_value(db, "fb_accounts", "acceptor",
                                               item["existing_id"]),
                        "new": _fb_owner_transition(item.get("from") or "",
                                                    item.get("to") or "")}
                undo_oc = {"account_id": item["account_id"], "cols": cols}
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
            if undo_oc is not None:
                undo_owner_changes.append(undo_oc)
            if collect_undo:
                # 表侧：这几列在**表里的原值**（由调用方从 parse_row 的结果算好传入）。
                # 空 cells 由 Task 5 自行跳过（没有可回退的表侧内容）。
                undo_sheet_back.append({
                    "account_id": item["account_id"],
                    "cells": dict((sheet_from or {}).get(item["account_id"]) or {}),
                })
            # 带上 "to"（新归属名）：路由收尾直接用它回写运营列，不必再拿行号反查。
            # "from" 一并带上：路由收尾的 FB 定向回写要用它拼「旧转新」。
            applied_owner_rows.append({"account_id": item["account_id"],
                                       "to": item["to"],
                                       "from": item.get("from", "")})
        except Exception:
            # 同前两处：固定文案回响应体，异常详情进日志（路由整体回出 result）。
            log.exception("户管同步：归属变更落库失败 platform=%s row=%s",
                          platform, item["row"])
            errors.append({"row": item["row"], "sheet": item.get("sheet", ""),
                           "error": "归属变更失败，详情见服务端日志"})

    # 缺字典项的「孤儿行」收尾（见 build_diff 的 `pending_master_rows`）：这些既存账户
    # 既不新建也不更新（其余列与库里逐字相同），上面的 create/update 两个分支都够不到
    # 它们 —— 若不在**这里**补建并定向挂链，dry_run 报告里列出的「将新增 BC/渠道」
    # 落库时一个都不兑现，「已存账户要挂新字典项」也永远挂不上。
    # 与其它分支同：逐行 try，异常只回固定中文文案（result 会被路由整体回出，CWE-209）。
    for item in diff.get("pending_master_rows", []):
        try:
            link = {}
            for x in item.get("pending_master") or []:
                if x["kind"] == "bc":
                    bc_id = ensure_bc(db, x["name"], item.get("scope_owner_id"))
                    if bc_id is not None:
                        link["bc_id"] = bc_id
                elif x["kind"] == "agent":
                    agent_id = ensure_agent(db, x["name"], item.get("scope_owner_id"))
                    if agent_id is not None:
                        link["agent_id"] = agent_id
                else:                                   # region：只建，无 id 可挂
                    _ensure_region(db, x["name"], x.get("timezone"))
            if link:
                # BC 变更留痕：与 update 分支同款，**必须在 UPDATE 之前**（旧值写完读不到）。
                # 只 tt 有 `_CHANNEL_HISTORY_SPEC`（fb 无此键，且孤儿项本就只在 tt 产）。
                if platform != "fb" and "bc_id" in link:
                    _record_channel_change(db, platform, item["existing_id"], link, user_id)
                sets = [f"{k}=?" for k in link]
                db.execute(f"UPDATE {table} SET {', '.join(sets)}, "
                           f"updated_at=datetime('now','localtime') WHERE {key_field}=?",
                           tuple(link.values()) + (item["account_id"],))
        except Exception:
            log.exception("户管同步：补建字典项挂链失败 platform=%s row=%s",
                          platform, item.get("row"))
            errors.append({"row": item.get("row"), "sheet": item.get("sheet", ""),
                           "error": "字典项挂链失败，详情见服务端日志"})

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
    result = {"created": created, "updated": updated, "owner_changed": owner_changed,
              "applied_owner_rows": applied_owner_rows, "not_applied": not_applied,
              "remark_m_writeback": remark_m_writeback,
              "remark_operator_push": remark_operator_push,
              "errors": errors, "warnings": warnings}
    if collect_undo:
        # 快照键集是 Task 5 的接口契约（逐键消费）：少一个键就静默漏掉一整类撤回。
        result["undo"] = {"updates": undo_updates, "owner_changes": undo_owner_changes,
                          "created": undo_created, "created_statuses": undo_statuses,
                          "sheet_back": undo_sheet_back}
    return result


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
SELECT a.advertiser_id AS account_id, a.account_type, a.acquired_date, a.death_date, a.country,
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


def collect_rows_for_push(db, platform: str, account_ids=None,
                          col_maps_by_type=None) -> list:
    """系统 → 表：查出待写账户并转成 update_rows_by_account_id 的入参。

    产出里刻意不含归属变更通道列（规格 §7.2 规则 2）。
    account_ids=None 表示全部；给了具体 ID 时只取这些。
    两条路径都排除软删账户（`a.deleted_at IS NULL`）：与「从表同步」对软删做
    to_skip 的口径对称，也符合规格 §6.2「软删不触发回写」的意图 —— 软删是用户
    主动从看板撤下的意图，刷新不该把它复活。

    `col_maps_by_type`（可选）是 `{户类型名: 该表的 col_map}`。给了就逐行按该行
    `account_type` 取到本表的 col_map 再产出 cells（tt 表头顺序不同 ⇒ 固定列字母会
    串列）；没给（None）⇒ 既有合成 map，gg/fb 与既有调用点零改动、逐字节不变。
    调用方负责把 col_map 解析好（读表头需要 service，本函数只有 db）。
    """
    sql = _ROW_SQL[platform]
    # 两个基语句都没有 WHERE 子句，故条件先累积成 list 再统一拼 —— 避免
    # 「先拼 WHERE 再找地方插 AND」那种在无 WHERE 时静默拼错条件的写法。
    conds = ["a.deleted_at IS NULL"]
    # 每项是 (sql, params)。account_ids 给定时用 chunk 切成多段查询（防上万账户
    # 超 SQLite 的 32766 变量上限）；None 表示全部，单条查询即可。
    queries = []
    if account_ids is None:
        queries.append((sql + " WHERE " + " AND ".join(conds), ()))
    else:
        if not account_ids:
            return []
        for part in chunk(account_ids):
            marks = ",".join("?" for _ in part)
            part_conds = conds + [f"a.{ACCOUNT_KEY_FIELD[platform]} IN ({marks})"]
            queries.append((sql + " WHERE " + " AND ".join(part_conds), tuple(part)))

    out = []
    for q_sql, q_params in queries:
        for r in db.execute(q_sql, q_params).fetchall():
            row = dict(r)
            atype = row.get("account_type") or ""
            cm = col_maps_by_type.get(atype) if col_maps_by_type else None
            item = {"account_id": str(row.get("account_id") or "").strip(),
                    "cells": cells_for_row(row, platform, cm)}
            # 户类型只用于**路由**（决定写哪张 worksheet），不进 cells ——
            # cells 是「表列字母 → 单元格值」，没有类型这一列。
            # gg/fb 的 _ROW_SQL 没有这一列 ⇒ 取到空串，分组时只有一组，行为不变。
            item["account_type"] = atype
            out.append(item)
    return [o for o in out if o["account_id"]]


def cross_sheet_notes(db, platform: str, account_ids: list, sheet_name: str,
                      cap: int = 50) -> dict:
    """按表操作时的「跨表重复」提示（设计 §3.3）：这些账户**当前归属另一张表**。

    为什么只查库：读其它表会抵消按表操作带来的提速（与「只在该表内去重」的初衷冲突）。
    库里的 `account_type` 就是「上一次同步时它来自哪张表」的记账，够用。

    判据：本次同步里出现的账户，其库里 `account_type` 非空且与本次表名不同。
    `count` 给总数（前端能说「共 N 个」），`notes` 最多 `cap` 条（防空表刷爆报告）。
    软删账户不计（`deleted_at IS NULL`，与 `collect_rows_for_push` 同口径）。
    """
    ids = [a for a in (account_ids or []) if a]
    if not ids:
        return {"count": 0, "notes": []}
    table = _TABLE_FOR_PLATFORM[platform]
    hits = []
    for part in chunk(ids):
        marks = ",".join("?" for _ in part)
        for r in db.execute(
                f"SELECT {ACCOUNT_KEY_FIELD[platform]} AS aid, account_type "
                f"FROM {table} WHERE {ACCOUNT_KEY_FIELD[platform]} IN ({marks}) "
                "AND deleted_at IS NULL", tuple(part)).fetchall():
            cur = _conf_text(r["account_type"])
            if cur and cur != sheet_name:
                hits.append({"account_id": _conf_text(r["aid"]),
                             "current_type": cur, "this_sheet": sheet_name})
    return {"count": len(hits), "notes": hits[:cap]}


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


def snapshot_push_targets(service, conf: dict, platform: str, groups: list,
                          col_maps: dict | None = None) -> dict:
    """读每张表，记下「本次刷新将会写到的每个格子」的当前值。

    `groups` 是 `group_rows_by_sheet` 的产出：`[(sheet_name, rows)]`。

    - 行：`rows` 里在表中命中**定位键**的那些（表里没有的账户
      update_rows_by_account_id 会进 not_found、一个字都不写）
    - 列：该行 `cells` 会产出的列（即写表器会真正写到的列；tt 表头映射后它就是
      该表 col_map 里 writable 的那几列，`cells` 已由 col_map 版 `cells_for_row` 产出）

    `col_maps`（可选）是 `{sheet_name: 该表的 col_map}`：给了就用该表 col_map 的
    定位键列找行，**与写表器用同一列**（tt 表头顺序不同时尤其关键）；没给（None）
    ⇒ 回落到既有 `KEY_COL[platform]`，gg/fb 与既有调用点零改动、零额外读。

    ⚠️ 必须在**写表之前**调用 —— 写完之后原值就没了。
    ⚠️ 返回值从「单表快照」改成**每张表一份**（2026-10-08 多表规格 §4.4）：
       TT 现在一个平台有多张 worksheet，撤回必须逐表还原。
       兼容性：旧快照 payload 是 `{spreadsheet_id, sheet_name, cells}`，
       `push_undo_cells` 两种形状都认（见下），所以历史快照仍能撤回一次。
    """
    spreadsheets = conf.get("spreadsheet_id") or ""
    out_sheets = []
    for sheet_name, rows in groups:
        if not rows:
            continue
        grid = read_sheet_values(service, spreadsheets, sheet_name, READ_RANGE[platform])
        cm = (col_maps or {}).get(sheet_name)
        key_col = key_col_of_col_map(cm, platform) if isinstance(cm, dict) \
            else KEY_COL[platform]
        key_i = col_index(key_col)

        where = {}
        for i, values in enumerate(grid[1:], start=2):
            if len(values) <= key_i:
                continue
            raw = ("" if values[key_i] is None else str(values[key_i])).strip().lstrip("'").strip()
            if raw and raw not in where:
                where[raw] = values

        cells = []
        for r in rows:
            aid = r["account_id"]
            values = where.get(aid)
            if values is None:
                continue
            row_cells = {}
            for col in r["cells"]:
                i = col_index(col)
                row_cells[col] = ("" if len(values) <= i or values[i] is None
                                  else str(values[i])).strip()
            if row_cells:
                cells.append({"account_id": aid, "cells": row_cells})
        # 逐表记下**本次定位用的列字母**（新增键）：撤回时按它定位，与写表器/快照同一列，
        # 且不受此后表头漂移影响。账户ID 经手工覆盖映射时尤为关键 —— 撤回若按别名重解析会
        # 认不出（`resolve_table_col_map` 抛错 → 500）。旧快照没有该键，`undo_push` 回落既有解析。
        out_sheets.append({"sheet_name": sheet_name, "key_col": key_col, "cells": cells})
    return {"spreadsheet_id": spreadsheets, "sheets": out_sheets}


def push_undo_cells(payload: dict) -> list:
    """把 push 快照转成「按表分组」的写表入参：`[{"sheet_name", "rows"}]`。

    兼容两种快照形状：
      - 新（2026-10-08 起）：`{spreadsheet_id, sheets: [{sheet_name, cells}]}`
      - 旧（多表之前）：`{spreadsheet_id, sheet_name, cells}`
    旧快照必须继续认，否则升级那一刻「撤回上次」会静默变成空操作。

    ⚠️ 每项的形状是 `{"sheet_name", "rows"}`（计划里的 Produces 契约行），
      **不是**元组 —— Task 7 的验收用例按 `c["sheet_name"]` / `c["rows"]` 取值。
    """
    payload = payload or {}
    sheets = payload.get("sheets")
    if isinstance(sheets, list):
        return [{"sheet_name": s.get("sheet_name") or "",
                 # `key_col` 是快照记录的定位列（新键）；旧快照没有 ⇒ None ⇒
                 # `undo_push` 回落到按表头重新解析（带该表的 `columns` 覆盖）。
                 "key_col": s.get("key_col"),
                 "rows": [{"account_id": c["account_id"], "cells": dict(c["cells"])}
                          for c in (s.get("cells") or [])]}
                for s in sheets if isinstance(s, dict) and s.get("sheet_name")]
    legacy_name = payload.get("sheet_name") or ""
    if not legacy_name:
        return []
    return [{"sheet_name": legacy_name,
             "rows": [{"account_id": c["account_id"], "cells": dict(c["cells"])}
                      for c in (payload.get("cells") or [])]}]


def push_undo_row_count(payload: dict) -> int:
    """push 快照覆盖的行数（撤回按钮小字「影响 N 行」）。

    三种形状都要数对，否则升级后按钮亮着却显示「影响 0 行」：
      - 新：`{sheets: [{sheet_name, cells}]}`（各表行数之和）
      - 旧：`{sheet_name, cells}`
      - 裸：`{cells}`（历史/既有测试里的最小形状）
    """
    payload = payload or {}
    sheets = payload.get("sheets")
    if isinstance(sheets, list):
        return sum(len(s.get("cells") or []) for s in sheets if isinstance(s, dict))
    return len(payload.get("cells") or [])


def push_rows(user_id: int, platform: str, account_ids=None) -> None:
    """把账户当前值写进该户管自己的看板表。

    未配置看板 → 静默返回（不是每个用户都是户管，这不是错误）。
    后台线程写，失败落统一治理日志（可查可重试），不影响调用方的接口返回。
    """
    db = _open_db()
    try:
        tables = get_platform_tables(db, user_id, platform)
        spreadsheet_id = get_platform_config(db, user_id, platform)["spreadsheet_id"]
        # 配置闸门必须在**登记 pending 之前**短路：未配置看板的实例上，写表点要
        # 静默 no-op。闸门一旦失效，每次改状态都会凭空多一条 retry_failed 行 + ⚠️ 标记
        # —— 二期踩过这个坑（回归守卫：tests/test_gg_sheet_write.py::
        # test_status_change_without_sheets_config_registers_nothing）。
        # ⚠️ gg/fb 的 `get_platform_tables` **即使未配置也返回一个元素**（name 与
        # sheet_name 都是空串），故 `not tables` 挡不住它们，必须显式查这两个空值；
        # tt 未配置时返回 []，`not tables` 即可挡住。空表名这一档也不能漏：POST 配置
        # 端点不校验工作表名非空，能存下「有 spreadsheet_id 但表名为空」的半截配置。
        if not tables or not spreadsheet_id or not any(t["sheet_name"] for t in tables):
            return
        # 只取 business_key 列表：**整行重建（含「按户类型分表」）在 target 内做**，
        # 本函数不调 `collect_rows_for_push`。若在这里先查一次 rows、target 内再查一次，
        # 同一批账户会被查两遍，且把「上游意图」的调用计数守卫打红（三期回归修复）。
        if account_ids is None:
            key_col = ACCOUNT_KEY_FIELD[platform]
            keys = [str(r["k"]).strip() for r in db.execute(
                f"SELECT a.{key_col} AS k FROM {_TABLE_FOR_PLATFORM[platform]} a "
                "WHERE a.deleted_at IS NULL").fetchall()]
        else:
            keys = [str(k).strip() for k in account_ids]
    finally:
        db.close()

    keys = [k for k in keys if k]
    if not keys:
        return

    # 接入统一写表治理（三期）：登记 + 后台写 + 失败可查可重试。
    # business_key 逐账户一行；一次 N 户走 run_write_many（一个线程、N 行日志）。
    #
    # ⚠️ 多账户表（tt 按户类型分 worksheet）**不在这里按表发批**。master 侧的写法是
    # `for sheet_name, rows in groups: _sync_sheets_background(_do, …)` —— 那是直调、
    # 绕开 run_write，等于把三期的治理（持久记录 / 可见 / 可重试）整个撤销。
    # 正确的分工：分组与选表下沉到 target 的 rebuild（`huguan_dashboard_sync` 内
    # 调 `group_rows_by_sheet` 逐表写），入口这一层只负责登记与分派。
    import sheet_write
    import routes.huguan_sheet_targets as _hst
    _payload = {"platform": platform}
    _db = _open_db()
    try:
        if len(keys) == 1:
            sheet_write.run_write(
                _db, user_id=user_id, platform=platform, target="huguan_dashboard",
                business_key=keys[0],
                sync_fn=sheet_write.build_sync("huguan_dashboard", user_id, keys[0], _payload),
                payload=_payload)
        else:
            sheet_write.run_write_many(
                _db, user_id=user_id, platform=platform, target="huguan_dashboard",
                business_keys=keys,
                sync_fn=_hst.huguan_dashboard_many_sync(user_id, platform, keys),
                payload=_payload)
    finally:
        _db.close()


def undo_push(user_id: int, platform: str) -> dict:
    """撤回上一次「刷新到看板」：把快照里的格子写回原值，然后作废快照。

    **无条件写回**，不做 CAS（spec §6.1）：快照记的就是「写之前那格长什么样」，
    把它盖回去即可，不比对表当前值（表在后来的协同里被改过也照盖 —— 那是 spec
    明确接受的口径）。未配置看板或没有快照 → 返回全零。

    **逐表还原**：快照是「每张工作表一份」（2026-10-08 多表规格 §4.4），本函数按
    `push_undo_cells` 的分组逐张表各写一次；`updated` / `not_found` 是各表之和。

    **同步执行**，不挂后台线程：撤回是用户当场点、当场要结果的显式操作，
    要能立刻报出 `updated` / `not_found`（与 push_rows 的「后台、失败只记日志」
    契约相反，故不复用 _sync_sheets_background）。
    """
    db = _open_db()
    try:
        conf = get_platform_config(db, user_id, platform)
        tables = get_platform_tables(db, user_id, platform)
        # gg/fb：只有一张表，工作表名仍在 conf 里 —— 判据与改动前逐字等价（表名为空
        # 时同样返回全零，不碰写入器）。
        # tt：工作表名在 tables 里。多表配置的 `conf["sheet_name"]` **恒为空串**
        # （表名存在 `tables` 里），沿用旧判据会让 TT 撤回**静默变成空操作**：
        # 一个字都不写、快照也不作废，撤回按钮永久亮着。
        if not conf["spreadsheet_id"] or not tables or (platform != "tt" and not conf["sheet_name"]):
            return {"updated": 0, "not_found": []}
        payload = load_undo(db, user_id, platform, "push")
        # 各表的手工覆盖（`{sheet_name: columns}`）：只在**旧快照**（没有 `key_col`）
        # 回落按表头重解析时用得上 —— 账户ID 经覆盖映射时，不带覆盖会抛「找不到账户ID列」。
        overrides_by_sheet = {t["sheet_name"]: (t.get("columns") or {}) for t in tables}
    finally:
        db.close()
    if not payload:
        return {"updated": 0, "not_found": []}

    groups = push_undo_cells(payload)
    if not any(g["rows"] for g in groups):
        # 快照存在但覆盖 0 行 ⇒ 没东西可退；作废它，否则撤回按钮永久亮着。
        db = _open_db()
        try:
            delete_undo(db, user_id, platform, "push")
            db.commit()
        finally:
            db.close()
        return {"updated": 0, "not_found": []}

    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG
    service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
    # 表地址取自**快照自己记的那张**（与它描述的那次写入同源），不取当前配置 ——
    # 两者之间用户可能改过配置，撤回要退回到当初写的地方。
    spreadsheet_id = payload.get("spreadsheet_id") or ""
    total_updated, total_not_found = 0, []
    # 定位列必须与**快照用的同一列**：优先用快照里**逐表记下的 `key_col`**（本次修复新增），
    # 它由 `snapshot_push_targets` 按该表 col_map（含手工覆盖）记，且不受此后表头漂移影响。
    # 旧快照没有该键 ⇒ 回落到按**该表表头**重新解析 col_map 再取定位键，并把该表的
    # `columns` 覆盖一并传入 —— 账户ID 经覆盖映射时，不带覆盖会抛「找不到账户ID列」⇒ 撤回 500
    # （这正是终审 Important #1）。写入器默认值是 "C"（GG/TT 的账户ID列），而 **FB 的账户ID
    # 在 D 列**（C 是「账户名称」）—— 不显式传就按错误的列定位、整批写空且不抛异常（静默）。
    for g in groups:
        sheet_name, rows = g["sheet_name"], g["rows"]
        if not rows:
            continue
        key_col = g.get("key_col")
        if not key_col:
            cm = resolve_table_col_map(service, spreadsheet_id, sheet_name, platform,
                                       overrides_by_sheet.get(sheet_name) or {})
            key_col = key_col_of_col_map(cm, platform)
        res = gs.update_rows_by_account_id(service, spreadsheet_id, sheet_name, rows,
                                           key_col=key_col)
        total_updated += res["updated"]
        total_not_found.extend(res["not_found"])
    db = _open_db()
    try:
        delete_undo(db, user_id, platform, "push")
        db.commit()
    finally:
        db.close()
    return {"updated": total_updated, "not_found": total_not_found}


# 「这一项不能撤」的文案：库里的值与本次同步写下去的值不等 ⇒ 同步之后有人改过它。
# 库侧 CAS（字段 / 归属）与「新建账户被别人改过」两种情况共用这一句，
# 前端的冲突报告按原样显示（spec §八）。
_UNDO_CONFLICT_REASON = "同步后被改过"

# created_statuses 的引用检查要扫的三张表 —— `status_id` 在这三张表上都外键引用
# account_statuses(id)（database.py:272 / :719 / :977）。**必须三张全扫**：
# 只扫快照那个 platform 对应的表会漏判跨平台引用，删出一条悬空 status_id
# （2026-09-24 的「69 户 status_id 悬空」是同类后果：外键方向是「账户 → 状态」，
# 删状态行没有任何外键保护，判据只能自己查全）。宁可少删也不能删出悬空引用。
_STATUS_REF_TABLES = ("accounts", "fb_accounts", "tt_accounts")


def undo_sync(user_id: int, platform: str) -> dict:
    """撤回上一次「从表同步到系统」（spec §6.2）。

    **顺序铁律：先回退表，再回退库。不能反。** 反了会让下次同步把撤回又自动撤销掉
    （spec §6.2 有完整推演）：先回库再回表，表那步一旦失败 —— 库里归属已回到张三、
    表里运营列还是李四 —— 下次同步立刻判定出归属变更，把撤回重做一遍。

    库部分用 CAS：只回滚「当前值仍等于本次写入的新值」的列，别人在同步之后改过的
    一律跳过并进冲突报告，绝不覆盖。`updates`（字段）与 `owner_changes`（归属）走
    同一段 CAS，但**逐条各自判定**（同一账户可能两类都有，合成一条会让冲突定错类）。

    快照**只在库事务提交成功之后**才删（中途失败可重试；表写入是幂等的，写固定值）。

    返回 `{"reverted", "conflicts", "kept", "not_found"}` —— 无论有没有快照，键集都一致。
    `reverted` 是撤回成功的项数（一条 updates / 一条 owner_changes / 一个被删的账户 /
    一个被删的状态各算一项）。报告项的形状（Task 6 前端按此渲染）：
      - `conflicts`：账户类 `{"account_id", "kind": "update"|"owner", "reason"}`；
        状态类 `{"name", "platform", "kind": "status", "reason"}`（`kind` 用来区分是哪一类）
      - `kept`：`{"account_id", "reason"}`（新建账户被别人改过 —— 保留、不删）
      - `not_found`：表侧回退时表里找不到的账户ID 列表（原样透传写入器的返回）
    """
    db = _open_db()
    try:
        conf = get_platform_config(db, user_id, platform)
        tables = get_platform_tables(db, user_id, platform)
        payload = load_undo(db, user_id, platform, "sync")
    finally:
        db.close()
    if not payload:
        # 键集必须与成功路径一致：前端逐键取字段，少一个就报错（Task 5 补充说明）
        return {"reverted": 0, "conflicts": [], "kept": [], "not_found": []}
    # 各表的手工覆盖：只在旧快照（没有 `sheet_key_cols`）回落按表头重解析时用 ——
    # 账户ID 经覆盖映射时，不带覆盖会抛「找不到账户ID列」。
    overrides_by_sheet = {t["sheet_name"]: (t.get("columns") or {}) for t in tables}

    table = _TABLE_FOR_PLATFORM[platform]
    key_field = ACCOUNT_KEY_FIELD[platform]

    # ---- 1. 先回退表 ----
    # 空 cells 跳过：没有可回退的表侧内容。未配置看板时这一步不做（快照里那几列
    # 本来也没地方可写），库那步照常走。
    # **必须显式传 key_col**：写入器默认 "C"（GG/TT 的账户ID列），
    # 而 **FB 的账户ID在 D 列**，不传就按错误的列定位、整批静默写空（不抛异常）。
    # tt 表头顺序不同时账户ID 也不在 C 列 ⇒ 逐表按**该表表头**解析 col_map 再取定位键
    # （gg/fb 走合成 map、零额外读）。这是本仓库已修五处的同一缺陷族。
    back = [{"account_id": item["account_id"], "cells": dict(item["cells"])}
            for item in payload.get("sheet_back", []) if item.get("cells")]
    table_result = {"updated": 0, "not_found": []}
    # 逐表分组写回（审查修复轮 1 · Finding 1）：tt 多表下 `conf["sheet_name"]` **恒为空串**
    # （`get_platform_config` 只读顶层 `sheet_name`，而 tt 多表的表名写在 `tables` 里）
    # ⇒ 沿用旧的单表判据 `... and conf["sheet_name"]` 会**恒假**：库侧 CAS 照做、表侧一个字
    # 都不写，下次同步立刻判定出归属变更、把撤回重做一遍（正是本函数 docstring 的失败模式）。
    #
    # 表名的来源优先级：
    #   ① 快照里的 `sheet_back_sheets[account_id]`（审查修复轮 1 新增键，多表同步才有）；
    #   ② 回落到 `conf["sheet_name"]` —— 旧存量快照没有该键，gg/fb 与旧的单表 tt 走这条，
    #      与改动前**逐字等价**（表名为空时同样一个字不写）。
    # 两边都没有 ⇒ 跳过该账户并记 warning，**绝不退回写第一张表**（与本批其它任务同一口径：
    # 宁可漏写也不写错表）。
    if back and conf["spreadsheet_id"]:
        sheet_back_sheets = payload.get("sheet_back_sheets") or {}
        # 逐表记下的定位列（新增键）：撤回按它定位，与读/写路径同一列，也不受表头漂移影响。
        # 旧快照没有该键 ⇒ 回落既有解析（带该表 `columns` 覆盖）。
        sheet_key_cols = payload.get("sheet_key_cols") or {}
        by_sheet = {}
        for item in back:
            name = sheet_back_sheets.get(item["account_id"]) or conf["sheet_name"]
            if not name:
                log.warning("撤回同步：账户 %s 查不到所在工作表，跳过表侧回退 platform=%s",
                            item["account_id"], platform)
                continue
            by_sheet.setdefault(name, []).append(item)
        if by_sheet:
            import google_sheets_service as gs
            from main import _GOOGLE_SHEETS_CONFIG
            service = gs.build_service(_GOOGLE_SHEETS_CONFIG["credentials_path"])
            for name, rows in by_sheet.items():
                # 定位列必须与**快照/写表器用的同一列**：优先用快照逐表记的 `sheet_key_cols`；
                # 旧快照没有该键 ⇒ 回落按该表表头解析 col_map（并带上该表 `columns` 覆盖 ——
                # 账户ID 经覆盖映射时不带覆盖会抛「找不到账户ID列」）。gg/fb 合成 map、零额外读。
                key_col = sheet_key_cols.get(name)
                if not key_col:
                    cm = resolve_table_col_map(service, conf["spreadsheet_id"], name, platform,
                                               overrides_by_sheet.get(name) or {})
                    key_col = key_col_of_col_map(cm, platform)
                res = gs.update_rows_by_account_id(
                    service, conf["spreadsheet_id"], name, rows, key_col=key_col)
                table_result["updated"] += res["updated"]
                table_result["not_found"].extend(res["not_found"])

    # ---- 2. 再回退库（单事务）----
    reverted, conflicts, kept = 0, [], []
    db = _open_db()
    try:
        def _norm(value) -> str:
            """CAS 比较用的归一化：None 与空串同形（与表侧「空值=清空」口径一致）。"""
            return "" if value is None else str(value)

        def _cas_revert(item, kind):
            """CAS 回滚一条 `{account_id, cols:{列:{old,new}}}`。"""
            nonlocal reverted
            aid = item["account_id"]
            row = db.execute(f"SELECT * FROM {table} WHERE {key_field}=?", (aid,)).fetchone()
            if row is None:
                # 账户已不存在（同步后被删）⇒ 没有可回滚的东西，不算冲突
                return
            keys = row.keys()
            sets, vals = [], []
            for col, pair in (item.get("cols") or {}).items():
                if col not in keys:
                    # 快照列在当前 schema 里不存在：`row[col]` 会 IndexError、拼进
                    # UPDATE 会 OperationalError —— 两种都会杀掉整次撤回。按冲突报出。
                    conflicts.append({"account_id": aid, "kind": kind,
                                      "reason": f"库中无列 {col}，未撤回"})
                    return
                if _norm(row[col]) != _norm(pair.get("new")):
                    # 别人在同步之后改过这一列 ⇒ 整条跳过，绝不覆盖（spec §6.2）
                    conflicts.append({"account_id": aid, "kind": kind,
                                      "reason": _UNDO_CONFLICT_REASON})
                    return
                sets.append(f"{col}=?")
                vals.append(pair.get("old"))
            if sets:
                # 刻意不刷 updated_at：撤回应被读作「回到同步前」，不是一次新的编辑
                # （也避免与上面 created 的 updated_at 判定互相干扰）。
                db.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?",
                           tuple(vals) + (row["id"],))
                reverted += 1

        for item in payload.get("updates", []):
            _cas_revert(item, "update")
        for item in payload.get("owner_changes", []):
            _cas_revert(item, "owner")

        # 删本次新建的账户：`updated_at` 仍等于 `created_at`（没人动过它）才删。
        for aid in payload.get("created", []):
            row = db.execute(f"SELECT id, updated_at, created_at FROM {table} "
                             f"WHERE {key_field}=?", (aid,)).fetchone()
            if row is None:
                continue
            if _norm(row["updated_at"]) != _norm(row["created_at"]):
                kept.append({"account_id": aid, "reason": _UNDO_CONFLICT_REASON})
                continue
            # `fb_account_bm_history` 没有 ON DELETE CASCADE（`account_mcc_history` /
            # `tt_account_bc_history` 有）⇒ 必须先显式清掉，否则 PRAGMA foreign_keys=ON
            # 会用外键把整次删除挡下来（spec §9.1）。
            if platform == "fb":
                db.execute("DELETE FROM fb_account_bm_history WHERE account_id=?",
                           (row["id"],))
            db.execute(f"DELETE FROM {table} WHERE id=?", (row["id"],))
            reverted += 1

        # 删本次新建的状态：**三张表全查、零引用**才删（spec §6.2 / §十.4）。
        for item in payload.get("created_statuses", []):
            name = (item.get("name") or "").strip()
            plat = item.get("platform") or platform
            srow = db.execute("SELECT id FROM account_statuses WHERE name=? AND platform=?",
                              (name, plat)).fetchone()
            if srow is None:
                continue
            sid = srow["id"]
            refs = sum(db.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE status_id=?",
                                  (sid,)).fetchone()["n"]
                       for t in _STATUS_REF_TABLES)
            if refs:
                # 有引用即保留（宁可少删，也不能删出一条悬空 status_id）
                conflicts.append({"name": name, "platform": plat, "kind": "status",
                                  "reason": f"状态仍被 {refs} 个账户引用"})
                continue
            db.execute("DELETE FROM account_statuses WHERE id=?", (sid,))
            reverted += 1

        db.commit()
    except Exception:
        # 库那步失败 ⇒ 整个事务回滚（但**不回退**已经落定的表那步）。此时快照必须
        # 留着可重试，故绝不在这里 delete_undo；异常原样抛出，由路由层定错误码。
        db.rollback()
        raise
    finally:
        db.close()

    # 快照只在库提交成功之后才删（spec §6.2 末句）。自己开连接：上面那条已关闭。
    db = _open_db()
    try:
        delete_undo(db, user_id, platform, "sync")
        db.commit()
    finally:
        db.close()
    return {"reverted": reverted, "conflicts": conflicts, "kept": kept,
            "not_found": table_result.get("not_found", [])}


def push_remark_to_operator_dashboard(owner_id: int, account_id: str, value: str) -> None:
    """把备注写进该投手「我的看板」的 J 列（按 D 列定位行）。

    与 push_rows 的区别：push_rows 面向**户管看板**（配置来自 huguan_dashboard_{uid}），
    本函数面向**投手看板**（配置来自 tags.tt_sheet_id + tt_sheet_mappings）。

    全局未配 tt_sheet_id → 静默返回（保留：不保留会让未配置的实例每次改备注都凭空
    产生一条 retry_failed 行 —— 二期修复轮 1 的同一类坑）。
    绝不抛异常（与 writeback_rows 同契约：回写失败不得影响主流程）。
    """
    try:
        db = _open_db()
        try:
            row = db.execute("SELECT value FROM tags WHERE key='tt_sheet_id'").fetchone()
            sheet_id = (row["value"] if row and row["value"] else "").strip()
            if not sheet_id:
                return
        finally:
            db.close()

        import sheet_write
        # ⚠️ 备注原文（value）进 payload：写表与重试都从它取 J 列的值。
        # **不**回读 `tt_accounts.remark` —— 本函数有一条调用路径
        # （`routes/tt_accounts_routes.py::update_account`）是「先推投手看板、后 commit」，
        # 另建连接读不到本次尚未提交的 UPDATE，回读会把**旧备注**写进 J 列。
        # 值随 payload 落 `sheet_write_log.payload_json`，重试端点据此复现同一串。
        _payload = {"kind": "remark", "value": value}
        _db = _open_db()
        try:
            sheet_write.run_write(
                # ⚠️ user_id 传 **owner_id**（表主人），不是操作者 —— 本期唯一真正的第三方，
                # 规格 §3.5。日志行记在表主人名下，他才能看到并重试。
                _db, user_id=owner_id, platform="tt", target="operator_dashboard_remark",
                business_key=account_id,
                sync_fn=sheet_write.build_sync("operator_dashboard_remark", owner_id,
                                               account_id, _payload),
                payload=_payload)
        finally:
            _db.close()
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

    写表值随 payload 交给 target：TT 是「旧转新月.日」整串、GG 是解析出的新归属名。
    **不**让 rebuild 回读 DB 重算 —— TT 的「旧归属人」是 reassign 端点才知道的信息，
    rebuild 从 `tt_accounts.owner_change_note` 读回会丢掉它；且调用方未必已 commit。
    """
    try:
        db = _open_db()
        try:
            tables = get_platform_tables(db, user_id, platform)
            if not tables:
                return
            spreadsheet_id = get_platform_config(db, user_id, platform)["spreadsheet_id"]
            if not spreadsheet_id:
                return
            atype = ""
            if platform == "tt":
                r0 = db.execute("SELECT account_type FROM tt_accounts WHERE advertiser_id=?",
                                (account_id,)).fetchone()
                atype = (r0["account_type"] if r0 else "") or ""
            sheet_name = None
            for t in tables:
                if t["name"] == atype:
                    sheet_name = t["sheet_name"]
                    break
            if not sheet_name:
                # 解析不到工作表 → 跳过 + 日志（规格 §4.4）：绝不退回写第一张表。
                # `not` 而非 `is None`：gg 的历史配置可能是 spreadsheet_id 有值而
                # sheet_name 为空，改前那句 `if not conf["sheet_name"]: return` 正是
                # 拦这一档，语义不能缩。
                log.warning("归属变更通道列回写跳过：户类型「%s」查不到工作表 account=%s",
                            atype, account_id)
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
        value = text if text is not None else name

        # 接入统一治理（三期）：登记 + 后台写 + 失败可查可重试。
        # 上方 master 的多表守卫（tables / spreadsheet_id / 按 account_type 解析
        # sheet_name，解析不到就跳过 + 日志）**原样保留** —— 那是入口处的配置闸门，
        # 与计划「配置未就绪就早退、不凭空产生失败行」的要求一致。
        # 「按户类型选表」的执行下沉到 target（`huguan_owner_channel_sync` 内重解析，
        # 重试路径也要用），**不在这里直调 `_sync_sheets_background`** —— 那会绕开治理。
        import sheet_write
        _payload = {"platform": platform, "mode": "owner", "value": value}
        _db = _open_db()
        try:
            sheet_write.run_write(
                _db, user_id=user_id, platform=platform, target="huguan_owner_channel",
                business_key=account_id,
                sync_fn=sheet_write.build_sync("huguan_owner_channel", user_id,
                                               account_id, _payload),
                payload=_payload)
        finally:
            _db.close()
    except Exception as e:
        log.warning("归属变更通道列回写触发失败: %s", e)


def writeback_fb_acceptor(user_id, platform, account_id, note):
    """把 FB 的换绑记录（"{旧}转{新}"）定向写进表里的 I 列。

    与 `writeback_owner_channel` 同形但**语义不同**：那个写的是「新归属名」，
    这个写的是「旧转新」整串（spec §6.5）。因此刻意不复用 `OWNER_CHANNEL_COL`
    （它不含 fb 键，硬塞会 KeyError）。

    绝不抛异常（理由同 `writeback_rows`）。

    写表值（「旧转新」整串）随 payload 交给 target，不回读 `fb_accounts.acceptor`。
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

        import sheet_write
        _payload = {"platform": platform, "value": note}
        _db = _open_db()
        try:
            sheet_write.run_write(
                _db, user_id=user_id, platform=platform, target="huguan_fb_acceptor",
                business_key=account_id,
                sync_fn=sheet_write.build_sync("huguan_fb_acceptor", user_id,
                                               account_id, _payload),
                payload=_payload)
        finally:
            _db.close()
    except Exception as e:
        log.warning("FB 接户运营回写触发失败: %s", e)
