import pytest
from fastapi.testclient import TestClient

from service.config import Settings
from service.cpnu import ResultadoCPNU
from service.main import create_app

RADICADO = "15236408900120200006200"

CONSULTA = {"procesos": [{
    "idProceso": 111, "llaveProceso": RADICADO, "fechaProceso": "2020-02-03T00:00:00",
    "fechaUltimaActuacion": "2024-05-10T00:00:00", "despacho": "JUZGADO 001 PROMISCUO MUNICIPAL DE CÓMBITA",
    "departamento": "BOYACÁ", "sujetosProcesales": "Demandante: ANA PÉREZ | Demandado: BANCO X", "esPrivado": False,
}]}
DETALLE = {"despacho": "JUZGADO 001 PROMISCUO MUNICIPAL DE CÓMBITA", "ponente": "JUEZ UNO",
           "tipoProceso": "Declarativo", "claseProceso": "Verbal Sumario", "fechaProceso": "2020-02-03T00:00:00"}
SUJETOS = [{"tipoSujeto": "Demandante", "nombreRazonSocial": "ANA PÉREZ"},
           {"tipoSujeto": "Demandado", "nombreRazonSocial": "BANCO X"}]
ACTUACIONES = [
    {"fechaActuacion": "2024-04-01T00:00:00", "actuacion": "Auto admite demanda", "anotacion": "  Se admite  ",
     "fechaRegistro": "2024-04-02T00:00:00", "conDocumentos": False},
    {"fechaActuacion": "2024-05-10T00:00:00", "actuacion": "Fijación estado", "anotacion": "Auto de pruebas",
     "fechaInicial": "2024-05-13T00:00:00", "fechaFinal": "2099-05-15T00:00:00",
     "fechaRegistro": "2024-05-10T00:00:00", "conDocumentos": True},
]


class FakeCPNU:
    def __init__(self, resultado: ResultadoCPNU):
        self.resultado = resultado
        self.llamadas = 0
        self.listo = False

    async def consultar(self, radicado):
        self.llamadas += 1
        return self.resultado

    async def stop(self):
        pass


def ok_result():
    return ResultadoCPNU("ok", procesos=CONSULTA["procesos"], detalle=DETALLE, sujetos=SUJETOS,
                         actuaciones=ACTUACIONES, total_actuaciones=2)


@pytest.fixture
def make_client(tmp_path):
    def _make(resultado=None, keys=("web_test", "desktop_test"), ttl=600):
        fake = FakeCPNU(resultado or ok_result())
        s = Settings(api_keys=keys, cache_ttl_seconds=ttl, store_dir=tmp_path)
        return TestClient(create_app(s, cpnu=fake)), fake
    return _make


WEB = {"Authorization": "Bearer web_test"}
