from service.radicado import formatear_radicado, normalizar_radicado


def test_normaliza_con_guiones_y_espacios():
    assert normalizar_radicado("15-236-40-89-001-2020-00062-00") == "15236408900120200006200"
    assert normalizar_radicado(" 15236 40890012020 0006200 ") == "15236408900120200006200"


def test_rechaza_longitud_incorrecta():
    assert normalizar_radicado("123") is None
    assert normalizar_radicado("") is None
    assert normalizar_radicado(None) is None
    assert normalizar_radicado("1" * 24) is None


def test_formato_legible():
    assert formatear_radicado("15236408900120200006200") == "15-236-40-89-001-2020-00062-00"
