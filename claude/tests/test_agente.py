"""Pruebas sin internet: python -m pytest tests"""
from datetime import datetime
from pathlib import Path

import yaml

from licitaciones.db import Base
from licitaciones.filtros import Filtro
from licitaciones.fuentes.boletin_oficial import parsear_avisos, parsear_listado
from licitaciones.fuentes.privadas import oportunidad_desde_mail
from licitaciones.texto import buscar_fechas

RAIZ = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
PAGINAS = (RAIZ / "tests" / "boletin_ejemplo.txt").read_text(encoding="utf-8").split("=====PAGINA=====")


def avisos():
    return {a.organismo.split(" (")[0]: a for a in parsear_avisos(PAGINAS, "https://x/")}


def test_separa_avisos_y_campos():
    a = avisos()
    assert len(parsear_avisos(PAGINAS)) == 9
    epen = a["ENTE PROVINCIAL DE ENERGÍA DEL NEUQUÉN"]
    assert epen.numero_proceso == "Licitación Pública 0045/2026"
    assert epen.fecha_limite_consultas == datetime(2026, 11, 24, 12, 0)
    assert epen.fecha_apertura == datetime(2026, 12, 2, 10, 0)
    assert epen.titulo.startswith("Provisión de rectificadores")
    assert epen.link == "https://x/#page=2"


def test_fechas_en_texto_libre():
    enarsa = [x for x in parsear_avisos(PAGINAS) if "ENERGÍA ARGENTINA" in x.organismo]
    assert enarsa[0].fecha_apertura == datetime(2026, 12, 10, 12, 30)
    assert enarsa[1].es_circular and enarsa[1].fecha_apertura == datetime(2026, 12, 15, 12, 30)


def test_filtro_descarta_baterias_de_vehiculos_y_obra_civil():
    f, a = Filtro(CONFIG), avisos()
    assert f.evaluar(a["ENTE PROVINCIAL DE ENERGÍA DEL NEUQUÉN"])
    assert not f.evaluar(a["EJÉRCITO ARGENTINO"])
    assert not f.evaluar(a["COMISIÓN NACIONAL DE ENERGÍA ATÓMICA"])
    assert a["YACIMIENTOS MINEROS DE AGUA DE DIONISIO"].provincia in ("", "Catamarca")


def test_semaforo():
    f, a = Filtro(CONFIG), avisos()
    hoy = datetime(2026, 11, 11)
    assert f.semaforo(a["YACIMIENTOS MINEROS DE AGUA DE DIONISIO"], hoy) == "amarillo"
    assert f.semaforo(a["ENTE PROVINCIAL DE ENERGÍA DEL NEUQUÉN"], hoy) == "verde"
    assert f.semaforo(a["UNIVERSIDAD NACIONAL DEL OESTE"], hoy) == "rojo"
    assert f.semaforo(a["FABRICACIONES MILITARES S.A.U."], hoy) == "gris"


def test_circular_genera_alerta_con_link(tmp_path):
    base, f = Base(tmp_path / "t.db"), Filtro(CONFIG)
    ops = sorted([x for x in parsear_avisos(PAGINAS, "https://x/") if "ENERGÍA ARGENTINA" in x.organismo],
                 key=lambda o: o.fecha_publicacion)
    f.evaluar(ops[0])
    assert base.registrar(ops[0]) == []
    alertas = base.registrar(ops[1])
    tipos = {a["tipo"] for a in alertas}
    assert tipos == {"Circular nueva", "Fecha modificada"}
    assert all(a["link"] == "https://x/#page=4" for a in alertas)
    assert base.registrar(ops[1]) == []          # republicado otro día: no repite la alerta


def test_listado_otslist():
    html = "<h4>11-11-2026</h4><table><tr><td>1</td><td>" + "a" * 64 + "</td></tr><tr><td>3</td><td>" + "b" * 64 + "</td></tr></table>"
    assert parsear_listado(html)[datetime(2026, 11, 11).date()]["3"] == "b" * 64


def test_mail_de_invitacion():
    op = oportunidad_desde_mail("Invitación a evento Doc123456789 - Baterías estacionarias", "TGS <no-reply@ansmtp.ariba.com>",
                                "Fecha de cierre: 20/11/2026 15:00. Ingrese en https://service.ariba.com/Sourcing/x", None)
    assert op.fecha_apertura == datetime(2026, 11, 20, 15, 0)
    assert op.link.startswith("https://service.ariba.com") and op.numero_proceso == "Doc123456789"


def test_fechas_variadas():
    fechas = [f for _, f in buscar_fechas("hasta el 5/3/26 a las 9:30 y el 1 de diciembre de 2026")]
    assert fechas == [datetime(2026, 3, 5, 9, 30), datetime(2026, 12, 1)]
