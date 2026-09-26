# Legal-IA · consulta de procesos (Rama Judicial)

Tools para el chat de **legal-ia.co** y **Legal-IA Desktop**. El usuario pega o dicta un radicado de 23 dígitos:

| Tool | Endpoint | Fuente | Qué responde |
|---|---|---|---|
| `consultar_estados` ⭐ | `POST /v1/consultar_estados` | publicacionesprocesales.ramajudicial.gov.co | ¿Salió el radicado en **Notificaciones por Estados** en los últimos 5 días hábiles? Número de estado, fecha, anotación del auto, PDF del estado y de la providencia. |
| `consultar_proceso` | `POST /v1/consultar_proceso` | consultaprocesos.ramajudicial.gov.co (CPNU) | Estado del proceso, actuaciones y bloque «Para el abogado». |

### Servidor MCP

Las dos herramientas también se exponen como **servidor MCP** (Model Context Protocol, transporte
Streamable HTTP sin estado) para conectar legal-ia.co, Legal-IA Desktop o cualquier cliente MCP:

- URL: `https://consulta.legal-ia.co/mcp`
- Header: `Authorization: Bearer <TOOL_API_KEY>` (mismas claves `web_` / `desktop_`)
- Herramientas: `consultar_estados`, `consultar_proceso` (misma lógica, cache y navegador que `/v1/*`)
- Cada `tools/call` devuelve `content` (texto: `mensaje_chat` + «Para el abogado») y `structuredContent`
  (la respuesta JSON completa). `isError: true` cuando el portal falló.

Configuración típica de un cliente MCP:

```json
{
  "mcpServers": {
    "legal-ia-procesos": {
      "type": "http",
      "url": "https://consulta.legal-ia.co/mcp",
      "headers": { "Authorization": "Bearer ${LEGAL_IA_TOOL_KEY}" }
    }
  }
}
```

### Cómo funciona `consultar_estados`
Replica el flujo manual del portal de publicaciones:
1. Deduce el despacho de los primeros 12 dígitos del radicado. Si el código exacto no está publicado, prueba
   despachos con igual departamento + municipio + entidad + número (p. ej. radicado `080013153002…` publicado por
   `080013103002 - JUZGADO 002 CIVIL DEL CIRCUITO DE BARRANQUILLA`).
2. Filtra por despacho y rango de fechas → **BUSCAR** → categoría **Notificaciones por Estados**.
3. Entra a **VER DETALLE** de cada estado, lista los documentos y descarga los PDF de fijación de estados.
4. Lee la tabla (Radicación, Clase, Demandante, Demandado, Fecha auto, Auto/Anotación, Ponente) y busca el radicado.
   Los PDF de autos cuyo nombre corresponde al radicado (`002-2026-00146 Admite….pdf`) se devuelven como enlace.

Limitaciones: PDF escaneados (sin texto) se reportan en `pdfs_ilegibles`; los festivos no se descuentan del rango.

Diagnóstico contra el portal real: `python scripts/diagnostico_publicaciones.py <radicado> [--headed]`.

---

## `consultar_proceso` (CPNU)

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
  publicaciones.py  cliente Playwright contra publicacionesprocesales (Notificaciones por Estados)
  estados_pdf.py    lectura de PDF de fijación de estados (pdfplumber) y búsqueda del radicado
  despachos.py      despacho a partir del radicado; fechas.py (días hábiles); browser.py (Chromium compartido)
  cpnu.py           cliente Playwright contra CPNU (UI + API :448 con la misma sesión)
  formatter.py      mensaje_chat, «Para el abogado», alertas
  store.py          store/procesos/<radicado>/{meta.json, actuaciones.json, pdfs/}
  cache.py auth.py config.py models.py radicado.py tool_schema.py
clients/contract.json   contrato para legal-ia.co / Desktop
deploy/             Caddyfile + snippet nginx
scripts/            diagnostico_publicaciones.py, diagnostico_cpnu.py; legacy/ (diff de actuaciones)
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

curl -s -X POST http://127.0.0.1:8088/v1/consultar_estados \
  -H "Authorization: Bearer web_dev" -H "Content-Type: application/json" \
  -d '{"radicado":"08001315300220260014600","fecha_inicio":"2026-09-21","fecha_fin":"2026-09-25"}' --max-time 90
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
- **Publicaciones procesales (estados):** <https://publicacionesprocesales.ramajudicial.gov.co/> — tool `consultar_estados`.

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
