"""邮件发送模块测试。"""
import pytest
from unittest.mock import patch, MagicMock, call


class TestSendDelistEmail:
    """测试掉包邮件通知发送。"""

    def test_sends_email_to_single_recipient(self):
        """发送单个收件人的掉包通知邮件。"""
        from email_sender import send_delist_notification, _SmtpConfig

        config = _SmtpConfig(
            host="smtp.qq.com",
            port=465,
            user="sender@qq.com",
            password="test-auth-code",
            from_name="GG-Server"
        )
        pkg_info = {
            "product_name": "测试产品",
            "series_name": "S1",
            "package_name": "com.test.app",
            "url": "https://play.google.com/store/apps/details?id=com.test.app",
        }

        mock_server = MagicMock()
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_server

        with patch("email_sender.smtplib.SMTP_SSL", return_value=mock_smtp):
            result = send_delist_notification(config, ["user@qq.com"], pkg_info)

        assert result is True
        mock_server.login.assert_called_once_with("sender@qq.com", "test-auth-code")
        mock_server.sendmail.assert_called_once()

    def test_sends_to_multiple_recipients(self):
        """发送给多个收件人。"""
        from email_sender import send_delist_notification, _SmtpConfig

        config = _SmtpConfig("smtp.qq.com", 465, "s@qq.com", "pwd")
        pkg_info = {"product_name": "P1", "series_name": "", "package_name": "com.test", "url": ""}

        mock_server = MagicMock()
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_server

        with patch("email_sender.smtplib.SMTP_SSL", return_value=mock_smtp):
            send_delist_notification(config, ["a@qq.com", "b@qq.com"], pkg_info)

        # sendmail 调用一次，收件人列表包含两个地址
        call_args = mock_server.sendmail.call_args
        assert call_args is not None
        recipients = call_args[0][1]
        assert "a@qq.com" in recipients
        assert "b@qq.com" in recipients

    def test_returns_false_on_smtp_error(self):
        """SMTP 连接失败返回 False 而非抛异常。"""
        from email_sender import send_delist_notification, _SmtpConfig

        config = _SmtpConfig("smtp.qq.com", 465, "s@qq.com", "pwd")
        pkg_info = {"product_name": "P1", "series_name": "", "package_name": "com.test", "url": ""}

        with patch("email_sender.smtplib.SMTP_SSL", side_effect=Exception("连接失败")):
            result = send_delist_notification(config, ["u@qq.com"], pkg_info)

        assert result is False

    def test_skips_empty_recipients(self):
        """空收件人列表直接返回 False，不发邮件。"""
        from email_sender import send_delist_notification, _SmtpConfig

        config = _SmtpConfig("smtp.qq.com", 465, "s@qq.com", "pwd")
        pkg_info = {"product_name": "P1", "series_name": "", "package_name": "com.test", "url": ""}

        with patch("email_sender.smtplib.SMTP_SSL") as mock_smtp_class:
            result = send_delist_notification(config, [], pkg_info)

        assert result is False
        mock_smtp_class.assert_not_called()

    def test_uses_ssl_protocol(self):
        """使用 SMTP_SSL 加密连接。"""
        from email_sender import send_delist_notification, _SmtpConfig

        config = _SmtpConfig("smtp.qq.com", 465, "s@qq.com", "pwd")
        pkg_info = {"product_name": "P1", "series_name": "", "package_name": "com.test", "url": ""}

        mock_server = MagicMock()
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_server

        with patch("email_sender.smtplib.SMTP_SSL", return_value=mock_smtp) as mock_ssl:
            send_delist_notification(config, ["u@qq.com"], pkg_info)

        mock_ssl.assert_called_once_with("smtp.qq.com", 465)


class TestGetRunnerEmails:
    """测试从数据库获取在跑人员邮箱。"""

    def test_returns_emails_for_runners_with_email(self):
        """返回有邮箱的在跑人员邮箱列表。"""
        from email_sender import get_runner_emails

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            {"email": "a@qq.com"},
            {"email": "b@qq.com"},
            {"email": ""},       # 没填邮箱
            {"email": None},     # 字段为 NULL
        ]

        emails = get_runner_emails(db, [1, 2, 3, 4])

        assert emails == ["a@qq.com", "b@qq.com"]

    def test_returns_empty_list_when_no_runners(self):
        """无在跑人员时返回空列表。"""
        from email_sender import get_runner_emails

        db = MagicMock()

        emails = get_runner_emails(db, [])

        assert emails == []
        db.execute.assert_not_called()
