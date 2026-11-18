"""Pruebas sin internet de fechas y enlaces de COMPR.AR."""
from licitaciones.fuentes.paginas_web import extraer_items, paginas_enlazadas

def test_comprar_fecha_apertura_con_cabecera():
    page = '<table><thead><tr><th>Proceso</th><th>Publicación</th><th>Fecha de Apertura</th><th>Detalle</th></tr></thead><tbody><tr><td>392-0016-LPR26</td><td>01/11/2026</td><td>21/11/2026</td><td><a href="/Proceso/Detalle/392-0016-LPR26">UPS industrial y bancos de baterías</a></td></tr></tbody></table>'
    items = extraer_items(page, "https://comprar.gob.ar/Buscar", "COMPR.AR")
    assert len(items) == 1
    assert items[0].fecha_apertura is not None
    assert items[0].fecha_apertura.day == 21
    assert "Detalle" in items[0].link

def test_comprar_no_infiere_apertura_sin_cabecera():
    page = "<table><tr><td>392-0016-LPR26</td><td>01/11/2026</td><td>UPS industrial y bancos de baterías</td></tr></table>"
    items = extraer_items(page, "https://comprar.gob.ar/Buscar", "COMPR.AR")
    assert len(items) == 1
    assert items[0].fecha_apertura is None

def test_paginacion_real():
    page = '<a href="?page=2">2</a><a href="https://externo.com/?page=3">3</a>'
    links = paginas_enlazadas(page, "https://comprar.gob.ar/buscar")
    assert links == ["https://comprar.gob.ar/buscar?page=2"]

def test_distingue_cierre_de_apertura():
    page = ('<table><tr><th>Proceso</th><th>Fecha de presentación</th><th>Fecha de apertura</th><th>Objeto</th></tr>'
            '<tr><td>392-0016-LPR26</td><td>19/11/2026</td><td>21/11/2026</td>'
            '<td>Rectificador industrial 110 Vcc</td></tr></table>')
    items = extraer_items(page, "https://comprar.gob.ar/buscar", "COMPR.AR")
    assert len(items) == 1
    assert items[0].fecha_presentacion.day == 19
    assert items[0].fecha_apertura.day == 21
