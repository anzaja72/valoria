"""Configuración por variables de entorno."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

CPNU_BASE_URL = "https://consultaprocesos.ramajudicial.gov.co"
CPNU_API_BASE = "https://consultaprocesos.ramajudicial.gov.co:448/api/v2"
URL_OFICIAL = f"{CPNU_BASE_URL}/Procesos/NumeroRadicacion"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _keys() -> tuple[str, ...]:
    raw = os.getenv("TOOL_API_KEYS", "")
    return tuple(k.strip() for k in raw.split(",") if k.strip())


@dataclass(frozen=True)
class Settings:
    api_keys: tuple[str, ...] = field(default_factory=_keys)
    cache_ttl_seconds: int = field(default_factory=lambda: _int("CACHE_TTL_SECONDS", 600))
    scraper_timeout_seconds: int = field(default_factory=lambda: _int("SCRAPER_TIMEOUT_SECONDS", 75))
    max_concurrent_queries: int = field(default_factory=lambda: _int("MAX_CONCURRENT_QUERIES", 2))
    max_actuaciones: int = field(default_factory=lambda: _int("MAX_ACTUACIONES", 30))
    store_dir: Path = field(default_factory=lambda: Path(os.getenv("STORE_DIR", "store")))
    headless: bool = field(default_factory=lambda: os.getenv("HEADLESS", "true").lower() != "false")
    publicaciones_url: str = field(default_factory=lambda: os.getenv(
        "PUBLICACIONES_URL", "https://publicacionesprocesales.ramajudicial.gov.co/"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


def get_settings() -> Settings:
    return Settings()
