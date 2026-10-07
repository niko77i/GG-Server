"""定时任务：权限、周期配置、调度计算。

运行：cd py && python -m pytest tests/test_scheduler_config.py -v
"""
import json
import pytest
from flask import jsonify
from flask_jwt_extended import jwt_required

import database
from main import app as _shared_app
from routes.decorators import scheduler_required


# 探针路由：直接测装饰器本身（不依赖 Task 4 才落地的真实接口）。
#
# ⚠️ 为何注册在模块级、而不是 fixture 里：
# conftest.py 的 app fixture 复用的是 main.py 的全局 app 单例（跨测试同一个对象），
# 且 Flask 3 在 app 处理过首个请求后即锁定，再调 @app.route 会抛
# 「The setup method 'route' can no longer be called on the application」。
# 若放在 fixture 中逐测试注册，第一个用到的测试能过、其后全部报错。
# 模块导入发生在本次会话的任何请求之前、且每进程只执行一次，故在此注册一次。
@_shared_app.route("/api/_probe/gg", methods=["POST"], endpoint="_probe_gg")
@jwt_required()
@scheduler_required("gg")
def _probe_gg():
    return jsonify(success=True, platform="gg")


@_shared_app.route("/api/_probe/tt", methods=["POST"], endpoint="_probe_tt")
@jwt_required()
@scheduler_required("tt")
def _probe_tt():
    return jsonify(success=True, platform="tt")


@pytest.fixture
def probe_client(app):
    """返回挂了探针路由的 test client。"""
    return app.test_client()


class TestSchedulerRequired:
    def test_developer_passes_both_platforms(self, probe_client, dev_headers):
        """developer 跨平台放行。"""
        assert probe_client.post("/api/_probe/gg", headers=dev_headers).status_code == 200
        assert probe_client.post("/api/_probe/tt", headers=dev_headers).status_code == 200

    def test_gg_admin_passes_gg_only(self, probe_client, admin_gg_headers):
        """GG 管理员：自己的平台放行，别的平台 403。"""
        assert probe_client.post("/api/_probe/gg", headers=admin_gg_headers).status_code == 200
        assert probe_client.post("/api/_probe/tt", headers=admin_gg_headers).status_code == 403

    def test_tt_admin_passes_tt_only(self, probe_client, admin_tt_headers):
        assert probe_client.post("/api/_probe/tt", headers=admin_tt_headers).status_code == 200
        assert probe_client.post("/api/_probe/gg", headers=admin_tt_headers).status_code == 403

    def test_fb_admin_passes_neither(self, probe_client, admin_fb_headers):
        """FB 管理员：两个探针都 403（FB 没有定时任务）。"""
        assert probe_client.post("/api/_probe/gg", headers=admin_fb_headers).status_code == 403
        assert probe_client.post("/api/_probe/tt", headers=admin_fb_headers).status_code == 403

    def test_huguan_rejected(self, probe_client, huguan_headers):
        """⚠️ 核心对照腿：户管必须被拒。

        require_platform() 的 PLATFORM_SWITCH_ROLES 含 HUGUAN_ROLE，会放行户管 ——
        若有人图省事改用 require_platform，本类会红。
        """
        assert probe_client.post("/api/_probe/gg", headers=huguan_headers).status_code == 403
        assert probe_client.post("/api/_probe/tt", headers=huguan_headers).status_code == 403

    def test_plain_user_rejected(self, probe_client, auth_headers):
        """普通 user（platform=gg）也是 403 —— 只有 admin 才够格，平台匹配不是唯一条件。"""
        assert probe_client.post("/api/_probe/gg", headers=auth_headers).status_code == 403
