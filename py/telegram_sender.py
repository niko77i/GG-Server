"""Telegram 通知模块 — 通过 Telegram Bot API 发送掉包通知到群组。"""

from dataclasses import dataclass

import requests

# Telegram Bot API 基础 URL
_BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

# 请求超时秒数
_TIMEOUT = 10


@dataclass
class _TelegramConfig:
    """Telegram Bot 配置。"""
    bot_token: str
    chat_id: str
    parse_mode: str = "HTML"


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符，防止 Telegram API 报错（400 Bad Request）。

    在 parse_mode=HTML 模式下，只有 <b>、<i>、<u>、<s>、<code>、
    <pre>、<a href> 是合法标签。文本中的 &、<、> 必须被转义。
    """
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _build_mentions(usernames: list[str]) -> str:
    """构建 @提及字符串。

    Args:
        usernames: Telegram 用户名列表（不带 @ 前缀）

    Returns:
        如 "@carl567 @zhangsan"，usernames 为空时返回 ""
    """
    if not usernames:
        return ""
    return " ".join(f"@{u}" for u in usernames)


def _build_message(pkg_info: dict, usernames: list[str]) -> str:
    """构建发往 Telegram 的通知消息正文（HTML 格式）。

    Args:
        pkg_info: 包含 product_name, series_name, package_name, url 的字典
        usernames: Telegram 用户名列表（不带 @ 前缀）

    Returns:
        HTML 格式的通知消息
    """
    product_name = _escape_html(pkg_info.get("product_name", "") or "-")
    series_name = _escape_html(pkg_info.get("series_name", "") or "-")
    package_name = _escape_html(pkg_info.get("package_name", "") or "-")
    url = pkg_info.get("url", "")

    mentions = _build_mentions(usernames)

    lines = [
        "<b>【GG-Server 掉包通知】</b>",
    ]

    if mentions:
        lines.append("")
        lines.append(mentions)

    lines.extend([
        "",
        f"<b>产品：</b>{product_name}",
        f"<b>系列：</b>{series_name}",
        f"<b>包名：</b><code>{package_name}</code>",
    ])

    if url:
        escaped_url = _escape_html(url)
        lines.append(f'<b>链接：</b><a href="{escaped_url}">Google Play</a>')
    else:
        lines.append("<b>链接：</b>-")

    lines.extend([
        "",
        '该包已被下架，请尽快将包状态设置为"掉包"。',
    ])

    return "\n".join(lines)


def send_delist_notification(
    config: _TelegramConfig,
    pkg_info: dict,
    usernames: list[str],
) -> bool:
    """发送掉包通知到 Telegram 群组。

    Args:
        config: Telegram Bot 配置
        pkg_info: 包含 product_name, series_name, package_name, url 的字典
        usernames: Telegram 用户名列表（不带 @ 前缀），空列表表示不 @任何人

    Returns:
        True 表示发送成功，False 表示失败
    """
    if not config.bot_token or not config.chat_id:
        return False

    text = _build_message(pkg_info, usernames)

    payload = {
        "chat_id": config.chat_id,
        "text": text,
        "parse_mode": config.parse_mode,
        "disable_web_page_preview": True,
    }

    url = _BASE_URL.format(token=config.bot_token)

    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        data = resp.json()
        if not resp.ok:
            description = data.get("description", resp.text)
            print(f"[Telegram] 发送失败: {description}")
            return False
        return True
    except requests.Timeout:
        print("[Telegram] 发送超时")
        return False
    except requests.ConnectionError:
        print("[Telegram] 网络连接失败")
        return False
    except Exception as e:
        print(f"[Telegram] 发送异常: {e}")
        return False
