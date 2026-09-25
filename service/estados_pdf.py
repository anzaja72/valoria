"""Lectura de los PDF de «Fijación de estados» y búsqueda de un radicado dentro de ellos."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from .despachos import sin_tildes

_NO_DIGITOS = re.compile(r"\D+")

# Encabezados típicos del reporte rptFijacionEstado.
COLUMNAS = {
    "radicacion": ("RADICACION", "RADICADO", "PROCESO", "NUMERO"),
    "clase": ("CLASE", "TIPO"),
    "demandante": ("DEMANDANTE", "ACCIONANTE"),
    "demandado": ("DEMANDADO", "ACCIONADO"),
    "fecha_auto": ("FECHA AUTO", "FECHA PROVIDENCIA", "FECHA"),
    "anotacion": ("AUTO / ANOTACION", "ANOTACION", "AUTO", "ACTUACION", "DESCRIPCION"),
    "ponente": ("PONENTE", "MAGISTRADO", "JUEZ"),
}


@dataclass
class FilaEstado:
    radicacion: str | None = None
    clase: str | None = None
    demandante: str | None = None
    demandado: str | None = None
    fecha_auto: str | None = None
    anotacion: str | None = None
    ponente: str | None = None
    texto: str | None = None  # texto crudo cuando no se pudo leer como tabla


@dataclass
class LecturaPDF:
    texto: str = ""
    tablas: list[list[list[str | None]]] = field(default_factory=list)
    encabezado: str = ""
    legible: bool = True


def leer_pdf(contenido: bytes) -> LecturaPDF:
    import pdfplumber

    lectura = LecturaPDF()
    textos = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            textos.append(pagina.extract_text() or "")
            try:
                lectura.tablas.extend(pagina.extract_tables() or [])
            except Exception:  # noqa: BLE001 — tablas mal formadas no deben tumbar la lectura
                pass
    lectura.texto = "\n".join(textos)
    lectura.encabezado = "\n".join(lectura.texto.splitlines()[:8])
    lectura.legible = bool(lectura.texto.strip())  # PDF escaneado sin capa de texto -> False
    return lectura


def _limpio(v: str | None) -> str | None:
    if v is None:
        return None
    t = " ".join(str(v).split())
    return t or None


def _mapear_encabezados(fila: list[str | None]) -> dict[str, int] | None:
    normal = [sin_tildes(c or "").replace("\n", " ") for c in fila]
    mapa: dict[str, int] = {}
    for campo, aliases in COLUMNAS.items():
        for i, celda in enumerate(normal):
            if i in mapa.values():
                continue
            if any(celda == a or celda.startswith(a) for a in aliases):
                mapa[campo] = i
                break
    return mapa if "radicacion" in mapa and len(mapa) >= 3 else None


def _contiene_radicado(celda: str | None, radicado: str) -> bool:
    return radicado in _NO_DIGITOS.sub("", celda or "")


def buscar_en_tablas(tablas: list[list[list[str | None]]], radicado: str) -> list[FilaEstado]:
    encontrados: list[FilaEstado] = []
    mapa: dict[str, int] | None = None
    for tabla in tablas:
        for fila in tabla:
            posible = _mapear_encabezados(fila)
            if posible:
                mapa = posible  # las tablas que continúan en otra página heredan el encabezado
                continue
            if not any(_contiene_radicado(c, radicado) for c in fila):
                continue
            if mapa:
                datos = {campo: _limpio(fila[i]) if i < len(fila) else None for campo, i in mapa.items()}
                datos["radicacion"] = radicado  # la celda puede venir partida en dos líneas
                encontrados.append(FilaEstado(**datos))
            else:
                encontrados.append(FilaEstado(radicacion=radicado,
                                              texto=_limpio(" | ".join(c or "" for c in fila))))
    return encontrados


def buscar_en_texto(texto: str, radicado: str) -> list[FilaEstado]:
    """Respaldo cuando no hay tablas: líneas cuyo contenido (solo dígitos) incluye el radicado."""
    out = []
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        if _contiene_radicado(linea, radicado):
            contexto = " ".join(lineas[i:i + 3])
            out.append(FilaEstado(radicacion=radicado, texto=_limpio(contexto)))
    return out


def buscar_radicado(lectura: LecturaPDF, radicado: str) -> list[FilaEstado]:
    return buscar_en_tablas(lectura.tablas, radicado) or buscar_en_texto(lectura.texto, radicado)


_ESTADO_NO = re.compile(r"ESTADO\s*(?:NO\.?|N[°º]|NUMERO)?\s*(\d{1,5})", re.I)


def numero_estado(texto: str) -> str | None:
    m = _ESTADO_NO.search(sin_tildes(texto or ""))
    return m.group(1) if m else None
