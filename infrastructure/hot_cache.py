"""Camada quente do CAG (ADR-022, S14-3): Redis no collab (vale para a API e os workers), memória
do processo no solo. Falha do Redis vira falta no cache, nunca erro: o chat segue pelo RAG."""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessCache:
    """ponytail: dicionário com validade e teto simples; Redis se o solo ganhar mais de um processo."""

    MAX_KEYS = 5000

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            found = self._data.get(key)
            if found and found[0] < time.monotonic():
                del self._data[key]
                return None
            return found[1] if found else None

    def set(self, key: str, value: str, ttl: int) -> None:
        with self._lock:
            if len(self._data) >= self.MAX_KEYS:
                self._data.pop(next(iter(self._data)))  # o mais antigo inserido
            self._data[key] = (time.monotonic() + ttl, value)

    def incr(self, key: str) -> None:
        with self._lock:
            _, value = self._data.get(key, (0, "0"))
            self._data[key] = (float("inf"), str(int(value) + 1))


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis
        self._r = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1, decode_responses=True)

    def get(self, key: str) -> Optional[str]:
        try:
            return self._r.get(key)
        except Exception as exc:
            logger.warning("Cache quente indisponível: %s", exc)
            return None

    def set(self, key: str, value: str, ttl: int) -> None:
        try:
            self._r.set(key, value, ex=ttl)
        except Exception as exc:
            logger.warning("Cache quente indisponível: %s", exc)

    def incr(self, key: str) -> None:
        try:
            self._r.incr(key)
        except Exception as exc:
            logger.warning("Cache quente indisponível: %s", exc)


def build_hot_cache(settings):
    return RedisCache(settings.redis_url) if settings.is_collab else ProcessCache()
