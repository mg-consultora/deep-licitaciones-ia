"""Reglas conservadoras para candidatos COMPR.AR. No infiere fechas ni estados."""
import re
from datetime import datetime
from urllib.parse import urlparse
from .texto import normalizar

CERRADOS = re.compile(r"\b(adjudicad[oa]s?|preadjudicad[oa]s?|finalizad[oa]s?|anulad[oa]s?|desiert[oa]s?|fracasad[oa]s?|sin efecto)\b")
INFORMATICOS = re.compile(r"(ups\s+(?:para\s+)?(?:pc|computador|escritorio)|(?:ups|sai).{0,60}(?:informatic|notebook|computador|escritorio)|(?:informatic|notebook|computador).{0,60}(?:ups|sai))")
INDUSTRIAL = re.compile(r"(industrial|trifasic|rectificador|banco de bater|baterias estacionarias|vrla|ni.cd|subestacion|transformadora|energia critica|\b(?:48|110|125|220)\s*v\s*(?:cc|dc))")

def motivo_descarte(op, ahora=None):
    ahora = ahora or datetime.now()
    titulo = normalizar(op.titulo + " " + op.texto)
    estado = normalizar(op.estado)
    if CERRADOS.search(estado):
        return "proceso_cerrado_o_adjudicado"
    if INFORMATICOS.search(titulo) and not INDUSTRIAL.search(titulo):
        return "ups_informatica"
    # Un plazo de presentación vencido descarta, pero una apertura NO sustituye el cierre.
    if op.fecha_presentacion and op.fecha_presentacion < ahora:
        return "presentacion_vencida"
    if op.fecha_apertura and op.fecha_apertura < ahora and not op.fecha_presentacion:
        return "apertura_pasada_sin_vigencia_acreditada"
    return None

def _vigencia_en_ficha(html, numero, ahora=None):
    """Confirma cierre futuro etiquetado; una coincidencia de numero sola no basta."""
    from bs4 import BeautifulSoup
    from .texto import buscar_fechas
    ahora = ahora or datetime.now()
    soup = BeautifulSoup(html, "html.parser")
    texto = normalizar(soup.get_text(" ", strip=True))
    if normalizar(numero) not in texto:
        return False, "numero_no_coincide_en_ficha"
    # Buscar estado en celdas/campos, no en todo el documento: puede incluir historial.
    for fila in soup.select("tr"):
        celdas = fila.find_all(["td", "th"], recursive=False)
        if len(celdas) < 2:
            continue
        etiqueta = normalizar(celdas[0].get_text(" ", strip=True))
        valor = normalizar(celdas[1].get_text(" ", strip=True))
        if ("estado" in etiqueta or "situacion" in etiqueta) and CERRADOS.search(valor):
            return False, "estado_oficial_cerrado"
    # Solo fecha de recepcion/presentacion de ofertas; apertura no equivale a cierre.
    fechas = []
    for fila in soup.select("tr"):
        celdas = fila.find_all(["td", "th"], recursive=False)
        if len(celdas) < 2:
            continue
        etiqueta = normalizar(celdas[0].get_text(" ", strip=True))
        if any(x in etiqueta for x in ("fin de recepcion", "cierre de ofertas",
                                       "fecha limite de presentacion", "fin de presentacion",
                                       "fecha de presentacion de ofertas")):
            fechas.extend(fecha for _, fecha in buscar_fechas(celdas[1].get_text(" ", strip=True)))
    if not fechas:
        return False, "sin_cierre_oficial_identificable"
    if max(fechas) <= ahora:
        return False, "cierre_oficial_vencido"
    return True, "cierre_oficial_futuro_verificado"


def ficha_oficial_verificada(op, sesion):
    """Valida ficha individual y cierre futuro, nunca solo coincidencia de numero."""
    url = op.link
    u = urlparse(url)
    if u.scheme != "https" or u.hostname != "comprar.gob.ar":
        return False, "enlace_no_oficial"
    if not op.numero_proceso or not u.path or u.path.lower() in ("/", "/default.aspx"):
        return False, "sin_ficha_individual"
    try:
        r = sesion.get(url, timeout=(8, 20), allow_redirects=False)
        if r.status_code != 200:
            return False, "ficha_http_" + str(r.status_code)
        if urlparse(r.url).hostname != "comprar.gob.ar":
            return False, "redireccion_externa"
        return _vigencia_en_ficha(r.text, op.numero_proceso)
    except Exception as exc:
        return False, "error_ficha_" + type(exc).__name__
