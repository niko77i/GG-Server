"""邮件通知模块 — 通过 SMTP 发送掉包通知邮件。"""

import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from dataclasses import dataclass


@dataclass
class _SmtpConfig:
    """SMTP 连接配置。"""
    host: str
    port: int
    user: str
    password: str
    from_name: str = "GG-Server"


def get_runner_emails(db, runner_ids: list[int]) -> list[str]:
    """获取在跑人员中已配置邮箱的列表。

    Args:
        db: 数据库连接
        runner_ids: 在跑人员用户 ID 列表

    Returns:
        有效的邮箱地址列表（已过滤空值和 NULL）
    """
    if not runner_ids:
        return []

    placeholders = ",".join("?" * len(runner_ids))
    rows = db.execute(
        f"SELECT email FROM users WHERE id IN ({placeholders})",
        runner_ids
    ).fetchall()

    emails = []
    for r in rows:
        email = (r["email"] or "").strip()
        if email:
            emails.append(email)
    return emails


def send_delist_notification(
    config: _SmtpConfig,
    recipients: list[str],
    pkg_info: dict,
) -> bool:
    """发送掉包通知邮件。

    Args:
        config: SMTP 配置
        recipients: 收件人邮箱列表
        pkg_info: 包含 product_name, series_name, package_name, url 的字典

    Returns:
        True 表示发送成功，False 表示失败
    """
    if not recipients:
        return False

    product_name = pkg_info.get("product_name", "")
    series_name = pkg_info.get("series_name", "")
    package_name = pkg_info.get("package_name", "")
    url = pkg_info.get("url", "")

    subject = f"[GG-Server] 检测到包掉包 - {package_name}"
    body = f"""【GG-Server 掉包通知】

产品：{product_name}
系列：{series_name or '-'}
包名：{package_name}
链接：{url or '-'}

该包在 Google Play 上已被下架，请尽快将包状态设置为"掉包"。

---
此邮件由 GG-Server 自动发送"""

    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header(config.from_name, "utf-8")), config.user))
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL(config.host, config.port) as server:
            server.login(config.user, config.password)
            msg["To"] = ", ".join(recipients)
            server.sendmail(config.user, recipients, msg.as_string())
        return True
    except Exception:
        return False
