"""Deducción del despacho a partir del radicado de 23 dígitos.

Estructura del radicado (Acuerdo PSAA / CGP):
    DD MMM EE EE DDD AAAA NNNNN RR
    │  │   │  │  │   │    │     └ recurso
    │  │   │  │  │   │    └ consecutivo
    │  │   │  │  │   └ año
    │  │   │  │  └ número del despacho
    │  │   │  └ especialidad
    │  │   └ entidad / corporación
    │  └ municipio (DANE)
    └ departamento (DANE)

El código de despacho son los primeros 12 dígitos. En la práctica el código publicado en
publicacionesprocesales puede diferir en la especialidad (p. ej. radicado 080013153002…
publicado por «080013103002 - JUZGADO 002 CIVIL DEL CIRCUITO DE BARRANQUILLA»), por eso se
buscan candidatos con mismo departamento+municipio+entidad+número de despacho.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEPARTAMENTOS = {
    "05": "ANTIOQUIA", "08": "ATLÁNTICO", "11": "BOGOTÁ", "13": "BOLÍVAR", "15": "BOYACÁ",
    "17": "CALDAS", "18": "CAQUETÁ", "19": "CAUCA", "20": "CESAR", "23": "CÓRDOBA",
    "25": "CUNDINAMARCA", "27": "CHOCÓ", "41": "HUILA", "44": "LA GUAJIRA", "47": "MAGDALENA",
    "50": "META", "52": "NARIÑO", "54": "NORTE DE SANTANDER", "63": "QUINDÍO", "66": "RISARALDA",
    "68": "SANTANDER", "70": "SUCRE", "73": "TOLIMA", "76": "VALLE DEL CAUCA", "81": "ARAUCA",
    "85": "CASANARE", "86": "PUTUMAYO", "88": "SAN ANDRÉS", "91": "AMAZONAS", "94": "GUAINÍA",
    "95": "GUAVIARE", "97": "VAUPÉS", "99": "VICHADA",
}

_CODIGO = re.compile(r"\b(\d{12})\b")


@dataclass(frozen=True)
class PartesRadicado:
    radicado: str
    departamento: str
    municipio: str  # 5 dígitos DANE (depto + municipio)
    entidad: str
    especialidad: str
    numero_despacho: str
    anio: str
    consecutivo: str
    recurso: str

    @property
    def codigo_despacho(self) -> str:
        return self.radicado[:12]

    @property
    def nombre_departamento(self) -> str | None:
        return DEPARTAMENTOS.get(self.departamento)

    @property
    def patron_auto(self) -> str:
        """Prefijo con que los despachos suelen nombrar los PDF de autos: 002-2026-00146."""
        return f"{self.numero_despacho}-{self.anio}-{self.consecutivo}"


def partes(radicado: str) -> PartesRadicado:
    r = radicado
    return PartesRadicado(r, r[0:2], r[0:5], r[5:7], r[7:9], r[9:12], r[12:16], r[16:21], r[21:23])


def codigo_de_opcion(texto: str) -> str | None:
    """'080013103002 - JUZGADO 002 CIVIL…' -> '080013103002'."""
    m = _CODIGO.search(texto or "")
    return m.group(1) if m else None


# Especialidades que publican bajo el mismo despacho (observado en el portal: radicado 080013153002…
# publicado por 080013103002 - JUZGADO 002 CIVIL DEL CIRCUITO DE BARRANQUILLA).
ESPECIALIDADES_EQUIVALENTES = {"53": {"03"}, "03": {"53"}}


def candidatos_despacho(radicado: str, opciones: list[str], maximo: int = 4) -> list[str]:
    """Despachos del portal a revisar para el radicado, del más al menos probable.

    1. Código exacto (12 dígitos) → solo ese.
    2. Si no, misma ubicación/entidad/número con especialidad equivalente (53 ↔ 03) → solo esos.
    3. Si no, mismo depto+municipio+entidad y número de despacho con otra especialidad (hasta `maximo`).
    """
    p = partes(radicado)
    equivalentes = ESPECIALIDADES_EQUIVALENTES.get(p.especialidad, set())
    exactos, afines, parecidos = [], [], []
    for texto in opciones:
        cod = codigo_de_opcion(texto)
        if not cod:
            continue
        if cod == p.codigo_despacho:
            exactos.append(texto)
        elif cod[:7] == radicado[:7] and cod[9:12] == p.numero_despacho:
            (afines if cod[7:9] in equivalentes else parecidos).append(texto)
    return exactos or afines or parecidos[:maximo]


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").upper().strip()
