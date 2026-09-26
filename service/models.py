"""Modelos de request/response del tool consultar_proceso."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "not_found", "captcha_required", "error"]


class ConsultaRequest(BaseModel):
    radicado: str = Field(..., description="Número de radicación de 23 dígitos (se aceptan guiones/espacios).")
    forzar_actualizacion: bool = Field(False, description="Ignora la cache y consulta el portal.")


class Actuacion(BaseModel):
    fecha_actuacion: str | None = None
    actuacion: str | None = None
    anotacion: str | None = None
    fecha_inicia_termino: str | None = None
    fecha_finaliza_termino: str | None = None
    fecha_registro: str | None = None
    con_documentos: bool = False


class Sujeto(BaseModel):
    tipo: str | None = None
    nombre: str | None = None


class Proceso(BaseModel):
    id_proceso: int | None = None
    despacho: str | None = None
    departamento: str | None = None
    ponente: str | None = None
    tipo_proceso: str | None = None
    clase_proceso: str | None = None
    subclase_proceso: str | None = None
    recurso: str | None = None
    ubicacion: str | None = None
    contenido_radicacion: str | None = None
    fecha_radicacion: str | None = None
    fecha_ultima_actuacion: str | None = None
    es_privado: bool = False
    sujetos: list[Sujeto] = []


class ParaElAbogado(BaseModel):
    resumen: str
    ultima_actuacion: Actuacion | None = None
    terminos_en_curso: list[Actuacion] = []
    nuevas_desde_ultima_consulta: list[Actuacion] = []
    alertas: list[str] = []
    texto: str = Field(..., description="Bloque markdown listo para mostrar en el chat.")
    aviso: str


class ConsultaResponse(BaseModel):
    status: Status
    radicado: str | None
    mensaje_chat: str
    url_oficial: str
    fuente: str = "cpnu"
    consultado_en: str
    desde_cache: bool = False
    error_code: str | None = None
    proceso: Proceso | None = None
    coincidencias: int = 0
    total_actuaciones: int = 0
    actuaciones: list[Actuacion] = []
    para_el_abogado: ParaElAbogado | None = None
    debug: dict[str, Any] | None = None


# ---------------------------------------------------------------------------------------------
# consultar_estados (publicacionesprocesales.ramajudicial.gov.co)

class EstadosRequest(BaseModel):
    radicado: str = Field(..., description="Número de radicación de 23 dígitos.")
    fecha_inicio: str | None = Field(None, description="YYYY-MM-DD. Por defecto: hace 5 días hábiles.")
    fecha_fin: str | None = Field(None, description="YYYY-MM-DD. Por defecto: hoy.")
    forzar_actualizacion: bool = False


class DocumentoOut(BaseModel):
    nombre: str
    url: str


class PublicacionOut(BaseModel):
    titulo: str
    despacho: str
    numero_estado: str | None = None
    fecha_publicacion: str | None = None
    url_detalle: str | None = None
    documentos: int = 0
    pdfs_leidos: int = 0
    pdfs_ilegibles: list[str] = []


class CoincidenciaOut(BaseModel):
    numero_estado: str | None = None
    fecha_publicacion: str | None = None
    despacho: str
    titulo: str
    clase: str | None = None
    demandante: str | None = None
    demandado: str | None = None
    fecha_auto: str | None = None
    anotacion: str | None = None
    ponente: str | None = None
    texto: str | None = None
    pdf_estado: DocumentoOut | None = None
    autos: list[DocumentoOut] = []
    url_detalle: str | None = None


class EstadosResponse(BaseModel):
    status: Status
    radicado: str | None
    aparece: bool | None = None
    mensaje_chat: str
    url_oficial: str
    fuente: str = "publicacionesprocesales"
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    consultado_en: str
    desde_cache: bool = False
    error_code: str | None = None
    despachos_revisados: list[str] = []
    coincidencias: list[CoincidenciaOut] = []
    publicaciones_revisadas: list[PublicacionOut] = []
    advertencias: list[str] = []
    para_el_abogado: str | None = None
