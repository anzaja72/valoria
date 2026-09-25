from datetime import date

import pytest

from service.despachos import candidatos_despacho, partes
from service.estados_pdf import buscar_radicado, buscar_en_tablas, leer_pdf, numero_estado
from service.fechas import ultimos_dias_habiles
from service.publicaciones import (
    Coincidencia, Documento, Publicacion, ResultadoEstados, clasificar_documento, parsear_tarjeta,
)
from service.estados_pdf import FilaEstado

from .conftest import WEB

RAD = "08001315300220260014600"  # fila del video: Estado No. 70, Juzgado 002 Civil Circuito Barranquilla

OPCIONES = [
    "Todos",
    "080013103001 - JUZGADO 001 CIVIL DEL CIRCUITO DE BARRANQUILLA",
    "080013103002 - JUZGADO 002 CIVIL DEL CIRCUITO DE BARRANQUILLA",
    "080013110002 - JUZGADO 002 DE FAMILIA DEL CIRCUITO DE BARRANQUILLA",
    "080014003002 - JUZGADO 002 CIVIL MUNICIPAL DE BARRANQUILLA",
]


def test_partes_radicado():
    p = partes(RAD)
    assert p.codigo_despacho == "080013153002"
    assert p.nombre_departamento == "ATLÁNTICO"
    assert p.patron_auto == "002-2026-00146"


def test_candidatos_despacho_por_numero_y_entidad():
    c = candidatos_despacho(RAD, OPCIONES)
    assert c[0].startswith("080013103002")          # civil circuito 002 (el del video)
    assert all("MUNICIPAL" not in x for x in c)       # entidad distinta (40) descartada
    assert candidatos_despacho("08001310300120200000100", OPCIONES)[0].startswith("080013103001")


def test_clasificar_documentos_del_video():
    assert clasificar_documento("002-2026-00146 AdmiteDemandaResponsabilidad.pdf", RAD) == "auto_radicado"
    assert clasificar_documento("002-2026-00014 Retiro.pdf", RAD) == "otro"
    assert clasificar_documento("08001310300719970179607 AutoResuelveRecursos.pdf", RAD) == "otro"
    assert clasificar_documento(f"{RAD} Auto.pdf", RAD) == "auto_radicado"
    assert clasificar_documento("juzgado de circuito civil 002 mixto barranquilla_22-09-2026.pdf", RAD) == "estado"


def test_parsear_tarjeta():
    texto = ("Notificación por Estado No.70 de 22 de septiembre de 2026\nCategorías | Tipo de publicación:"
             "Notificaciones por Estados\nFecha de Publicación: 2026-09-22\nVER DETALLE")
    titulo, fecha, numero = parsear_tarjeta(texto)
    assert titulo.startswith("Notificación por Estado No.70") and fecha == "2026-09-22" and numero == "70"


def test_numero_estado():
    assert numero_estado("Estado No.     70     De   Martes, 22 De Septiembre") == "70"


def test_ultimos_dias_habiles():
    assert ultimos_dias_habiles(5, date(2026, 9, 25)) == (date(2026, 9, 21), date(2026, 9, 25))
    assert ultimos_dias_habiles(5, date(2026, 9, 27)) == (date(2026, 9, 21), date(2026, 9, 27))  # domingo


def test_buscar_en_tablas_con_encabezado_en_otra_pagina():
    tablas = [
        [["FIJACIÓN DE ESTADOS", None, None, None, None, None, None],
         ["Radicación", "Clase", "Demandante", "Demandado", "Fecha\nAuto", "Auto / Anotación", "Ponente"],
         ["08001310300719970179607", "Ordinario", "Francisco", "Herrera", "21/09/2026", "Auto Decide", "Melvin"]],
        [[RAD, "Procesos\nVerbales", "Vilma Esther Pacheco", "Allianz Seguros De Vida S.A.", "21/09/2026",
          "Auto Admite -\nAuto Avoca", "Melvin Munir Cohen Puerta"]],
    ]
    filas = buscar_en_tablas(tablas, RAD)
    assert len(filas) == 1
    f = filas[0]
    assert f.clase == "Procesos Verbales" and f.demandado == "Allianz Seguros De Vida S.A."
    assert f.fecha_auto == "21/09/2026" and f.anotacion == "Auto Admite - Auto Avoca"


