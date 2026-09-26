"""Servidor MCP (Model Context Protocol) sobre Streamable HTTP, en modo sin estado.

Endpoint: POST /mcp  (JSON-RPC 2.0, respuestas application/json)
Auth:     Authorization: Bearer <TOOL_API_KEY>  (mismas claves que la API REST)
Tools:    consultar_estados, consultar_proceso  (misma lógica, cache y navegador que /v1/*)

Se implementa directamente (sin SDK) porque el servidor solo expone herramientas: no usa
sesiones, notificaciones del servidor ni streaming. Cada POST es independiente.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from . import __version__
from .auth import verificar_bearer
from .models import ConsultaRequest, EstadosRequest
from .tool_schema import ESTADOS_TOOL_SCHEMA, TOOL_SCHEMA

log = logging.getLogger("mcp")

# Versiones del protocolo que este servidor entiende; si el cliente pide otra, se responde la última.
VERSIONES = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
INSTRUCCIONES = (
    "Herramientas de consulta judicial colombiana (Rama Judicial). Usa consultar_estados para saber si "
    "un radicado salió en Notificaciones por Estados (lo más útil para el abogado) y consultar_proceso "
    "para ver el estado y las actuaciones en la Consulta Nacional Unificada. Muestra siempre "
    "`mensaje_chat`. Si status=captcha_required, ofrece `url_oficial` y no reintentes en bucle."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602

_ANOTACIONES = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                "openWorldHint": True}


def _tool(schema: dict[str, Any], titulo: str) -> dict[str, Any]:
    return {
        "name": schema["name"],
        "title": titulo,
        "description": schema["description"],
        "inputSchema": schema["input_schema"],
        "annotations": {"title": titulo, **_ANOTACIONES},
    }


TOOLS_MCP = [
    _tool(ESTADOS_TOOL_SCHEMA, "Consultar notificaciones por estados"),
    _tool(TOOL_SCHEMA, "Consultar proceso (CPNU)"),
]


def _ok(id_: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _texto(resp: dict[str, Any]) -> str:
    """Texto para el modelo: mensaje_chat + bloque «Para el abogado» (+ enlace oficial)."""
    partes = [resp.get("mensaje_chat") or ""]
    pa = resp.get("para_el_abogado")
    if isinstance(pa, dict):
        pa = pa.get("texto")
    if pa:
        partes.append(pa)
    if resp.get("status") in ("captcha_required", "error") and resp.get("url_oficial"):
        partes.append(f"Consulta oficial: {resp['url_oficial']}")
    return "\n\n".join(p for p in partes if p)


async def _llamar_tool(app: FastAPI, nombre: str, args: dict[str, Any], canal: str) -> dict[str, Any]:
    from .main import ejecutar_estados, ejecutar_proceso  # import tardío: main importa este módulo

    if nombre == "consultar_estados":
        resp = await ejecutar_estados(app, EstadosRequest(**args), canal)
    elif nombre == "consultar_proceso":
        resp = await ejecutar_proceso(app, ConsultaRequest(**args), canal)
    else:
        raise KeyError(nombre)
    datos = resp.model_dump(mode="json", exclude_none=True)
    return {
        "content": [{"type": "text", "text": _texto(datos)}],
        "structuredContent": datos,
        # Un error del portal es un resultado válido para el modelo (debe mostrar mensaje_chat),
        # pero se marca para que el cliente sepa que la consulta no se completó.
        "isError": datos.get("status") == "error",
    }


async def _despachar(app: FastAPI, msg: Any, canal: str) -> dict[str, Any] | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _err(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "Invalid Request")
    metodo, id_, params = msg["method"], msg.get("id"), msg.get("params") or {}
    es_notificacion = "id" not in msg

    if metodo.startswith("notifications/"):
        return None
    if metodo == "initialize":
        pedida = params.get("protocolVersion")
        return _ok(id_, {
            "protocolVersion": pedida if pedida in VERSIONES else VERSIONES[-1],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "legal-ia-procesos", "title": "Legal-IA · Rama Judicial",
                           "version": __version__},
            "instructions": INSTRUCCIONES,
        })
    if metodo == "ping":
        return _ok(id_, {})
    if metodo == "tools/list":
        return _ok(id_, {"tools": TOOLS_MCP})
    if metodo == "tools/call":
        nombre, args = params.get("name"), params.get("arguments") or {}
        try:
            return _ok(id_, await _llamar_tool(app, nombre, args, canal))
        except KeyError:
            return _err(id_, INVALID_PARAMS, f"Herramienta desconocida: {nombre}")
        except (ValidationError, TypeError) as e:
            return _err(id_, INVALID_PARAMS, f"Argumentos inválidos: {e}")
    if es_notificacion:
        return None
    return _err(id_, METHOD_NOT_FOUND, f"Método no soportado: {metodo}")


def registrar_mcp(app: FastAPI) -> None:
    @app.post("/mcp")
    async def mcp_post(request: Request, canal: str = Depends(verificar_bearer)):
        try:
            cuerpo = json.loads(await request.body())
        except ValueError:
            return JSONResponse(_err(None, PARSE_ERROR, "Parse error"), status_code=400)

        if isinstance(cuerpo, list):  # lotes JSON-RPC (protocolo 2025-03-26)
            respuestas = [r for m in cuerpo if (r := await _despachar(app, m, canal)) is not None]
            return JSONResponse(respuestas) if respuestas else Response(status_code=202)
        respuesta = await _despachar(app, cuerpo, canal)
        if respuesta is None:
            return Response(status_code=202)
        if isinstance(cuerpo, dict) and cuerpo.get("method") == "tools/call":
            log.info("tools/call canal=%s tool=%s", canal, (cuerpo.get("params") or {}).get("name"))
        return JSONResponse(respuesta)

    @app.get("/mcp")
    async def mcp_get(canal: str = Depends(verificar_bearer)):
        # Sin flujo SSE iniciado por el servidor (modo sin estado).
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.delete("/mcp")
    async def mcp_delete(canal: str = Depends(verificar_bearer)):
        return Response(status_code=405, headers={"Allow": "POST"})
