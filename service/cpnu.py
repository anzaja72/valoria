"""Cliente CPNU (consultaprocesos.ramajudicial.gov.co) con Playwright + Chromium headless.

Estrategia:
1. Abrir la SPA oficial en un contexto nuevo, detectar CAPTCHA y lanzar la búsqueda
   por número de radicación desde la UI, capturando las respuestas JSON de su API (:448).
2. Si la UI cambió (selectores rotos), consultar la misma API con `context.request`,
   que comparte cookies/sesión con la página.
3. Con el idProceso, pedir Detalle, Sujetos y Actuaciones.

Política CAPTCHA: nunca se resuelve ni se evade. Si aparece, se devuelve
status=captcha_required y el chat hace handoff humano a url_oficial.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .browser import (CAPTCHA_TEXTO, CaptchaRequerido, Navegador, PortalError, detectar_captcha,
                      es_error_de_red)
from .config import CPNU_API_BASE, CPNU_BASE_URL, URL_OFICIAL

log = logging.getLogger("cpnu")

INPUT_SELECTORES = (
    "input[maxlength='23']",
    "input[placeholder*='23' i]",
    "input[aria-label*='radicaci' i]",
    "input[type='text']",
)


@dataclass
class ResultadoCPNU:
    status: str  # ok | not_found | captcha_required | error
    procesos: list[dict[str, Any]] = field(default_factory=list)
    detalle: dict[str, Any] | None = None
    sujetos: list[dict[str, Any]] = field(default_factory=list)
    actuaciones: list[dict[str, Any]] = field(default_factory=list)
    total_actuaciones: int = 0
    error_code: str | None = None
    detalle_error: str | None = None


def elegir_proceso(procesos: list[dict[str, Any]]) -> dict[str, Any]:
    """Si hay varios registros con el mismo radicado, toma el de actuación más reciente."""
    return max(procesos, key=lambda p: (p.get("fechaUltimaActuacion") or "", p.get("idProceso") or 0))


class CPNUClient:
    def __init__(self, headless: bool = True, max_concurrent: int = 2, timeout_s: int = 75,
                 max_paginas_actuaciones: int = 3, navegador: Navegador | None = None) -> None:
        self.nav = navegador or Navegador(headless)
        self.timeout_s = timeout_s
        self.max_paginas = max_paginas_actuaciones
        self._sem = asyncio.Semaphore(max_concurrent)

    async def start(self) -> None:
        await self.nav.start()

    async def stop(self) -> None:
        await self.nav.stop()

    @property
    def listo(self) -> bool:
        return self.nav.listo

    # ---------- API pública ----------
    async def consultar(self, radicado: str) -> ResultadoCPNU:
        async with self._sem:
            try:
                return await asyncio.wait_for(self._consultar(radicado), timeout=self.timeout_s)
            except asyncio.TimeoutError:
                return ResultadoCPNU("error", error_code="timeout",
                                     detalle_error=f"El portal no respondió en {self.timeout_s}s")
            except CaptchaRequerido:
                return ResultadoCPNU("captcha_required", error_code="captcha")
            except PortalError as e:
                return ResultadoCPNU("error", error_code=e.code, detalle_error=str(e))
            except Exception as e:  # noqa: BLE001 — siempre error estructurado
                if es_error_de_red(e):
                    log.warning("Red/portal caído consultando %s: %s", radicado, str(e).splitlines()[0])
                    return ResultadoCPNU("error", error_code="portal_unavailable",
                                         detalle_error="No hay conexión con el portal CPNU")
                log.exception("Fallo inesperado consultando %s", radicado)
                return ResultadoCPNU("error", error_code="scraper_error", detalle_error=type(e).__name__)

    # ---------- implementación ----------
    async def _consultar(self, radicado: str) -> ResultadoCPNU:
        context = await self.nav.new_context()
        try:
            page = await context.new_page()
            resp = await page.goto(URL_OFICIAL, wait_until="domcontentloaded", timeout=30_000)
            if resp is not None and resp.status >= 500:
                raise PortalError("portal_unavailable", f"CPNU respondió HTTP {resp.status}")
            await detectar_captcha(page)

            consulta = await self._buscar_por_ui(page, radicado)
            procesos = (consulta or {}).get("procesos") or []
            if not procesos:
                # La UI puede haber buscado solo procesos activos o haber cambiado:
                # se confirma siempre con la API pidiendo todos los procesos.
                log.info("UI %s; confirmando con API directa (SoloActivos=false) para %s",
                         "sin resultados" if consulta is not None else "no disponible", radicado)
                await detectar_captcha(page)
                consulta = await self._api(context, "/Procesos/Consulta/NumeroRadicacion",
                                           {"numero": radicado, "SoloActivos": "false", "pagina": 1})
                procesos = (consulta or {}).get("procesos") or []
            if not procesos:
                return ResultadoCPNU("not_found")

            elegido = elegir_proceso(procesos)
            idp = elegido.get("idProceso")
            if elegido.get("esPrivado"):
                return ResultadoCPNU("ok", procesos=procesos)

            detalle, sujetos = await asyncio.gather(
                self._api(context, f"/Proceso/Detalle/{idp}"),
                self._api(context, f"/Proceso/Sujetos/{idp}", {"pagina": 1}),
            )
            actuaciones, total = await self._actuaciones(context, idp)
            return ResultadoCPNU(
                "ok", procesos=procesos, detalle=detalle,
                sujetos=(sujetos or {}).get("sujetos") or [],
                actuaciones=actuaciones, total_actuaciones=total,
            )
        finally:
            await context.close()

    async def _buscar_por_ui(self, page, radicado: str) -> dict | None:
        """Llena el formulario oficial. Devuelve el JSON de la búsqueda o None si la UI no cuadra."""
        campo = None
        for sel in INPUT_SELECTORES:
            loc = page.locator(sel).first
            try:
                await loc.wait_for(state="visible", timeout=8_000 if campo is None else 1_000)
                campo = loc
                break
            except Exception:  # noqa: BLE001
                continue
        if campo is None:
            return None
        try:
            # "Todos los procesos" (no solo activos), si el radio existe.
            todos = page.get_by_text(re.compile(r"todos los procesos", re.I)).first
            if await todos.count():
                await todos.click(timeout=2_000)
        except Exception:  # noqa: BLE001
            pass
        try:
            await campo.fill(radicado)
            boton = page.get_by_role("button", name=re.compile(r"consultar", re.I)).first
            async with page.expect_response(
                lambda r: "NumeroRadicacion" in r.url and "/api/" in r.url, timeout=25_000
            ) as info:
                await boton.click(timeout=5_000)
            r = await info.value
        except Exception as e:  # noqa: BLE001
            log.info("Búsqueda por UI falló: %s", str(e).splitlines()[0] if str(e) else type(e).__name__)
            return None
        log.info("UI -> %s HTTP %s", r.url, r.status)
        try:
            data = await r.json()
        except Exception:  # noqa: BLE001
            data = None
        return self._validar_respuesta(r.status, data)

    def _validar_respuesta(self, status: int, data: Any) -> dict | None:
        if status in (401, 403, 429):
            raise CaptchaRequerido()
        if status >= 500:
            raise PortalError("portal_unavailable", f"CPNU respondió HTTP {status}")
        if status == 404:
            return {"procesos": []}
        if status >= 400:
            raise PortalError("portal_error", f"CPNU respondió HTTP {status}")
        if isinstance(data, dict):
            return data
        raise PortalError("respuesta_invalida", "El portal no devolvió JSON")

    async def _api(self, context, path: str, params: dict | None = None) -> dict:
        resp = await context.request.get(
            f"{CPNU_API_BASE}{path}", params=params,
            headers={"Origin": CPNU_BASE_URL, "Referer": URL_OFICIAL, "Accept": "application/json"},
            timeout=25_000,
        )
        try:
            data = await resp.json()
        except Exception:  # noqa: BLE001
            texto = (await resp.text())[:2000] if resp.ok else ""
            if CAPTCHA_TEXTO.search(texto):
                raise CaptchaRequerido()
            data = None
        return self._validar_respuesta(resp.status, data)

    async def _actuaciones(self, context, idp) -> tuple[list[dict], int]:
        todas: list[dict] = []
        total = 0
        for pagina in range(1, self.max_paginas + 1):
            data = await self._api(context, f"/Proceso/Actuaciones/{idp}", {"pagina": pagina})
            todas.extend(data.get("actuaciones") or [])
            pag = data.get("paginacion") or {}
            total = pag.get("cantidadRegistros") or len(todas)
            if pagina >= (pag.get("cantidadPaginas") or 1):
                break
        return todas, max(total, len(todas))
