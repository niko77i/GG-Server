"""共享账号网关的启动器：每个站点一个 waitress 线程 + 一个状态心跳线程。

设计约束：
- **不能影响主服务**：所有异常只打日志；端口占用时该站点标记不可用，其它站点和
  GG-Server 照常运行。
- 网关是独立端口（默认 8901/8902），与 5001 完全隔离；进程退出时线程一并结束。
- waitress 意外退出时循环重启（5 秒退避），避免「一次偶发异常 = 共享账号永久失效」。
"""
import threading
import time

from share_gateway import store
from share_gateway.proxy import GatewayApp
from share_gateway.runtime import SiteRuntime

_registry: dict[str, SiteRuntime] = {}
_registry_lock = threading.Lock()
_started = False
_heartbeat_thread: threading.Thread | None = None
HEARTBEAT_SECONDS = 300


def get_runtime(site_id: str) -> SiteRuntime | None:
    with _registry_lock:
        return _registry.get(site_id)


def list_runtimes() -> dict[str, SiteRuntime]:
    with _registry_lock:
        return dict(_registry)


def start_all(config: dict, secret: str) -> None:
    """按 config.share_gateway.sites 启动网关。重复调用安全（只启动一次）。"""
    global _started, _heartbeat_thread
    cfg = (config or {}).get("share_gateway") or {}
    if not cfg.get("enabled", True):
        print("[ShareGW] share_gateway.enabled=false，跳过启动")
        return
    with _registry_lock:
        if _started:
            return
        _started = True

    for site in cfg.get("sites") or []:
        site_id = site.get("id")
        if not site_id:
            continue
        if not site.get("enabled", True):
            print(f"[ShareGW] 站点 {site_id} 未启用，跳过")
            continue
        try:
            store.ensure_site(site)
            rt = SiteRuntime(site, secret)
            with _registry_lock:
                _registry[site_id] = rt
            threading.Thread(
                target=_serve_forever, args=(site, rt, secret),
                name=f"share-gw-{site_id}", daemon=True,
            ).start()
            print(f"[ShareGW] 站点 {site_id} 已启动：http://0.0.0.0:{site.get('port')}")
        except Exception as exc:
            print(f"[ShareGW] 站点 {site_id} 启动失败：{exc}")

    if _registry and (_heartbeat_thread is None or not _heartbeat_thread.is_alive()):
        _heartbeat_thread = threading.Thread(target=_heartbeat_loop, name="share-gw-heartbeat", daemon=True)
        _heartbeat_thread.start()


def _serve_forever(site: dict, rt: SiteRuntime, secret: str) -> None:
    from waitress import serve
    port = int(site.get("port") or 0)
    if not port:
        print(f"[ShareGW] 站点 {site.get('id')} 端口无效，跳过")
        return
    app = GatewayApp(site, rt, secret)
    failures = 0
    while True:
        try:
            rt.listening = True
            serve(app, host="0.0.0.0", port=port, threads=16)
            rt.listening = False
            return  # serve 正常返回（几乎不会）→ 结束线程
        except Exception as exc:
            rt.listening = False
            failures += 1
            # 端口被占用之类的问题会一直失败，别每 5 秒刷屏
            wait = 5 if failures <= 3 else 60
            print(f"[ShareGW] 站点 {site.get('id')} 监听 {port} 失败：{exc}；{wait} 秒后重试")
            time.sleep(wait)


def _heartbeat_loop() -> None:
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        for rt in list_runtimes().values():
            try:
                rt.refresh_status()
            except Exception as exc:
                print(f"[ShareGW] 站点 {rt.site_id} 状态自检失败：{exc}")
