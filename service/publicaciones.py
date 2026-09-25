"""Cliente de publicacionesprocesales.ramajudicial.gov.co — «Notificaciones por Estados».

Flujo (igual al manual):
1. Abrir el portal y elegir el Despacho (deducido del radicado) + rango de fechas.
2. BUSCAR y abrir la categoría «Notificaciones por Estados».
3. Por cada publicación («Notificación por Estado No.70 de 22 de septiembre de 2026») entrar a
   VER DETALLE y listar los documentos.
4. Descargar los PDF de fijación de estado, leer la tabla y buscar el radicado.
   Los PDF de autos cuyo nombre corresponde al radicado (p. ej. «002-2026-00146 Admite….pdf")
   se devuelven como enlace directo.

Política CAPTCHA: igual que CPNU, nunca se resuelve ni se evade → captcha_required.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin

from .browser import CaptchaRequerido, Navegador, PortalError, detectar_captcha, es_error_de_red
from .despachos import candidatos_despacho, partes, sin_tildes
from .estados_pdf import FilaEstado, buscar_radicado, leer_pdf, numero_estado

log = logging.getLogger("publicaciones")

URL_PUBLICACIONES = "https://publicacionesprocesales.ramajudicial.gov.co/"
CATEGORIA_ESTADOS = re.compile(r"notificaciones\s+por\s+estados", re.I)
BOTON_BUSCAR = re.compile(r"^\s*buscar\s*$", re.I)
VER_DETALLE = re.compile(r"ver\s+detalle", re.I)
MAX_PDFS_POR_PUBLICACION = 6
MAX_PAGINAS_DOCS = 10

# --- JS auxiliar -------------------------------------------------------------------------------

JS_SELECTS = """
() => Array.from(document.querySelectorAll('select')).map((s, i) => {
  let label = '';
  if (s.id) { const l = document.querySelector(`label[for="${CSS.escape(s.id)}"]`); if (l) label = l.innerText; }
  let p = s.parentElement;
  for (let k = 0; k < 4 && p && !label; k++) {
    const l = p.querySelector('label, .control-label, h5, h6, span.label'); if (l) label = l.innerText;
    p = p.parentElement;
  }
  return {i, id: s.id, name: s.name, label: (label || s.name || s.id || '').trim(), n: s.options.length};
})
"""

JS_OPCIONES = """
(i) => Array.from(document.querySelectorAll('select')[i].options)
          .map(o => ({v: o.value, t: (o.text || '').trim()}))
"""

JS_SET = """
([i, v]) => {
  const s = document.querySelectorAll('select')[i];
  s.value = v;
  s.dispatchEvent(new Event('input', {bubbles: true}));
  s.dispatchEvent(new Event('change', {bubbles: true}));
  if (window.jQuery) { window.jQuery(s).trigger('change.select2'); }
  return s.value;
}
"""

JS_TARJETAS = """
() => {
  const re = /ver\\s+detalle/i;
  const out = [];
  document.querySelectorAll('a, button, input[type=button], input[type=submit]').forEach((el, idx) => {
    const txt = (el.innerText || el.value || '').trim();
    if (!re.test(txt)) return;
    let card = el, k = 0;
    while (card.parentElement && k < 8 && !/Fecha de Publicaci/i.test(card.innerText || '')) {
      card = card.parentElement; k++;
    }
    out.push({href: el.getAttribute('href') || '', texto: (card.innerText || '').trim().slice(0, 1500)});
  });
  return out;
}
"""

JS_DOCUMENTOS = """
() => Array.from(document.querySelectorAll('a[href]'))
  .filter(a => /get_file|\\/documents\\/|\\.pdf(\\?|$)/i.test(a.getAttribute('href')) || /\\.pdf\\s*$/i.test(a.innerText || ''))
  .map(a => {
    const tr = a.closest('tr');
    return {nombre: (a.innerText || '').trim(), href: a.href, fila: tr ? tr.innerText.trim() : ''};
  })
