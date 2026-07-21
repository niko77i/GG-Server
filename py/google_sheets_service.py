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
        m = re.match(r'^(\D+)(\d{6})$', title)
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
    for i in range(len(existing) - 1, -1, -1):
        row = existing[i]
        if any(row[j] for j in range(min(10, len(row))) if row[j]):
            last_row = i + 1
            break

    # 3. 构建索引
    existing_index = {}
    for i, row in enumerate(existing):
        d = (row[0] or "").strip() if len(row) > 0 else ""
        cid = (row[3] or "").strip() if len(row) > 3 else ""
        cam = (row[9] or "").strip() if len(row) > 9 else ""
        if d or cid or cam:
            existing_index[(d, cid, cam)] = i

    # 4. 构建新行
    percent_str = f"{int(agency_ratio)}%" if agency_ratio is not None else ""
    new_rows = []
    for row in rows:
        new_rows.append([
            report_date, operator_name,
            row.get("account", ""), str(row.get("customerId", "")),
            row.get("cost", 0), "",
            product_name, sales_person or "", region,
            row.get("campaign", ""), "", percent_str, "", "",
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
            data.append({
                "range": f"'{sheet_name}'!A{row_idx + 1}:N{row_idx + 1}",
                "values": [row_data],
            })
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        ).execute()

    # 7. 追加新行（用 info 中的 rowCount，不再调 API）
    if appends:
        start = last_row + 1
        end = last_row + len(appends)
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
