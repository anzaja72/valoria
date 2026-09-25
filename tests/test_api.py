import json

from service.cpnu import ResultadoCPNU

from .conftest import RADICADO, WEB


def test_health_sin_auth(make_client):
    c, _ = make_client()
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_auth_requerida(make_client):
    c, _ = make_client()
    assert c.get("/v1/tool_schema").status_code == 401
    assert c.get("/v1/tool_schema", headers={"Authorization": "Bearer otra"}).status_code == 401
    assert c.get("/v1/tool_schema", headers={"Authorization": "Bearer desktop_test"}).status_code == 200


def test_clave_sin_prefijo_valido_se_rechaza(make_client):
    c, _ = make_client(keys=("legacy_key",))
    assert c.get("/v1/tool_schema", headers={"Authorization": "Bearer legacy_key"}).status_code == 401


def test_sin_claves_configuradas_fail_closed(make_client):
    c, _ = make_client(keys=())
    assert c.get("/v1/tool_schema", headers=WEB).status_code == 503


def test_tool_schema(make_client):
    c, _ = make_client()
    s = c.get("/v1/tool_schema", headers=WEB).json()
    assert s["name"] == "consultar_proceso"
    assert s["input_schema"]["required"] == ["radicado"]


def test_consulta_ok_y_store(make_client, tmp_path):
    c, fake = make_client()
    r = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["actuaciones"][0]["fecha_actuacion"] == "2024-05-10"  # más reciente primero
    assert d["actuaciones"][1]["anotacion"] == "Se admite"
    assert d["proceso"]["ponente"] == "JUEZ UNO"
    assert len(d["proceso"]["sujetos"]) == 2
    assert "Fijación estado" in d["mensaje_chat"]
    pa = d["para_el_abogado"]
    assert pa["terminos_en_curso"] and "### Para el abogado" in pa["texto"]
    base = tmp_path / "procesos" / RADICADO
    assert (base / "meta.json").exists() and (base / "pdfs").is_dir()
    assert len(json.loads((base / "actuaciones.json").read_text())["actuaciones"]) == 2


def test_cache(make_client):
    c, fake = make_client()
    c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO})
    r = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": "15-236-40-89-001-2020-00062-00"})
    assert r.json()["desde_cache"] is True and fake.llamadas == 1
    c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO, "forzar_actualizacion": True})
    assert fake.llamadas == 2


def test_nuevas_actuaciones_desde_store(make_client):
    c, fake = make_client(ttl=0)
    c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO})
    fake.resultado.actuaciones = fake.resultado.actuaciones + [
        {"fechaActuacion": "2024-06-01T00:00:00", "actuacion": "Sentencia", "anotacion": "Accede"}]
    d = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO}).json()
    nuevas = d["para_el_abogado"]["nuevas_desde_ultima_consulta"]
    assert [a["actuacion"] for a in nuevas] == ["Sentencia"]


def test_radicado_invalido(make_client):
    c, fake = make_client()
    d = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": "123"}).json()
    assert d["status"] == "error" and d["error_code"] == "invalid_radicado" and fake.llamadas == 0


def test_not_found(make_client):
    c, _ = make_client(ResultadoCPNU("not_found"))
    d = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO}).json()
    assert d["status"] == "not_found" and d["mensaje_chat"]


def test_captcha_no_se_cachea(make_client):
    c, fake = make_client(ResultadoCPNU("captcha_required", error_code="captcha"))
    for _ in range(2):
        d = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO}).json()
        assert d["status"] == "captcha_required"
        assert d["url_oficial"].startswith("https://consultaprocesos.ramajudicial.gov.co")
    assert fake.llamadas == 2


def test_502_portal_error_estructurado(make_client):
    c, _ = make_client(ResultadoCPNU("error", error_code="portal_unavailable"))
    r = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO})
    d = r.json()
    assert r.status_code == 200
    assert d["status"] == "error" and d["error_code"] == "portal_unavailable"
    assert "no está respondiendo" in d["mensaje_chat"]


def test_proceso_privado(make_client):
    procesos = [{"idProceso": 5, "despacho": "JUZGADO X", "esPrivado": True}]
    c, _ = make_client(ResultadoCPNU("ok", procesos=procesos))
    d = c.post("/v1/consultar_proceso", headers=WEB, json={"radicado": RADICADO}).json()
    assert d["status"] == "ok" and d["proceso"]["es_privado"] is True
    assert "reserva" in d["mensaje_chat"]
