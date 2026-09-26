#!/usr/bin/env python3
"""Diagnóstico de publicacionesprocesales: muestra el formulario y ejecuta la consulta de estados paso a paso.

Uso (desde la raíz del repo, con el venv activo):
    python scripts/diagnostico_publicaciones.py 08001315300220260014600
    python scripts/diagnostico_publicaciones.py 08001315300220260014600 --desde 2026-09-21 --hasta 2026-09-25
    python scripts/diagnostico_publicaciones.py 08001315300220260014600 --headed    # ver el navegador
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.browser import Navegador  # noqa: E402
from service.fechas import ultimos_dias_habiles  # noqa: E402
from service.publicaciones import (  # noqa: E402
    JS_OPCIONES, JS_SELECTS, URL_PUBLICACIONES, PublicacionesClient,
)


async def estructura(nav: Navegador) -> None:
    ctx = await nav.new_context()
    page = await ctx.new_page()
    xhr = []
    page.on("request", lambda r: xhr.append(f"{r.method} {r.url}") if r.resource_type in ("xhr", "fetch") else None)
    await page.goto(URL_PUBLICACIONES, wait_until="networkidle", timeout=60_000)
    print("== Título:", await page.title())
    selects = await page.evaluate(JS_SELECTS)
    for s in selects:
        ops = await page.evaluate(JS_OPCIONES, s["i"])
        print(f"== select[{s['i']}] label={s['label']!r} id={s['id']!r} name={s['name']!r} opciones={len(ops)}")
        print("   ", [o["t"] for o in ops[:6]])
    print("== inputs:", await page.locator("input").evaluate_all(
        "els => els.map(e => [e.type, e.placeholder, e.id, e.name].join('|'))"))
    print("== botones:", [b.strip() for b in await page.locator("button, input[type=submit], a.btn").all_inner_texts()
                          if b.strip()][:20])
    print("== XHR al cargar:", xhr[:30])
    await page.screenshot(path="diagnostico_publicaciones.png", full_page=True)
    print("== Screenshot: diagnostico_publicaciones.png")
    await ctx.close()


async def main(radicado: str, desde: date, hasta: date, headed: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    nav = Navegador(headless=not headed)
    try:
        print("\n######## 1) Estructura del formulario ########")
        await estructura(nav)
        print(f"\n######## 2) Consulta de estados {radicado} ({desde} a {hasta}) ########")
        cliente = PublicacionesClient(nav, timeout_s=180)
        r = await cliente.consultar(radicado, desde, hasta)
        print("\n######## 3) Resultado ########")
        print(json.dumps(asdict(r), ensure_ascii=False, indent=2, default=str)[:8000])
    finally:
        await nav.stop()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("radicado")
    p.add_argument("--desde", type=date.fromisoformat)
    p.add_argument("--hasta", type=date.fromisoformat)
    p.add_argument("--headed", action="store_true")
    a = p.parse_args()
    ini, fin = ultimos_dias_habiles(5)
    asyncio.run(main(a.radicado, a.desde or ini, a.hasta or fin, a.headed))
