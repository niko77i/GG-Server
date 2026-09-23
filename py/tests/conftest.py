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