def _pdf_estado(filas):
    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF(orientation="L")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.cell(0, 6, "Juzgado De Circuito Civil 002 Mixto Barranquilla", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Estado No. 70 De Martes, 22 De Septiembre De 2026", new_x="LMARGIN", new_y="NEXT")
    with pdf.table() as t:
        for fila in [("Radicacion", "Clase", "Demandante", "Demandado", "Fecha Auto", "Auto / Anotacion",
                      "Ponente")] + filas:
            r = t.row()
            for c in fila:
                r.cell(c)
    return bytes(pdf.output())


def test_leer_pdf_real_y_encontrar_radicado():
    contenido = _pdf_estado([
        ("08001315300220260001400", "Procesos Verbales", "Autocar", "Leasing Bancoldex", "21/09/2026",
         "Auto Decide", "Melvin Munir Cohen Puerta"),
        (RAD, "Procesos Verbales", "Vilma Esther Pacheco", "Allianz Seguros", "21/09/2026",
         "Auto Admite - Auto Avoca", "Melvin Munir Cohen Puerta"),
    ])
    lectura = leer_pdf(contenido)
    assert lectura.legible and numero_estado(lectura.encabezado) == "70"
    filas = buscar_radicado(lectura, RAD)
    assert len(filas) == 1 and "Admite" in (filas[0].anotacion or filas[0].texto)
    assert buscar_radicado(lectura, "08001315300220269999900") == []


# ---------------- endpoint ----------------

class FakePublicaciones:
    def __init__(self, resultado):
        self.resultado = resultado
        self.llamadas = []

    async def consultar(self, radicado, ini, fin):
        self.llamadas.append((radicado, ini, fin))
        return self.resultado


DESP = "080013103002 - JUZGADO 002 CIVIL DEL CIRCUITO DE BARRANQUILLA"


def _pub():
    return Publicacion(titulo="Notificación por Estado No.70 de 22 de septiembre de 2026", despacho=DESP,
                       url_detalle="https://x/detalle", fecha_publicacion="2026-09-22", numero_estado="70",
                       documentos=[Documento("estado.pdf", "https://x/e.pdf", "estado")], pdfs_leidos=1)


@pytest.fixture
def client_estados(make_client):
    def _make(resultado):
        from fastapi.testclient import TestClient

        from service.config import Settings
        from service.main import create_app
        from .conftest import FakeCPNU, ok_result
        import tempfile, pathlib

        fake = FakePublicaciones(resultado)
        s = Settings(api_keys=("web_test",), store_dir=pathlib.Path(tempfile.mkdtemp()))
        return TestClient(create_app(s, cpnu=FakeCPNU(ok_result()), publicaciones=fake)), fake
    return _make


def test_estados_aparece(client_estados):
    pub = _pub()
    fila = FilaEstado(radicacion=RAD, clase="Procesos Verbales", demandante="Vilma", demandado="Allianz",
                      fecha_auto="21/09/2026", anotacion="Auto Admite - Auto Avoca", ponente="Melvin")
    auto = Documento("002-2026-00146 AdmiteDemanda.pdf", "https://x/a.pdf", "auto_radicado")
    res = ResultadoEstados("ok", despachos_revisados=[DESP], publicaciones=[pub],
                           coincidencias=[Coincidencia(pub, fila, pub.documentos[0], [auto])])
    c, fake = client_estados(res)
    d = c.post("/v1/consultar_estados", headers=WEB,
               json={"radicado": RAD, "fecha_inicio": "2026-09-21", "fecha_fin": "2026-09-25"}).json()
    assert d["status"] == "ok" and d["aparece"] is True
    assert "Estado No. 70" in d["mensaje_chat"] and "Auto Admite" in d["mensaje_chat"]
    assert d["coincidencias"][0]["autos"][0]["url"] == "https://x/a.pdf"
    assert "### Para el abogado" in d["para_el_abogado"]
    assert fake.llamadas[0][1] == date(2026, 9, 21)
    # segunda llamada: cache
    d2 = c.post("/v1/consultar_estados", headers=WEB,
                json={"radicado": RAD, "fecha_inicio": "2026-09-21", "fecha_fin": "2026-09-25"}).json()
    assert d2["desde_cache"] is True and len(fake.llamadas) == 1


def test_estados_no_aparece(client_estados):
    res = ResultadoEstados("ok", despachos_revisados=[DESP], publicaciones=[_pub()])
    c, _ = client_estados(res)
    d = c.post("/v1/consultar_estados", headers=WEB, json={"radicado": RAD}).json()
    assert d["aparece"] is False and d["mensaje_chat"].startswith("No:")
    assert d["fecha_inicio"] and d["fecha_fin"]


def test_estados_sin_publicaciones(client_estados):
    c, _ = client_estados(ResultadoEstados("ok", despachos_revisados=[DESP]))
    d = c.post("/v1/consultar_estados", headers=WEB, json={"radicado": RAD}).json()
    assert d["aparece"] is False and "No hay «Notificaciones por Estados»" in d["mensaje_chat"]


def test_estados_errores(client_estados):
    c, _ = client_estados(ResultadoEstados("error", error_code="despacho_no_encontrado"))
    d = c.post("/v1/consultar_estados", headers=WEB, json={"radicado": RAD}).json()
    assert d["status"] == "error" and "despacho" in d["mensaje_chat"]
    d = c.post("/v1/consultar_estados", headers=WEB,
               json={"radicado": RAD, "fecha_inicio": "2026-01-01", "fecha_fin": "2026-09-01"}).json()
    assert d["error_code"] == "rango_invalido"
    c2, _ = client_estados(ResultadoEstados("captcha_required"))
    d = c2.post("/v1/consultar_estados", headers=WEB, json={"radicado": RAD}).json()
    assert d["status"] == "captcha_required" and "publicacionesprocesales" in d["url_oficial"]


def test_tools_schema(client_estados):
    c, _ = client_estados(ResultadoEstados("ok"))
    nombres = [t["name"] for t in c.get("/v1/tools", headers=WEB).json()]
    assert nombres == ["consultar_proceso", "consultar_estados"]
    assert c.get("/v1/tool_schema?tool=consultar_estados", headers=WEB).json()["name"] == "consultar_estados"
    assert c.get("/v1/tool_schema?tool=x", headers=WEB).status_code == 404
