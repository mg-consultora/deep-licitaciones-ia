"""Diagnostico robusto de metadatos publicos AMBA I (no descarga pliegos).
Ejecutar: python probar_fuentes_deep_robusto.py
Solo lectura; no modifica el tablero. Python 3.12, sin dependencias.
"""
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FUENTES = {
    "CONTRAT.AR - AMBA I": "https://contratar.gob.ar/PLIEGO/VistaPreviaPliegoCiudadano.aspx?qs=BQoBkoMoEhyeqdlsIRjlbVzpmYCDKQ1YOo1f39Qg%7Cky815ZCD%7CkfxdssdIaOnmLmI4ts42%2FeS0aiuALKYAdQz06KinBOvULkr%2FDpt5kPBe0%3D",
    "CAMMESA - AMBA I": "https://cammesaweb.cammesa.com/ambai/",
    "CAMMESA - Convocatorias": "https://cammesaweb.cammesa.com/inicio-licitaciones/",
}
PATRON_FECHA = re.compile(r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-]20\d{2}(?:\s+\d{1,2}:\d{2})?(?!\d)")
PATRON_PROCESO = re.compile(r"\b\d{1,3}-\d{3,5}-[A-Z]{2,5}\d{2}\b", re.I)
ETIQUETAS = {
    "publicacion": ("fecha de publicacion", "publicado el"),
    "apertura": ("fecha de apertura", "apertura de ofertas", "acto de apertura"),
    "presentacion": ("presentacion de ofertas", "recepcion de ofertas", "fecha limite de presentacion"),
    "consultas": ("fecha limite de consultas", "limite de consultas", "consultas hasta"),
    "circular": ("circular", "aclaratoria", "modificatoria"),
    "prorroga": ("prorroga", "postergacion"),
}


def normalizar(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c))


def limpiar(s):
    return " ".join(s.split()).strip()


