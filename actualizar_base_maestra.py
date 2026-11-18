"""Base maestra DEEP dinámica: solo registros reales del agente, sin filas precargadas.
La fecha de actualización del tablero NO acredita vigencia de cada convocatoria.
"""
import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

DATA_RE = re.compile(r"const D\s*=\s*(\{.*?\});\s*\n", re.S)
SECTION_RE = re.compile(r'<section\s+class="panel"\s+id="base-maestra-deep">.*?</section>', re.S)
HISTORY = Path("base_maestra_registros.json")

def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)

def key(p):
    return (str(p.get("numero_proceso") or "").strip().casefold(),
            str(p.get("organismo") or "").strip().casefold())

def actualizar(path):
    page = path.read_text(encoding="utf-8")
    match = DATA_RE.search(page)
    if not match:
        raise RuntimeError("No se encontraron los datos D del agente: se cancela para evitar publicar información engañosa")
    data = json.loads(match.group(1))
    actuales = data.get("procesos", [])
    if not isinstance(actuales, list):
        raise ValueError("D.procesos debe ser una lista")
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previo = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    if not isinstance(previo, list):
        raise ValueError("Historial inválido")
    registros = {key(p): dict(p) for p in previo if isinstance(p, dict) and key(p)[0]}
    detectados = 0
    for p in actuales:
        if not isinstance(p, dict) or not key(p)[0]:
            continue
        k = key(p)
        anterior = registros.get(k, {})
        nuevo = dict(anterior)
        nuevo.update(p)
        nuevo["primera_deteccion_utc"] = anterior.get("primera_deteccion_utc", ahora)
        nuevo["ultima_deteccion_utc"] = ahora
        registros[k] = nuevo
        detectados += 1
    filas = []
    for p in sorted(registros.values(), key=lambda x: x.get("ultima_deteccion_utc", ""), reverse=True):
        reciente = p.get("ultima_deteccion_utc") == ahora
        # Una convocatoria histórica nunca se presenta como abierta sin nueva verificación.
        estado = (p.get("estado") or "Sin estado oficial") if reciente else "Histórico: no detectado en la última ejecución"
        vigencia = p.get("semaforo", "gris") if reciente else "gris"
        etiqueta = "Verde/amarillo: verificar cierre oficial" if vigencia in ("verde", "amarillo") else "Vigencia no confirmada"
        enlace = p.get("link") or ""
        link_html = ('<a href="' + esc(enlace) + '" target="_blank" rel="noopener noreferrer">Abrir aviso detectado</a>'
                     if isinstance(enlace, str) and enlace.startswith(("https://", "http://")) else "Sin enlace verificable")
        filas.append("<tr><td>" + esc(p.get("organismo") or "No informado") +
                     "</td><td>" + esc(p.get("numero_proceso")) +
                     "</td><td>" + esc(p.get("titulo") or "No informado") +
                     "</td><td>" + esc(estado) + " · " + etiqueta +
                     "</td><td>" + esc(p.get("fecha_presentacion") or "No informada") +
                     "</td><td>" + esc(p.get("ultima_deteccion_utc") or "No informada") +
                     "</td><td>" + link_html + "</td></tr>")
    if filas:
        tabla = ('<div style="overflow-x:auto"><table><thead><tr><th>Organismo</th><th>Proceso</th>'
                 '<th>Objeto</th><th>Estado / verificación</th><th>Presentación</th>'
                 '<th>Última detección (UTC)</th><th>Fuente</th></tr></thead><tbody>' +
                 "".join(filas) + '</tbody></table></div>')
    else:
        tabla = ('<p>No hay procesos con identificador detectados por el agente. '
                 'Esta sección se completará cuando se incorporen resultados reales. '
                 'No se muestran antecedentes fijos como si fueran convocatorias actuales.</p>')
    section = ('<section class="panel" id="base-maestra-deep">'
               '<h2>Base maestra DEEP — seguimiento automático</h2>'
               '<p><b>' + str(len(registros)) + ' procesos registrados · ' +
               str(detectados) + ' detectados en esta ejecución.</b> '
               'Generación: ' + esc(ahora) + '. '
               'La detección no confirma vigencia: consultar fechas, circulares y pliegos oficiales. '
               'Los procesos no detectados nuevamente se identifican como históricos.</p>' +
               '<details open><summary>Consultar procesos detectados</summary>' + tabla +
               '</details></section>')
    page = SECTION_RE.sub("", page)
    anchor = '<div id="lista"></div>'
    if anchor not in page:
        raise RuntimeError("No se encontró el lugar de inserción de la base maestra")
    page = page.replace(anchor, anchor + "\n" + section, 1)
    path.write_text(page, encoding="utf-8")
    HISTORY.write_text(json.dumps(list(registros.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Base maestra dinámica: {len(registros)} registros, {detectados} detectados en esta ejecución")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True)
    actualizar(Path(parser.parse_args().html))
