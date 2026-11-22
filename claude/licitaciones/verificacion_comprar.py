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
    if CERRADOS.search(estado) or CERRADOS.search(titulo):
        return "proceso_cerrado_o_adjudicado"
    if INFORMATICOS.search(titulo) and not INDUSTRIAL.search(titulo):
        return "ups_informatica"
    # Un plazo de presentación vencido descarta, pero una apertura NO sustituye el cierre.
    if op.fecha_presentacion and op.fecha_presentacion < ahora:
        return "presentacion_vencida"
    if op.fecha_apertura and op.fecha_apertura < ahora:
        return "apertura_pasada_sin_vigencia_acreditada"
    return None

def ficha_oficial_verificada(op, sesion):
    """Requiere URL individual HTTP(S) del portal y número coincidente en HTML."""
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
        texto = normalizar(__import__("bs4").BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
        if normalizar(op.numero_proceso) not in texto:
            return False, "numero_no_coincide_en_ficha"
        if CERRADOS.search(texto):
            return False, "ficha_indica_cerrado"
        return True, "numero_confirmado_en_ficha"
    except Exception as exc:
        return False, "error_ficha_" + type(exc).__name__
