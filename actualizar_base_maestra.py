"""Actualiza la base maestra del tablero a partir de registros del agente diario.
Mantiene antecedentes como pendientes; nunca infiere una convocatoria abierta.
"""
import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path

BASE = "<section class=\"panel\" id=\"base-maestra-deep\"><h2>Base maestra DEEP — referencias pendientes de verificación</h2><p><b>29 empresas · 11 licitaciones · 5 obras · 8 fuentes.</b> Estos registros son antecedentes y <b>no se consideran convocatorias abiertas</b> sin confirmar cierre y circulares oficiales. Las fechas de apertura del Excel no se usan para calcular el semáforo.</p><details><summary>Consultar las licitaciones de la base maestra</summary><div style=\"overflow-x:auto\"><table style=\"width:100%;border-collapse:collapse;font-size:13px\"><thead><tr><th>Empresa</th><th>Proceso</th><th>Objeto</th><th>Validación pendiente</th><th>Referencia</th></tr></thead><tbody><tr><td>AABE</td><td>392-0016-LPR26</td><td>UPS y cuatro bancos de baterías</td><td>Referencia previa: ficha oficial; verificar número y fecha</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://comprar.gob.ar/\">Fuente de referencia</a></td></tr><tr><td>INV</td><td>49-0002-LPR26</td><td>Adquisición e instalación de UPS para laboratorio</td><td>Referencia previa: confirmar pliego y apertura</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://comprar.gob.ar/\">Fuente de referencia</a></td></tr><tr><td>EPEC</td><td>1530</td><td>Rectificador y banco de baterías para SEA Paraguay</td><td>Aviso secundario; contrastar oficial</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://indicadores.ar/contrataciones/llamados/aviso/empresa-provincial-de-energia-de-cordoba-licitacion-publica-electronica-21a7ea\">Fuente de referencia</a></td></tr><tr><td>EPEC</td><td>1534</td><td>Rectificador y banco de baterías de electrolito absorbido</td><td>Aviso secundario; contrastar oficial</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://indicadores.ar/contrataciones/llamados/aviso/empresa-provincial-de-energia-de-cordoba-licitacion-publica-electronica-102857\">Fuente de referencia</a></td></tr><tr><td>EPEN</td><td>40/2026</td><td>Cinco interruptores 132 kV – ET Centenario Oeste</td><td>Fecha y pliego sin corroborar</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://www.epen.gov.ar/index.php/licitaciones/\">Fuente de referencia</a></td></tr><tr><td>EPEN</td><td>18/2026</td><td>Nuevo campo transformador – ET Pío Protto</td><td>Fecha y pliego sin corroborar</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://www.epen.gov.ar/index.php/licitaciones/\">Fuente de referencia</a></td></tr><tr><td>EPSE</td><td>01/2026</td><td>Recuperación de equipamiento planta VERSU</td><td>Fecha y alcance sin corroborar</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://www.epse.com.ar/web/licitaciones\">Fuente de referencia</a></td></tr><tr><td>AYSAM</td><td>87/26</td><td>Materiales eléctricos para stock electromecánico</td><td>Fecha indicada en relevamiento previo; verificar oficial</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://aysam.com.ar/pliegosdigitales/licitaciones\">Fuente de referencia</a></td></tr><tr><td>AYSAM</td><td>3/26</td><td>Colector cloacal Colonia Segovia, etapa II</td><td>Fecha indicada en relevamiento previo; verificar oficial</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://aysam.com.ar/pliegosdigitales/licitaciones\">Fuente de referencia</a></td></tr><tr><td>Transener</td><td>34-003</td><td>AMBA I: estaciones transformadoras y sistemas auxiliares</td><td>Referencia de seguimiento comercial; sin fecha actual verificada</td><td><a target=\"_blank\" rel=\"noopener\" href=\"https://www.transener.com.ar/\">Fuente de referencia</a></td></tr><tr><td>Genneia</td><td>PABRA / Ariba</td><td>Banco de baterías, cargador rectificador e inversor 5 kVA</td><td>Referencia comercial previa; contratación privada</td><td>Sin enlace</td></tr></tbody></table></div></details></section>"
def actualizar(path):
    contenido = path.read_text(encoding="utf-8")
    m = re.search(r"const D\s*=\s*(\{.*?\});\s*\n", contenido, re.S)
    procesos = []
    if m:
        try:
            procesos = json.loads(m.group(1)).get("procesos", [])
        except (ValueError, TypeError):
            pass
    iniciales = re.findall(r"<tr>(.*?)</tr>", BASE, re.S)[1:]
    filas = list(iniciales)
    claves = set()
    for fila in iniciales:
        celdas = re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)
        if len(celdas) > 1:
            claves.add(re.sub(r"<[^>]+>", "", celdas[1]).strip().lower())
    nuevos = 0
    for p in procesos:
        numero = str(p.get("numero_proceso") or "").strip()
        if not numero or numero.lower() in claves:
            continue
        claves.add(numero.lower())
        nombre = html.escape(str(p.get("organismo") or "No informado"))
        objeto = html.escape(str(p.get("titulo") or "No informado"))
        estado = html.escape(str(p.get("estado") or "Pendiente de verificar"))
        fecha = html.escape(str(p.get("fecha_presentacion") or "No informada"))
        link = str(p.get("link") or "")
        enlace = '<a href="' + html.escape(link, quote=True) + '" target="_blank" rel="noopener">Aviso registrado</a>' if link.startswith(("https://","http://")) else "Sin enlace"
        filas.append("<tr><td>" + nombre + "</td><td>" + html.escape(numero) + "</td><td>" + objeto + "</td><td>Agente: " + estado + " · Presentación: " + fecha + " (verificar fuente oficial)</td><td>" + enlace + "</td></tr>")
        nuevos += 1
    fecha_revision = datetime.now().strftime("%d/%m/%Y %H:%M")
    tabla = re.search(r"<table.*?</table>", BASE, re.S).group(0)
    tabla = re.sub(r"<tbody>.*?</tbody>", "<tbody>" + "".join(filas) + "</tbody>", tabla, flags=re.S)
    seccion = '<section class="panel" id="base-maestra-deep"><h2>Base maestra DEEP — antecedentes y seguimiento automático</h2>'
    seccion += '<p><b>' + str(len(filas)) + ' procesos registrados</b> · Revisión automática: ' + fecha_revision + '. Se incorporan registros detectados por el agente; <b>no se consideran abiertos sin validar fechas, pliegos y circulares oficiales</b>. Los antecedentes no verificados permanecen identificados como tales.</p>'
    seccion += '<details><summary>Consultar procesos de la base maestra</summary><div style="overflow-x:auto">' + tabla + '</div></details></section>'
    contenido = re.sub(r'<section class="panel" id="base-maestra-deep">.*?</section>', '', contenido, flags=re.S)
    contenido = contenido.replace('<div id="lista"></div>', '<div id="lista"></div>\n' + seccion, 1)
    path.write_text(contenido, encoding="utf-8")
    print(f"Base maestra: {len(filas)} registros ({nuevos} nuevos del agente).")
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--html", required=True)
    actualizar(Path(p.parse_args().html))
