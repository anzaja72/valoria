"""Mensajes del tool consultar_estados."""
from __future__ import annotations

from datetime import date

from .models import CoincidenciaOut, DocumentoOut, PublicacionOut
from .publicaciones import Coincidencia, Publicacion
from .radicado import formatear_radicado

AVISO = ("Información tomada de publicacionesprocesales.ramajudicial.gov.co. Verifique el estado y la "
         "providencia en el portal oficial; los términos corren según la publicación oficial.")


def coincidencia_out(c: Coincidencia) -> CoincidenciaOut:
    f = c.fila
    return CoincidenciaOut(
        numero_estado=c.publicacion.numero_estado, fecha_publicacion=c.publicacion.fecha_publicacion,
        despacho=c.publicacion.despacho, titulo=c.publicacion.titulo,
        clase=f.clase if f else None, demandante=f.demandante if f else None,
        demandado=f.demandado if f else None, fecha_auto=f.fecha_auto if f else None,
        anotacion=f.anotacion if f else None, ponente=f.ponente if f else None,
        texto=f.texto if f else None,
        pdf_estado=DocumentoOut(nombre=c.pdf_estado.nombre, url=c.pdf_estado.url) if c.pdf_estado else None,
        autos=[DocumentoOut(nombre=a.nombre, url=a.url) for a in c.autos],
        url_detalle=c.publicacion.url_detalle,
    )


def publicacion_out(p: Publicacion) -> PublicacionOut:
    return PublicacionOut(titulo=p.titulo, despacho=p.despacho, numero_estado=p.numero_estado,
                          fecha_publicacion=p.fecha_publicacion, url_detalle=p.url_detalle,
                          documentos=len(p.documentos), pdfs_leidos=p.pdfs_leidos,
                          pdfs_ilegibles=p.pdfs_ilegibles)


def _rango(ini: date, fin: date) -> str:
    return f"{ini.strftime('%d/%m/%Y')} y {fin.strftime('%d/%m/%Y')}"


def mensaje_estados(radicado: str, ini: date, fin: date, coincidencias: list[CoincidenciaOut],
                    publicaciones: list[PublicacionOut], despachos: list[str]) -> str:
    r = formatear_radicado(radicado)
    if coincidencias:
        c = coincidencias[0]
        est = f"Estado No. {c.numero_estado}" if c.numero_estado else "un estado"
        msg = f"Sí: el radicado {r} salió en {est}"
        if c.fecha_publicacion:
            msg += f" del {c.fecha_publicacion}"
        msg += f" ({c.despacho})."
        if c.anotacion:
            msg += f" Anotación: {c.anotacion}"
            if c.fecha_auto:
                msg += f" (auto del {c.fecha_auto})"
            msg += "."
        if len(coincidencias) > 1:
            msg += f" Aparece en {len(coincidencias)} publicaciones del periodo."
        return msg
    if not publicaciones:
        desp = despachos[0] if despachos else "el despacho"
        return (f"No hay «Notificaciones por Estados» publicadas por {desp} entre {_rango(ini, fin)}, "
                f"así que el radicado {r} no salió en estados en ese periodo.")
    total = sum(p.pdfs_leidos for p in publicaciones)
    msg = (f"No: el radicado {r} no aparece en los {len(publicaciones)} estado(s) publicados entre "
           f"{_rango(ini, fin)} ({total} PDF revisados).")
    ilegibles = sum(len(p.pdfs_ilegibles) for p in publicaciones)
    if ilegibles:
        msg += f" Ojo: {ilegibles} PDF no se pudieron leer (posible escaneo); revíselos en el portal."
    return msg


def para_el_abogado(radicado: str, coincidencias: list[CoincidenciaOut],
                    publicaciones: list[PublicacionOut], advertencias: list[str]) -> str:
    lineas = ["### Para el abogado"]
    for c in coincidencias:
        cab = f"**Estado No. {c.numero_estado or '?'}** · publicado {c.fecha_publicacion or 's.f.'} · {c.despacho}"
        lineas.append(cab)
        det = []
        if c.clase:
            det.append(f"- Clase: {c.clase}")
        if c.demandante or c.demandado:
            det.append(f"- Partes: {c.demandante or '—'} vs. {c.demandado or '—'}")
        if c.anotacion:
            det.append(f"- Auto / anotación: {c.anotacion}" + (f" ({c.fecha_auto})" if c.fecha_auto else ""))
        if c.ponente:
            det.append(f"- Ponente: {c.ponente}")
        if c.texto and not c.anotacion:
            det.append(f"- Texto del estado: {c.texto}")
        if c.pdf_estado:
            det.append(f"- [PDF del estado]({c.pdf_estado.url})")
        for a in c.autos:
            det.append(f"- [Providencia: {a.nombre}]({a.url})")
        lineas.append("\n".join(det) if det else "- El auto del radicado está publicado (ver enlaces).")
    if not coincidencias and publicaciones:
        lineas.append("Estados revisados: " + "; ".join(
            f"No. {p.numero_estado or '?'} ({p.fecha_publicacion or 's.f.'})" for p in publicaciones))
    if advertencias:
        lineas.append("**Advertencias:**\n" + "\n".join(f"- {a}" for a in advertencias))
    lineas.append(f"_{AVISO}_")
    return "\n\n".join(lineas)


MENSAJES_ERROR = {
    "despacho_no_encontrado": "No pude identificar en publicacionesprocesales el despacho del radicado {r}. "
                              "Consulte el portal filtrando por el juzgado.",
    "rango_invalido": "El rango de fechas no es válido (formato YYYY-MM-DD, máximo 31 días).",
    "formulario_cambiado": "El portal de publicaciones cambió su formulario y no pude completar la consulta. "
                           "Consulte directamente en el enlace oficial.",
}
