"""音频替换历史按归属收窄 —— 安全审查 item-7（IDOR）。

**原状**（`audio_replace_history` 表在 `database.py` 的建表语句里**没有 owner 字段**，
唯一写入点 `main.py` 的音频替换端点也不记归属）：

- `GET  /api/audio-replace/history`      回**所有人**的记录，还带 `output_path`
  （服务端绝对路径）与指向它的 `download_url`；
- `DELETE /api/audio-replace/history/<id>` 按 id 删，**无归属** —— 任何登录用户可删
  **任何人**的记录，并**连带删掉磁盘上的产物文件**；
- `DELETE /api/audio-replace/history`   **清空整张表**并删光所有文件 ——
  一次抹掉全公司的历史。

三者都只挂 `@jwt_required() @no_huguan`，即对**任何登录的非户管用户**开放。

**口径**（2026-10-11）：
- 非 `CROSS_USER_ROLES` 只看/只删**自己名下**的记录；跨用户角色看全部、清全部。
- 删「不是自己的」记录返回 **404**（不是 403）—— `delete` 端点原有契约就是
  「记录不存在 → 404」，按归属过滤后二者合一，且不泄露「这条存在但不归你」。
- **存量行**（加列之前的历史）`owner_id` 为 **NULL** ⇒ 普通用户不可见、不可删
  （用户裁定：不凭空编造归属；跨用户角色仍看得到）。
- `GET /download` **不在本次范围**：`_download_authorized` 的 docstring 明写
  「产物在设计上是全局共享的」，签名分享是有意功能（形如「不公开列出、可凭链接访问」）。
"""
import os
import sys

import pytest

_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import database  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")


