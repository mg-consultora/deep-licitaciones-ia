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
VERSION_AGENTE = "DEEP-CONTRATAR-V3-CONTROL-PLAZOS-20261026"

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
    "34-0003-LPU26": "https://contratar.gob.ar/PLIEGO/VistaPreviaPliegoCiudadano.aspx?qs=BQoBkoMoEhxOJxLD06czKChcO7PsIP31cJs|uiIncWV|dxCP/3sCf1Fw6UcIk7ayHGc1kVP7y4wA7rS59FmCcn2vkT32fptk1Z3HKj24DOx|hRAD6Rx4ExCwk2N0Qsho2oLH5u|dwaXIBYELf63mtqxFnApErChR",
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
