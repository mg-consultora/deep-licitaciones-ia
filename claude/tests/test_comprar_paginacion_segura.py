"""Pruebas sin red: paginación y avisos de COMPR.AR."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from licitaciones.fuentes.comprar_webforms import acciones_paginacion, campos_formulario, paginas_postback


class Respuesta:
    url = "https://comprar.gob.ar/Default.aspx"
    text = ""
    headers = {"Content-Type": "text/html"}
    def raise_for_status(self):
        pass


class Sesion:
    def __init__(self, respuestas):
        self.respuestas = iter(respuestas)
        self.envios = []
    def post(self, url, data, **kwargs):
        self.envios.append(dict(data))
        r = Respuesta()
        r.text = next(self.respuestas)
        return r


def pagina(numero, siguiente=True):
    link = (f'<a href="javascript:__doPostBack(\'ctl00$grid\',\'Page$Next\')">Next</a>'
            if siguiente else "")
    return ('<html><form action="/Default.aspx">'
            f'<input type="hidden" name="__VIEWSTATE" value="estado{numero}">'
            f'<input type="hidden" name="__EVENTVALIDATION" value="validacion{numero}">'
            f'<p>84/77-1626-LPR26 pagina {numero}</p>{link}</form></html>')


def test_postback_preserva_estado_y_avanza():
    sesion = Sesion([pagina(2), pagina(3, False)])
    paginas, estado = paginas_postback(sesion, "https://comprar.gob.ar/Default.aspx",
                                      pagina(1), max_paginas=10)
    assert len(paginas) == 2
    assert [x["__VIEWSTATE"] for x in sesion.envios] == ["estado1", "estado2"]
    assert [x["__EVENTVALIDATION"] for x in sesion.envios] == ["validacion1", "validacion2"]
    assert "sin controles" in estado


def test_limite_no_equivale_a_cobertura_completa():
    sesion = Sesion([pagina(2)])
    paginas, estado = paginas_postback(sesion, "https://comprar.gob.ar/Default.aspx",
                                      pagina(1), max_paginas=2)
    assert len(paginas) == 1
    assert "LIMITE_DE_PAGINAS_ALCANZADO" in estado


def test_origen_externo_no_se_consulta():
    sesion = Sesion([])
    paginas, estado = paginas_postback(sesion, "https://ejemplo.com", pagina(1))
    assert paginas == []
    assert not sesion.envios
    assert "no seguro" in estado
