"""Pruebas offline de navegación ASP.NET, sin llamadas a COMPR.AR."""
from licitaciones.fuentes.comprar_webforms import (
    acciones_paginacion, campos_formulario, paginas_postback
)

def _pagina(numero, siguiente=True):
    boton = ("<a href=\"javascript:__doPostBack('ctl00$Main$Grid','Page$Next')\">Siguiente</a>"
             if siguiente else "")
    return ('<form><input type="hidden" name="__VIEWSTATE" value="token' + str(numero) +
            '"><input type="hidden" name="__EVENTVALIDATION" value="ev' + str(numero) +
            '"></form><table><tr><td>392-0016-LPR26 pagina ' + str(numero) +
            '</td></tr></table>' + boton)

def test_extrae_accion_next():
    assert acciones_paginacion(_pagina(1)) == [("ctl00$Main$Grid", "Page$Next")]

def test_conserva_campos_ocultos():
    assert campos_formulario(_pagina(1))["__VIEWSTATE"] == "token1"

def test_no_ejecuta_acciones_ajenas():
    html = '<a href="javascript:__doPostBack(\'ctl00$Main$Login\',\'Login\')">Ingresar</a>'
    assert acciones_paginacion(html) == []

def test_post_secuencial_con_estado_actualizado():
    class Respuesta:
        def __init__(self, pagina):
            self.url = "https://comprar.gob.ar/buscar"
            self.text = _pagina(pagina, siguiente=pagina < 3)
            self.headers = {"Content-Type": "text/html"}
        def raise_for_status(self):
            pass
    class Sesion:
        def __init__(self):
            self.posts = []
        def post(self, url, data, timeout, headers):
            self.posts.append(dict(data))
            assert data["__VIEWSTATE"] == "token" + str(len(self.posts))
            return Respuesta(len(self.posts) + 1)
    s = Sesion()
    paginas, detalle = paginas_postback(s, "https://comprar.gob.ar/buscar", _pagina(1))
    assert len(paginas) == 2
    assert len(s.posts) == 2
    assert "cobertura total no acreditada" in detalle