class Estructura(HTMLParser):
    """Lee tablas, etiquetas y bloques de texto, aun sin tablas HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bloques, self.tablas, self.pila_tablas = [], [], []
        self.bloque, self.celda = [], None
        self.fila = None
        self.skip = 0

    def volcar(self):
        v = limpiar(" ".join(self.bloque))
        if v and (not self.bloques or self.bloques[-1] != v):
            self.bloques.append(v)
        self.bloque = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if self.skip:
            return
        if tag in ("p", "div", "li", "section", "article", "h1", "h2", "h3", "br", "tr", "td", "th", "dt", "dd"):
            self.volcar()
        if tag == "table":
            self.pila_tablas.append([])
        elif tag == "tr" and self.pila_tablas:
            self.fila = []
        elif tag in ("td", "th") and self.fila is not None:
            self.celda = []

    def handle_data(self, data):
        if self.skip:
            return
        v = limpiar(data)
        if v:
            self.bloque.append(v)
            if self.celda is not None:
                self.celda.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("td", "th") and self.celda is not None:
            self.fila.append(limpiar(" ".join(self.celda)))
            self.celda = None
        elif tag == "tr" and self.fila is not None and self.pila_tablas:
            if any(self.fila):
                self.pila_tablas[-1].append(self.fila)
            self.fila = None
        elif tag == "table" and self.pila_tablas:
            tabla = self.pila_tablas.pop()
            if tabla:
                self.tablas.append(tabla)
        if tag in ("p", "div", "li", "section", "article", "h1", "h2", "h3", "tr", "td", "th", "dt", "dd"):
            self.volcar()


def descargar(url, intentos=3, espera=18):
    errores = []
    for n in range(1, intentos + 1):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DEEP-Metadata/1.0)", "Accept": "text/html,application/xhtml+xml"})
            with urlopen(req, timeout=espera) as r:
                estado = r.status
                tipo = r.headers.get("Content-Type", "")
                if "html" not in tipo.lower() and "text/plain" not in tipo.lower():
                    return None, estado, errores + ["Contenido no HTML; no se descarga ni analiza"]
                contenido = r.read(1_500_001)
                if len(contenido) > 1_500_000:
                    return None, estado, errores + ["Pagina demasiado grande para el diagnostico"]
                charset = r.headers.get_content_charset() or "utf-8"
                return contenido.decode(charset, errors="replace"), estado, errores
        except (HTTPError, URLError, TimeoutError, OSError) as e:
            errores.append(f"Intento {n}/{intentos}: {type(e).__name__}: {e}")
            if n < intentos:
                time.sleep(n * 2)
    return None, None, errores


def extraer(nombre, url):
    html, http, errores = descargar(url)
    r = {"fuente": nombre, "url": url, "http": http, "accesible": html is not None,
         "numero_proceso": None, "tablas": 0, "candidatos": [], "fechas_sin_etiqueta": [],
         "advertencias": errores, "validado": False}
    if html is None:
        return r
    parser = Estructura()
    parser.feed(html)
    parser.volcar()
    r["tablas"] = len(parser.tablas)
    texto = " ".join(parser.bloques)
    proceso = PATRON_PROCESO.search(texto)
    if proceso:
        r["numero_proceso"] = proceso.group(0)
    evidencias = []
    # En tablas, conservar celdas y filas para poder revisar la asociacion.
    for nt, tabla in enumerate(parser.tablas, 1):
        for nf, fila in enumerate(tabla, 1):
            linea = limpiar(" | ".join(fila))
            if linea:
                evidencias.append((f"tabla {nt}, fila {nf}", linea))
    # En bloques, tomar solo la linea y el siguiente bloque inmediato.
    for i, bloque in enumerate(parser.bloques):
        siguiente = parser.bloques[i + 1] if i + 1 < len(parser.bloques) else ""
        evidencias.append((f"bloque {i+1}", bloque + (" | " + siguiente if siguiente else "")))
    vistos = set()
    for ubicacion, linea in evidencias:
        fechas = PATRON_FECHA.findall(linea)
        if not fechas:
            continue
        clave = (linea[:250], tuple(fechas))
        if clave in vistos:
            continue
        vistos.add(clave)
        clases = [categoria for categoria, etiquetas in ETIQUETAS.items()
                   if any(etiqueta in normalizar(linea) for etiqueta in etiquetas)]
        evidencia = {"ubicacion": ubicacion, "fechas": fechas[:8], "contexto": linea[:380]}
        if clases:
            evidencia["etiquetas_posibles"] = clases
            evidencia["estado"] = "candidato_sin_validar"
            if len(r["candidatos"]) < 30:
                r["candidatos"].append(evidencia)
        elif len(r["fechas_sin_etiqueta"]) < 15:
            r["fechas_sin_etiqueta"].append(evidencia)
    if not parser.tablas:
        r["advertencias"].append("Sin tablas HTML; se analizaron bloques de texto")
    if not r["candidatos"]:
        r["advertencias"].append("No se encontraron fechas asociables a etiquetas")
    r["advertencias"].append("Los candidatos NO son plazos verificados; validar fuente, fila y contexto")
    return r


def main():
    reporte = {"generado_utc": datetime.now(timezone.utc).isoformat(), "modo": "diagnostico_sin_publicacion", "fuentes": []}
    for nombre, url in FUENTES.items():
        print(f"\n=== {nombre} ===", flush=True)
        resultado = extraer(nombre, url)
        reporte["fuentes"].append(resultado)
        print(f"HTTP: {resultado['http']} | accesible: {resultado['accesible']} | tablas: {resultado['tablas']} | proceso: {resultado['numero_proceso']}", flush=True)
        for c in resultado["candidatos"][:12]:
            print(f"CANDIDATO {c['etiquetas_posibles']}: {c['fechas']} | {c['ubicacion']} | {c['contexto'][:230]}", flush=True)
        for c in resultado["fechas_sin_etiqueta"][:5]:
            print(f"SIN ETIQUETA: {c['fechas']} | {c['ubicacion']}", flush=True)
        for aviso in resultado["advertencias"]:
            print("AVISO:", aviso, flush=True)
    ruta = Path("prueba_extractor_robusto.json")
    ruta.write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReporte: {ruta}. No se modifico el tablero ni se descargaron pliegos.", flush=True)


if __name__ == "__main__":
    main()
