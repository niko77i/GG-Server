"""签名 URL 工具的单测。

全部为纯函数测试，不依赖 Flask app / 数据库。
"""
import time

from url_signing import sign_query, verify_query

SECRET = "unit-test-secret"
EP = "/api/video/download"
PATH = r"D:\data\temp\video\out.mp4"


def _parse(qs):
    """把 sign_query 的输出解析成 dict。"""
    out = {}
    for part in qs.split("&"):
        k, _, v = part.partition("=")
        out[k] = v
    return out


class TestSignVerify:
    def test_valid_signature_verifies(self):
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET) is True

    def test_tampered_path_rejected(self):
        """承重：改 path 必须失效（否则签名形同虚设，可下任意文件）。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, r"D:\data\temp\video\OTHER.mp4",
                            p["exp"], p["sig"], SECRET) is False

    def test_tampered_exp_rejected(self):
        """承重：改 exp 必须失效（否则可把过期时间改到 2099 年）。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, str(int(p["exp"]) + 999999), p["sig"], SECRET) is False

    def test_cross_endpoint_reuse_rejected(self):
        """承重：一个端点的签名不能挪用到另一个端点。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query("/api/scrape/download", PATH, p["exp"], p["sig"], SECRET) is False

    def test_wrong_secret_rejected(self):
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, p["exp"], p["sig"], "other-secret") is False

    def test_expired_rejected(self):
        """过期必须失效。用注入的 now 做确定性测试，不 sleep。"""
        now = 1_000_000.0
        qs = sign_query(EP, PATH, SECRET, ttl=300, now=now)
        p = _parse(qs)
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=now + 301) is False
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=now + 299) is True

    def test_exp_boundary_is_exclusive(self):
        """钉死 exp 语义：**exp 那一刻本身即失效**（与 JWT 一致）。

        为什么必须有这条：`test_expired_rejected` 用 now+299 / now+301 对称地
        ±1 绕开了等号，因此**无法区分 `<` 与 `<=`** —— 有人把判据改松、改严，
        现有测试都全绿、零信号。这条专门钉住等号那一点。
        """
        now = 1_000_000.0
        qs = sign_query(EP, PATH, SECRET, ttl=300, now=now)
        p = _parse(qs)
        exp = int(p["exp"])  # = 1_000_300

        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=exp) is False, (
            "now == exp 时签名仍被接受 —— exp 这一刻应已失效（与 JWT 语义一致）"
        )
        assert verify_query(EP, PATH, p["exp"], p["sig"], SECRET, now=exp - 1) is True, (
            "now == exp-1 时签名被拒 —— 有效期右端点被收得过紧"
        )

    def test_missing_fields_rejected(self):
        """缺任一字段 ⇒ False（不得因「空签名匹配空签名」而放行）。"""
        assert verify_query(EP, PATH, "", "", SECRET) is False
        assert verify_query(EP, PATH, "abc", "", SECRET) is False
        assert verify_query(EP, PATH, "", "abc", SECRET) is False

    def test_non_numeric_exp_rejected(self):
        """exp 非数字 ⇒ False，不得抛异常（异常逸出会变成 500）。"""
        qs = sign_query(EP, PATH, SECRET)
        p = _parse(qs)
        assert verify_query(EP, PATH, "not-a-number", p["sig"], SECRET) is False


class TestPathEncoding:
    def test_windows_path_roundtrip(self):
        """Windows 反斜杠路径经 URL 编码后必须能原样还原（本项目路径全为 Windows 形式）。"""
        from urllib.parse import parse_qs
        qs = sign_query(EP, PATH, SECRET)
        got = parse_qs(qs)["path"][0]
        assert got == PATH
