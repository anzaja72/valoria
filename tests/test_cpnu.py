import pytest

from service.cpnu import CaptchaRequerido, CPNUClient, PortalError, elegir_proceso


def test_elegir_proceso_mas_reciente():
    ps = [{"idProceso": 1, "fechaUltimaActuacion": "2021-01-01"},
          {"idProceso": 2, "fechaUltimaActuacion": "2024-01-01"},
          {"idProceso": 3, "fechaUltimaActuacion": None}]
    assert elegir_proceso(ps)["idProceso"] == 2


@pytest.mark.parametrize("status,exc", [(502, PortalError), (503, PortalError), (403, CaptchaRequerido),
                                         (429, CaptchaRequerido)])
def test_validar_respuesta_errores(status, exc):
    with pytest.raises(exc):
        CPNUClient()._validar_respuesta(status, None)


def test_validar_respuesta_404_es_vacio():
    assert CPNUClient()._validar_respuesta(404, None) == {"procesos": []}


def test_502_se_marca_portal_unavailable():
    with pytest.raises(PortalError) as e:
        CPNUClient()._validar_respuesta(502, None)
    assert e.value.code == "portal_unavailable"
