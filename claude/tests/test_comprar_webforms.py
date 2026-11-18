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

def test_selectores_webforms_se_envian_en_post():
    html = """<form><input type="hidden" name="__VIEWSTATE" value="token">
    <select name="ctl00$CPH1$ddlEstadoProceso">
      <option value="-2">Seleccionar</option>
      <option value="6" selected>Publicado</option>
    </select>
    <input type="checkbox" name="activa" value="1" checked>
    </form>"""
    datos = campos_formulario(html)
    assert datos["ctl00$CPH1$ddlEstadoProceso"] == "6"
    assert datos["activa"] == "1"


def test_paginacion_numerica_sin_next():
    def pagina(n):
        enlace = (f"""<a href="javascript:__doPostBack('ctl00$Main$Grid','Page${n+1}')">{n+1}</a>"""
                  if n < 3 else "")
        return f"""<form action="/buscar"><input type="hidden" name="__VIEWSTATE" value="t{n}"></form>{enlace}<p>pagina {n}</p>"""
    class Respuesta:
        def __init__(self, n):
            self.url = "https://comprar.gob.ar/buscar"
            self.text = pagina(n)
            self.headers = {"Content-Type": "text/html"}
        def raise_for_status(self):
            pass
    class Sesion:
        def __init__(self):
            self.n = 1
        def post(self, url, data, timeout, headers):
            assert data["__EVENTARGUMENT"] == f"Page${self.n+1}"
            self.n += 1
            return Respuesta(self.n)
    paginas, _ = paginas_postback(Sesion(), "https://comprar.gob.ar/buscar", pagina(1))
    assert len(paginas) == 2
