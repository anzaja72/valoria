"""Autenticación Bearer con TOOL_API_KEYS (prefijos web_ / desktop_)."""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

CANALES = ("web", "desktop")


def canal_de_clave(clave: str) -> str | None:
    prefijo = clave.split("_", 1)[0]
    return prefijo if prefijo in CANALES and "_" in clave else None


def verificar_bearer(request: Request) -> str:
    """Dependencia FastAPI: devuelve el canal ('web' | 'desktop') o lanza 401/503."""
    claves: tuple[str, ...] = request.app.state.settings.api_keys
    if not claves:
        # Fail-closed: sin claves configuradas no se atiende a nadie.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "TOOL_API_KEYS no configurado")

    header = request.headers.get("authorization", "")
    esquema, _, token = header.partition(" ")
    token = token.strip()
    if esquema.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Falta Authorization: Bearer <TOOL_API_KEY>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    valida = False
    for clave in claves:
        # Recorre todas las claves para no filtrar información por tiempo.
        if hmac.compare_digest(clave.encode(), token.encode()):
            valida = True
    canal = canal_de_clave(token) if valida else None
    if not canal:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Clave inválida", headers={"WWW-Authenticate": "Bearer"}
        )
    return canal
