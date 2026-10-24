"""Diagnóstico de campos públicos de AMBA I (sin descargar pliegos ni anexos).
Ejecutar con: python probar_fuentes_deep.py
"""
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

FUENTES = {
    "CONTRAT.AR - AMBA I": "https://contratar.gob.ar/PLIEGO/VistaPreviaPliegoCiudadano.aspx?qs=BQoBkoMoEhyeqdlsIRjlbVzpmYCDKQ1YOo1f39Qg%7Cky815ZCD%7CkfxdssdIaOnmLmI4ts42%2FeS0aiuALKYAdQz06KinBOvULkr%2FDpt5kPBe0%3D",
    "CAMMESA - AMBA I": "https://cammesaweb.cammesa.com/ambai/",
    "CAMMESA - Convocatorias": "https://cammesaweb.cammesa.com/inicio-licitaciones/",
}

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(" ".join(data.split()))

def normalizar(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))

def analizar(nombre, url):
    resultado = {"fuente": nombre, "url": url, "acceso": False, "http": None,
                 "numero_proceso": None, "campos": {}, "circulares": [],
                 "fechas_en_pagina": [], "alertas": []}
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DEEP-Licitaciones/1.0)"})
        with urlopen(req, timeout=25) as resp:
            resultado["http"] = resp.status
            raw = resp.read(2_000_000)
            charset = resp.headers.get_content_charset() or "utf-8"
        html = raw.decode(charset, errors="replace")
        parser = TextExtractor()
        parser.feed(html)
        partes = parser.parts
        texto = "\n".join(partes)
        resultado["acceso"] = True
        resultado["numero_proceso"] = next(iter(re.findall(r"\b34-0003-LPU26\b", texto, re.I)), None)
        etiquetas = ["Número del Proceso de Contratación", "Nombre del Proceso de Contratación",
                     "Objeto de la contratación", "Unidad Operativa de Contrataciones",
                     "Procedimiento de selección", "Fecha de publicación", "Fecha y hora de apertura",
                     "Fecha de apertura", "Fecha límite de presentación", "Circulares"]
        # Extraer solo valores contiguos; no inferir si hay ambigüedad.
        for etiqueta in etiquetas:
            posiciones = [i for i, p in enumerate(partes) if normalizar(p) == normalizar(etiqueta)]
            if posiciones:
                muestras = []
                for i in posiciones[:3]:
                    siguientes = partes[i + 1:i + 4]
                    muestras.append(" | ".join(siguientes) if siguientes else "(sin valor contiguo)")
                resultado["campos"][etiqueta] = muestras
        resultado["fechas_en_pagina"] = list(dict.fromkeys(re.findall(
            r"\b(?:0?[1-9]|[12][0-9]|3[01])[/\-](?:0?[1-9]|1[0-2])[/\-]20\d{2}(?:\s+\d{1,2}:\d{2})?\b", texto)))[:30]
        if "CONTRAT.AR" in nombre:
            resultado["alertas"].append("Fechas detectadas sin etiqueta NO son plazos verificados.")
        if not resultado["numero_proceso"] and "CONTRAT.AR" in nombre:
            resultado["alertas"].append("No se encontró el identificador esperado; revisar estructura HTML.")
        resultado["caracteres_texto"] = len(texto)
    except Exception as exc:
        resultado["alertas"].append(f"Error de acceso: {type(exc).__name__}: {exc}")
    return resultado

def main():
    reporte = {"fecha_prueba_utc": datetime.now(timezone.utc).isoformat(), "resultados": []}
    for nombre, url in FUENTES.items():
        r = analizar(nombre, url)
        reporte["resultados"].append(r)
        print("\nFUENTE:", nombre)
        print("ACCESO:", r["acceso"], "HTTP:", r["http"])
        print("NÚMERO DE PROCESO:", r["numero_proceso"] or "no detectado")
        print("CAMPOS (texto vecino; requiere validación):")
        for etiqueta, muestras in r["campos"].items():
            print(" -", etiqueta, ":", " || ".join(muestras))
        print("FECHAS SIN CLASIFICAR:", ", ".join(r["fechas_en_pagina"][:15]) or "ninguna")
        for alerta in r["alertas"]:
            print("ADVERTENCIA:", alerta)
    Path("prueba_campos_deep.json").write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDiagnóstico generado: prueba_campos_deep.json")
    print("ATENCIÓN: no se validaron plazos ni se sincronizó el tablero.")

if __name__ == "__main__":
    main()
