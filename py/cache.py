"""内存 TTL 缓存层 — 用于缓存低频变化的查询结果。

线程安全，基于字典 + 锁实现，不依赖外部服务。适合 20 人以下局域网部署。
"""

import time
import threading


class SimpleCache:
    """线程安全的 TTL 内存缓存。"""

    def __init__(self, default_ttl: float = 300):
        self._data: dict[str, tuple[float, any]] = {}
        self._default_ttl = default_ttl
        self._lock = threading.Lock()

    def get(self, key: str):
        """获取缓存值。过期返回 None。"""
        with self._lock:
            if key in self._data:
                ts, val = self._data[key]
                if time.time() < ts:
                    return val
                del self._data[key]
        return None

    def set(self, key: str, value, ttl: float = None):
        """写入缓存。"""
        with self._lock:
            self._data[key] = (time.time() + (ttl or self._default_ttl), value)

    def delete(self, key: str):
        """删除指定缓存。"""
        with self._lock:
            self._data.pop(key, None)

    def clear_prefix(self, prefix: str):
        """清除所有匹配前缀的缓存键。"""
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                del self._data[k]

    def clear(self):
        """清除全部缓存。"""
        with self._lock:
            self._data.clear()


# 全局缓存实例
cache = SimpleCache(default_ttl=60)  # 默认 60 秒 TTL
