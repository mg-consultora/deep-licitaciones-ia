#!/usr/bin/env python3
"""Agente de licitaciones DEEP S.A. - CONTRAT.AR (versión con sesión ASP.NET y paginación).

Qué hace
--------
* Abre una sesión pública (cookies) en contratar.gob.ar. No usa usuario ni clave.
* Recorre los listados oficiales con límites de seguridad, avanzando de página con
  postbacks ASP.NET (POST normal; si no funciona, POST asíncrono de UpdatePanel).
* Descubre TODAS las filas y recién después clasifica la relevancia para DEEP.
* Abre la ficha de las filas relevantes (enlace directo o postback) y lee fechas y circulares.
* Conserva los registros verificados si la consulta falla o queda incompleta.
* Escribe licitaciones.json con el mismo formato que usa el tablero (index.html).
* Termina con código distinto de 0 si la extracción fue incompleta o falló.

Solo se leen metadatos públicos y fechas. No se descargan ni analizan pliegos.
Solo se usa la biblioteca estándar de Python (no requiere instalar paquetes).

Variables de entorno opcionales (todas tienen valor por defecto)
-----------------------------------------------------------------
CONTRATAR_BASE_URL      https://contratar.gob.ar
CONTRATAR_LISTADOS      proximas,ultimos90  (opciones: proximas, ultimos90; separadas por coma)
CONTRATAR_MAX_PAGINAS   10                  páginas máximas por listado
CONTRATAR_MAX_DETALLES  25                  fichas máximas por ejecución
CONTRATAR_MAX_PEDIDOS   80                  pedidos HTTP máximos por ejecución
CONTRATAR_PAUSA         2.0                 segundos entre pedidos
CONTRATAR_TIMEOUT       35                  segundos de espera por pedido
CONTRATAR_EXCLUIR_APERTURA_VENCIDA 0        1 = sin cierre publicado, se excluye si la apertura ya pasó
DEEP_ARCHIVO_SALIDA     licitaciones.json
"""
import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

URL_CAMMESA = "https://cammesaweb.cammesa.com/inicio-licitaciones/"
PUBLICAR_CAMMESA = False  # CAMMESA queda desactivada hasta una segunda etapa.
# Términos que usa el bloque de CAMMESA (sin cambios respecto de la versión estable).
TERMINOS = ["ups", "rectificador", "cargador de bateria", "banco de bateria", "baterias estacionarias", "corriente continua", "energia critica", "subestacion", "estacion transformadora", "transporte de energia electrica", "sistema de transporte de energia", "bess", "almacenamiento de energia"]
VERSION_AGENTE = "DEEP-CONTRATAR-V3-BUSQUEDA-NUMERO-20261025"

LISTADOS_CONTRATAR = {
    "proximas": ("Próximas aperturas", "/ListarAperturaProxima.aspx"),
    "ultimos90": ("Aperturas de los últimos 90 días", "/ListarAperturaUltimos30Dias.aspx"),
}
USER_AGENT = ("Mozilla/5.0 (compatible; DEEP-licitaciones/3.0; "
              "+https://github.com/mg-consultora/deep-licitaciones-ia)")
NUMERO_RE = re.compile(r"^[0-9]+(?:/[0-9]+)?-[0-9]+-[A-Za-z]+[0-9]+$")
POSTBACK_RE = re.compile(r"__doPostBack\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)")
POSTBACK_OPCIONES_RE = re.compile(r"WebForm_PostBackOptions\(\s*[\"']([^\"']+)[\"']\s*,\s*[\"']([^\"']*)[\"']")

# Semilla: ficha oficial de AMBA I tomada del licitaciones.json verificado (ejecución #48).
# No es una URL inventada. Solo se usa si el portal no entrega otra mejor.
FICHAS_CONOCIDAS = {
    "34-0003-LPU26": "https://contratar.gob.ar/PLIEGO/VistaPreviaPliegoCiudadano.aspx?qs=BQoBkoMoEhyeqdlsIRjlbVzpmYCDKQ1YOo1f39Qg%7Cky815ZCD%7CkfxdssdIaOnmLmI4ts42%2FeS0aiuALKYAdQz06KinBOvULkr%2FDpt5kPBe0%3D",
}


def _entero(nombre, defecto):
    try:
        return int(os.environ.get(nombre, defecto))
    except ValueError:
        return int(defecto)


def _decimal(nombre, defecto):
    try:
        return float(os.environ.get(nombre, defecto))
    except ValueError:
        return float(defecto)


def configuracion():
    return {
        "base": os.environ.get("CONTRATAR_BASE_URL", "https://contratar.gob.ar").rstrip("/"),
        "listados": [x.strip() for x in os.environ.get("CONTRATAR_LISTADOS", "proximas,ultimos90").split(",")
                     if x.strip() in LISTADOS_CONTRATAR] or ["proximas"],
        "max_paginas": max(1, _entero("CONTRATAR_MAX_PAGINAS", 10)),
        "max_detalles": max(0, _entero("CONTRATAR_MAX_DETALLES", 25)),
        "max_pedidos": max(2, _entero("CONTRATAR_MAX_PEDIDOS", 80)),
        "pausa": max(0.0, _decimal("CONTRATAR_PAUSA", 2.0)),
        "timeout": max(5, _entero("CONTRATAR_TIMEOUT", 35)),
        "excluir_apertura_vencida": os.environ.get("CONTRATAR_EXCLUIR_APERTURA_VENCIDA", "0") != "0",
        "salida": os.environ.get("DEEP_ARCHIVO_SALIDA", "licitaciones.json"),
    }


