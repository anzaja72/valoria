#!/usr/bin/env python3
"""PoC exploratorio: publicacionesprocesales.ramajudicial.gov.co (estados / fijaciones).

NO es parte del tool consultar_proceso. Abre el portal, busca un texto (p. ej. nombre del despacho)
y guarda un screenshot + el HTML para análisis manual de selectores.
Si aparece un CAPTCHA, se detiene: nunca se automatiza.

Uso:
    python scripts/legacy/publicaciones_poc.py "JUZGADO 001 PROMISCUO MUNICIPAL" --out store/publicaciones
"""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

URL = "https://publicacionesprocesales.ramajudicial.gov.co/"


async def main(texto: str, out: Path, headless: bool) -> None:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        page = await browser.new_page(locale="es-CO")
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        if await page.locator("iframe[src*='captcha']").count():
            print("captcha_required — abrir manualmente:", URL)
            await browser.close()
            return
        buscador = page.locator("input[type='search'], input[type='text']").first
        if await buscador.count():
            await buscador.fill(texto)
            await buscador.press("Enter")
            await page.wait_for_load_state("networkidle", timeout=30_000)
        slug = re.sub(r"\W+", "_", texto)[:60]
        await page.screenshot(path=str(out / f"{slug}.png"), full_page=True)
        (out / f"{slug}.html").write_text(await page.content(), encoding="utf-8")
        print("Guardado en", out)
        await browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("texto")
    p.add_argument("--out", type=Path, default=Path("store/publicaciones"))
    p.add_argument("--headed", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.texto, a.out, not a.headed))
