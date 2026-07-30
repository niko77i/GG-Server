"""Google Sheets API 客户端 — 通过服务账号 (Service Account) 读写 Google 在线表格。

用户只需将表格分享给服务账号邮箱即可，无需各自 OAuth 授权。
"""

import os
import json
import logging

log = logging.getLogger("gg-server")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsServiceError(Exception):
    """Google Sheets 服务错误。"""
    pass


def check_configured(credentials_path: str) -> dict:
    """检查 Google Sheets API 配置状态。

    Returns:
        {"configured": bool, "client_email": str, "message": str}
    """
    result = {"configured": False, "client_email": "", "message": ""}

    if not credentials_path or not os.path.isfile(credentials_path):
        result["message"] = "凭据文件不存在，请在 GCP 控制台创建服务账号并下载 JSON 密钥文件"
        return result

    try:
        with open(credentials_path, "r", encoding="utf-8") as f:
            creds_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        result["message"] = f"凭据文件格式无效: {e}"
        return result

    if creds_data.get("type") != "service_account":
        result["message"] = "凭据文件不是服务账号类型，请使用服务账号 JSON 密钥"
        return result

    client_email = creds_data.get("client_email", "")
    if not client_email:
        result["message"] = "凭据文件缺少 client_email"
        return result

    result["configured"] = True
    result["client_email"] = client_email
    result["message"] = f"服务账号已配置 ({client_email})，可使用 Google Sheets API"
    return result


def _get_credentials(credentials_path: str):
    """从服务账号 JSON 密钥文件获取凭据。"""
    from google.oauth2 import service_account

    if not os.path.isfile(credentials_path):
        raise GoogleSheetsServiceError(f"凭据文件不存在: {credentials_path}")

    try:
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        return creds
    except Exception as e:
        raise GoogleSheetsServiceError(f"加载服务账号凭据失败: {e}") from e


def build_service(credentials_path: str):
    """构建 Google Sheets API v4 服务对象。"""
    from googleapiclient.discovery import build

    try:
        creds = _get_credentials(credentials_path)
        service = build("sheets", "v4", credentials=creds)
        return service
    except GoogleSheetsServiceError:
        raise
    except Exception as e:
        raise GoogleSheetsServiceError(f"构建 Google Sheets 服务失败: {e}") from e


def get_spreadsheet_info(service, spreadsheet_id: str) -> dict:
    """获取表格标题、所有 sheet 信息（含行数），解析运营名。

    Returns:
        {"title": "卡尔202607", "operator": "卡尔", "year_month": "202607",
         "sheets": [{"name": "Sheet1", "gid": 0, "rowCount": 1000}, ...]}
    """
    import re
    try:
        ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    except Exception as e:
        raise GoogleSheetsServiceError(f"获取表格信息失败: {e}") from e

    title = ss.get("properties", {}).get("title", "")

    operator = ""
    year_month = ""
    if title:
        m = re.match(r'^(\D+)(\d{4}\.?\d{2})$', title)
        if m:
            operator = m.group(1)
            year_month = m.group(2)

    sheets = []
    for s in ss.get("sheets", []):
        props = s.get("properties", {})
        sheets.append({
            "name": props.get("title", ""),
            "gid": props.get("sheetId", 0),
            "rowCount": props.get("gridProperties", {}).get("rowCount", 1000),
        })

    return {
        "title": title,
        "operator": operator,
        "year_month": year_month,
        "sheets": sheets,
    }


