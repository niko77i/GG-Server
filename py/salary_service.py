"""薪资计算的数据来源：读用户做表（Google Sheets）并聚合成四项输入。

做表列结构（A–N，写入端见 `google_sheets_service.upsert_zuobiao`）：

| 列 | 含义 | 谁填 |
|---|---|---|
| A | 日期 | 做表写入 |
| E | 费用 | 做表写入 |
| F | 报给客户 | 人工 |
| K | 平台实际 | **人工，滞后填** |
| L | 代投比例 | 做表写入 |
| M | `=F*L` 代投费 | 公式 |
| N | `=F-K+M` 利润 | 公式 |

聚合口径（2026-11-04 用户确认）：

- **只统计 K 列有值的行**：K 为空的行整行跳过（K 没填 ⇒ 纯增值与消耗都不成立）。
- 代投费 = ΣM；纯增值 = Σ(F−K)；消耗 = ΣK；基数 = 代投费 + 纯增值。
- **最新日期**取自「最后一条 K 有值的行」的 A 列 —— 前端据此提示「计算到几号」。

本模块只做读表 + 纯计算，不写任何东西。
"""
import datetime

# 做表列下标（0-based）
_COL_DATE = 0
_COL_F = 5    # 报给客户
_COL_K = 10   # 平台实际
_COL_L = 11   # 代投比例
_COL_M = 12   # 代投费（公式）
_COL_N = 13   # 利润（公式）

# Google Sheets 的日期序列号基准（1899-12-30；UNFORMATTED_VALUE 下日期就是数字）
_EXCEL_EPOCH = datetime.date(1899, 12, 30)


def parse_number(value) -> float | None:
    """把单元格值解析成数字；空 / 非数字返回 None。

    兼容 `UNFORMATTED_VALUE` 之外的几种常见形态：千分位（`1,234.56`）、
    货币符号、百分号、首尾空格、Excel 错误串（`#VALUE!`）。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    for ch in (",", "¥", "$", "￥", " "):
        text = text.replace(ch, "")
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    try:
        num = float(text)
    except (TypeError, ValueError):
        return None
    return num / 100.0 if percent else num


def parse_date_cell(value) -> str:
    """把 A 列日期单元格转成 `YYYY-MM-DD`；认不出就原样返回（空则返回空串）。

    `UNFORMATTED_VALUE` 下日期是序列号数字，必须转换，否则前端会显示 `46000`。
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        serial = float(value)
        # 只把 1954 年以后的值当日期序列号：`A 列里出现 100` 这类非日期数字
        # 旧实现会算出「1900-04-09」，比原样显示更误导。
        if 20000 <= serial <= 90000:
            try:
                return (_EXCEL_EPOCH + datetime.timedelta(days=int(serial))).isoformat()
            except (OverflowError, ValueError):
                return ""
        return str(value).strip()
    text = str(value).strip()
    if not text:
        return ""
    # 字符串形态的序列号（表格里存成文本的数字）同样转日期
    numeric = text.replace(".", "", 1).replace("-", "", 1) if text.count("-") <= 1 else ""
    if numeric.isdigit():
        try:
            serial = float(text)
        except ValueError:
            serial = 0
        if 20000 <= serial <= 90000:
            return (_EXCEL_EPOCH + datetime.timedelta(days=int(serial))).isoformat()
    normalized = text.replace("/", "-").replace(".", "-")
    parts = normalized.split("-")
    if len(parts) == 3:
        try:
            y, m, d = (int(p) for p in parts)
            return datetime.date(y, m, d).isoformat()
        except (TypeError, ValueError):
            return text
    return text


def _cell(row: list, idx: int):
    """安全取单元格，越界返回 None。"""
    return row[idx] if isinstance(row, (list, tuple)) and len(row) > idx else None


def _percent_ratio(value) -> float | None:
    """代投比例列 → 小数比率（`6%`→0.06、`0.06`→0.06、`6`→0.06、`1`→0.01）。"""
    num = parse_number(value)
    if num is None:
        return None
    text = str(value or "").strip()
    if text.endswith("%"):
        return num  # parse_number 已除以 100
    # 写成 6 而不是 6% 时按百分数处理。边界取 `>= 1`（而不是 `> 1`）：
    # `L=1` 在「数字即百分数」的口径下是 1%，旧实现会当成 100%（1000×1=1000）。
    if num >= 1:
        return num / 100.0
    return num


def _looks_like_header(value) -> bool:
    """K 列的「表头」文本：标题行不该计入「K 列不是数字」告警。

    真机数据里第一行常是表头（`平台实际`、`平台实际(USDT)` 这类），旧实现会给每次
    计算都挂一条「1 行 K 列不是数字」的噪音告警。判据刻意放宽到 20 字符以内且
    含「平台/实际」，同时保留 8 字符内的纯 `K`。
    """
    text = str(value or "").strip()
    if not text or len(text) > 20:
        return False
    if text in ("K", "k", "平台实际", "平台", "实际"):
        return True
    return "平台" in text or "实际" in text


