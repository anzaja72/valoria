"""Definición del tool para el LLM del chat (compatible con Anthropic `input_schema` y OpenAI `parameters`)."""
from __future__ import annotations

_PARAMS = {
    "type": "object",
    "properties": {
        "radicado": {
            "type": "string",
            "description": "Número de radicación del proceso judicial colombiano: 23 dígitos. "
                           "Se aceptan guiones, puntos o espacios (se normalizan).",
        },
        "forzar_actualizacion": {
            "type": "boolean",
            "description": "true solo si el usuario pide explícitamente datos frescos (ignora la cache).",
            "default": False,
        },
    },
    "required": ["radicado"],
    "additionalProperties": False,
}

TOOL_SCHEMA = {
    "name": "consultar_proceso",
    "description": (
        "Consulta en tiempo real un proceso judicial en la Consulta Nacional Unificada de la Rama Judicial "
        "de Colombia (consultaprocesos.ramajudicial.gov.co) por número de radicación de 23 dígitos. "
        "Devuelve estado, despacho, partes, actuaciones recientes y un bloque «Para el abogado». "
        "Úsalo cuando el usuario pegue o dicte un radicado. Interpreta `status`: ok | not_found | "
        "captcha_required | error. Muestra siempre `mensaje_chat`. Si status=captcha_required, ofrece abrir "
        "`url_oficial` para consulta manual y NO reintentes en bucle."
    ),
    "input_schema": _PARAMS,
    "parameters": _PARAMS,
    "response_statuses": ["ok", "not_found", "captcha_required", "error"],
    "timeout_ms": 90000,
}
