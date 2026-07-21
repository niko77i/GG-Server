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


class GoogleSheetsServiceError(Exception):
    """Google Sheets 服务错误。"""
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


def _get_credentials(credentials_path: str, token_path: str):
    """获取 OAuth 2.0 凭据（含 token 缓存和自动刷新）。

    首次调用时启动本地 HTTP 服务器完成 OAuth 授权流程，
    之后将 token 缓存到 token_path 文件中，下次启动自动复用。

    Args:
        credentials_path: OAuth 客户端凭据 JSON 文件路径
        token_path: token 缓存文件路径（不存在则创建）

    Returns:
        google.oauth2.credentials.Credentials 对象
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None

    # 尝试从缓存文件加载已有 token
    if os.path.isfile(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            log.info("Google Sheets: 从缓存文件加载 token 成功")
        except Exception as e:
            log.warning("Google Sheets: 加载缓存 token 失败: %s", e)

    # 如果没有有效凭据，启动 OAuth 流程
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Google Sheets: token 已过期，尝试刷新")
            try:
                creds.refresh(Request())
                log.info("Google Sheets: token 刷新成功")
            except Exception as e:
                log.warning("Google Sheets: token 刷新失败，将重新授权: %s", e)
                creds = None

        if not creds:
            # 首次授权 —— 启动本地服务器
            if not os.path.isfile(credentials_path):
                raise GoogleSheetsServiceError(
                    f"凭据文件不存在: {credentials_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES
            )
            log.info("Google Sheets: 启动本地 OAuth 授权服务器...")
            creds = flow.run_local_server(port=0)
            log.info("Google Sheets: OAuth 授权完成")

        # 缓存 token 到文件
        token_dir = os.path.dirname(token_path)
        if token_dir:
            os.makedirs(token_dir, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        log.info("Google Sheets: token 已缓存到 %s", token_path)

    return creds


def build_service(credentials_path: str, token_path: str):
    """构建 Google Sheets API v4 服务对象。

    Args:
        credentials_path: OAuth 客户端凭据 JSON 文件路径
        token_path: token 缓存文件路径

    Returns:
        googleapiclient.discovery.Resource 对象

    Raises:
        GoogleSheetsServiceError: 凭据无效或授权失败
    """
    from googleapiclient.discovery import build

    try:
        creds = _get_credentials(credentials_path, token_path)
        service = build("sheets", "v4", credentials=creds)
        return service
    except Exception as e:
        raise GoogleSheetsServiceError(
            f"构建 Google Sheets 服务失败: {e}"
        ) from e
