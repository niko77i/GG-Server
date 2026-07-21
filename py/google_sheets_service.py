"""Google Sheets API 客户端 — 读取和写入 Google 在线表格。

独立服务模块，通过 Flask API 路由调用。
参照 google_ads_service.py 模式设计。
"""

import os
import json
import logging

log = logging.getLogger("gg-server")

# Google Sheets API 权限范围（仅电子表格，最小权限原则）
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# 内存中暂存授权中的 flow（state → flow 映射）
_pending_flows = {}


class GoogleSheetsServiceError(Exception):
    """Google Sheets 服务错误。"""
    pass


class AuthRequiredError(GoogleSheetsServiceError):
    """需要 OAuth 授权（token 不存在且无法刷新）。"""
    pass


def check_configured(credentials_path: str) -> dict:
    """检查 Google Sheets API 配置状态（纯本地文件检查，无需网络）。

    Args:
        credentials_path: OAuth 客户端凭据 JSON 文件的绝对路径

    Returns:
        {
            "configured": bool,       # 凭据文件存在且格式有效
            "has_credentials": bool,  # client_id 可正常读取
            "has_token": bool,        # token 文件已存在（已完成用户授权）
            "message": str,           # 人类可读的状态描述
        }
    """
    result = {
        "configured": False,
        "has_credentials": False,
        "has_token": False,
        "message": "",
    }

    # 检查凭据文件
    if not credentials_path or not os.path.isfile(credentials_path):
        result["message"] = "凭据文件不存在，请在 GCP 控制台下载 OAuth 客户端 JSON 文件"
        return result

    try:
        with open(credentials_path, "r", encoding="utf-8") as f:
            creds_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        result["message"] = f"凭据文件格式无效: {e}"
        return result

    # 验证凭据文件结构（桌面应用类型）
    installed = creds_data.get("installed", {})
    if not installed.get("client_id") or not installed.get("client_secret"):
        result["message"] = "凭据文件缺少 client_id 或 client_secret 字段"
        return result

    result["has_credentials"] = True

    # 推断 token 文件路径（与凭据文件同目录）
    token_dir = os.path.dirname(credentials_path)
    token_path = os.path.join(token_dir, "google_sheets_token.json")

    if os.path.isfile(token_path):
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                token_data = json.load(f)
            if token_data.get("refresh_token") or token_data.get("token"):
                result["has_token"] = True
                result["message"] = "已配置且已授权，可以正常使用 Google Sheets API"
            else:
                result["message"] = "Token 文件存在但格式无效，需要重新授权"
        except (json.JSONDecodeError, IOError):
            result["message"] = "Token 文件损坏，需要重新授权"
    else:
        result["message"] = "凭据已就位，但尚未完成 OAuth 授权（需首次运行时在浏览器中授权）"

    result["configured"] = True
    return result


def _get_credentials(credentials_path: str, token_path: str, auto_auth: bool = True):
    """获取 OAuth 2.0 凭据。

    auto_auth=True:  首次调用时启动本地 HTTP 服务器阻塞等待 OAuth 回调
    auto_auth=False: token 无效时抛出 AuthRequiredError，不阻塞

    Returns:
        google.oauth2.credentials.Credentials 对象

    Raises:
        AuthRequiredError: auto_auth=False 且 token 无效/不存在
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None

    if os.path.isfile(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            log.info("Google Sheets: 从缓存文件加载 token 成功")
        except Exception as e:
            log.warning("Google Sheets: 加载缓存 token 失败: %s", e)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Google Sheets: token 已过期，尝试刷新")
            try:
                creds.refresh(Request())
                log.info("Google Sheets: token 刷新成功")
            except Exception as e:
                log.warning("Google Sheets: token 刷新失败: %s", e)
                creds = None

        if not creds:
            if not os.path.isfile(credentials_path):
                raise GoogleSheetsServiceError(
                    f"凭据文件不存在: {credentials_path}"
                )
            if auto_auth:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, SCOPES
                )
                log.info("Google Sheets: 启动本地 OAuth 授权服务器...")
                creds = flow.run_local_server(port=0)
                log.info("Google Sheets: OAuth 授权完成")
            else:
                raise AuthRequiredError(
                    "需要 Google Sheets 授权，请通过 /api/google-sheets/auth-url 获取授权链接"
                )

        token_dir = os.path.dirname(token_path)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        log.info("Google Sheets: token 已缓存到 %s", token_path)

    return creds


def generate_auth_url(credentials_path: str) -> str:
    """生成 Google OAuth 授权 URL。

    用户在浏览器中打开此 URL 完成授权后，
    Google 会重定向到 localhost:PORT/?code=...&state=...
    将浏览器地址栏中的完整 URL 复制下来传给 complete_auth() 即可。

    Returns:
        授权 URL 字符串
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.isfile(credentials_path):
        raise GoogleSheetsServiceError(f"凭据文件不存在: {credentials_path}")

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    _pending_flows[state] = flow
    log.info("Google Sheets: 已生成授权 URL (state=%s)", state)
    return auth_url


