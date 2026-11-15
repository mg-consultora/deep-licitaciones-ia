"""Anexo informativo de la base maestra: no inventa licitaciones vigentes."""
import json, html
from pathlib import Path

def anexar_base_maestra(ruta_html: Path, ruta_json: Path) -> None:
    if not ruta_json.exists():
        return
    base = json.loads(ruta_json.read_text(encoding="utf-8"))
    def e(s): return html.escape(str(s or ""), quote=True)
    empresas = base.get("empresas", [])
    licitaciones = base.get("licitaciones", [])
    obras = base.get("obras", [])
    fuentes = base.get("fuentes", [])
    filas = []
    for lic in licitaciones:
        num = lic.get("N.º proceso", "")
        obj = lic.get("Objeto", "")
        org = lic.get("Empresa", "")
        url = lic.get("URL / fuente", "")
        validacion = lic.get("Validación", "Sin verificación oficial")
        ref = '<a target="_blank" rel="noopener" href="'+e(url)+'">Fuente de referencia</a>' if str(url).startswith('https://') else 'Sin enlace'
        filas.append('<tr><td>'+e(org)+'</td><td>'+e(num)+'</td><td>'+e(obj)+'</td><td>'+e(validacion)+'</td><td>'+ref+'</td></tr>')
    tabla = '<table style="width:100%;border-collapse:collapse;font-size:13px"><thead><tr><th>Empresa</th><th>Proceso</th><th>Objeto</th><th>Validación pendiente</th><th>Referencia</th></tr></thead><tbody>'+''.join(filas)+'</tbody></table>'
    bloque = ('<section class="panel" id="base-maestra-deep"><h2>Base maestra DEEP — referencias pendientes de verificación</h2>'
       '<p><b>'+str(len(empresas))+' empresas · '+str(len(licitaciones))+' licitaciones · '+str(len(obras))+' obras · '+str(len(fuentes))+' fuentes.</b> '
       'Estos registros son antecedentes y <b>no se consideran convocatorias abiertas</b> sin confirmar cierre y circulares oficiales. '
       'Las fechas de apertura del Excel no se usan para calcular el semáforo.</p>'
       '<details><summary>Consultar las licitaciones de la base maestra</summary><div style="overflow-x:auto">'+tabla+'</div></details></section>')
    documento = ruta_html.read_text(encoding="utf-8")
    if 'id="base-maestra-deep"' in documento: return
    documento = documento.replace('</main>',bloque+'</main>',1)
    ruta_html.write_text(documento,encoding="utf-8")
