"""Prueba independiente de acceso a páginas públicas; NO descarga pliegos ni anexos.
Ejecutar: python probar_fuentes_deep.py
"""
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

FUENTES = [
    {"nombre": "CAMMESA - Convocatorias", "url": "https://cammesaweb.cammesa.com/inicio-licitaciones/", "buscar": ["AMBA I", "AlmaSADI"]},
    {"nombre": "CAMMESA - AMBA I", "url": "https://cammesaweb.cammesa.com/ambai/", "buscar": ["AMBA I", "Resol"]},
    {"nombre": "CONTRAT.AR - AMBA I", "url": "https://contratar.gob.ar/PLIEGO/VistaPreviaPliegoCiudadano.aspx?qs=BQoBkoMoEhyeqdlsIRjlbVzpmYCDKQ1YOo1f39Qg%7Cky815ZCD%7CkfxdssdIaOnmLmI4ts42%2FeS0aiuALKYAdQz06KinBOvULkr%2FDpt5kPBe0%3D", "buscar": ["34-0003-LPU26", "AMBA I"]},
]

class TextoHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.textos = []
        self.omitir = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.omitir += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.omitir:
            self.omitir -= 1
    def handle_data(self, data):
        if not self.omitir and data.strip():
            self.textos.append(data.strip())

def probar(fuente):
    salida = {"fuente": fuente["nombre"], "url": fuente["url"], "accesible": False,
              "terminos": {}, "nota": "Prueba de lectura HTML, no extracción completa de licitaciones"}
    try:
        req = Request(fuente["url"], headers={"User-Agent": "DEEP-Licitaciones-Prueba/1.0 (consulta de paginas publicas)", "Accept": "text/html"})
        with urlopen(req, timeout=25) as respuesta:
            cuerpo = respuesta.read(1_500_000)
            salida["http"] = respuesta.status
            salida["tipo_contenido"] = respuesta.headers.get("Content-Type", "")
            salida["bytes_leidos"] = len(cuerpo)
        parser = TextoHTML()
        parser.feed(cuerpo.decode("utf-8", errors="replace"))
        texto = re.sub(r"\s+", " ", " ".join(parser.textos))
        salida["accesible"] = True
        salida["caracteres_texto"] = len(texto)
        salida["terminos"] = {termino: termino.casefold() in texto.casefold() for termino in fuente["buscar"]}
        salida["muestra_texto"] = texto[:450]
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        salida["error"] = f"{type(exc).__name__}: {exc}"
    return salida

if __name__ == "__main__":
    resultados = [probar(f) for f in FUENTES]
    reporte = {"fecha_utc": datetime.now(timezone.utc).isoformat(), "pruebas": resultados}
    Path("prueba_fuentes_deep.json").write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in resultados:
        print(f"\nFUENTE: {r['fuente']}")
        print("ACCESO:", "SI" if r["accesible"] else "NO", "HTTP:", r.get("http", "-"))
        print("TERMINOS:", r["terminos"])
        if "error" in r:
            print("ERROR:", r["error"])
    print("\nReporte: prueba_fuentes_deep.json")
    print("IMPORTANTE: Encontrar palabras no equivale a sincronizar procesos ni fechas.")
