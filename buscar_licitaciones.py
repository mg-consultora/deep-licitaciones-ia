import http.cookiejar
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from urllib.request import (
    HTTPCookieProcessor, Request, build_opener, urlopen
)
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError

URL_CAMMESA = "https://cammesaweb.cammesa.com/inicio-licitaciones/"
URL_CONTRATAR_INICIO = "https://contratar.gob.ar/"
URL_CONTRATAR = "https://contratar.gob.ar/ListarAperturaProxima.aspx"

TERMINOS = ["ups", "rectificador", "cargador de bateria", "banco de bateria", "baterias estacionarias", "corriente continua", "energia critica", "subestacion", "estacion transformadora", "transporte de energia electrica", "sistema de transporte de energia", "bess", "almacenamiento de energia"]
PUBLICAR_CAMMESA = False
VERSION_AGENTE = "DEEP-CONTRATAR-20261024-VERIFICABLE"



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