def aggregate_rows(rows: list) -> dict:
    """把做表 A–N 行聚合成薪资计算所需的四项输入。

    Args:
        rows: `read_sheet_values` 返回的二维列表（含表头则自动跳过无法解析的行）。

    Returns:
        {
          rows_total, rows_counted, rows_skipped_empty_k, rows_invalid_k,
          rows_missing_f, rows_m_missing,
          agency_fee, net_value, spend, core, sheet_n_sum,
          latest_date, by_date: [...], warnings: [...]
        }
    """
    agency_fee = 0.0
    net_value = 0.0
    spend = 0.0
    sheet_n_sum = 0.0
    counted = 0
    skipped_empty_k = 0
    skipped_header_k = 0
    invalid_k = 0
    missing_f = 0
    m_missing = 0
    latest_date = ""
    groups: dict[str, dict] = {}
    date_order: list[str] = []

    for row in rows or []:
        if not isinstance(row, (list, tuple)):
            continue
        k_raw = _cell(row, _COL_K)
        k = parse_number(k_raw)
        if k is None:
            if k_raw is None or str(k_raw).strip() == "":
                skipped_empty_k += 1
            elif _looks_like_header(k_raw):
                skipped_header_k += 1
            else:
                invalid_k += 1
            continue

        f = parse_number(_cell(row, _COL_F))
        if f is None:
            f = 0.0
            missing_f += 1

        m = parse_number(_cell(row, _COL_M))
        if m is None:
            # M 是公式；公式报错或没铺到时，用 F × L 兜底（不让整行作废）
            ratio = _percent_ratio(_cell(row, _COL_L))
            if ratio is not None:
                m = f * ratio
            else:
                m = 0.0
            m_missing += 1

        n = parse_number(_cell(row, _COL_N))
        if n is not None:
            sheet_n_sum += n

        net = f - k
        agency_fee += m
        net_value += net
        spend += k
        counted += 1

        day = parse_date_cell(_cell(row, _COL_DATE)) or "（无日期）"
        if day != "（无日期）":
            latest_date = day  # 按表内顺序推进：最后一条 K 有值的行即最新
        if day not in groups:
            groups[day] = {"date": day, "rows": 0, "agency_fee": 0.0,
                           "net_value": 0.0, "spend": 0.0}
            date_order.append(day)
        g = groups[day]
        g["rows"] += 1
        g["agency_fee"] += m
        g["net_value"] += net
        g["spend"] += k

    core = agency_fee + net_value
    warnings = []
    if invalid_k:
        warnings.append(f"有 {invalid_k} 行 K 列不是数字，已跳过")
    if missing_f:
        warnings.append(f"有 {missing_f} 行 K 有值但 F 为空，已按 0 计（纯增值会偏负）")
    if m_missing:
        warnings.append(f"有 {m_missing} 行 M 列无值，已按 `F×L` 兜底计算")
    if counted and abs(sheet_n_sum - core) > max(1.0, abs(core) * 0.001):
        warnings.append(
            f"表内 N 列合计 {sheet_n_sum:,.2f} 与「代投费+纯增值」{core:,.2f} 不一致，"
            "请检查公式或手工改动"
        )

    return {
        "rows_total": len(rows or []),
        "rows_counted": counted,
        "rows_skipped_empty_k": skipped_empty_k,
        "rows_header_k": skipped_header_k,
        "rows_invalid_k": invalid_k,
        "rows_missing_f": missing_f,
        "rows_m_missing": m_missing,
        "agency_fee": agency_fee,
        "net_value": net_value,
        "spend": spend,
        "core": core,
        "sheet_n_sum": sheet_n_sum,
        "latest_date": latest_date,
        "by_date": [groups[d] for d in date_order],
        "warnings": warnings,
    }


def read_and_aggregate(spreadsheet_id: str) -> dict:
    """读取表格第一个工作表的 A–N 列并聚合。

    与写表端保持一致：**做表固定写第一个 Sheet**（见 `upsert_zuobiao`）。
    """
    import google_sheets_service as gs
    from main import _GOOGLE_SHEETS_CONFIG

    creds_path = (_GOOGLE_SHEETS_CONFIG or {}).get("credentials_path", "")
    if not creds_path:
        raise gs.GoogleSheetsServiceError("Google Sheets 未配置")

    service = gs.build_service(creds_path)
    try:
        info = gs.get_spreadsheet_info(service, spreadsheet_id)
    except gs.GoogleSheetsServiceError as e:
        # 真机最常见的失败：这张表压根没共享给服务账号（403 PERMISSION_DENIED）。
        # 默认文案（「获取表格信息失败」）看不出该去改什么，这里换成可操作的提示。
        raise gs.GoogleSheetsServiceError(
            "无法读取这张表：请确认它已共享给服务账号，或表格 ID 是否仍然有效"
        ) from e
    sheets = info.get("sheets") or []
    if not sheets:
        raise gs.GoogleSheetsServiceError("该表格里没有任何工作表")

    sheet_name = sheets[0].get("name") or "Sheet1"
    rows = gs.read_sheet_values(
        service, spreadsheet_id, sheet_name, "A:N",
        value_render_option="UNFORMATTED_VALUE",
    )
    agg = aggregate_rows(rows)
    agg["sheet_name"] = sheet_name
    agg["spreadsheet_title"] = info.get("title", "")
    return agg
