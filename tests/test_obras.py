"""Pruebas del módulo de obras (sin internet): python -m pytest tests"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from licitaciones.obras import extraer as ex
from licitaciones.obras import seccion
from licitaciones.obras.empresas import Catalogo, huella, norm_empresa
from licitaciones.obras.extraer import NO_INFO, Extractor, completar_con_ia
from licitaciones.obras.fuentes import Nota, parsear_rss
from licitaciones.obras.registro import Registro

RAIZ = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RAIZ / "config_obras.yaml").read_text(encoding="utf-8"))
AHORA = datetime(2026, 11, 13)


def notas():
    datos = json.loads((RAIZ / "tests" / "notas_ejemplo.json").read_text(encoding="utf-8"))
    return {n["link"][-1]: Nota(n["titulo"], n["link"], n["medio"], datetime.fromisoformat(n["fecha"]), "", n["texto"]) for n in datos}


def extractor():
    return Extractor(CONFIG, Catalogo(RAIZ), AHORA)


def test_licitacion_abierta_con_fecha_confirmada():
    x, n = extractor(), notas()["1"]
    ok, info = x.relevante(n)
    r = x.extraer(n, info)
    assert ok and r["tipo"] == ex.LIC_ABIERTA
    assert r["fechas"]["lic_obra"] == {**r["fechas"]["lic_obra"], "texto": "15 de diciembre de 2026", "tipo": "confirmada"}
    assert r["fechas"]["fin_obra"]["tipo"] == "estimada"
    assert r["provincia"] == "Neuquén" and r["presupuesto"] == "US$ 38 millones"


def test_no_inventa_datos():
    x, n = extractor(), notas()["1"]
    r = x.extraer(n, x.relevante(n)[1])
    # La nota no nombra contratista, ingeniería ni desarrolladora.
    assert r["epc"] == r["ingenieria"] == r["desarrolladora"] == NO_INFO
    for campo in ("operadora", "desarrolladora", "ingenieria", "epc", "localidad", "presupuesto"):
        assert r[campo] == NO_INFO or r[campo].lower() in n.contenido.lower()
    for f in r["fechas"].values():
        assert f["texto"].lower() in n.contenido.lower()


def test_proyecto_y_anuncio_se_distinguen():
    x, N = extractor(), notas()
    r2 = x.extraer(N["2"], x.relevante(N["2"])[1])
    r3 = x.extraer(N["3"], x.relevante(N["3"])[1])
    r4 = x.extraer(N["4"], x.relevante(N["4"])[1])
    assert r2["tipo"] == ex.LIC_ANUNCIADA and r2["ingenieria"] == "Ingeniería Ejemplar"
    assert all(f["tipo"] == "estimada" for f in r2["fechas"].values())
    assert r3["tipo"] == ex.EN_EJECUCION and r3["epc"] == "UTE Montajes Ejemplo" and r3["desarrolladora"] == "Solar Ejemplo Desarrollos"
    assert "RIGI aprobado" in r4["estado"] and r4["fechas"]["lic_productos"]["tipo"] == "estimada"


def test_descarta_notas_financieras():
    x = extractor()
    assert not x.relevante(notas()["6"])[0]


def test_duplicados_se_unen_y_guardan_historial(tmp_path):
    x, N, reg = extractor(), notas(), Registro(tmp_path / "o.db")
    for k in ("2", "5"):
        reg.guardar(x.extraer(N[k], x.relevante(N[k])[1]), N[k].link)
    p = [p for p in reg.proyectos() if "Gasoducto Ejemplo Sur" in p["obra"]]
    assert len(p) == 1 and len(p[0]["fuentes"]) == 2
    assert p[0]["historial_fechas"][0]["antes"] == "principios de 2027"
    assert any(n["tipo"] == "Fecha modificada" for n in reg.novedades())


def test_nunca_borra(tmp_path):
    x, N = extractor(), notas()
    reg = Registro(tmp_path / "o.db")
    reg.guardar(x.extraer(N["3"], x.relevante(N["3"])[1]), N["3"].link)
    reg2 = Registro(tmp_path / "o.db")       # corrida siguiente, sin esa nota
    assert len(reg2.proyectos()) == 1


def test_registro_manual_tiene_prioridad(tmp_path):
    reg = Registro(tmp_path / "o.db")
    manual = {"obra": "Los Azules (cobre)", "obra_identificada": True, "operadora": "McEwen Copper", "tipo": "Proyecto anunciado",
              "estado": "RIGI aprobado", "fechas": {}, "fuentes": [{"link": "https://f", "titulo": "", "medio": ""}],
              "verificado_manual": True, "subobras": [], "equipos": [], "empresas": [], "propias": []}
    reg.guardar(manual)
    auto = dict(manual, verificado_manual=False, obra="Proyecto Los Azules", operadora="Otra", tipo=ex.LIC_ABIERTA,
                fuentes=[{"link": "https://nota", "titulo": "", "medio": ""}])
    reg.guardar(auto, "https://nota")
    (p,) = reg.proyectos()
    assert p["operadora"] == "McEwen Copper" and p["tipo"] == "Proyecto anunciado" and len(p["fuentes"]) == 2


def test_lista_propia_cifrada(tmp_path):
    shutil.copytree(RAIZ / "datos", tmp_path / "datos")
    (tmp_path / "datos" / "empresas_propias.txt").write_text(huella(norm_empresa("Montajes Patagónicos S.R.L.")) + "\n")
    cat = Catalogo(tmp_path)
    assert cat.propias_en("La obra la hará Montajes Patagónicos junto a otra firma.") == ["Montajes Patagónicos"]
    assert cat.propias_en("montajes patagonicos en minúscula no es nombre propio") == []


def test_privacidad_en_tablero():
    p = [{"obra": "X", "tipo": ex.PROYECTO, "propias": ["Empresa Secreta"], "fechas": {}}]
    html = seccion.insertar("<html><body><main></main></body></html>", p, [], [], mostrar_propias=False)
    assert "Empresa Secreta" not in html and '"propias_n": 1' in html


def test_insercion_no_toca_el_tablero_original():
    original = (RAIZ / "tests" / "boletin_ejemplo.txt").read_text(encoding="utf-8")[:50]
    base = f"<html><body><main><div id='lista'>{original}</div></main></body></html>"
    una = seccion.insertar(base, [], [], [], False)
    dos = seccion.insertar(una, [], [], [], False)
    assert dos.count(seccion.INICIO) == 1
    assert re.sub(re.escape(seccion.INICIO) + ".*?" + re.escape(seccion.FIN), "", dos, flags=re.S) == base


def test_ia_descarta_datos_que_no_estan_en_la_nota(monkeypatch):
    x, n = extractor(), notas()["1"]
    r = x.extraer(n, x.relevante(n)[1])

    class Resp:
        def raise_for_status(self): pass
        def json(self):
            datos = {"epc": {"valor": "Constructora Inventada", "cita": "La obra la hará Constructora Inventada"},
                     "ingenieria": {"valor": "sala de control", "cita": "La obra incluye una nueva sala de control"}}
            return {"content": [{"text": json.dumps(datos)}]}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: Resp())
    r = completar_con_ia(r, n, "modelo")
    assert r["epc"] == NO_INFO                   # cita inexistente: descartado
    assert r["ingenieria"] == "sala de control"  # cita real (el valor es literal de la nota)


def test_rss():
    xml = b"""<rss><channel><item><title>Licitan subestaci\xc3\xb3n</title><link>https://m/1</link>
    <pubDate>Tue, 10 Nov 2026 10:00:00 -0300</pubDate><description>&lt;p&gt;Texto&lt;/p&gt;</description>
    <source url="https://m">Medio</source></item></channel></rss>"""
    (n,) = parsear_rss(xml, "X")
    assert n.titulo == "Licitan subestación" and n.medio == "Medio" and n.fecha == datetime(2026, 11, 10, 10, 0)