"""


# --- modelos internos --------------------------------------------------------------------------

@dataclass
class Documento:
    nombre: str
    url: str
    tipo: str = "otro"  # estado | auto_radicado | otro


@dataclass
class Publicacion:
    titulo: str
    despacho: str
    url_detalle: str | None = None
    fecha_publicacion: str | None = None
    numero_estado: str | None = None
    documentos: list[Documento] = field(default_factory=list)
    pdfs_leidos: int = 0
    pdfs_ilegibles: list[str] = field(default_factory=list)


@dataclass
class Coincidencia:
    publicacion: Publicacion
    fila: FilaEstado | None
    pdf_estado: Documento | None
    autos: list[Documento] = field(default_factory=list)


@dataclass
class ResultadoEstados:
    status: str  # ok | captcha_required | error
    despachos_revisados: list[str] = field(default_factory=list)
    publicaciones: list[Publicacion] = field(default_factory=list)
    coincidencias: list[Coincidencia] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    error_code: str | None = None
    detalle_error: str | None = None


# --- clasificación de documentos ---------------------------------------------------------------

def clasificar_documento(nombre: str, radicado: str) -> str:
    """auto_radicado si el nombre corresponde al radicado; estado si parece fijación de estados."""
    p = partes(radicado)
    digitos = re.sub(r"\D", "", nombre)
    if radicado in digitos:
        return "auto_radicado"
    if re.search(rf"(?<!\d){p.anio}\D{{0,3}}{p.consecutivo}(?!\d)", nombre):
        return "auto_radicado"
    n = sin_tildes(nombre)
    if re.search(r"ESTADO|FIJACI|RPTFIJACION", n):
        return "estado"
    if re.search(r"(?<!\d)\d{2,4}-\d{4}-\d{3,5}(?!\d)", nombre) or re.search(r"\d{23}", digitos):
        return "otro"  # auto de otro proceso
    return "estado"  # sin radicado en el nombre: normalmente el estado del día


def parsear_tarjeta(texto: str) -> tuple[str, str | None, str | None]:
    """Devuelve (titulo, fecha_publicacion, numero_estado) desde el texto de la tarjeta."""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    titulo = next((l for l in lineas if re.search(r"estado", l, re.I)), lineas[0] if lineas else "")
    m = re.search(r"Fecha de Publicaci\S*:?\s*(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", texto, re.I)
    return titulo, (m.group(1) if m else None), numero_estado(titulo)


# --- cliente -----------------------------------------------------------------------------------

class PublicacionesClient:
    def __init__(self, navegador: Navegador, max_concurrent: int = 2, timeout_s: int = 80,
                 url: str = URL_PUBLICACIONES) -> None:
        self.nav = navegador
        self.url = url
        self.timeout_s = timeout_s
        self._sem = asyncio.Semaphore(max_concurrent)

    async def consultar(self, radicado: str, fecha_inicio: date, fecha_fin: date) -> ResultadoEstados:
        async with self._sem:
            try:
                return await asyncio.wait_for(self._consultar(radicado, fecha_inicio, fecha_fin),
                                              timeout=self.timeout_s)
            except asyncio.TimeoutError:
                return ResultadoEstados("error", error_code="timeout",
                                        detalle_error=f"El portal no respondió en {self.timeout_s}s")
            except CaptchaRequerido:
                return ResultadoEstados("captcha_required", error_code="captcha")
            except PortalError as e:
                return ResultadoEstados("error", error_code=e.code, detalle_error=str(e))
            except Exception as e:  # noqa: BLE001
                if es_error_de_red(e):
                    return ResultadoEstados("error", error_code="portal_unavailable",
                                            detalle_error="No hay conexión con publicacionesprocesales")
                log.exception("Fallo inesperado consultando estados de %s", radicado)
                return ResultadoEstados("error", error_code="scraper_error", detalle_error=type(e).__name__)

    async def _consultar(self, radicado: str, ini: date, fin: date) -> ResultadoEstados:
        ctx = await self.nav.new_context(accept_downloads=True)
        try:
            page = await ctx.new_page()
            res = ResultadoEstados("ok")
            candidatos = await self._abrir_y_candidatos(page, radicado)
            if not candidatos:
                return ResultadoEstados("error", error_code="despacho_no_encontrado",
                                        detalle_error=f"No se encontró el despacho {radicado[:12]} en el portal")
            for i, despacho in enumerate(candidatos):
                if i > 0:
                    await self._abrir_y_candidatos(page, radicado)
                res.despachos_revisados.append(despacho)
                pubs = await self._buscar_estados(page, despacho, ini, fin, res)
                for pub in pubs:
                    await self._revisar_publicacion(page, ctx, pub, radicado, res)
                res.publicaciones.extend(pubs)
                if res.coincidencias:
                    break  # ya se encontró el despacho correcto
            return res
        finally:
            await ctx.close()

    # ---------- formulario ----------
    async def _abrir_y_candidatos(self, page, radicado: str) -> list[str]:
        resp = await page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
        if resp is not None and resp.status >= 500:
            raise PortalError("portal_unavailable", f"Publicaciones respondió HTTP {resp.status}")
        await _esperar_red(page, 15_000)
        await detectar_captcha(page)

        self._selects = await page.evaluate(JS_SELECTS)
        i_desp = self._indice("DESPACHO")
        if i_desp is None:
            raise PortalError("formulario_cambiado", "No se encontró el filtro Despacho")

        textos = [o["t"] for o in await page.evaluate(JS_OPCIONES, i_desp)]
        cands = candidatos_despacho(radicado, textos)
        log.info("Filtros: %s · despachos visibles=%d · candidatos=%s",
                 [s["label"] for s in self._selects], len(textos), cands)
        if cands:
            return cands

        # Cascada: departamento -> municipio, luego se vuelve a leer la lista de despachos.
        p = partes(radicado)
        for etiqueta, claves in (("DEPARTAMENTO", (p.departamento, p.nombre_departamento)),
                                 ("MUNICIPIO", (p.municipio, p.municipio[2:]))):
            idx = self._indice(etiqueta)
            if idx is None:
                continue
            opciones = await page.evaluate(JS_OPCIONES, idx)
            valor = _buscar_opcion(opciones, [c for c in claves if c])
            if valor is None:
                continue
            previas = len(textos)
            await page.evaluate(JS_SET, [idx, valor])
            await _esperar_red(page, 10_000)
            textos = await _esperar_opciones(page, i_desp, previas)
            cands = candidatos_despacho(radicado, textos)
            log.info("Tras elegir %s=%s · despachos visibles=%d · candidatos=%s",
                     etiqueta, valor, len(textos), cands)
            if cands:
                return cands
        return []

    def _indice(self, etiqueta: str) -> int | None:
        for s in self._selects:
            if etiqueta in sin_tildes(s["label"]) or etiqueta in sin_tildes(s["name"] or s["id"] or ""):
                return s["i"]
        return None

    async def _buscar_estados(self, page, despacho: str, ini: date, fin: date,
                              res: ResultadoEstados) -> list[Publicacion]:
        i_desp = self._indice("DESPACHO")
        opciones = await page.evaluate(JS_OPCIONES, i_desp)
        valor = next((o["v"] for o in opciones if o["t"] == despacho), None)
        if valor is None:
            res.advertencias.append(f"No se pudo seleccionar el despacho «{despacho}».")
            return []
        await page.evaluate(JS_SET, [i_desp, valor])
        await _esperar_red(page, 5_000)
        await self._fechas(page, ini, fin)

        await _clic_boton(page, BOTON_BUSCAR)
        await _esperar_red(page, 20_000)
        await detectar_captcha(page)

        chip = page.get_by_text(CATEGORIA_ESTADOS).first
        if not await chip.count():
            log.info("Sin categoría «Notificaciones por Estados» para %s entre %s y %s", despacho, ini, fin)
            return []  # sin «Notificaciones por Estados» en el rango
        await chip.click(timeout=5_000)
        await _esperar_red(page, 15_000)

        tarjetas = await page.evaluate(JS_TARJETAS)
        log.info("Publicaciones (VER DETALLE) encontradas: %d", len(tarjetas))
        pubs = []
        for t in tarjetas:
            titulo, fecha, numero = parsear_tarjeta(t["texto"])
            if not re.search(r"estado", titulo, re.I):
                continue
            href = t["href"]
            url = urljoin(page.url, href) if href and not href.startswith(("#", "javascript")) else None
            pubs.append(Publicacion(titulo=titulo, despacho=despacho, url_detalle=url,
                                    fecha_publicacion=fecha, numero_estado=numero))
        if tarjetas and not any(p.url_detalle for p in pubs):
            res.advertencias.append("Las publicaciones no exponen enlace de detalle; revisar selectores.")
        return pubs

    async def _fechas(self, page, ini: date, fin: date) -> None:
        fechas = page.locator("input[type='date']")
        if await fechas.count() >= 2:
            await fechas.nth(0).fill(ini.isoformat())
            await fechas.nth(1).fill(fin.isoformat())
            return
        textos = page.locator("input[placeholder*='dd/mm' i]")
        if await textos.count() >= 2:
            await textos.nth(0).fill(ini.strftime("%d/%m/%Y"))
            await textos.nth(1).fill(fin.strftime("%d/%m/%Y"))
            return
        raise PortalError("formulario_cambiado", "No se encontraron los campos de fecha")

    # ---------- detalle y PDFs ----------
    async def _revisar_publicacion(self, page, ctx, pub: Publicacion, radicado: str,
                                   res: ResultadoEstados) -> None:
        if not pub.url_detalle:
            return
        await page.goto(pub.url_detalle, wait_until="domcontentloaded", timeout=30_000)
        await _esperar_red(page, 15_000)
        await detectar_captcha(page)
        await _max_resultados_por_pagina(page)

        vistos: dict[str, Documento] = {}
        for _ in range(MAX_PAGINAS_DOCS):
            for d in await page.evaluate(JS_DOCUMENTOS):
                if d["href"] not in vistos:
                    nombre = d["nombre"] or d["href"].rsplit("/", 1)[-1]
                    vistos[d["href"]] = Documento(nombre, d["href"], clasificar_documento(nombre, radicado))
            siguiente = page.get_by_text(re.compile(r"^\s*siguiente\s*$", re.I)).first
            antes = len(vistos)
            if not await siguiente.count():
                break
            try:
                await siguiente.click(timeout=3_000)
                await _esperar_red(page, 8_000)
            except Exception:  # noqa: BLE001
                break
            nuevos = [d for d in await page.evaluate(JS_DOCUMENTOS) if d["href"] not in vistos]
            if not nuevos and len(vistos) == antes:
                break
        pub.documentos = list(vistos.values())
        log.info("%s · documentos=%s", pub.titulo, [(d.nombre, d.tipo) for d in pub.documentos])

        autos = [d for d in pub.documentos if d.tipo == "auto_radicado"]
        estados = [d for d in pub.documentos if d.tipo == "estado"][:MAX_PDFS_POR_PUBLICACION]
        encontrado = False
        for doc in estados:
            contenido = await _descargar(ctx, doc.url)
            if contenido is None:
                pub.pdfs_ilegibles.append(doc.nombre)
                continue
            try:
                lectura = leer_pdf(contenido)
            except Exception:  # noqa: BLE001 — PDF corrupto o no-PDF
                pub.pdfs_ilegibles.append(doc.nombre)
                continue
            pub.pdfs_leidos += 1
            if not lectura.legible:
                pub.pdfs_ilegibles.append(doc.nombre)
                continue
            if not pub.numero_estado:
                pub.numero_estado = numero_estado(lectura.encabezado)
            filas = buscar_radicado(lectura, radicado)
            log.info("PDF %s leído (%d tablas) · coincidencias=%d", doc.nombre, len(lectura.tablas), len(filas))
            for fila in filas:
                res.coincidencias.append(Coincidencia(pub, fila, doc, autos))
                encontrado = True
        if autos and not encontrado:
            # El auto del radicado está publicado aunque no se haya podido leer la fila del estado.
            res.coincidencias.append(Coincidencia(pub, None, None, autos))


# --- utilidades --------------------------------------------------------------------------------

def _buscar_opcion(opciones: list[dict], claves: list[str]) -> str | None:
    for clave in claves:
        c = sin_tildes(clave)
        for o in opciones:
            if o["v"] and (o["v"] == clave or sin_tildes(o["t"]) == c or sin_tildes(o["t"]).startswith(c)):
                return o["v"]
    return None


async def _esperar_opciones(page, indice: int, previas: int, timeout_s: float = 10) -> list[str]:
    """Espera a que la lista (cargada en cascada) cambie de tamaño; devuelve los textos."""
    fin = asyncio.get_running_loop().time() + timeout_s
    while True:
        textos = [o["t"] for o in await page.evaluate(JS_OPCIONES, indice)]
        if len(textos) != previas or asyncio.get_running_loop().time() > fin:
            return textos
        await asyncio.sleep(0.3)


async def _esperar_red(page, timeout: int) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:  # noqa: BLE001 — portales con long-polling nunca quedan 'idle'
        await asyncio.sleep(1)


async def _clic_boton(page, nombre: re.Pattern) -> None:
    for loc in (page.get_by_role("button", name=nombre), page.get_by_role("link", name=nombre),
                page.locator("input[type=submit], input[type=button]").filter(has_text=nombre)):
        if await loc.count():
            await loc.first.click(timeout=5_000)
            return
    boton = page.locator("input[value='BUSCAR' i], input[value='Buscar']")
    if await boton.count():
        await boton.first.click(timeout=5_000)
        return
    raise PortalError("formulario_cambiado", "No se encontró el botón BUSCAR")


async def _max_resultados_por_pagina(page) -> None:
    """Sube «10 Resultados por página» al máximo disponible para evitar paginar."""
    try:
        selects = page.locator("select")
        for i in range(await selects.count()):
            s = selects.nth(i)
            opciones = await s.evaluate("s => Array.from(s.options).map(o => [o.value, o.text])")
            if any("por p" in (t or "").lower() for _, t in opciones):
                numeros = [(int(m.group()), v) for v, t in opciones if (m := re.search(r"\d+", t or ""))]
                if numeros:
                    await s.select_option(max(numeros)[1])
                    await _esperar_red(page, 8_000)
                return
    except Exception:  # noqa: BLE001
        pass


async def _descargar(ctx, url: str) -> bytes | None:
    try:
        resp = await ctx.request.get(url, timeout=25_000)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo descargar %s: %s", url, e)
        return None
    if not resp.ok:
        return None
    cuerpo = await resp.body()
    return cuerpo if cuerpo[:5] == b"%PDF-" else None
