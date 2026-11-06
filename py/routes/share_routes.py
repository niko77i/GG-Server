"""共享账号网关的 HTTP 入口（GG-Server 侧）。

设计见 docs/superpowers/specs/2026-11-06-shared-account-gateway-design.md。
权限：
- 列表 / 进入：任意已登录用户（viewer 也可浏览，只读视角）
- 管理（日志 / 清空会话 / 启用停用 / 探测）：仅 developer
"""
import datetime
import socket

from flask import Blueprint, current_app, request
from flask_jwt_extended import jwt_required

import auth
from routes.decorators import developer_required
from routes.helpers import err, get_uid, ok
from share_gateway import runner, store, ticket

share_bp = Blueprint("share", __name__)

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0", ""}


def _local_ips() -> set[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.5)
        probe.connect(("223.5.5.5", 80))
        ips.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return {ip for ip in ips if ip and ip not in _LOOPBACK}


def _preferred_local_ip() -> str:
    """本机对外地址：优先 Tailscale（100.64.0.0/10），其次内网网段。

    团队成员是通过 Tailscale 访问 GG-Server 的（100.x），所以回退时优先给 Tailscale 地址。
    """
    ips = _local_ips()
    tailscale = []
    for ip in ips:
        parts = ip.split(".")
        if len(parts) == 4 and parts[0] == "100":
            try:
                if 64 <= int(parts[1]) <= 127:
                    tailscale.append(ip)
            except ValueError:
                continue
    if tailscale:
        return sorted(tailscale)[0]
    for prefix in ("192.168.", "10.", "172."):
        hits = sorted(ip for ip in ips if ip.startswith(prefix))
        if hits:
            return hits[0]
    return ""


def _public_host(request_host: str) -> str:
    """拼网关 URL 用的主机名。

    - 浏览器用的是**域名** → 原样复用（同事能解析）；
    - 用的是 **Tailscale IP（100.64/10）** → 原样复用；
    - 用的是**内网 IP（10/172.16/192.168）** → 换成 Tailscale IP（若本机有）。
      团队成员基本都走 Tailscale，内网 IP 对不在同一局域网的人不可达，
      浏览器会报「无法访问 / 请检查防火墙」——2026-11-06 阿伟踩到；
    - 在服务器本机用 127.0.0.1 打开 → 用配置的 public_host 或本机对外 IP。
    """
    raw_host = (request_host or "").split(":")[0].strip()
    host = raw_host.lower()
    if host and host not in _LOOPBACK:
        if _is_private_lan_ip(host):
            lan = _preferred_local_ip()
            if lan and lan != host:
                return lan
        return raw_host
    cfg = current_app.config.get("SHARE_GATEWAY_CFG") or {}
    configured = str(cfg.get("public_host") or "").strip()
    if configured:
        return configured
    return _preferred_local_ip() or raw_host or "127.0.0.1"


def _is_private_lan_ip(host: str) -> bool:
    parts = host.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if any(n < 0 or n > 255 for n in nums):
        return False
    return (nums[0] == 10
            or (nums[0] == 172 and 16 <= nums[1] <= 31)
            or (nums[0] == 192 and nums[1] == 168))


def _secret() -> str:
    return current_app.config.get("JWT_SECRET_KEY") or "gg-server-default-secret"


def _configured_sites() -> list[dict]:
    cfg = current_app.config.get("SHARE_GATEWAY_CFG") or {}
    return [s for s in (cfg.get("sites") or []) if isinstance(s, dict) and s.get("id")]


def _fmt_ts(epoch) -> str | None:
    if not epoch:
        return None
    try:
        return datetime.datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return None


def _site_view(cfg_site: dict, can_manage: bool) -> dict:
    site_id = cfg_site["id"]
    row = store.get_site(site_id) or {}
    enabled = bool(row.get("enabled", 1)) if row else bool(cfg_site.get("enabled", True))
    rt = runner.get_runtime(site_id)

    if not enabled:
        status = "disabled"
    elif rt is None or not getattr(rt, "listening", False):
        status = "down"
    else:
        status = rt.status

    expires_at = None
    last_error = None
    cookie_count = 0
    if rt is not None:
        desc = rt.describe()
        expires_at = _fmt_ts(desc.get("expires_at"))
        last_error = desc.get("last_error")
        cookie_count = desc.get("cookie_count") or 0

    session_row = store.get_session(site_id) or {}
    try:
        today = store.today_users(site_id)
        last = store.last_access(site_id)
    except Exception:
        today, last = 0, None

    return {
        "id": site_id,
        "name": cfg_site.get("name") or row.get("name") or site_id,
        "upstream": cfg_site.get("upstream") or row.get("upstream") or "",
        "port": int(cfg_site.get("port") or row.get("port") or 0),
        "enabled": enabled,
        "running": bool(rt is not None and getattr(rt, "listening", False)),
        "status": status,
        "last_error": last_error or session_row.get("last_error"),
        "expires_at": expires_at,
        "cookie_count": cookie_count,
        "session_updated_at": session_row.get("updated_at"),
        "last_ok_at": session_row.get("last_ok_at"),
        "today_users": today,
        "last_access": last,
        "can_manage": can_manage,
    }