def upsert_zuobiao(service, info: dict, spreadsheet_id: str, sheet_gid: str,
                   rows: list, product_name: str, region: str, report_date: str,
                   sales_person: str, agency_ratio, operator_name: str) -> dict:
    """将做表数据 upsert 到 Google Sheets。

    info: get_spreadsheet_info 的返回值（含 sheets 列表和 rowCount）
    """
    # 1. 从已缓存的 info 解析 sheet 名和行数（不再调 API）
    sheet_name = "Sheet1"
    sheet_rows = 1000
    for s in info.get("sheets", []):
        if str(s.get("gid", 0)) == str(sheet_gid):
            sheet_name = s["name"]
            sheet_rows = s.get("rowCount", 1000)
            break
    sheet_id_int = int(sheet_gid) if str(sheet_gid).isdigit() else 0

    # 2. 读取现有数据
    range_read = f"'{sheet_name}'!A:N"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_read,
    ).execute()
    existing = result.get("values", [])
    last_row = 0
    last_date = ""
    for i in range(len(existing) - 1, -1, -1):
        row = existing[i]
        if any(row[j] for j in range(min(10, len(row))) if row[j]):
            last_row = i + 1
            last_date = (row[0] or "").strip() if len(row) > 0 else ""
            break

    # 3. 构建索引
    existing_index = {}
    for i, row in enumerate(existing):
        d = (row[0] or "").strip() if len(row) > 0 else ""
        cid = (row[3] or "").strip() if len(row) > 3 else ""
        cam = (row[9] or "").strip() if len(row) > 9 else ""
        if d or cid or cam:
            existing_index[(d, cid, cam)] = i

    # 4. 构建新行，养户行覆盖 G(客户名称)、H(商务)、L(代投比例=0%)
    percent_str = f"{int(agency_ratio)}%" if agency_ratio is not None else ""
    new_rows = []
    for row in rows:
        is_yanghu = row.get("is_yanghu", False)
        g_val = "养户" if is_yanghu else product_name
        h_val = "止戈" if is_yanghu else (sales_person or "")
        l_val = "0%" if is_yanghu else percent_str
        new_rows.append([
            report_date, operator_name,
            row.get("account", ""), str(row.get("customerId", "")),
            row.get("cost", 0), "",
            g_val, h_val, region,
            row.get("campaign", ""), "", l_val, None, None,  # M/N 公式稍后填入
        ])

    # 5. 分拣
    updates = []
    appends = []
    for new_row in new_rows:
        key = (new_row[0].strip(), new_row[3].strip(), new_row[9].strip())
        if key in existing_index:
            updates.append((existing_index[key], new_row))
        else:
            appends.append(new_row)

    log.info("Google Sheets: 更新 %d 行，新增 %d 行", len(updates), len(appends))

    # 6. 批量更新 — 一次 API 调用
    if updates:
        data = []
        for row_idx, row_data in updates:
            row_num = row_idx + 1  # 1-indexed
            row_data[12] = f"=F{row_num}*L{row_num}"
            row_data[13] = f"=F{row_num}-K{row_num}+M{row_num}"
            data.append({
                "range": f"'{sheet_name}'!A{row_num}:N{row_num}",
                "values": [row_data],
            })
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()

    # 7. 追加新行（用 info 中的 rowCount，不再调 API）
    if appends:
        start = last_row + 1
        # 不同日期之间空一行
        if last_date and last_date != (report_date or "").strip():
            start += 1
        end = start + len(appends) - 1
        # 填入公式：M=F*L, N=F-K+M
        for i, row_data in enumerate(appends):
            row_num = start + i
            row_data[12] = f"=F{row_num}*L{row_num}"
            row_data[13] = f"=F{row_num}-K{row_num}+M{row_num}"
        if end > sheet_rows:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{
                    "appendDimension": {
                        "sheetId": sheet_id_int,
                        "dimension": "ROWS",
                        "length": end - sheet_rows
                    }
                }]}
            ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A{start}:N{end}",
            valueInputOption="USER_ENTERED",
            body={"values": appends},
        ).execute()

    # 8. 格式化 — 仅对新写入的行
    if appends:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [
                {"repeatCell": {
                    "range": {"sheetId": sheet_id_int, "startColumnIndex": 3,
                              "endColumnIndex": 4, "startRowIndex": start - 1,
                              "endRowIndex": end},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                    "fields": "userEnteredFormat.numberFormat"
                }},
                {"repeatCell": {
                    "range": {"sheetId": sheet_id_int, "startColumnIndex": 4,
                              "endColumnIndex": 5, "startRowIndex": start - 1,
                              "endRowIndex": end},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                              "pattern": "#,##0.00"}}},
                    "fields": "userEnteredFormat.numberFormat"
                }}
            ]}
        ).execute()

    return {"updated": len(updates), "inserted": len(appends)}


