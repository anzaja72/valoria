"""Normalización y validación del número de radicación (23 dígitos)."""
from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D+")


def normalizar_radicado(valor: str | None) -> str | None:
    """Quita espacios, guiones y puntos. Devuelve None si no quedan 23 dígitos."""
    if not valor:
        return None
    digitos = _NON_DIGITS.sub("", str(valor))
    return digitos if len(digitos) == 23 else None


def formatear_radicado(radicado: str) -> str:
    """15236408900120200006200 -> 15-236-40-89-001-2020-00062-00 (formato legible)."""
    r = radicado
    return f"{r[0:2]}-{r[2:5]}-{r[5:7]}-{r[7:9]}-{r[9:12]}-{r[12:16]}-{r[16:21]}-{r[21:23]}"