@share_bp.route("/sites", methods=["GET"])
@jwt_required()
def share_sites_list():
    user = auth.get_user_by_id(get_uid()) or {}
    can_manage = user.get("role") == "developer"
    sites = [_site_view(s, can_manage) for s in _configured_sites()]
    return ok({"sites": sites})


@share_bp.route("/sites/<site_id>/enter", methods=["POST"])
@jwt_required()
def share_site_enter(site_id):
    cfg_site = next((s for s in _configured_sites() if s["id"] == site_id), None)
    if not cfg_site:
        return err("站点不存在", 404)
    rt = runner.get_runtime(site_id)
    if rt is None or not getattr(rt, "listening", False):
        return err("网关未启动，请联系管理员", 503)
    row = store.get_site(site_id) or {}
    if row and not int(row.get("enabled", 1)):
        return err("该共享站点已停用", 403)

    uid = get_uid()
    user = auth.get_user_by_id(uid) if uid is not None else None
    if not user:
        return err("无法识别当前用户", 401)
    name = user.get("display_name") or user.get("username") or ""

    # 网关与 GG-Server 同机：用浏览器当前访问的主机名拼网关地址（LAN / Tailscale 都能用）；
    # 在服务器本机以 127.0.0.1 打开时回退到对外 IP，避免复制出去后同事连到自己机器。
    host = _public_host(request.host)
    port = int(rt.site.get("port") or 0)
    token = ticket.issue_ticket(_secret(), site_id, int(uid), name)
    url = f"http://{host}:{port}/__sgw/enter?t={token}"
    try:
        current_app.logger.info(
            "[ShareGW] enter api user=%s(uid=%s) 浏览器host=%s ip=%s → %s:%s",
            name, uid, request.host, request.remote_addr, host, port)
    except Exception:
        pass
    try:
        store.record_access(site_id, int(uid), name, request.remote_addr or "")
    except Exception:
        pass
    return ok({"url": url, "expires_in": ticket.TICKET_TTL})


@share_bp.route("/sites/<site_id>/logs", methods=["GET"])
@jwt_required()
@developer_required
def share_site_logs(site_id):
    return ok({"logs": store.list_logs(site_id, limit=200)})


@share_bp.route("/sites/<site_id>/reset", methods=["POST"])
@jwt_required()
@developer_required
def share_site_reset(site_id):
    rt = runner.get_runtime(site_id)
    if rt is None:
        return err("网关未启动，无法清空会话", 503)
    rt.clear()
    return ok({"status": "unknown"})


@share_bp.route("/sites/<site_id>/check", methods=["POST"])
@jwt_required()
@developer_required
def share_site_check(site_id):
    rt = runner.get_runtime(site_id)
    if rt is None:
        return err("网关未启动", 503)
    status, error = rt.refresh_status()
    return ok({"status": status, "last_error": error})


@share_bp.route("/sites/<site_id>", methods=["PUT"])
@jwt_required()
@developer_required
def share_site_update(site_id):
    cfg_site = next((s for s in _configured_sites() if s["id"] == site_id), None)
    if not cfg_site:
        return err("站点不存在", 404)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return err("请求体必须是 JSON 对象")

    if "port" in body:
        try:
            port = int(body.get("port") or 0)
        except (TypeError, ValueError):
            return err("端口必须是整数")
        if port != int(cfg_site.get("port") or 0):
            return err("端口变更需要改 config.json 并重启服务", 400)

    if "enabled" not in body:
        return err("没有可更新的字段")

    enabled = bool(body.get("enabled"))
    store.set_enabled(site_id, enabled)
    if not enabled:
        rt = runner.get_runtime(site_id)
        if rt is not None:
            # 只吊销已发出的网关 cookie（代次 +1），不动会话罐：
            # 重新启用后管理员不用再登录一次。
            rt.bump_ver()
    return ok({"sites": [_site_view(cfg_site, True)]})
