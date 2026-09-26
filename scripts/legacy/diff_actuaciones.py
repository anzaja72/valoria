#!/usr/bin/env python3
"""Compara dos snapshots de actuaciones.json y lista altas/bajas.

Uso:
    python scripts/legacy/diff_actuaciones.py viejo.json nuevo.json
    python scripts/legacy/diff_actuaciones.py --store store <radicado> nuevo.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def cargar(ruta: Path) -> list[dict]:
    data = json.loads(ruta.read_text(encoding="utf-8"))
    return data.get("actuaciones", data) if isinstance(data, dict) else data


def clave(a: dict) -> tuple:
    return (a.get("fecha_actuacion") or a.get("fechaActuacion"),
            a.get("actuacion"), a.get("anotacion"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--store", type=Path)
    p.add_argument("viejo")
    p.add_argument("nuevo", type=Path)
    a = p.parse_args()
    viejo = a.store / "procesos" / a.viejo / "actuaciones.json" if a.store else Path(a.viejo)
    va, na = cargar(viejo), cargar(a.nuevo)
    kv, kn = {clave(x) for x in va}, {clave(x) for x in na}
    altas = [x for x in na if clave(x) not in kv]
    bajas = [x for x in va if clave(x) not in kn]
    print(json.dumps({"nuevas": altas, "eliminadas": bajas}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