def _create_user(client, username, role="user", platform="gg"):
    """注册 → 改写 role/platform → 登录，返回 (headers, user_id)。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?",
               (role, platform, username))
    db.commit()
    uid = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    return {"Authorization": f"Bearer {resp.get_json()['access_token']}"}, uid


def _mk_row(db, name, owner_id):
    """直接落一条历史（绕过 ffmpeg）。owner_id 传 None 即模拟**存量行**。"""
    path = os.path.join("temp", "audio_out", f"{name}.mp4")
    db.execute(
        "INSERT INTO audio_replace_history"
        "(video_name, audio_name, output_name, output_path, size_mb, owner_id) "
        "VALUES(?,?,?,?,?,?)", (name, name, name, path, 1.0, owner_id))
    db.commit()
    return db.execute("SELECT id FROM audio_replace_history WHERE output_name=?",
                      (name,)).fetchone()["id"]


def _names(hdr, client):
    body = client.get("/api/audio-replace/history", headers=hdr).get_json()
    return {it["output_name"] for it in body["items"]}


def _exists(hid):
    db = database.get_db()
    n = db.execute("SELECT COUNT(*) FROM audio_replace_history WHERE id=?", (hid,)).fetchone()[0]
    db.close()
    return n == 1


class TestAudioReplaceHistoryOwnership:
    """列表 / 单删 / 清空三条腿都按归属收窄。"""

    # ---------------- 列表 ----------------

    def test_list_hides_others_records(self, client):
        """越权写照：不收窄时 B 会看到 A 的记录**连同服务端绝对路径**。"""
        a_hdr, a_id = _create_user(client, "ar_a")
        b_hdr, _ = _create_user(client, "ar_b")
        db = database.get_db()
        _mk_row(db, "A的产物", a_id)
        db.close()
        assert "A的产物" not in _names(b_hdr, client)

    def test_list_shows_own_records(self, client):
        """防过度收口。"""
        a_hdr, a_id = _create_user(client, "ar_a2")
        db = database.get_db()
        _mk_row(db, "A2的产物", a_id)
        db.close()
        assert "A2的产物" in _names(a_hdr, client)

    def test_legacy_row_without_owner_hidden_from_regular_user(self, client):
        """存量行（owner_id 为 NULL）对普通用户不可见 —— 不凭空编造归属。"""
        a_hdr, _ = _create_user(client, "ar_a3")
        db = database.get_db()
        _mk_row(db, "无主的存量产物", None)
        db.close()
        assert "无主的存量产物" not in _names(a_hdr, client)

    def test_legacy_row_visible_to_cross_user_role(self, client):
        """**放行腿**：存量行不能因为没主就彻底消失，跨用户角色要能看见。"""
        dev_hdr, _ = _create_user(client, "ar_dev3", role="developer")
        db = database.get_db()
        _mk_row(db, "无主的存量产物B", None)
        db.close()
        assert "无主的存量产物B" in _names(dev_hdr, client)

    def test_dev_sees_others_records(self, client):
        dev_hdr, _ = _create_user(client, "ar_dev4", role="developer")
        _, a_id = _create_user(client, "ar_a4")
        db = database.get_db()
        _mk_row(db, "A4的产物", a_id)
        db.close()
        assert "A4的产物" in _names(dev_hdr, client)

    # ---------------- 单删 ----------------

    def test_cannot_delete_others_record(self, client):
        """**这条最要紧**：缺归属时 B 删掉 A 的记录会**连带删掉磁盘上的产物**。"""
        _, a_id = _create_user(client, "ar_a5")
        b_hdr, _ = _create_user(client, "ar_b5")
        db = database.get_db()
        hid = _mk_row(db, "A5的产物", a_id)
        db.close()
        resp = client.delete(f"/api/audio-replace/history/{hid}", headers=b_hdr)
        assert resp.status_code == 404          # 按归属过滤后与「不存在」合一，不泄露存在性
        assert _exists(hid), "他人记录被删掉了"

    def test_can_delete_own_record(self, client):
        a_hdr, a_id = _create_user(client, "ar_a6")
        db = database.get_db()
        hid = _mk_row(db, "A6的产物", a_id)
        db.close()
        assert client.delete(f"/api/audio-replace/history/{hid}",
                             headers=a_hdr).status_code == 200
        assert not _exists(hid)

    def test_cannot_delete_legacy_row(self, client):
        """存量行无主 ⇒ 普通用户连删都删不掉（否则又是一条改数据的越权）。"""
        a_hdr, _ = _create_user(client, "ar_a7")
        db = database.get_db()
        hid = _mk_row(db, "无主的存量产物C", None)
        db.close()
        assert client.delete(f"/api/audio-replace/history/{hid}",
                             headers=a_hdr).status_code == 404
        assert _exists(hid)

    # ---------------- 清空 ----------------

    def test_clear_only_removes_own(self, client):
        """**最破坏性的一条**：原实现一次抹掉全公司历史 + 所有产物文件。"""
        _, a_id = _create_user(client, "ar_a8")
        b_hdr, b_id = _create_user(client, "ar_b8")
        db = database.get_db()
        a_row = _mk_row(db, "A8的产物", a_id)
        b_row = _mk_row(db, "B8的产物", b_id)
        legacy = _mk_row(db, "无主的存量产物D", None)
        db.close()

        assert client.delete("/api/audio-replace/history", headers=b_hdr).status_code == 200
        assert not _exists(b_row), "自己的记录应被清掉"
        assert _exists(a_row), "他人的记录**不得**被清掉"
        assert _exists(legacy), "存量无主行**不得**被普通用户清掉"

    def test_dev_clears_everything(self, client):
        """放行腿：跨用户角色的「清空」仍是全局清空。"""
        _, a_id = _create_user(client, "ar_a9")
        dev_hdr, _ = _create_user(client, "ar_dev9", role="developer")
        db = database.get_db()
        a_row = _mk_row(db, "A9的产物", a_id)
        legacy = _mk_row(db, "无主的存量产物E", None)
        db.close()
        assert client.delete("/api/audio-replace/history", headers=dev_hdr).status_code == 200
        assert not _exists(a_row)
        assert not _exists(legacy)
