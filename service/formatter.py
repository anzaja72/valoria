"""Transforma la respuesta cruda de CPNU en el contrato del tool (mensaje_chat + «Para el abogado»)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import Actuacion, ParaElAbogado, Proceso, Sujeto
from .radicado import formatear_radicado

AVISO = ("Información tomada de la Consulta Nacional Unificada (CPNU) de la Rama Judicial. "
         "Es de carácter informativo: verifique en el expediente y en los estados/notificaciones oficiales.")
DIAS_INACTIVIDAD_ALERTA = 180


def _fecha(valor: Any) -> str | None:
    """'2024-05-10T00:00:00' -> '2024-05-10'."""
    if not valor:
        return None
    return str(valor)[:10]


def _limpio(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = " ".join(str(valor).split())
    return texto or None


def normalizar_actuacion(a: dict[str, Any]) -> Actuacion:
    return Actuacion(
        fecha_actuacion=_fecha(a.get("fechaActuacion")),
        actuacion=_limpio(a.get("actuacion")),
        anotacion=_limpio(a.get("anotacion")),
        fecha_inicia_termino=_fecha(a.get("fechaInicial")),
        fecha_finaliza_termino=_fecha(a.get("fechaFinal")),
        fecha_registro=_fecha(a.get("fechaRegistro")),
        con_documentos=bool(a.get("conDocumentos")),
    )


def _sujetos_desde_texto(texto: str | None) -> list[Sujeto]:
    """'Demandante: ANA | Demandado: BANCO' -> [Sujeto(...), ...]."""
    out = []
    for parte in (texto or "").split("|"):
        tipo, sep, nombre = parte.partition(":")
        if sep and nombre.strip():
            out.append(Sujeto(tipo=_limpio(tipo), nombre=_limpio(nombre)))
    return out


def normalizar_proceso(elegido: dict, detalle: dict | None, sujetos: list[dict]) -> Proceso:
    d = detalle or {}
    lista = [Sujeto(tipo=_limpio(s.get("tipoSujeto")), nombre=_limpio(s.get("nombreRazonSocial")))
             for s in sujetos] or _sujetos_desde_texto(elegido.get("sujetosProcesales"))
    return Proceso(
        id_proceso=elegido.get("idProceso"),
        despacho=_limpio(d.get("despacho") or elegido.get("despacho")),
        departamento=_limpio(elegido.get("departamento")),
        ponente=_limpio(d.get("ponente")),
        tipo_proceso=_limpio(d.get("tipoProceso")),
        clase_proceso=_limpio(d.get("claseProceso")),
        subclase_proceso=_limpio(d.get("subclaseProceso")),
        recurso=_limpio(d.get("recurso")),
        ubicacion=_limpio(d.get("ubicacion")),
        contenido_radicacion=_limpio(d.get("contenidoRadicacion")),
        fecha_radicacion=_fecha(d.get("fechaProceso") or elegido.get("fechaProceso")),
        fecha_ultima_actuacion=_fecha(elegido.get("fechaUltimaActuacion")),
        es_privado=bool(elegido.get("esPrivado") or d.get("esPrivado")),
        sujetos=lista,
    )


def ordenar_actuaciones(acts: list[Actuacion]) -> list[Actuacion]:
    return sorted(acts, key=lambda a: (a.fecha_actuacion or "", a.fecha_registro or ""), reverse=True)


def _clave(a: Actuacion) -> tuple:
    return (a.fecha_actuacion, a.actuacion, a.anotacion)


def nuevas_actuaciones(actuales: list[Actuacion], previas: list[Actuacion] | None) -> list[Actuacion]:
    if previas is None:
        return []
    vistas = {_clave(a) for a in previas}
    return [a for a in actuales if _clave(a) not in vistas]


def _linea(a: Actuacion) -> str:
    texto = f"**{a.fecha_actuacion or 's.f.'}** · {a.actuacion or 'Actuación'}"
    if a.anotacion:
        anot = a.anotacion if len(a.anotacion) <= 220 else a.anotacion[:217] + "…"
        texto += f" — {anot}"
    return texto


def construir_para_el_abogado(proceso: Proceso, actuaciones: list[Actuacion], total: int,
                              nuevas: list[Actuacion], hoy: date | None = None) -> ParaElAbogado:
    hoy = hoy or date.today()
    ultima = actuaciones[0] if actuaciones else None
    iso_hoy = hoy.isoformat()
    terminos = [a for a in actuaciones
                if a.fecha_finaliza_termino and a.fecha_finaliza_termino >= iso_hoy]

    alertas: list[str] = []
    if proceso.es_privado:
        alertas.append("Proceso con reserva: el portal no publica actuaciones; consulte directamente en el despacho.")
    if nuevas:
        alertas.append(f"{len(nuevas)} actuación(es) nueva(s) desde la última consulta registrada.")
    for a in terminos:
        alertas.append(f"Término en curso: «{a.actuacion}» vence {a.fecha_finaliza_termino}.")
    ref = (ultima.fecha_actuacion if ultima else None) or proceso.fecha_ultima_actuacion
    if ref:
        try:
            dias = (hoy - datetime.strptime(ref, "%Y-%m-%d").date()).days
            if dias > DIAS_INACTIVIDAD_ALERTA:
                alertas.append(f"Sin movimiento hace {dias} días (última actuación {ref}).")
        except ValueError:
            pass
    if ultima and ultima.con_documentos:
        alertas.append("La última actuación tiene documentos adjuntos en el portal.")

    partes = [p for p in (proceso.clase_proceso, proceso.despacho) if p]
    resumen = " en ".join(partes) if partes else "Proceso registrado en CPNU"
    if total:
        resumen += f". {total} actuación(es) registradas"
    resumen += "."

    lineas = ["### Para el abogado", resumen]
    if proceso.sujetos:
        lineas.append("**Partes:** " + "; ".join(f"{s.tipo}: {s.nombre}" for s in proceso.sujetos[:6]))
    if proceso.ponente:
        lineas.append(f"**Ponente:** {proceso.ponente}")
    if ultima:
        lineas.append("**Última actuación:** " + _linea(ultima))
    if alertas:
        lineas.append("**Alertas:**\n" + "\n".join(f"- {x}" for x in alertas))
    recientes = actuaciones[1:5]
    if recientes:
        lineas.append("**Anteriores:**\n" + "\n".join(f"- {_linea(a)}" for a in recientes))
    lineas.append(f"_{AVISO}_")

    return ParaElAbogado(
        resumen=resumen, ultima_actuacion=ultima, terminos_en_curso=terminos,
        nuevas_desde_ultima_consulta=nuevas, alertas=alertas, texto="\n\n".join(lineas), aviso=AVISO,
    )


def mensaje_ok(radicado: str, proceso: Proceso, actuaciones: list[Actuacion], coincidencias: int) -> str:
    cab = f"Proceso {formatear_radicado(radicado)}"
    if proceso.despacho:
        cab += f" — {proceso.despacho}"
    if proceso.es_privado:
        return cab + ". El proceso tiene reserva y el portal no muestra sus actuaciones."
    if actuaciones:
        a = actuaciones[0]
        cab += f". Última actuación ({a.fecha_actuacion}): {a.actuacion}"
        if a.anotacion:
            anot = a.anotacion if len(a.anotacion) <= 160 else a.anotacion[:157] + "…"
            cab += f" — {anot}"
    else:
        cab += ". Sin actuaciones publicadas"
    cab += "."
    if coincidencias > 1:
        cab += f" (Hay {coincidencias} registros con este radicado; se muestra el de actuación más reciente.)"
    return cab


MENSAJES = {
    "not_found": "No encontré procesos con el radicado {r} en la Consulta Nacional Unificada. "
                 "Verifique los 23 dígitos; si es reciente puede no estar publicado aún.",
    "captcha_required": "El portal de la Rama Judicial está pidiendo verificación humana (CAPTCHA). "
                        "Abra el enlace oficial y consulte el radicado {r} directamente.",
    "invalid_radicado": "El radicado debe tener exactamente 23 dígitos (puede incluir guiones o espacios).",
    "portal_unavailable": "El portal de la Rama Judicial no está respondiendo (error del servidor). "
                          "Intente de nuevo en unos minutos o consulte en el enlace oficial.",
    "timeout": "El portal de la Rama Judicial tardó demasiado en responder. "
               "Intente de nuevo en unos minutos o consulte en el enlace oficial.",
    "default": "No fue posible completar la consulta en la Rama Judicial en este momento. "
               "Intente más tarde o consulte en el enlace oficial.",
}


def mensaje_estado(clave: str, radicado: str | None) -> str:
    r = formatear_radicado(radicado) if radicado else "indicado"
    return MENSAJES.get(clave, MENSAJES["default"]).format(r=r)
