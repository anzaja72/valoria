# Imagen oficial de Playwright: trae Chromium + dependencias del sistema.
# Mantener la versión alineada con `playwright==` en requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    STORE_DIR=/app/store

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY service ./service
COPY clients ./clients
RUN mkdir -p /app/store && chown -R pwuser:pwuser /app

USER pwuser
EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8088/health',timeout=4).status==200 else 1)"

# Un solo worker: el navegador y la cache viven en memoria del proceso.
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8088", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