def append_recharge(service, spreadsheet_id: str, sheet_name: str, rows: list) -> dict:
    """将充值记录追加到 Google Sheets 指定 sheet 表。

    sheet_name: 目标 sheet 名，为空时回退到「充值表」
    rows: [{"account_id": "123-456-7890", "amount": "1000",
            "agent": "卡尔", "operator": "张三", "status": "死亡"}, ...]

    A=账户ID, B=金额, C=代理, D=运营, E=留空, F=留空, G=状态
    """
    # 1. 按传入的 sheet_name 查找目标 sheet（为空时回退到「充值表」）
    effective_name = sheet_name.strip() if sheet_name else "充值表"
    ss = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    target_sheet = None
    for s in ss.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title", "") == effective_name:
            target_sheet = {
                "name": props["title"],
                "gid": props["sheetId"],
                "rowCount": props.get("gridProperties", {}).get("rowCount", 1000),
            }
            break

    if not target_sheet:
        raise GoogleSheetsServiceError(f"表格中未找到「{effective_name}」工作表")

    sheet_name = target_sheet["name"]
    sheet_id_int = target_sheet["gid"]
    sheet_rows = target_sheet["rowCount"]

    # 2. 读取现有数据，找最后一行
    range_read = f"'{sheet_name}'!A:G"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_read,
    ).execute()
    existing = result.get("values", [])
    last_row = 0
    for i in range(len(existing) - 1, -1, -1):
        row = existing[i]
        if any(row[j] for j in range(min(4, len(row))) if row[j]):
            last_row = i + 1
            break

    # 3. 构建待写入行（A-G，E和F留空）
    new_rows = []
    for r in rows:
        new_rows.append([
            r.get("account_id", ""),
            str(r.get("amount", "")),
            r.get("agent", ""),
            r.get("operator", ""),
            "",  # E列 时间 留空
            "",  # F列 是否充值 留空
            r.get("status", ""),  # G列 状态
        ])

    # 4. 检查是否需要扩充行数
    start = last_row + 1
    end = last_row + len(new_rows)
    if end > sheet_rows:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "appendDimension": {
                    "sheetId": sheet_id_int,
                    "dimension": "ROWS",
                    "length": end - sheet_rows
                }
            }]}
        ).execute()

    # 5. 追加写入
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A{start}:G{end}",
        valueInputOption="USER_ENTERED",
        body={"values": new_rows},
    ).execute()

    log.info("充值记录已追加到 Google Sheets: %d 行", len(new_rows))
    return {"appended": len(new_rows)}


def read_sheet_values(service, spreadsheet_id: str, sheet_name: str, range_str: str) -> list[list]:
    """通用读取 Google Sheet 指定范围的值。

    Args:
        service: Google Sheets API service 对象
        spreadsheet_id: 表格 ID
        sheet_name: sheet 名称
        range_str: 范围字符串，如 'A:G'

    Returns:
        二维列表，每行为一个 list[str]，不包含空行之后的数据
    """
    range_full = f"'{sheet_name}'!{range_str}"
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_full,
        ).execute()
        return result.get("values", [])
    except Exception as e:
        raise GoogleSheetsServiceError(f"读取工作表失败: {e}") from e