def ahora_argentina():
    """Hora local de Argentina (naive). Las fechas del portal están en hora argentina."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).replace(tzinfo=None)
    except Exception:
        return (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)


# ---------------------------------------------------------------
# Utilidades comunes (sin cambios)
# ---------------------------------------------------------------

class LectorEnlaces(HTMLParser):
    def __init__(self):
        super().__init__()
        self.enlaces = []
        self.url_actual = None
        self.texto_actual = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.url_actual = dict(attrs).get("href", "")
            self.texto_actual = []

    def handle_data(self, data):
        if self.url_actual is not None:
            self.texto_actual.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.url_actual is not None:
            texto = " ".join(" ".join(self.texto_actual).split())
            if texto and self.url_actual:
                self.enlaces.append((texto, self.url_actual))
            self.url_actual = None
            self.texto_actual = []


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(
        c for c in texto if not unicodedata.combining(c)
    )


def obtener_html(url):
    solicitud = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html"
        }
    )
    with urlopen(solicitud, timeout=35) as respuesta:
        if respuesta.status != 200:
            raise RuntimeError(
                f"Respuesta HTTP {respuesta.status}"
            )
        return respuesta.read().decode(
            "utf-8", errors="replace"
        )


# ---------------------------------------------------------------
# CAMMESA (sin cambios)
# ---------------------------------------------------------------

def buscar_cammesa():
    html = obtener_html(URL_CAMMESA)
    lector = LectorEnlaces()
    lector.feed(html)

    resultados = []
    vistos = set()

    for titulo, href in lector.enlaces:
        nombre = normalizar(titulo)
        if not any(t in nombre for t in TERMINOS):
            continue

        enlace = urljoin(URL_CAMMESA, href)
        dominio = urlparse(enlace).hostname or ""
        ruta = urlparse(enlace).path.lower()

        if dominio != "cammesaweb.cammesa.com":
            continue
        if re.search(r"\.(pdf|docx?|xlsx?|csv|zip|rar)$", ruta):
            continue
        if "/download/" in ruta:
            continue
        if enlace.rstrip("/") == URL_CAMMESA.rstrip("/"):
            continue
        if "/complejoshidrolectricos/" in ruta:
            continue

        clave = normalizar(titulo)
        if clave in vistos:
            continue
        vistos.add(clave)

        identificador = "CAMMESA-" + re.sub(
            r"[^A-Z0-9]+", "-",
            normalizar(titulo).upper()
        ).strip("-")[:65]

        resultados.append({
            "numero": identificador,
            "nombre": titulo,
            "organismo": "CAMMESA",
            "sector": "Energía",
            "fuente": "CAMMESA",
            "estadoOficial": "Pendiente de verificar",
            "publicacion": None,
            "consultas": None,
            "cierreOfertas": None,
            "documentacionFisica": None,
            "apertura": None,
            "plazoVerificado": False,
            "enlace": enlace,
            "observaciones": (
                "Referencia detectada en el portal oficial. "
                "Verificar vigencia, alcance y plazos."
            )
        })

    return resultados


# ---------------------------------------------------------------
# CONTRAT.AR: lectura del HTML (árbol mínimo, solo biblioteca estándar)
# ---------------------------------------------------------------

VACIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Nodo:
    __slots__ = ("tag", "attrs", "hijos", "padre")

    def __init__(self, tag, attrs=None, padre=None):
        self.tag, self.attrs, self.hijos, self.padre = tag, attrs or {}, [], padre

    def descendientes(self):
        pila = list(reversed(self.hijos))
        while pila:
            nodo = pila.pop()
            if isinstance(nodo, Nodo):
                yield nodo
                pila.extend(reversed(nodo.hijos))

    def texto(self):
        partes, pila = [], [iter(self.hijos)]
        while pila:
            for hijo in pila[-1]:
                if isinstance(hijo, str):
                    partes.append(hijo)
                elif hijo.tag in ("script", "style"):
                    continue
                else:
                    if hijo.tag in ("br", "p", "div", "li"):
                        partes.append(" ")
                    pila.append(iter(hijo.hijos))
                    break
            else:
                pila.pop()
        return " ".join("".join(partes).split())


class ConstructorArbol(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = Nodo("#raiz")
        self.actual = self.raiz

    def _cerrar_abiertos(self, cierran, limites):
        nodo = self.actual
        while nodo is not None and nodo.tag not in limites:
            if nodo.tag in cierran:
                self.actual = nodo.padre
                return
            nodo = nodo.padre

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self._cerrar_abiertos(("td", "th"), ("tr", "table"))
        elif tag == "tr":
            self._cerrar_abiertos(("td", "th", "tr"), ("table",))
        elif tag == "option":
            self._cerrar_abiertos(("option",), ("select",))
        nodo = Nodo(tag, {k: (v if v is not None else "") for k, v in attrs}, self.actual)
        self.actual.hijos.append(nodo)
        if tag not in VACIOS:
            self.actual = nodo

    def handle_startendtag(self, tag, attrs):
        self.actual.hijos.append(Nodo(tag, {k: (v if v is not None else "") for k, v in attrs}, self.actual))

    def handle_endtag(self, tag):
        nodo = self.actual
        while nodo is not None and nodo.tag != tag:
            nodo = nodo.padre
        if nodo is not None and nodo.padre is not None:
            self.actual = nodo.padre

    def handle_data(self, data):
        self.actual.hijos.append(data)


def parsear(html):
    constructor = ConstructorArbol()
    constructor.feed(html)
    constructor.close()
    return constructor.raiz


def campos_de(nodo):
    """Campos de formulario (input/select/textarea) dentro de un nodo."""
    campos = {}
    for n in nodo.descendientes():
        nombre = n.attrs.get("name")
        if not nombre:
            continue
        if n.tag == "input":
            tipo = n.attrs.get("type", "text").lower()
            if tipo in ("submit", "button", "image", "reset", "file"):
                continue
            if tipo in ("checkbox", "radio"):
                if "checked" in n.attrs:
                    campos[nombre] = n.attrs.get("value", "on")
            else:
                campos[nombre] = n.attrs.get("value", "")
        elif n.tag == "select":
            opciones = [o for o in n.descendientes() if o.tag == "option"]
            elegida = next((o for o in opciones if "selected" in o.attrs), opciones[0] if opciones else None)
            if elegida is not None:
                campos[nombre] = elegida.attrs.get("value", elegida.texto())
        elif n.tag == "textarea":
            campos[nombre] = n.texto()
    return campos


def formulario(raiz):
    formularios = [n for n in raiz.descendientes() if n.tag == "form"]
    if not formularios:
        return None
    for f in formularios:
        if f.attrs.get("id", "").lower() in ("aspnetform", "form1"):
            return f
    return formularios[0]


def filas_propias(tabla):
    """Filas <tr> cuya tabla más cercana es `tabla` (excluye tablas anidadas, p. ej. el paginador)."""
    for tr in tabla.descendientes():
        if tr.tag != "tr":
            continue
        padre = tr.padre
        while padre is not None and padre.tag != "table":
            padre = padre.padre
        if padre is tabla:
            yield tr


def celdas_de(tr):
    return [c for c in tr.hijos if isinstance(c, Nodo) and c.tag in ("td", "th")]


def encontrar_grilla(raiz):
    tablas = [n for n in raiz.descendientes() if n.tag == "table"]
    for t in tablas:
        if "gridlistapliegos" in t.attrs.get("id", "").lower():
            return t
    mejor, cuenta = None, 0
    for t in tablas:
        c = sum(1 for tr in filas_propias(t) if celdas_de(tr) and NUMERO_RE.match(celdas_de(tr)[0].texto()))
        if c > cuenta:
            mejor, cuenta = t, c
    return mejor


def clasificar_href(href):
    """Devuelve ('postback', destino, argumento), ('directo', href) o None."""
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return None
    if href.lower().startswith("javascript:"):
        m = POSTBACK_RE.search(href) or POSTBACK_OPCIONES_RE.search(href)
        return ("postback", m.group(1), m.group(2)) if m else None
    return ("directo", href)


def leer_filas(grilla):
    """Filas del listado oficial. Columnas (comprobadas en producción): número, nombre,
    tipo, apertura, estado, organismo. Cada fila conserva todos sus enlaces."""
    filas, sin_numero, encabezados = [], 0, []
    for tr in filas_propias(grilla):
        celdas = celdas_de(tr)
        if not celdas:
            continue
        textos = [c.texto() for c in celdas]
        if all(c.tag == "th" for c in celdas):
            encabezados = textos
            continue
        if len(celdas) < 6:
            continue
        if not NUMERO_RE.match(textos[0]):
            sin_numero += 1
            continue
        enlaces = []
        for c in celdas:
            for a in c.descendientes():
                if a.tag == "a":
                    accion = clasificar_href(a.attrs.get("href", ""))
                    if accion:
                        enlaces.append(accion)
        filas.append({"numero": textos[0], "nombre": textos[1], "tipo": textos[2],
                      "apertura_texto": textos[3], "estado": textos[4], "organismo": textos[5],
                      "enlaces": enlaces})
    return filas, sin_numero, encabezados


def controles_paginacion(raiz):
    """Enlaces del paginador del tipo __doPostBack('...','Page$n')."""
    controles = []
    for a in raiz.descendientes():
        if a.tag != "a":
            continue
        accion = clasificar_href(a.attrs.get("href", ""))
        if accion and accion[0] == "postback" and re.match(r"^Page\$", accion[2], re.I):
            controles.append((accion[1], accion[2], a.texto()))
    return controles


def siguiente_pagina(controles, actual):
    """Elige el control de la página siguiente. Devuelve (destino, argumento, número) o None."""
    for destino, argumento, _ in controles:
        if argumento.lower() == "page$%d" % (actual + 1):
            return destino, argumento, actual + 1
    mayores = []
    for destino, argumento, _ in controles:
        m = re.match(r"^Page\$(\d+)$", argumento, re.I)
        if m and int(m.group(1)) > actual:
            mayores.append((int(m.group(1)), destino, argumento))
    if mayores:
        n, destino, argumento = min(mayores)
        return destino, argumento, n
    for destino, argumento, _ in controles:
        if argumento.lower() == "page$next":
            return destino, argumento, actual + 1
    return None


def script_manager(html):
    """(id del ScriptManager, id del primer UpdatePanel) si la página usa MS-Ajax."""
    m = re.search(r"PageRequestManager\._initialize\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][^'\"]*['\"]\s*,\s*\[(.*?)\]", html, re.S)
    if not m:
        return None
    paneles = re.findall(r"['\"][tf]?([^'\"]+)['\"]", m.group(2))
    return (m.group(1), paneles[0]) if paneles else None


def parsear_delta(texto):
    """Respuesta asíncrona de ASP.NET AJAX: longitud|tipo|id|contenido| ..."""
    piezas, i = [], 0
    while i < len(texto):
        j = texto.index("|", i)
        largo = int(texto[i:j])
        k = texto.index("|", j + 1)
        tipo = texto[j + 1:k]
        l = texto.index("|", k + 1)
        ident = texto[k + 1:l]
        contenido = texto[l + 1:l + 1 + largo]
        if texto[l + 1 + largo:l + 2 + largo] != "|":
            raise ValueError("respuesta asíncrona mal formada")
        piezas.append((tipo, ident, contenido))
        i = l + 2 + largo
    return piezas


def es_delta(texto):
    return bool(re.match(r"^\d+\|[A-Za-z]+\|[^|]*\|", texto.lstrip("\ufeff")))


# ---------------------------------------------------------------
# CONTRAT.AR: sesión HTTP con cookies, pausas y límites
# ---------------------------------------------------------------

class ErrorPortal(Exception):
    pass


class SinEnlace(ErrorPortal):
    """La fila del listado no trae ningún enlace a su ficha (no es un fallo de extracción)."""


class Pagina:
    """Una página ASP.NET ya leída: su estado de formulario permite hacer postbacks."""

    def __init__(self, url, html, campos, action, raiz, sm):
        self.url, self.html, self.campos, self.action, self.raiz, self.sm = url, html, campos, action, raiz, sm

    @classmethod
    def desde_html(cls, url, html):
        raiz = parsear(html)
        f = formulario(raiz)
        campos = campos_de(f) if f is not None else {}
        return cls(url, html, campos, f.attrs.get("action", "") if f is not None else "", raiz, script_manager(html))


class SesionContratar:
    def __init__(self, cfg):
        self.base = cfg["base"]
        self.parsed = urlparse(self.base)
        self.pausa, self.timeout, self.max_pedidos = cfg["pausa"], cfg["timeout"], cfg["max_pedidos"]
        self.pedidos, self._ultimo = 0, 0.0
        self.bitacora = []
        self.reiniciar()

    def reiniciar(self):
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def url_permitida(self, url):
        p = urlparse(url)
        return p.scheme == self.parsed.scheme and p.hostname == self.parsed.hostname

    def pedir(self, url, datos=None, cabeceras=None, referer=None):
        if not self.url_permitida(url):
            raise ErrorPortal("URL fuera del portal oficial: %s" % url[:80])
        ultimo_error = None
        for intento in (1, 2):
            if self.pedidos >= self.max_pedidos:
                raise ErrorPortal("límite de pedidos alcanzado (%d)" % self.max_pedidos)
            espera = self.pausa - (time.time() - self._ultimo)
            if espera > 0 and self.pedidos:
                time.sleep(espera)
            cab = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml",
                   "Accept-Language": "es-AR,es;q=0.9"}
            if referer:
                cab["Referer"] = referer
            cab.update(cabeceras or {})
            self.pedidos += 1
            t0 = time.time()
            self._ultimo = t0
            try:
                with self.opener.open(Request(url, data=datos, headers=cab), timeout=self.timeout) as r:
                    crudo = r.read(6_000_000)
                    charset = r.headers.get_content_charset() or "utf-8"
                    texto = crudo.decode(charset if charset.lower() != "utf-8" else "utf-8-sig", errors="replace")
                    resp = {"html": texto, "url_final": r.geturl(), "status": r.status}
                self.bitacora.append(("POST" if datos else "GET", url, resp["status"], resp["url_final"], round(time.time() - t0, 2)))
                return resp
            except HTTPError as e:
                self.bitacora.append(("POST" if datos else "GET", url, e.code, None, round(time.time() - t0, 2)))
                ultimo_error = ErrorPortal("HTTP %s en %s" % (e.code, urlparse(url).path))
                if e.code < 500:
                    break
            except (URLError, TimeoutError, OSError) as e:
                self.bitacora.append(("POST" if datos else "GET", url, None, None, round(time.time() - t0, 2)))
                ultimo_error = ErrorPortal("%s: %s" % (type(e).__name__, e))
            if intento == 1:
                time.sleep(3 if self.pausa else 0)
        raise ultimo_error

    def abrir(self):
        """Abre la sesión pública: la home entrega las cookies ASP.NET."""
        self.reiniciar()
        return self.pedir(self.base + "/")

    def leer_pagina(self, url, referer=None):
        resp = self.pedir(url, referer=referer)
        if es_default(resp["url_final"]) and not es_default(url):
            raise ErrorPortal("el portal redirigió a Default.aspx (sesión no aceptada)")
        return Pagina.desde_html(resp["url_final"], resp["html"])

    def postback(self, pagina, destino, argumento, asincrono=False):
        if "__VIEWSTATE" not in pagina.campos:
            raise ErrorPortal("la página no trae __VIEWSTATE; no se puede hacer postback")
        campos = dict(pagina.campos)
        campos["__EVENTTARGET"], campos["__EVENTARGUMENT"] = destino, argumento
        cab = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        if asincrono:
            if not pagina.sm:
                raise ErrorPortal("la página no tiene ScriptManager")
            campos[pagina.sm[0]] = "%s|%s" % (pagina.sm[1], destino)
            campos["__ASYNCPOST"] = "true"
            cab.update({"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest",
                        "Cache-Control": "no-cache", "Accept": "*/*"})
        url = urljoin(pagina.url, pagina.action) if pagina.action else pagina.url
        return self.pedir(url, datos=urlencode(campos).encode("utf-8"), cabeceras=cab, referer=pagina.url)

    def respuesta_a_pagina(self, resp, anterior):
        """Convierte la respuesta de un postback en una Pagina (maneja el formato asíncrono)."""
        texto = resp["html"]
        if not es_delta(texto):
            return Pagina.desde_html(resp["url_final"], texto), None
        piezas = parsear_delta(texto.lstrip("\ufeff"))
        for tipo, ident, contenido in piezas:
            if tipo == "pageRedirect":
                return None, urljoin(anterior.url, contenido)
            if tipo == "error":
                raise ErrorPortal("error asíncrono del servidor: %s" % contenido[:120])
        html = " ".join(c for t, _, c in piezas if t == "updatePanel")
        raiz = parsear(html)
        campos = dict(anterior.campos)
        campos.update(campos_de(raiz))
        for t, ident, contenido in piezas:
            if t == "hiddenField":
                campos[ident] = contenido
        return Pagina(anterior.url, html, campos, anterior.action, raiz, anterior.sm), None


def es_default(url):
    return urlparse(url or "").path.lower().endswith("/default.aspx")


class LectorDetalle(HTMLParser):
    """Extrae texto visible, pares etiqueta/valor y filas de circulares."""
    def __init__(self):
        super().__init__()
        self.bloques = []
        self.actual = []
        self.nivel = 0
        self.filas = []
        self.fila = None
        self.celda = None
        self.enlaces = []

    def handle_starttag(self, tag, attrs):
        if tag in ('div', 'span', 'label', 'td', 'th', 'p', 'h3', 'h4'):
            self.actual.append(' ')
        if tag == 'tr':
            self.fila = []
        if tag in ('td', 'th') and self.fila is not None:
            self.celda = []
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if href:
                self.enlaces.append(href)

    def handle_data(self, data):
        self.actual.append(data)
        if self.celda is not None:
            self.celda.append(data)

    def handle_endtag(self, tag):
        if tag in ('div', 'span', 'label', 'td', 'th', 'p', 'h3', 'h4'):
            self.actual.append('\n')
        if tag in ('td', 'th') and self.celda is not None:
            self.fila.append(' '.join(''.join(self.celda).split()))
            self.celda = None
        if tag == 'tr' and self.fila is not None:
            if self.fila:
                self.filas.append(self.fila)
            self.fila = None


def fecha_iso(texto):
    m = re.search(r'(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?', texto)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + ' ' + (m.group(2) or '00:00'), '%d/%m/%Y %H:%M').strftime('%Y-%m-%dT%H:%M:00')
    except ValueError:
        return None


def obtener_campo(texto, etiquetas):
    """Busca la fecha junto a una etiqueta exacta, incluso si está en la línea siguiente."""
    lineas = [normalizar(' '.join(linea.split())).strip(' :') for linea in texto.splitlines()]
    etiquetas = [normalizar(etiqueta) for etiqueta in etiquetas]
    for i, linea in enumerate(lineas):
        if not any(linea.startswith(etiqueta) for etiqueta in etiquetas):
            continue
        # La página oficial separa etiqueta y fecha con etiquetas HTML.
        for candidato in [linea] + lineas[i + 1:i + 5]:
            fecha = fecha_iso(candidato)
            if fecha:
                return fecha
            if candidato != linea and candidato and any(c.isalpha() for c in candidato) and not re.match(r'^\d{2}/\d{2}/\d{4}', candidato):
                break
    return None


def extraer_detalle(html, numero):
    lector = LectorDetalle()
    lector.feed(html)
    texto = unescape(''.join(lector.actual))
    if numero.lower() not in texto.lower():
        raise RuntimeError('El detalle no contiene el número de proceso solicitado')
    campos = {
        'consultas': obtener_campo(texto, ['fecha y hora final de consultas']),
        'documentacionFisica': obtener_campo(texto, ['fecha y hora fin recepcion de documentos en soporte fisico']),
        'apertura': obtener_campo(texto, ['fecha y hora del 1', 'fecha y hora primer acto de apertura']),
        'publicacion': obtener_campo(texto, ['fecha y hora estimada de publicacion en el portal', 'fecha de publicacion', 'fecha y hora de publicacion']),
        'cierreOfertas': obtener_campo(texto, ['fecha y hora limite de presentacion de ofertas', 'fecha limite de presentacion de ofertas', 'fecha y hora de cierre de ofertas', 'fecha de cierre de ofertas', 'fin de recepcion de ofertas']),
    }
    circulares = []
    # Solo filas de tabla que parecen circulares (número + fecha + tipo).
    for fila in lector.filas:
        if len(fila) >= 3 and re.fullmatch(r'\d{1,3}', fila[0]) and re.fullmatch(r'\d{2}/\d{2}/\d{4}', fila[1]):
            tipo = normalizar(fila[2])
            if 'consulta' in tipo:
                circulares.append({'numero': fila[0], 'publicacion': fila[1], 'tipo': fila[2]})
    return campos, circulares



# ---------------------------------------------------------------
# CONTRAT.AR: clasificación de relevancia (separada del descubrimiento)
# ---------------------------------------------------------------

EQUIPOS_DEEP = [
    r"ups", r"sai", r"sistemas? de alimentacion ininterrumpida", r"rectificador(?:es)?",
    r"cargadores? (?:de )?bateri\w*", r"cargadores? y rectificadores?", r"bancos? de bateri\w*",
    r"bateri\w* (?:estacionari\w*|industrial\w*|de plomo|de niquel|de litio|de respaldo)",
    r"corriente continua", r"energia critica",
    r"convertidor(?:es)? (?:de frecuencia|estatic\w*|cc|ca|de potencia)", r"inversor(?:es)?",
    r"bess", r"almacenamiento de energia", r"fuentes? de alimentacion", r"servicios auxiliares",
    r"grupos? electrogenos?",
]
OBRAS_ELECTRICAS = [
    r"subestacion(?:es)?", r"estaci(?:on|ones) transformador\w*", r"transformador(?:es)? de potencia",
    r"transporte de energia electrica", r"sistema de transporte de energia", r"alta tension",
    r"media tension", r"lineas? de transmision", r"lineas? electricas?",
    r"centrales? (?:termic\w*|hidroelectric\w*|nuclear\w*|solar\w*|eolic\w*|fotovoltaic\w*)",
    r"parques? (?:solar\w*|eolic\w*|fotovoltaic\w*)", r"energia electrica", r"electrificacion",
    r"interconexion electrica", r"tableros? electricos?", r"scada", r"telecontrol",
    r"protecciones? electricas?", r"distribucion electrica", r"redes? electricas?",
]
_RE_EQUIPOS = re.compile(r"\b(?:%s)\b" % "|".join(EQUIPOS_DEEP))
_RE_OBRAS = re.compile(r"\b(?:%s)\b" % "|".join(OBRAS_ELECTRICAS))


def clasificar_relevancia(nombre, tipo):
    """Clasifica solo con los metadatos públicos del listado (nombre y tipo). No lee pliegos."""
    texto = normalizar(nombre)
    equipos = sorted({m.group(0) for m in _RE_EQUIPOS.finditer(texto)})
    obras = sorted({m.group(0) for m in _RE_OBRAS.finditer(texto)})
    directa = "directa" in normalizar(tipo)
    if equipos:
        return ("Compra directa de equipos" if directa else "Coincidencia directa"), equipos + obras
    if obras:
        return "Obra contextual: revisar pliego", obras
    return None, []


# ---------------------------------------------------------------
# CONTRAT.AR: fichas (enlace directo o postback)
# ---------------------------------------------------------------

def enlace_ficha(sesion, href, base_pagina):
    url = urljoin(base_pagina, unescape(href).replace("&amp;", "&"))
    if not sesion.url_permitida(url) or es_default(url):
        return None
    if re.search(r"\.(pdf|zip|rar|docx?|xlsx?)$", urlparse(url).path, re.I):
        return None
    return url


def _ruta(url):
    return urlparse(url).path.lower()


def abrir_postback(sesion, pagina, destino, argumento, estado):
    """Ejecuta el postback de una fila y devuelve (html, url_final). Prueba POST normal y, si la
    página usa ScriptManager, también asíncrono. Siempre exige un resultado distinto del listado."""
    modos = [False, True] if estado.get("modo_async") is not True else [True, False]
    fallos = []
    for asincrono in modos:
        if asincrono and not pagina.sm:
            continue
        try:
            resp = sesion.postback(pagina, destino, argumento, asincrono=asincrono)
            nueva, redireccion = sesion.respuesta_a_pagina(resp, pagina)
            if redireccion:
                resp2 = sesion.pedir(redireccion, referer=pagina.url)
                return resp2["html"], resp2["url_final"]
            if es_default(resp["url_final"]):
                raise ErrorPortal("el postback devolvió Default.aspx")
            return nueva.html, resp["url_final"]
        except ErrorPortal as e:
            fallos.append("%s: %s" % ("asíncrono" if asincrono else "normal", e))
    raise ErrorPortal("postback de ficha sin resultado (%s)" % "; ".join(fallos))


def resolver_ficha(sesion, pagina, fila, estado):
    """Intenta abrir la ficha del expediente. Devuelve (campos, circulares, url_ficha_verificada)
    o lanza ErrorPortal con el detalle."""
    candidatos = []
    for accion in fila["enlaces"]:
        if accion[0] == "directo":
            url = enlace_ficha(sesion, accion[1], pagina.url)
            if url:
                candidatos.append(("directo", url))
        else:
            candidatos.append(("postback", accion[1], accion[2]))
    semilla = FICHAS_CONOCIDAS.get(fila["numero"])
    if semilla and not any(c[0] == "directo" and c[1] == semilla for c in candidatos):
        candidatos.append(("directo", semilla))
    candidatos.sort(key=lambda c: (c[0] != "directo", "vistaprevia" not in c[1].lower() if c[0] == "directo" else False))
    if not candidatos:
        raise SinEnlace("la fila no tiene enlace a la ficha")
    fallos = []
    for cand in candidatos[:3]:
        try:
            if cand[0] == "directo":
                resp = sesion.pedir(cand[1], referer=pagina.url)
                if es_default(resp["url_final"]):
                    raise ErrorPortal("redirigió a Default.aspx")
                html, url_final, estable = resp["html"], resp["url_final"], True
            else:
                html, url_final = abrir_postback(sesion, pagina, cand[1], cand[2], estado)
                estable = (_ruta(url_final) != _ruta(pagina.url) and bool(urlparse(url_final).query))
            campos, circulares = extraer_detalle(html, fila["numero"])
            if not any(campos.values()):
                raise ErrorPortal("la ficha no muestra fechas reconocibles")
            url = enlace_ficha(sesion, url_final, url_final) if estable else None
            return campos, circulares, url
        except (ErrorPortal, RuntimeError) as e:
            fallos.append(str(e)[:140])
    raise ErrorPortal("; ".join(fallos))


def apertura_de_listado(texto):
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", texto)
    if not m:
        return None
    try:
        return datetime.strptime(" ".join(m.groups()), "%d/%m/%Y %H:%M").strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        return None


def nuevo_registro(fila, clasificacion, terminos, clave_listado, url_listado, pagina_n):
    return {
        "clasificacionDEEP": clasificacion,
        "terminosDetectados": terminos,
        "numero": fila["numero"],
        "nombre": fila["nombre"] or "No disponible",
        "organismo": fila["organismo"] or "No disponible",
        "sector": "Obra pública / posible energía",
        "fuente": "CONTRAT.AR",
        "tipoProceso": fila["tipo"] or "No disponible",
        "estadoOficial": fila["estado"] or "No disponible",
        "publicacion": None,
        "consultas": None,
        "cierreOfertas": None,
        "documentacionFisica": None,
        "apertura": apertura_de_listado(fila["apertura_texto"]),
        "detalleVerificado": False,
        "circulares": [],
        "enlaceCirculares": "",
        "revisionCirculares": "pendiente",
        "plazoVerificado": False,
        "enlace": url_listado,
        "tipoEnlace": "consulta_listado",
        "listadoOrigen": clave_listado,
        "paginaListado": pagina_n,
        "observaciones": "",
        "alertas": [],
    }


def texto_observaciones(reg):
    partes = ["Referencia detectada en el listado oficial de CONTRAT.AR (%s). "
              "Fechas y circulares tomadas de la ficha cuando se pudo acceder. "
              "La apertura no equivale al cierre de ofertas. Tipo: %s." % (reg["listadoOrigen"], reg["tipoProceso"])]
    if reg["tipoEnlace"] == "consulta_listado":
        partes.append("El enlace es de consulta al listado oficial, no una ficha directa: buscar el expediente por su número.")
    elif reg["tipoEnlace"] == "ficha_sin_verificar":
        partes.append("El enlace proviene del portal pero la ficha no pudo verificarse en esta ejecución.")
    if not reg["detalleVerificado"]:
        partes.append("Fechas pendientes de verificar en la ficha oficial.")
    return " ".join(partes)


# ---------------------------------------------------------------
# CONTRAT.AR: recorrido de listados con paginación
# ---------------------------------------------------------------

def recorrer_listado(sesion, cfg, clave, estado, acumulado):
    nombre, ruta = LISTADOS_CONTRATAR[clave]
    url = cfg["base"] + ruta
    info = {"clave": clave, "nombre": nombre, "url": url, "paginas": 0, "filas": 0,
            "completa": False, "motivo": "", "errores": []}
    acumulado["listados"].append(info)

    pagina = None
    for intento in (1, 2):
        try:
            if intento == 2 or sesion.pedidos == 0:
                sesion.abrir()
            pagina = sesion.leer_pagina(url, referer=cfg["base"] + "/")
            if encontrar_grilla(pagina.raiz) is None:
                raise ErrorPortal("el listado no contiene la tabla esperada (HTML de %d caracteres)" % len(pagina.html))
            break
        except ErrorPortal as e:
            info["errores"].append("Apertura del listado (intento %d): %s" % (intento, e))
            pagina = None
    if pagina is None:
        info["motivo"] = "no se pudo abrir el listado"
        return

    actual = 1
    while True:
        info["paginas"] += 1
        grilla = encontrar_grilla(pagina.raiz)
        filas, sin_numero, _ = leer_filas(grilla)
        acumulado["sin_numero"] += sin_numero
        nuevas = 0
        for fila in filas:
            info["filas"] += 1
            if fila["numero"] in acumulado["vistos"]:
                acumulado["duplicados"] += 1
                continue
            acumulado["vistos"].add(fila["numero"])
            nuevas += 1
            clasificacion, terminos = clasificar_relevancia(fila["nombre"], fila["tipo"])
            numero_objetivo = cfg.get("numero_objetivo", "")
            if numero_objetivo and fila["numero"].upper() != numero_objetivo:
                continue
            if not clasificacion and not numero_objetivo:
                acumulado["no_relevantes"] += 1
                continue
            if not clasificacion:
                clasificacion = "Consulta por número"
            reg = nuevo_registro(fila, clasificacion, terminos, clave, url, info["paginas"])
            if estado["detalles"] < cfg["max_detalles"]:
                estado["detalles"] += 1
                try:
                    campos, circulares, url_ficha = resolver_ficha(sesion, pagina, fila, estado)
                    reg.update({
                        "publicacion": campos.get("publicacion"), "consultas": campos.get("consultas"),
                        "cierreOfertas": campos.get("cierreOfertas"), "documentacionFisica": campos.get("documentacionFisica"),
                        "apertura": campos.get("apertura") or reg["apertura"],
                        "circulares": circulares, "detalleVerificado": True, "revisionCirculares": "verificada",
                        "plazoVerificado": bool(campos.get("cierreOfertas")),
                    })
                    if url_ficha:
                        reg.update({"enlace": url_ficha, "enlaceCirculares": url_ficha, "tipoEnlace": "ficha"})
                except SinEnlace:
                    acumulado["sin_enlace"].append(fila["numero"])
                except ErrorPortal as e:
                    acumulado["detalles_fallidos"].append(fila["numero"])
                    info["errores"].append("Ficha %s: %s" % (fila["numero"], e))
                    directo = next((a[1] for a in fila["enlaces"] if a[0] == "directo" and enlace_ficha(sesion, a[1], pagina.url)), None)
                    if directo:
                        reg.update({"enlace": enlace_ficha(sesion, directo, pagina.url), "tipoEnlace": "ficha_sin_verificar"})
            else:
                acumulado["detalles_omitidos"].append(fila["numero"])
            reg["observaciones"] = texto_observaciones(reg)
            acumulado["registros"][fila["numero"]] = reg

        if info["paginas"] == 1 and not filas:
            info["completa"] = True
            info["motivo"] = "el listado no devolvió filas"
            return
        if info["paginas"] > 1 and nuevas == 0:
            info["motivo"] = "la página %d no aportó filas nuevas (posible bucle de paginación)" % actual
            return

        siguiente = siguiente_pagina(controles_paginacion(pagina.raiz), actual)
        if not siguiente:
            info["completa"] = True
            info["motivo"] = "sin más páginas"
            return
        if info["paginas"] >= cfg["max_paginas"]:
            info["motivo"] = "límite de %d páginas alcanzado; quedan páginas sin leer" % cfg["max_paginas"]
            return
        destino, argumento, numero_sig = siguiente
        try:
            pagina = avanzar_pagina(sesion, pagina, destino, argumento, estado)
        except ErrorPortal as e:
            info["errores"].append("Avance a la página %d: %s" % (numero_sig, e))
            info["motivo"] = "falló el avance a la página %d" % numero_sig
            return
        actual = numero_sig


def avanzar_pagina(sesion, pagina, destino, argumento, estado):
    modos = [True, False] if estado.get("modo_async") is True else [False, True]
    fallos = []
    for asincrono in modos:
        if asincrono and not pagina.sm:
            continue
        try:
            resp = sesion.postback(pagina, destino, argumento, asincrono=asincrono)
            nueva, redireccion = sesion.respuesta_a_pagina(resp, pagina)
            if redireccion or nueva is None:
                raise ErrorPortal("el avance redirigió fuera del listado")
            if es_default(resp["url_final"]):
                raise ErrorPortal("el avance devolvió Default.aspx")
            if encontrar_grilla(nueva.raiz) is None:
                raise ErrorPortal("la respuesta no contiene la tabla del listado")
            estado["modo_async"] = asincrono
            return nueva
        except ErrorPortal as e:
            fallos.append("%s: %s" % ("asíncrono" if asincrono else "normal", e))
    raise ErrorPortal("; ".join(fallos))


def extraer_contratar(cfg):
    sesion = SesionContratar(cfg)
    acumulado = {"registros": {}, "vistos": set(), "listados": [], "sin_numero": 0, "duplicados": 0,
                 "no_relevantes": 0, "detalles_fallidos": [], "detalles_omitidos": [], "sin_enlace": []}
    estado = {"detalles": 0, "modo_async": None}
    for clave in cfg["listados"]:
        try:
            recorrer_listado(sesion, cfg, clave, estado, acumulado)
        except ErrorPortal as e:  # p. ej. límite de pedidos
            acumulado["listados"][-1]["errores"].append(str(e))
            acumulado["listados"][-1]["motivo"] = acumulado["listados"][-1]["motivo"] or str(e)
    acumulado["pedidos"] = sesion.pedidos
    acumulado["modo_paginacion"] = {None: "no se probó", False: "POST normal", True: "POST asíncrono"}[estado["modo_async"]]
    acumulado["completa"] = (
        bool(acumulado["listados"]) and all(l["completa"] for l in acumulado["listados"])
        and not acumulado["detalles_fallidos"] and not acumulado["detalles_omitidos"]
    )
    return acumulado


# ---------------------------------------------------------------
# Fusión con registros previos, vigencia y alertas
# ---------------------------------------------------------------

def _fecha(valor):
    try:
        return datetime.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def vencido(reg, ahora, cfg):
    cierre = _fecha(reg.get("cierreOfertas"))
    if cierre:
        return cierre < ahora
    apertura = _fecha(reg.get("apertura"))
    # Sin cierre publicado, ya no se pueden presentar ofertas una vez realizado el acto de apertura.
    return bool(cfg["excluir_apertura_vencida"] and apertura and apertura < ahora)


def _ficha_previa(previo):
    tipo = previo.get("tipoEnlace") or ("ficha" if "VistaPrevia" in str(previo.get("enlace", "")) else "")
    return tipo == "ficha"


def fusionar(ext, previos, cfg, ahora):
    previos_por_numero = {p.get("numero"): p for p in previos if p.get("numero")}
    finales, notas = [], []
    for numero, reg in ext["registros"].items():
        previo = previos_por_numero.get(numero, {})
        if not reg["detalleVerificado"] and previo.get("detalleVerificado"):
            for campo in ("publicacion", "consultas", "cierreOfertas", "documentacionFisica", "apertura"):
                if not reg.get(campo) and previo.get(campo):
                    reg[campo] = previo[campo]
            reg["circulares"] = previo.get("circulares", [])
            reg["detalleVerificado"] = True
            reg["revisionCirculares"] = "pendiente"
            reg["plazoVerificado"] = bool(reg.get("cierreOfertas"))
            if _ficha_previa(previo):
                reg.update({"enlace": previo["enlace"], "enlaceCirculares": previo.get("enlaceCirculares") or previo["enlace"], "tipoEnlace": "ficha"})
            reg["observaciones"] = texto_observaciones(reg) + " Se conservan las fechas verificadas en una ejecución anterior."
            reg["alertas"] = previo.get("alertas", [])
        elif reg["detalleVerificado"]:
            alertas = []
            for campo, etiqueta in (("consultas", "Fin de consultas"), ("documentacionFisica", "Fin de documentación física"),
                                    ("apertura", "Primer acto de apertura"), ("cierreOfertas", "Cierre de ofertas")):
                antes, despues = previo.get(campo), reg.get(campo)
                if antes and despues and antes != despues:
                    alertas.append("%s: %s → %s" % (etiqueta, antes, despues))
            antes_circ = {str(c.get("numero")) + ":" + str(c.get("publicacion")) for c in previo.get("circulares", [])}
            for c in reg["circulares"]:
                if previo and str(c["numero"]) + ":" + str(c["publicacion"]) not in antes_circ:
                    alertas.append("Circular nueva N° %s (%s)" % (c["numero"], c["publicacion"]))
            reg["alertas"] = alertas
        reg["ultimaVerificacion"] = datetime.now(timezone.utc).isoformat()
        finales.append(reg)

    for numero, previo in previos_por_numero.items():
        if numero in ext["registros"]:
            continue
        # No apareció en esta consulta. Solo se descarta si ya venció; si no, se conserva.
        previo = dict(previo)
        aviso = ("No figuró en la última consulta completa del listado; se conserva el último dato verificado."
                 if ext["completa"] else
                 "La última consulta quedó incompleta; se conserva el último dato verificado.")
        previo["alertas"] = [a for a in previo.get("alertas", []) if not a.startswith(("No figuró", "La última consulta"))] + [aviso]
        finales.append(previo)
        notas.append("Conservado %s" % numero)

    vigentes = [r for r in finales if not vencido(r, ahora, cfg)]
    descartados = len(finales) - len(vigentes)
    vistos, unicos = set(), []
    for r in vigentes:
        if r.get("numero") not in vistos:
            vistos.add(r.get("numero"))
            unicos.append(r)
    unicos.sort(key=lambda r: (r.get("apertura") or "9999", r.get("numero") or ""))
    return unicos, notas, descartados


# ---------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------

def cargar_anterior(archivo):
    ruta = Path(archivo)
    if ruta.exists():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            lista = datos.get("licitaciones", []) if isinstance(datos, dict) else datos
            if isinstance(lista, list):
                return [i for i in lista if isinstance(i, dict)]
        except (ValueError, OSError, AttributeError):
            pass
    return []


def main():
    parser = argparse.ArgumentParser(description="Agente DEEP - CONTRAT.AR")
    parser.add_argument("--numero", default="", help="Número exacto del proceso a buscar en los listados oficiales")
    args = parser.parse_args()
    cfg = configuracion()
    cfg["numero_objetivo"] = args.numero.strip().upper()
    if cfg["numero_objetivo"] and not NUMERO_RE.fullmatch(cfg["numero_objetivo"]):
        parser.error("Número de proceso no válido. Ejemplo: 34-0003-LPU26")
    previos = [r for r in cargar_anterior(cfg["salida"]) if r.get("fuente") == "CONTRAT.AR"]
    ahora = ahora_argentina()

    try:
        ext = extraer_contratar(cfg)
        fallo_total = None
    except Exception as error:  # error inesperado: se conservan los registros previos
        ext = {"registros": {}, "listados": [], "completa": False, "pedidos": 0, "sin_numero": 0, "duplicados": 0,
               "no_relevantes": 0, "detalles_fallidos": [], "detalles_omitidos": [], "sin_enlace": [], "vistos": set(),
               "modo_paginacion": "no se probó"}
        fallo_total = "%s: %s" % (type(error).__name__, error)

    errores = [e for l in ext["listados"] for e in l["errores"]]
    if fallo_total:
        errores.append("Error inesperado: " + fallo_total)
    # Un listado vacío cuando había registros previos se considera anómalo, no una confirmación.
    if not ext["registros"] and previos and ext["completa"] and not cfg.get("numero_objetivo"):
        ext["completa"] = False
        errores.append("El listado devolvió 0 registros relevantes y existen registros previos: se considera anómalo y se conservan.")

    licitaciones, notas, descartados = fusionar(ext, previos, cfg, ahora)
    descubiertas = len(ext["vistos"])
    paginas = sum(l["paginas"] for l in ext["listados"])
    resumen_fuente = (
        "Páginas leídas: %d; filas descubiertas: %d; relevantes para DEEP: %d; no relevantes: %d; sin número válido: %d; "
        "duplicados: %d; fichas verificadas: %d de %d relevantes; pedidos HTTP: %d; paginación: %s; "
        "registros conservados: %d; vencidos descartados: %d."
        % (paginas, descubiertas, len(ext["registros"]), ext["no_relevantes"], ext["sin_numero"], ext["duplicados"],
           sum(1 for r in ext["registros"].values() if r["detalleVerificado"]), len(ext["registros"]), ext["pedidos"],
           ext["modo_paginacion"], len(notas), descartados))
    if ext["sin_enlace"]:
        resumen_fuente += " Sin enlace a ficha en el listado (pendientes de verificar, enlace de consulta): %s." % ", ".join(ext["sin_enlace"][:10])
    if ext["detalles_omitidos"]:
        resumen_fuente += " Fichas no consultadas por límite: %s." % ", ".join(ext["detalles_omitidos"][:10])

    if ext["completa"]:
        estado_fuente = "consultada"
    else:
        estado_fuente = "incompleta" if descubiertas else "error"
    fuentes = [
        {"nombre": "CAMMESA - Convocatorias", "url": URL_CAMMESA, "estado": "en pausa", "registros": 0},
        {"nombre": "CONTRAT.AR - Obra pública", "url": cfg["base"] + LISTADOS_CONTRATAR[cfg["listados"][0]][1],
         "estado": estado_fuente, "registros": len(licitaciones), "detalle": resumen_fuente,
         "listados": [{k: v for k, v in l.items() if k != "errores"} for l in ext["listados"]],
         "errores": errores[:20]},
    ]
    if not PUBLICAR_CAMMESA:
        licitaciones = [r for r in licitaciones if r.get("fuente") == "CONTRAT.AR"]

    resultado = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "versionAgente": VERSION_AGENTE,
        "estado": ("extraccion_incompleta" if not ext["completa"] else
                   "oportunidades_pendientes_de_verificacion" if licitaciones else "sin_registros_verificados"),
        "extraccionCompleta": bool(ext["completa"]),
        "fuentes": fuentes,
        "licitaciones": licitaciones,
    }
    salida = Path(cfg["salida"])
    temporal = salida.with_suffix(".tmp")
    temporal.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(salida)

    print("VERSION ACTIVA: " + VERSION_AGENTE)
    print("CONTRAT.AR: " + resumen_fuente)
    for e in errores:
        print("ERROR DETALLE: " + e)
        print("::warning title=CONTRAT.AR::" + e.replace("\n", " ")[:300])
    print("licitaciones.json generado. Total de registros:", len(licitaciones))
    if any(r.get("fuente") == "CAMMESA" for r in licitaciones) and not PUBLICAR_CAMMESA:
        raise RuntimeError("ERROR: CAMMESA sigue presente en el JSON")

    pasos = os.environ.get("GITHUB_STEP_SUMMARY")
    if pasos:
        with open(pasos, "a", encoding="utf-8") as f:
            f.write("## Resultado de la actualización\n\n| Fuente | Estado | Registros |\n|---|---|---|\n")
            for fu in fuentes:
                f.write("| %s | %s | %s |\n" % (fu["nombre"], fu["estado"], fu["registros"]))
            f.write("\n%s\n" % resumen_fuente)
            if errores:
                f.write("\n### Errores y pendientes\n\n" + "\n".join("- " + e for e in errores[:20]) + "\n")

    if cfg.get("numero_objetivo"):
        hallado = cfg["numero_objetivo"] in ext["registros"]
        print("BUSQUEDA_POR_NUMERO:", cfg["numero_objetivo"], "ENCONTRADO" if hallado else "NO ENCONTRADO EN LOS LISTADOS CONSULTADOS")
        if not hallado:
            print("Consultar en https://contratar.gob.ar/BuscarAvanzado.aspx (el buscador avanzado no está automatizado).")
            sys.exit(2)
        if not ext["completa"]:
            print("::warning title=Ficha sin verificar::Se halló el proceso en el listado, pero falta verificar su ficha.")
        return
    if not ext["completa"]:
        print("::error title=CONTRAT.AR extracción incompleta::Se conservaron los registros verificados; revisar el detalle.")
        sys.exit(1)


if __name__ == "__main__":
    main()
