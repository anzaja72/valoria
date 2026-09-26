"""Chromium compartido (un proceso) para todos los clientes; cada consulta usa su propio contexto."""
from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger("browser")

CAPTCHA_SELECTORES = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='turnstile']",
    "iframe[title*='captcha' i]",
    "div.g-recaptcha",
    "div.h-captcha",
    "div.cf-turnstile",
)
CAPTCHA_TEXTO = re.compile(r"captcha|no soy un robot|verifique que es humano|verify you are human", re.I)
ERRORES_RED = ("net::ERR_", "ECONNREFUSED", "ECONNRESET")


class CaptchaRequerido(Exception):
    pass


class PortalError(Exception):
    def __init__(self, code: str, msg: str = "") -> None:
        super().__init__(msg or code)
        self.code = code


def es_error_de_red(e: Exception) -> bool:
    return any(x in str(e) for x in ERRORES_RED)


async def detectar_captcha(page) -> None:
    for sel in CAPTCHA_SELECTORES:
        if await page.locator(sel).count():
            raise CaptchaRequerido()
    try:
        texto = await page.locator("body").inner_text(timeout=2_000)
    except Exception:  # noqa: BLE001
        return
    if CAPTCHA_TEXTO.search(texto or ""):
        raise CaptchaRequerido()


class Navegador:
    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return
            from playwright.async_api import async_playwright

            if self._pw is None:
                self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.headless, args=["--disable-dev-shm-usage", "--no-sandbox"]
            )
            log.info("Chromium iniciado")

    async def new_context(self, **kwargs):
        await self.start()
        opts = {"locale": "es-CO", "timezone_id": "America/Bogota",
                "extra_http_headers": {"Accept-Language": "es-CO,es;q=0.9"}}
        opts.update(kwargs)
        return await self._browser.new_context(**opts)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    @property
    def listo(self) -> bool:
        return bool(self._browser and self._browser.is_connected())
