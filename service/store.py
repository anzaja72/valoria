"""Store local: store/procesos/<radicado>/{meta.json, actuaciones.json, pdfs/}."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import Actuacion


class Store:
    def __init__(self, base: Path) -> None:
        self.base = Path(base) / "procesos"

    def _dir(self, radicado: str) -> Path:
        return self.base / radicado

    def cargar_actuaciones(self, radicado: str) -> list[Actuacion] | None:
        f = self._dir(radicado) / "actuaciones.json"
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return [Actuacion(**a) for a in data.get("actuaciones", [])]
        except (OSError, ValueError, TypeError):
            return None

    def guardar(self, radicado: str, meta: dict[str, Any], actuaciones: list[Actuacion]) -> None:
        d = self._dir(radicado)
        (d / "pdfs").mkdir(parents=True, exist_ok=True)
        _escribir(d / "meta.json", meta)
        _escribir(d / "actuaciones.json", {
            "radicado": radicado,
            "consultado_en": meta.get("consultado_en"),
            "actuaciones": [a.model_dump() for a in actuaciones],
        })


def _escribir(ruta: Path, data: Any) -> None:
    """Escritura atómica (tmp + rename) para no dejar JSON a medias."""
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)
