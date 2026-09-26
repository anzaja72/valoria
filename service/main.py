"""API FastAPI del tool consultar_proceso (Legal-IA / Rama Judicial)."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from . import __version__
from .auth import verificar_bearer
from .cache import TTLCache
from .config import URL_OFICIAL, Settings, get_settings
from .browser import Navegador
from .cpnu import CPNUClient, ResultadoCPNU, elegir_proceso
from .fechas import MAX_DIAS_RANGO, ultimos_dias_habiles
from .formatter import (
    construir_para_el_abogado, mensaje_estado, mensaje_ok, normalizar_actuacion,
    normalizar_proceso, nuevas_actuaciones, ordenar_actuaciones,
)
from .formatter_estados import (
    MENSAJES_ERROR, coincidencia_out, mensaje_estados, para_el_abogado, publicacion_out,
)
from .mcp_server import registrar_mcp
from .models import ConsultaRequest, ConsultaResponse, EstadosRequest, EstadosResponse
from .publicaciones import URL_PUBLICACIONES, PublicacionesClient, ResultadoEstados
from .radicado import normalizar_radicado
from .store import Store
from .tool_schema import TOOL_SCHEMA, TOOLS

log = logging.getLogger("service")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_app(settings: Settings | None = None, cpnu: CPNUClient | None = None,
               publicaciones: PublicacionesClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    nav = Navegador(settings.headless)
    cliente = cpnu or CPNUClient(max_concurrent=settings.max_concurrent_queries,
                                 timeout_s=settings.scraper_timeout_seconds, navegador=nav)
    pub_cliente = publicaciones or PublicacionesClient(
        nav, max_concurrent=settings.max_concurrent_queries, timeout_s=settings.scraper_timeout_seconds,
        url=settings.publicaciones_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.api_keys:
            log.warning("TOOL_API_KEYS vacío: /v1/* responderá 503")
        yield
        await cliente.stop()
        await nav.stop()

    app = FastAPI(title="Legal-IA · consultar_proceso", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.cpnu = cliente
    app.state.publicaciones = pub_cliente
    app.state.cache = TTLCache(settings.cache_ttl_seconds)
    app.state.cache_estados = TTLCache(settings.cache_ttl_seconds)
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
    async def tool_schema(tool: str = "consultar_proceso", canal: str = Depends(verificar_bearer)):
        for t in TOOLS:
            if t["name"] == tool:
                return t
        raise HTTPException(404, f"Tool desconocido: {tool}")

    @app.get("/v1/tools")
    async def tools(canal: str = Depends(verificar_bearer)):
        return TOOLS

    @app.post("/v1/consultar_proceso", response_model=ConsultaResponse, response_model_exclude_none=True)
    async def consultar_proceso(body: ConsultaRequest, canal: str = Depends(verificar_bearer)):
        return await ejecutar_proceso(app, body, canal)

    @app.post("/v1/consultar_estados", response_model=EstadosResponse, response_model_exclude_none=True)
    async def consultar_estados(body: EstadosRequest, canal: str = Depends(verificar_bearer)):
        return await ejecutar_estados(app, body, canal)

    registrar_mcp(app)
    return app


async def ejecutar_proceso(app: FastAPI, body: ConsultaRequest, canal: str) -> ConsultaResponse:
    """Lógica de consultar_proceso, compartida por la API REST y el servidor MCP."""
    t0 = time.monotonic()
    radicado = normalizar_radicado(body.radicado)
    if not radicado:
        return _error(None, "invalid_radicado")

    cache: TTLCache = app.state.cache
    async with cache.lock(radicado):
        if not body.forzar_actualizacion and (hit := cache.get(radicado)):
            out = hit[0].model_copy(update={"desde_cache": True})
            _log(canal, radicado, out.status, t0, cache=True)
            return out
        crudo = await app.state.cpnu.consultar(radicado)
        resp = _construir(radicado, crudo, app.state.store, app.state.settings)
        if resp.status in ("ok", "not_found"):
            cache.set(radicado, resp)
    _log(canal, radicado, resp.status, t0, cache=False, code=resp.error_code)
    return resp


async def ejecutar_estados(app: FastAPI, body: EstadosRequest, canal: str) -> EstadosResponse:
    """Lógica de consultar_estados, compartida por la API REST y el servidor MCP."""
    t0 = time.monotonic()
    radicado = normalizar_radicado(body.radicado)
    if not radicado:
        return _error_estados(None, "invalid_radicado")
    try:
        ini, fin = _rango(body.fecha_inicio, body.fecha_fin)
    except ValueError:
        return _error_estados(radicado, "rango_invalido")

    clave = f"{radicado}:{ini}:{fin}"
    cache: TTLCache = app.state.cache_estados
    async with cache.lock(clave):
        if not body.forzar_actualizacion and (hit := cache.get(clave)):
            out = hit[0].model_copy(update={"desde_cache": True})
            _log(canal, radicado, out.status, t0, cache=True)
            return out
        crudo = await app.state.publicaciones.consultar(radicado, ini, fin)
        resp = _construir_estados(radicado, ini, fin, crudo)
        if resp.status == "ok":
            cache.set(clave, resp)
    _log(canal, radicado, resp.status, t0, cache=False, code=resp.error_code)
    return resp


def _rango(fecha_inicio: str | None, fecha_fin: str | None) -> tuple[date, date]:
    def_ini, def_fin = ultimos_dias_habiles(5)
    fin = date.fromisoformat(fecha_fin) if fecha_fin else def_fin
    ini = date.fromisoformat(fecha_inicio) if fecha_inicio else (def_ini if not fecha_fin else
                                                                ultimos_dias_habiles(5, fin)[0])
    if ini > fin or (fin - ini).days > MAX_DIAS_RANGO:
        raise ValueError("rango")
    return ini, fin


def _error_estados(radicado: str | None, code: str, status: str = "error",
                   ini: date | None = None, fin: date | None = None) -> EstadosResponse:
    return EstadosResponse(
        status=status, radicado=radicado, error_code=code if status == "error" else None,
        mensaje_chat=mensaje_estado(code if status == "error" else status, radicado, MENSAJES_ERROR),
        url_oficial=URL_PUBLICACIONES, consultado_en=_ahora(),
        fecha_inicio=ini.isoformat() if ini else None, fecha_fin=fin.isoformat() if fin else None,
    )


def _construir_estados(radicado: str, ini: date, fin: date, crudo: ResultadoEstados) -> EstadosResponse:
    if crudo.status == "captcha_required":
        return _error_estados(radicado, "captcha", status="captcha_required", ini=ini, fin=fin)
    if crudo.status != "ok":
        return _error_estados(radicado, crudo.error_code or "default", ini=ini, fin=fin)
    coincidencias = [coincidencia_out(c) for c in crudo.coincidencias]
    publicaciones = [publicacion_out(p) for p in crudo.publicaciones]
    return EstadosResponse(
        status="ok", radicado=radicado, aparece=bool(coincidencias),
        mensaje_chat=mensaje_estados(radicado, ini, fin, coincidencias, publicaciones,
                                     crudo.despachos_revisados),
        url_oficial=URL_PUBLICACIONES, consultado_en=_ahora(),
        fecha_inicio=ini.isoformat(), fecha_fin=fin.isoformat(),
        despachos_revisados=crudo.despachos_revisados, coincidencias=coincidencias,
        publicaciones_revisadas=publicaciones, advertencias=crudo.advertencias,
        para_el_abogado=para_el_abogado(radicado, coincidencias, publicaciones, crudo.advertencias),
    )


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
