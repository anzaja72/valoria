# Despliegue en VPS (Linux)

## 1. Requisitos
- VPS Ubuntu 22.04/24.04, 2 vCPU / 2 GB RAM mínimo (Chromium), Docker + plugin Compose.
- DNS: registro `A` (y `AAAA` si aplica) de `consulta.legal-ia.co` → IP del VPS.
- Puertos 80/443 abiertos (Caddy). El 8088 queda solo en loopback.

## 2. Código en el servidor
```bash
git clone https://github.com/anzaja72/valoria.git legal-ia-procesos && cd legal-ia-procesos
# alternativa sin GitHub: rsync -av --exclude .venv --exclude store ./ usuario@vps:~/legal-ia-procesos/
```

## 3. Claves productivas
```bash
cp .env.example .env
python3 -c "import secrets;print('web_'+secrets.token_urlsafe(32))"
python3 -c "import secrets;print('desktop_'+secrets.token_urlsafe(32))"
# Pegar ambas en TOOL_API_KEYS=web_...,desktop_...   (nunca reutilizar web_dev/desktop_dev)
chmod 600 .env
```
Rotación: añadir la clave nueva junto a la vieja, actualizar clientes, quitar la vieja y `docker compose up -d`.

## 4. Levantar
Con Caddy (HTTPS automático):
```bash
docker compose --profile caddy up -d --build
```
Con nginx existente: `docker compose up -d --build` y usar `deploy/nginx.conf.snippet` (+ `certbot --nginx`).

## 5. Verificar
```bash
curl -s https://consulta.legal-ia.co/health
curl -s -X POST https://consulta.legal-ia.co/v1/consultar_proceso \
  -H "Authorization: Bearer $WEB_KEY" -H "Content-Type: application/json" \
  -d '{"radicado":"15236408900120200006200"}' --max-time 90
docker compose logs -f api
```

## 6. Operación
- Un solo worker uvicorn (navegador + cache en memoria). Escalar con `MAX_CONCURRENT_QUERIES` (2–3 por 2 GB RAM).
- `store/` es un volumen: respaldarlo si se quiere historial de actuaciones.
- Timeouts en cadena: scraper 75 s < proxy 95 s; el cliente usa 90 s.
- Si CPNU devuelve 502 o hay caída de red, la API responde `status: error`, `error_code: portal_unavailable`.
- Si aparecen CAPTCHAs frecuentes: bajar concurrencia y subir `CACHE_TTL_SECONDS`; nunca automatizar el CAPTCHA.
- Actualizar: `git pull && docker compose --profile caddy up -d --build`.