def complete_auth(redirect_url: str, token_path: str) -> bool:
    """用授权回调 URL 完成 OAuth，保存 token。

    Args:
        redirect_url: 用户授权后浏览器地址栏中的完整 URL
        token_path: token 缓存文件路径

    Returns:
        True 表示成功

    Raises:
        GoogleSheetsServiceError: code 缺失或 state 无效
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    state = params.get("state", [None])[0]

    if not code:
        raise GoogleSheetsServiceError("重定向 URL 中缺少授权码 (code)")
    if not state:
        raise GoogleSheetsServiceError("重定向 URL 中缺少 state")

    flow = _pending_flows.pop(state, None)
    if not flow:
        raise GoogleSheetsServiceError(
            "授权会话已过期或 state 不匹配，请重新发起授权"
        )

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise GoogleSheetsServiceError(f"换取 token 失败: {e}") from e

    creds = flow.credentials

    token_dir = os.path.dirname(token_path)
    if token_dir:
        os.makedirs(token_dir, exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    log.info("Google Sheets: OAuth 授权完成，token 已保存到 %s", token_path)
    return True


def build_service(credentials_path: str, token_path: str, auto_auth: bool = False):
    """构建 Google Sheets API v4 服务对象。

    Args:
        credentials_path: OAuth 客户端凭据 JSON 文件路径
        token_path: token 缓存文件路径
        auto_auth: 是否在需要授权时自动启动本地 OAuth 服务器（默认 False）

    Returns:
        googleapiclient.discovery.Resource 对象

    Raises:
        GoogleSheetsServiceError: 凭据无效或授权失败
        AuthRequiredError: auto_auth=False 且需要用户授权
    """
    from googleapiclient.discovery import build

    try:
        creds = _get_credentials(credentials_path, token_path, auto_auth=auto_auth)
        service = build("sheets", "v4", credentials=creds)
        return service
    except Exception as e:
        raise GoogleSheetsServiceError(
            f"构建 Google Sheets 服务失败: {e}"
        ) from e


def get_spreadsheet_info(service, spreadsheet_id: str) -> dict:
    """获取表格标题和所有 sheet（tab）信息，解析运营名。

    Args:
        service: Google Sheets API 服务对象
        spreadsheet_id: 表格 ID

    Returns:
        {
            "title": "卡尔202607",
            "operator": "卡尔",
            "year_month": "202607",
            "sheets": [{"name": "Sheet1", "gid": 0}, ...]
        }
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
        })

    return {
        "title": title,
        "operator": operator,
        "year_month": year_month,
        "sheets": sheets,
    }


def upsert_zuobiao(service, spreadsheet_id: str, sheet_gid: str, rows: list,
                   product_name: str, region: str, report_date: str,
                   sales_person: str, agency_ratio, operator_name: str) -> dict:
    """将做表数据 upsert 到 Google Sheets。

    以 (日期, 客户ID, 渠道号) 为唯一键，
    匹配到则覆盖该行，未匹配则追加到表格末尾。

    Args:
        service: Google Sheets API 服务对象
        spreadsheet_id: 表格 ID
        sheet_gid: sheet 的 gid（字符串数字）
        rows: 做表数据行 [{account, customerId, cost, campaign}, ...]
        product_name: 产品名 → G列
        region: 投放国家 → I列
        report_date: 日期 YYYY-MM-DD → A列
        sales_person: 商务 → H列
        agency_ratio: 代投比例（数字）→ L列，格式化为 "6%"
        operator_name: 运营名 → B列

    Returns:
        {"updated": int, "inserted": int}
    """
    # 1. 将 gid 转为 sheet 名称
    info = get_spreadsheet_info(service, spreadsheet_id)
    sheet_name = "Sheet1"
    for s in info.get("sheets", []):
        if str(s.get("gid", 0)) == str(sheet_gid):
            sheet_name = s["name"]
            break

    # 2. 读取现有数据（A-N 列）
    range_read = f"'{sheet_name}'!A:N"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_read,
    ).execute()
    existing = result.get("values", [])

    # 3. 构建索引：(日期, 客户ID, 渠道号) -> 行号(0-based)
    existing_index = {}
    for i, row in enumerate(existing):
        if len(row) >= 10:
            key = (
                (row[0] or "").strip() if len(row) > 0 else "",
                (row[3] or "").strip() if len(row) > 3 else "",
                (row[9] or "").strip() if len(row) > 9 else "",
            )
            if key[0] or key[1] or key[2]:
                existing_index[key] = i

    # 4. 构建新行（14列 A-N）
    percent_str = f"{int(agency_ratio)}%" if agency_ratio is not None else ""
    new_rows = []
    for row in rows:
        new_rows.append([
            report_date,                     # A: 日期
            operator_name,                   # B: 运营
            row.get("account", ""),          # C: 账户名称
            str(row.get("customerId", "")),  # D: 广告账户ID（强制文本）
            row.get("cost", 0),              # E: 账号消耗（数字）
            "",                              # F: 报给客户
            product_name,                    # G: 客户名称
            sales_person or "",              # H: 商务
            region,                          # I: 投放国家
            row.get("campaign", ""),         # J: 渠道号
            "",                              # K: 平台实际
            percent_str,                     # L: 代投比例
            "",                              # M: 代投费
            "",                              # N: 利润
        ])

    # 5. 分拣：更新 vs 新增
    updates = []
    appends = []
    for new_row in new_rows:
        key = (new_row[0], new_row[3], new_row[9])
        if key in existing_index:
            updates.append((existing_index[key], new_row))
        else:
            appends.append(new_row)

    # 6. 批量更新已存在的行
    for row_idx, row_data in updates:
        range_write = f"'{sheet_name}'!A{row_idx + 1}:N{row_idx + 1}"
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_write,
            valueInputOption="USER_ENTERED",
            body={"values": [row_data]},
        ).execute()

    # 7. 追加新行到末尾
    if appends:
        range_append = f"'{sheet_name}'!A:N"
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_append,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": appends},
        ).execute()

    # 8. 格式化 D列（文本）、E列（数字）
    sheet_id_int = int(sheet_gid) if str(sheet_gid).isdigit() else 0
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id_int,
                    "startColumnIndex": 3,
                    "endColumnIndex": 4,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "TEXT"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat"
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id_int,
                    "startColumnIndex": 4,
                    "endColumnIndex": 5,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat"
            }
        }
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()

    return {"updated": len(updates), "inserted": len(appends)}
