"""API FastAPI del tool consultar_proceso (Legal-IA / Rama Judicial)."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .auth import verificar_bearer
from .cache import TTLCache
from .config import URL_OFICIAL, Settings, get_settings
from .cpnu import CPNUClient, ResultadoCPNU, elegir_proceso
from .formatter import (
    construir_para_el_abogado, mensaje_estado, mensaje_ok, normalizar_actuacion,
    normalizar_proceso, nuevas_actuaciones, ordenar_actuaciones,
)
from .models import ConsultaRequest, ConsultaResponse
from .radicado import normalizar_radicado
from .store import Store
from .tool_schema import TOOL_SCHEMA

log = logging.getLogger("service")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_app(settings: Settings | None = None, cpnu: CPNUClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cliente = cpnu or CPNUClient(headless=settings.headless,
                                 max_concurrent=settings.max_concurrent_queries,
                                 timeout_s=settings.scraper_timeout_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.api_keys:
            log.warning("TOOL_API_KEYS vacío: /v1/* responderá 503")
        yield
        await cliente.stop()

    app = FastAPI(title="Legal-IA · consultar_proceso", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.cpnu = cliente
    app.state.cache = TTLCache(settings.cache_ttl_seconds)
    app.state.store = Store(settings.store_dir)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "browser": "up" if cliente.listo else "lazy",
            "cache_entries": len(app.state.cache),
            "cache_ttl_seconds": settings.cache_ttl_seconds,
            "auth_configured": bool(settings.api_keys),
        }

    @app.get("/v1/tool_schema")
    async def tool_schema(canal: str = Depends(verificar_bearer)):
        return TOOL_SCHEMA

    @app.post("/v1/consultar_proceso", response_model=ConsultaResponse, response_model_exclude_none=True)
    async def consultar_proceso(body: ConsultaRequest, request: Request,
                                canal: str = Depends(verificar_bearer)):
        t0 = time.monotonic()
        radicado = normalizar_radicado(body.radicado)
        if not radicado:
            return _error(None, "invalid_radicado")

        cache: TTLCache = app.state.cache
        async with cache.lock(radicado):
            if not body.forzar_actualizacion and (hit := cache.get(radicado)):
                resp, _edad = hit
                out = resp.model_copy(update={"desde_cache": True})
                _log(canal, radicado, out.status, t0, cache=True)
                return out

            crudo = await cliente.consultar(radicado)
            resp = _construir(radicado, crudo, app.state.store, settings)
            if resp.status in ("ok", "not_found"):
                cache.set(radicado, resp)
        _log(canal, radicado, resp.status, t0, cache=False, code=resp.error_code)
        return resp

    return app


def _log(canal, radicado, status, t0, cache, code=None):
    log.info("consulta canal=%s radicado=%s status=%s code=%s cache=%s ms=%d",
             canal, radicado, status, code, cache, (time.monotonic() - t0) * 1000)


def _error(radicado: str | None, code: str, status: str = "error") -> ConsultaResponse:
    return ConsultaResponse(
        status=status, radicado=radicado, error_code=code if status == "error" else None,
        mensaje_chat=mensaje_estado(code if status == "error" else status, radicado),
        url_oficial=URL_OFICIAL, consultado_en=_ahora(),
    )


def _construir(radicado: str, crudo: ResultadoCPNU, store: Store, settings: Settings) -> ConsultaResponse:
    if crudo.status == "not_found":
        return _error(radicado, "not_found", status="not_found")
    if crudo.status == "captcha_required":
        return _error(radicado, "captcha", status="captcha_required")
    if crudo.status != "ok":
        return _error(radicado, crudo.error_code or "default")

    consultado = _ahora()
    elegido = elegir_proceso(crudo.procesos)
    proceso = normalizar_proceso(elegido, crudo.detalle, crudo.sujetos)
    actuaciones = ordenar_actuaciones([normalizar_actuacion(a) for a in crudo.actuaciones])
    total = max(crudo.total_actuaciones, len(actuaciones))

    previas = store.cargar_actuaciones(radicado)
    nuevas = nuevas_actuaciones(actuaciones, previas)
    try:
        store.guardar(radicado, {
            "radicado": radicado, "consultado_en": consultado, "fuente": "cpnu",
            "proceso": proceso.model_dump(), "coincidencias": len(crudo.procesos),
            "total_actuaciones": total,
        }, actuaciones)
    except OSError:
        log.exception("No se pudo escribir el store para %s", radicado)

    return ConsultaResponse(
        status="ok", radicado=radicado, url_oficial=URL_OFICIAL, consultado_en=consultado,
        mensaje_chat=mensaje_ok(radicado, proceso, actuaciones, len(crudo.procesos)),
        proceso=proceso, coincidencias=len(crudo.procesos), total_actuaciones=total,
        actuaciones=actuaciones[: settings.max_actuaciones],
        para_el_abogado=construir_para_el_abogado(proceso, actuaciones, total, nuevas),
    )


app = create_app()