def update_cell_by_account_id(service, spreadsheet_id: str, sheet_name: str,
                               account_id: str, value: str, col_index: int = 5) -> dict:
    """在指定 sheet 中按 account_id（B 列）定位行，更新指定列。

    我的看板列结构：
      A=运营, B=账户ID, C=所属渠道, D=国家, E=时区, F=备注, G=是否封户, H=是否解绑

    Args:
        service: Google Sheets API service 对象
        spreadsheet_id: 表格 ID
        sheet_name: sheet 名称（用户私有的「我的看板」）
        account_id: 要查找的账户 ID
        value: 要写入的值（空字符串表示清空该单元格）
        col_index: 目标列索引，5=F列（备注），7=H列（是否解绑）

    Returns:
        {"updated": 1} 或 {"not_found": True}
    """
    import logging
    log = logging.getLogger("gg-server")

    # 列索引 → 列字母
    col_letter = chr(ord('A') + col_index)

    # 读取全表 A-H 列
    rows = read_sheet_values(service, spreadsheet_id, sheet_name, "A:H")

    # 查找匹配 account_id 的行（B 列 = 索引 1）
    target_row = None
    for i, row in enumerate(rows):
        if len(row) > 1 and (row[1] or "").strip() == account_id.strip():
            target_row = i
            break

    if target_row is None:
        log.info("update_cell_by_account_id: account_id=%s 在 sheet 中未找到", account_id)
        return {"not_found": True}

    # 确保行足够长
    while len(rows[target_row]) <= col_index:
        rows[target_row].append("")

    # 更新目标列
    rows[target_row][col_index] = value

    # 写回单个单元格
    row_num = target_row + 1  # 1-indexed
    range_write = f"'{sheet_name}'!{col_letter}{row_num}"
    try:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_write,
            valueInputOption="USER_ENTERED",
            body={"values": [[value]]},
        ).execute()
    except Exception as e:
        raise GoogleSheetsServiceError(f"更新{col_letter}列失败: {e}") from e

    log.info("update_cell_by_account_id: account_id=%s %s列已更新为 '%s'", account_id, col_letter, value)
    return {"updated": 1}


def upsert_fb_reports(db, user_id: int, product_name: str, line_name: str,
                      report_date: str, records: list) -> dict:
    """将 FB 做表数据写入 Google Sheets。

    列映射：客户名称 | 商务 | 投放国家 | 渠道号 | 账户名称 | 广告账户ID |
           账号消耗 | 展示次数 | 点击 | 完成注册 | 购物次数 | 单词购物费用
    """
    import json

    # 获取用户 Google Sheets 配置（按平台自动选 key）
    user = db.execute("SELECT platform, role FROM users WHERE id=?", (user_id,)).fetchone()
    platform = (user['platform'] or 'gg') if user else 'gg'
    key = f"google_sheets_fb_{user_id}" if platform == 'fb' else f"google_sheets_{user_id}"
    config = db.execute(
        "SELECT value FROM config WHERE key=?", (key,)
    ).fetchone()
    if not config:
        raise ValueError("用户未配置 Google Sheets")
    sheets_list = json.loads(config['value'] or '[]')
    if not isinstance(sheets_list, list) or not sheets_list:
        raise ValueError("用户未配置 Google Sheets")
    active_sheet = sheets_list[0]
    spreadsheet_id = active_sheet.get("spreadsheet_id", "")
    if not spreadsheet_id:
        raise ValueError("用户未配置 Google Sheets")

    # 获取产品信息（商务、地区等）
    product_info = db.execute(
        "SELECT p.product_name, p.region, p.agency_ratio, sp.name as sales_person "
        "FROM fb_products p LEFT JOIN sales_persons sp ON sp.id = p.sales_person_id "
        "WHERE p.product_name=?", (product_name,)
    ).fetchone()

    if not product_info:
        raise ValueError(f"FB产品不存在: {product_name}")

    sales_person = product_info['sales_person'] or ''
    region = product_info['region'] or ''
    channel = line_name

    # 获取运营名称
    operator = db.execute("SELECT display_name, username FROM users WHERE id=?", (user_id,)).fetchone()
    operator_name = (operator['display_name'] or operator['username']) if operator else ''

    # 构建行数据（12 列 A-L，M-N 是公式不覆盖）
    rows = []
    for rec in records:
        rows.append([
            report_date,                                      # A: 日期（用户选择的日期）
            operator_name,                                    # B: 运营
            rec.get('account_name', ''),                     # C: 账户名称
            f"'{rec.get('account_id', '')}",                 # D: 广告账户ID（文本）
            float(rec.get('cost', 0)),                       # E: 账号消耗
            '',                                               # F: 报给客户
            product_name,                                     # G: 客户名称
            sales_person,                                     # H: 商务
            region,                                           # I: 投放国家
            channel,                                          # J: 渠道号
            '',                                               # K: 平台实际
            f"{product_info['agency_ratio'] or 0}%",         # L: 代投比例
        ])

    result = _upsert_rows(
        user_id, spreadsheet_id, "FB做表数据", rows,
        report_date, product_name, region, report_date
    )
    return result


