"""Cache TTL en memoria + locks por radicado para deduplicar consultas simultáneas."""
from __future__ import annotations

import asyncio
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = ttl_seconds
        self._data: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> tuple[Any, float] | None:
        """Devuelve (valor, edad_en_segundos) o None si no existe o expiró."""
        item = self._data.get(key)
        if not item:
            return None
        guardado, valor = item
        edad = time.monotonic() - guardado
        if edad > self.ttl:
            self._data.pop(key, None)
            return None
        return valor, edad

    def set(self, key: str, valor: Any) -> None:
        if self.ttl > 0:
            self._data[key] = (time.monotonic(), valor)

    def lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    def __len__(self) -> int:
        return len(self._data)
