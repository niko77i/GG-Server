"""Telegram 通知模块测试。"""
import pytest
from unittest.mock import patch, MagicMock


class TestBuildProductMessage:
    """测试产品级掉包消息构建。"""

    def test_builds_message_with_product_and_series(self):
        from telegram_sender import _build_product_message
        msg = _build_product_message("某游戏", ["东南亚", "巴西"], ["carl567"])
        assert "【GG-Server 掉包通知】" in msg
        assert "产品：" in msg and "某游戏" in msg
        assert "东南亚" in msg
        assert "巴西" in msg
        assert "@carl567" in msg
        assert "com.example" not in msg  # 不展示包名

    def test_escapes_html_special_chars(self):
        from telegram_sender import _build_product_message
        msg = _build_product_message("<游戏>&", ["<系列>"], [])
        assert "&lt;" in msg and "&amp;" in msg

    def test_no_mentions_when_usernames_empty(self):
        from telegram_sender import _build_product_message
        msg = _build_product_message("P1", ["S1"], [])
        assert "@" not in msg


class TestSendProductDelistNotification:
    """测试产品级掉包通知发送。"""

    def test_sends_message(self):
        from telegram_sender import send_product_delist_notification, _TelegramConfig
        config = _TelegramConfig(bot_token="token123", chat_id="chat123")
        with patch("telegram_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {}
            mock_post.return_value = mock_resp
            result = send_product_delist_notification(config, "P1", ["S1"], ["u1"])
        assert result is True
        mock_post.assert_called_once()

    def test_returns_false_without_config(self):
        from telegram_sender import send_product_delist_notification, _TelegramConfig
        config = _TelegramConfig(bot_token="", chat_id="")
        result = send_product_delist_notification(config, "P1", ["S1"], [])
        assert result is False

    def test_returns_false_on_error(self):
        from telegram_sender import send_product_delist_notification, _TelegramConfig
        config = _TelegramConfig(bot_token="t", chat_id="c")
        with patch("telegram_sender.requests.post", side_effect=Exception("boom")):
            result = send_product_delist_notification(config, "P1", ["S1"], [])
        assert result is False