def _upsert_rows(user_id: int, spreadsheet_id: str, sheet_name: str,
                 rows: list, report_date: str, product_name: str,
                 region: str, date_str: str = "") -> dict:
    """FB 做表数据写入 Google Sheets（12列 A-L）。按 report_date 月份自动选/建 Sheet。"""
    if not rows:
        return {"updated": 0}

    import logging
    log = logging.getLogger(__name__)

    # 根据 report_date 生成 sheet 名：用户名YYYY.MM
    import database as _db
    db2 = _db.get_db()
    user = db2.execute("SELECT display_name, username FROM users WHERE id=?", (user_id,)).fetchone()
    db2.close()
    user_name = (user['display_name'] or user['username']) if user else f"user{user_id}"
    month_key = (date_str or report_date)[:7].replace('-', '.')  # 2026-07-30 → 2026.07
    target_sheet = f"{user_name}{month_key}"

    try:
        import os
        creds_path = os.environ.get(
            "GOOGLE_SHEETS_CREDENTIALS_PATH",
            os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "config", "fit-boulevard-503111-u4-812bc02c2000.json")
        )
        service = build_service(creds_path)
        info = get_spreadsheet_info(service, spreadsheet_id)

        # 检查 sheet 是否存在
        existing_sheets = {s.get("name", ""): s for s in info.get("sheets", [])}
        if target_sheet not in existing_sheets:
            raise ValueError(f"Sheet「{target_sheet}」不存在，请先在表格中创建对应月份的表")

        # 读取目标 sheet 现有数据
        range_read = f"'{target_sheet}'!A:L"
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=range_read
            ).execute()
            existing = result.get("values", [])
        except Exception:
            existing = []

        # 找最后一行 + 最后日期
        last_row = 0
        last_date = ""
        for i in range(len(existing) - 1, -1, -1):
            row = existing[i]
            if any(cell for cell in row if cell):
                last_row = i + 1
                last_date = (row[0] or "").strip() if len(row) > 0 else ""
                break

        # 新日期 → 空一行
        if date_str and last_date and last_date != date_str:
            last_row += 1

        # 去重索引：按 (A=日期, D=账户ID)
        existing_map = {}
        for i, row in enumerate(existing):
            if len(row) > 3 and row[0] and row[3]:
                key = (row[0].strip(), row[3].strip())
                existing_map[key] = i

        # 构建写入数据
        updates = []
        for r in rows:
            row_data = [str(v) if not isinstance(v, (int, float)) else v for v in r]
            d = str(r[0]) if isinstance(r, list) else date_str
            acct_id = str(r[3]).lstrip("'") if isinstance(r, list) else ""
            key = (d, acct_id)

            if key in existing_map:
                row_idx = existing_map[key]
                range_write = f"'{target_sheet}'!A{row_idx + 1}:L{row_idx + 1}"
            else:
                last_row += 1
                range_write = f"'{target_sheet}'!A{last_row}:L{last_row}"

            updates.append({"range": range_write, "values": [row_data]})

        if updates:
            body = {"valueInputOption": "USER_ENTERED", "data": updates}
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id, body=body
            ).execute()

        log.info(f"FB sheets written: {len(updates)} rows to {spreadsheet_id}/{target_sheet}")
        return {"updated": len(updates), "sheet": target_sheet}
    except Exception as e:
        log.error(f"FB sheets write failed: {e}")
        raise
