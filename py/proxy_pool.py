"""代理池管理模块。

为掉包检测提供代理 IP 轮换，避免使用服务端 IP 访问 Google Play。
"""

import random


class ProxyPool:
    """掉包检测代理池。

    解析配置、按 (ip, port) 去重、随机取用、转成 requests 的 proxies 参数。
    """

    def __init__(self, proxies_config, max_retries=3):
        self._proxies = self._load(proxies_config)
        self.max_retries = int(max_retries) if max_retries else 3

    @staticmethod
    def _load(proxies_config):
        """解析代理配置列表，按 (ip, port) 去重，跳过无效项。"""
        proxies = []
        seen = set()
        for cfg in proxies_config or []:
            if not isinstance(cfg, dict):
                continue
            ip = str(cfg.get("ip", "") or "").strip()
            port = cfg.get("port")
            if not ip or port is None:
                continue
            try:
                port = int(port)
            except (TypeError, ValueError):
                continue
            key = (ip, port)
            if key in seen:
                continue
            seen.add(key)
            proxies.append({
                "ip": ip,
                "port": port,
                "username": str(cfg.get("username", "") or ""),
                "password": str(cfg.get("password", "") or ""),
                "scheme": str(cfg.get("scheme", "http") or "http").strip() or "http",
            })
        return proxies

    @property
    def count(self):
        return len(self._proxies)

    def next(self, exclude=None):
        """随机取一个代理。

        Args:
            exclude: 已尝试的 (ip, port) 元组集合，取用时排除这些代理。

        Returns:
            代理字典；无可用代理时返回 None。

        说明：无共享可变状态（代理列表初始化后只读、exclude 为每线程局部
        集合），CPython GIL 下多线程安全；多个线程可能随机到同一代理，
        属预期行为（并发共用出口 IP 不影响本场景的轮换目的）。
        """
        if not self._proxies:
            return None
        candidates = self._proxies
        if exclude:
            candidates = [p for p in self._proxies if (p["ip"], p["port"]) not in exclude]
        if not candidates:
            return None
        return random.choice(candidates)

    @staticmethod
    def to_requests(proxy):
        """转成 requests 的 proxies 参数。

        Args:
            proxy: 代理字典（含 ip/port/username/password/scheme）。

        Returns:
            {"http": "...", "https": "..."} 形式的 proxies 参数。
        """
        scheme = proxy.get("scheme", "http")
        ip = proxy["ip"]
        port = proxy["port"]
        auth = ""
        if proxy.get("username") or proxy.get("password"):
            auth = f"{proxy['username']}:{proxy['password']}@"
        base = f"{scheme}://{auth}{ip}:{port}"
        return {"http": base, "https": base}
