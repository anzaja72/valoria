# Legal-IA · `consultar_proceso` (Rama Judicial / CPNU)

Tool para el chat de **legal-ia.co** y **Legal-IA Desktop**: el usuario pega o dicta un radicado de 23 dígitos
y recibe estado, actuaciones y un bloque **«Para el abogado»**, sin salir del chat.

- **Modo:** consulta puntual (no watchlist; queda para después).
- **Fuente:** Consulta Nacional Unificada — <https://consultaprocesos.ramajudicial.gov.co/> (CPNU).
- **Stack:** FastAPI + Playwright + Chromium headless.
- **Auth:** `Authorization: Bearer <TOOL_API_KEY>`, claves separadas `web_…` y `desktop_…` en `TOOL_API_KEYS`.
- **CAPTCHA:** nunca se automatiza ni se evade → `status: captcha_required` + `url_oficial` (handoff humano).
- **Cache:** TTL en memoria (`CACHE_TTL_SECONDS`, default 600 s). Solo se cachean `ok` y `not_found`.
- **Timeouts:** scraper 75 s (`SCRAPER_TIMEOUT_SECONDS`) < cliente 90 s (`timeout_ms: 90000`).
- **Producción (placeholder):** `https://consulta.legal-ia.co`

## Estructura

```
service/            API FastAPI
  main.py           endpoints /health, /v1/tool_schema, /v1/consultar_proceso
  cpnu.py           cliente Playwright contra CPNU (UI + API :448 con la misma sesión)
  formatter.py      mensaje_chat, «Para el abogado», alertas
  store.py          store/procesos/<radicado>/{meta.json, actuaciones.json, pdfs/}
  cache.py auth.py config.py models.py radicado.py tool_schema.py
clients/contract.json   contrato para legal-ia.co / Desktop
deploy/             Caddyfile + snippet nginx
scripts/legacy/     diff de actuaciones y PoC publicacionesprocesales (fuera del path crítico)
tests/              pytest (con un cliente CPNU falso; no tocan la red)
Dockerfile · docker-compose.yml · DEPLOY.md · .env.example
```

## Correr en local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
export TOOL_API_KEYS=web_dev,desktop_dev
uvicorn service.main:app --host 0.0.0.0 --port 8088
```

O con Compose:

```bash
cp .env.example .env   # editar TOOL_API_KEYS
docker compose up -d --build
```

Prueba:

```bash
curl -s http://127.0.0.1:8088/health
curl -s -X POST http://127.0.0.1:8088/v1/consultar_proceso \
  -H "Authorization: Bearer web_dev" -H "Content-Type: application/json" \
  -d '{"radicado":"15236408900120200006200"}' --max-time 90
```

Tests:

```bash
pip install -r requirements-dev.txt && pytest -q
```

## Contrato (resumen)

| Campo | Descripción |
|---|---|
| `status` | `ok` \| `not_found` \| `captcha_required` \| `error` |
| `mensaje_chat` | Texto listo para mostrar. **Mostrar siempre.** |
| `url_oficial` | Enlace a CPNU para consulta manual (obligatorio en `captcha_required`). |
| `error_code` | Solo en `error`: `invalid_radicado`, `portal_unavailable` (p. ej. HTTP 502 del portal), `timeout`, `portal_error`, `respuesta_invalida`, `scraper_error`. |
| `proceso` | Despacho, ponente, tipo/clase, partes, fechas, `es_privado`. |
| `actuaciones` | Más reciente primero (máx. `MAX_ACTUACIONES`). |
| `para_el_abogado` | `resumen`, `ultima_actuacion`, `terminos_en_curso`, `nuevas_desde_ultima_consulta`, `alertas`, `texto` (markdown), `aviso`. |
| `desde_cache`, `consultado_en`, `coincidencias`, `total_actuaciones` | Metadatos. |

Los resultados de negocio responden **HTTP 200** con `status`; `401` = clave inválida, `503` = sin claves configuradas.
Detalle completo en [`clients/contract.json`](clients/contract.json) y en `GET /v1/tool_schema`.

## Portales Rama Judicial

- **CPNU (principal):** <https://consultaprocesos.ramajudicial.gov.co/>
- TYBA: <https://procesojudicial.ramajudicial.gov.co/> — exploratorio, no es parte del contrato actual.
- Publicaciones procesales: <https://publicacionesprocesales.ramajudicial.gov.co/> — PoC secundario (`scripts/legacy`).

## Decisiones

- **Laya-MLX:** opcional, solo en Mac Apple Silicon (experimentación / Desktop offline). En VPS Linux solo Playwright.
  Jev no está en el camino crítico.
- Si la UI de CPNU cambia y los selectores fallan, el cliente usa la API del portal con la misma sesión del navegador.
  Laya/ONNX como fallback de selectores queda para el futuro, no en el VPS.

## Estado

- **Hecho:** API lista para chat, auth Bearer, tool schema, cache, store local, política CAPTCHA, errores estructurados
  (502/timeout/red), Docker/Compose/Caddy/nginx, contrato cliente, tests.
- **Pendiente crítico:** desplegar en VPS real (SSH + DNS de `consulta.legal-ia.co`), rotar claves productivas,
  cablear el tool en el chat de legal-ia.co y en Desktop, validar selectores contra el portal real.
- **Riesgos:** HTTP 502 ocasional de CPNU, CAPTCHAs intermitentes, cambios de UI del portal.
