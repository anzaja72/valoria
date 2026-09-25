"""Rango de fechas por defecto: últimos N días hábiles (lunes a viernes) incluyendo hoy."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")
MAX_DIAS_RANGO = 31


def hoy_bogota() -> date:
    return datetime.now(BOGOTA).date()


def ultimos_dias_habiles(n: int = 5, hasta: date | None = None) -> tuple[date, date]:
    """(inicio, fin). Festivos no se descuentan: un rango de 5 días hábiles puede cubrir 4."""
    fin = hasta or hoy_bogota()
    dia, contados = fin, 0
    while True:
        if dia.weekday() < 5:
            contados += 1
            if contados == n:
                return dia, fin
        dia -= timedelta(days=1)
