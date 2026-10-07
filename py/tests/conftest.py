"""测试夹具 — Flask test client + 临时数据库 + JWT 认证。

运行方式：cd py && python -m pytest tests/ -v
"""
import os
import sys
import tempfile
import pytest

# 确保 py/ 目录在 sys.path 最前面（使 from main import app 生效）
_py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _py_dir not in sys.path:
    sys.path.insert(0, _py_dir)

import logging_setup  # noqa: E402

# 测试日志不落盘：必须抢在 main 导入之前占位。main.py 顶层会调
# setup_logging()，而该函数首次调用后即锁定是否写文件 —— 先在这里用
# enable_file=False 占位，main 那次调用就不会再加 FileHandler。
# 否则测试造的假故障会写进生产日志（2026-10-07 实测：mock 出来的
# WARNING「读投手看板备注失败…网络炸了」混进了 temp/logs/gg-server.log）。
logging_setup.setup_logging(enable_file=False)

from main import app as _flask_app  # noqa: E402
import database  # noqa: E402


@pytest.fixture
def app():
    """返回配置好的 Flask 测试应用，使用临时数据库。"""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    original_db_path = database._db_path
    database._db_path = lambda: db_path

    _flask_app.config.update({
        "TESTING": True,
        "JWT_SECRET_KEY": "test-secret-key",
    })

    yield _flask_app

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass
    database._db_path = original_db_path


@pytest.fixture
def client(app):
    """返回 Flask test client。"""
    return app.test_client()


@pytest.fixture
def auth_headers(client):
    """创建测试用户并返回带 JWT token 的请求头。"""
    client.post("/api/auth/register", json={
        "username": "testuser", "password": "test123",
    })
    resp = client.post("/api/auth/login", json={
        "username": "testuser", "password": "test123",
    })
    data = resp.get_json()
    token = data.get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tt_headers(client):
    """创建 TT 平台测试用户并返回带 JWT token 的请求头。"""
    client.post("/api/auth/register", json={
        "username": "ttuser", "password": "test123",
    })
    # 直接把用户平台改为 tt（register 默认 gg）
    db = database.get_db()
    db.execute("UPDATE users SET platform='tt' WHERE username='ttuser'")
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={
        "username": "ttuser", "password": "test123",
    })
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def dev_headers(client):
    """创建 developer 角色测试用户并返回带 JWT token 的请求头。"""
    client.post("/api/auth/register", json={
        "username": "devuser", "password": "test123",
    })
    db = database.get_db()
    db.execute("UPDATE users SET role='developer' WHERE username='devuser'")
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={
        "username": "devuser", "password": "test123",
    })
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def _make_user_with_headers(client, username, role, platform):
    """建用户 → 改角色/平台 → 登录 → 返回认证头。"""
    client.post("/api/auth/register", json={"username": username, "password": "test123"})
    db = database.get_db()
    db.execute("UPDATE users SET role=?, platform=? WHERE username=?", (role, platform, username))
    db.commit()
    db.close()
    resp = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    token = resp.get_json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_gg_headers(client):
    """GG 平台的 admin。"""
    return _make_user_with_headers(client, "admingg", "admin", "gg")


@pytest.fixture
def admin_tt_headers(client):
    """TT 平台的 admin。"""
    return _make_user_with_headers(client, "admintt", "admin", "tt")


@pytest.fixture
def admin_fb_headers(client):
    """FB 平台的 admin。"""
    return _make_user_with_headers(client, "adminfb", "admin", "fb")


@pytest.fixture
def huguan_headers(client):
    """户管。"""
    return _make_user_with_headers(client, "huguanuser", "huguan", "gg")
