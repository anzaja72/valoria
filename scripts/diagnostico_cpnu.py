#!/usr/bin/env python3
"""Diagnóstico del portal CPNU: muestra paso a paso qué responde el portal para un radicado.

Uso (desde la raíz del repo, con el venv activo):
    python scripts/diagnostico_cpnu.py 15236408900120200006200
    python scripts/diagnostico_cpnu.py 15236408900120200006200 --headed   # ver el navegador
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.config import CPNU_API_BASE, CPNU_BASE_URL, URL_OFICIAL  # noqa: E402


def recorte(obj, n=1500) -> str:
    t = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return t if len(t) <= n else t[:n] + " …"


async def main(radicado: str, headed: bool) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        ctx = await browser.new_context(locale="es-CO", timezone_id="America/Bogota")
        page = await ctx.new_page()
        api_calls = []
        page.on("response", lambda r: api_calls.append((r.status, r.url)) if ":448/" in r.url else None)

        print(f"1) Abriendo {URL_OFICIAL}")
        r = await page.goto(URL_OFICIAL, wait_until="networkidle", timeout=45_000)
        print(f"   HTTP {r.status if r else '?'} · título: {await page.title()!r}")
        inputs = await page.locator("input").evaluate_all(
            "els => els.map(e => ({type:e.type, maxlength:e.maxLength, placeholder:e.placeholder, "
            "aria:e.getAttribute('aria-label'), visible: !!e.offsetParent}))")
        print("   inputs:", recorte(inputs, 800))
        botones = await page.locator("button").all_inner_texts()
        print("   botones:", [b.strip() for b in botones if b.strip()][:15])
        radios = await page.locator("label, .v-label").all_inner_texts()
        print("   labels:", [x.strip() for x in radios if x.strip()][:20])

        for solo in ("false", "true"):
            print(f"\n2) API directa SoloActivos={solo}")
            resp = await ctx.request.get(
                f"{CPNU_API_BASE}/Procesos/Consulta/NumeroRadicacion",
                params={"numero": radicado, "SoloActivos": solo, "pagina": 1},
                headers={"Origin": CPNU_BASE_URL, "Referer": URL_OFICIAL, "Accept": "application/json"},
            )
            print(f"   HTTP {resp.status}")
            print("  ", recorte(await resp.text()))

        print("\n3) Llamadas a la API :448 hechas por la página:")
        for st, url in api_calls:
            print(f"   {st} {url}")
        await page.screenshot(path="diagnostico_cpnu.png", full_page=True)
        print("\nScreenshot: diagnostico_cpnu.png")
        await browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("radicado")
    p.add_argument("--headed", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.radicado, a.headed))
