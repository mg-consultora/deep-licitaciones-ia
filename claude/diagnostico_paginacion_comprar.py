"""Diagnóstico conservador de paginación real COMPR.AR.

No almacena cookies ni VIEWSTATE en artefactos. Solo registra controles,
números de proceso y evidencia de diferencias entre páginas.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from licitaciones.fuentes.comprar_webforms import (
    acciones_paginacion, campos_formulario, paginas_postback
)
from licitaciones.fuentes.paginas_web import extraer_items

URL = "https://comprar.gob.ar/"
NUMERO = re.compile(r"\b\d{2,3}(?:/\d+)?-\d{4}-[A-Z]{3}\d{2}\b", re.I)

def procesos(html):
    return sorted(set(NUMERO.findall(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))))

def diagnosticar():
    sesion = requests.Session()
    sesion.headers["User-Agent"] = "Mozilla/5.0 (compatible; DEEP-Diagnostico/1.0)"
    salida = {"url_inicial": URL, "cobertura_total_acreditada": False}
    try:
        r = sesion.get(URL, timeout=(8, 25))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        acciones = acciones_paginacion(r.text)
        form = soup.find("form")
        salida.update({
            "url_final": r.url,
            "http": r.status_code,
            "titulo": soup.title.get_text(" ", strip=True)[:150] if soup.title else "",
            "form_action": form.get("action", "") if form else None,
            "formularios": len(soup.select("form")),
            "viewstate_presente": bool(soup.select_one('input[name="__VIEWSTATE"]')),
            "eventvalidation_presente": bool(soup.select_one('input[name="__EVENTVALIDATION"]')),
            "eventos_paginacion": [{"target": t, "argument": a} for t,a in acciones[:25]],
            "links_postback": [
                {"texto": a.get_text(" ", strip=True)[:70], "href_patron": (a.get("href") or "")[:150]}
                for a in soup.select("a[href]") if "__doPostBack" in (a.get("href") or "")
            ][:35],
            "procesos_pagina_1": procesos(r.text)[:100],
            "cantidad_procesos_pagina_1": len(procesos(r.text))
        })
        if urlparse(r.url).hostname != "comprar.gob.ar":
            salida["advertencia"] = "Redireccion a dominio distinto"
        paginas, detalle = paginas_postback(sesion, r.url, r.text, max_paginas=5)
        salida["diagnostico_webforms"] = detalle
        salida["paginas_adicionales"] = []
        previos = set(procesos(r.text))
        for i, (url, html) in enumerate(paginas, 2):
            actuales = set(procesos(html))
            salida["paginas_adicionales"].append({
                "pagina": i, "url": url, "cantidad_procesos": len(actuales),
                "procesos_nuevos": sorted(actuales - previos)[:100],
                "cantidad_nuevos": len(actuales - previos)
            })
            previos |= actuales
        salida["segunda_pagina_distinta_verificada"] = any(
            p["cantidad_nuevos"] > 0 for p in salida["paginas_adicionales"]
        )
        if not acciones:
            salida["hipotesis"] = "No hay Page$Next visible en la portada; investigar formulario de búsqueda y postbacks numéricos"
    except Exception as e:
        salida["error"] = type(e).__name__ + ": " + str(e)[:250]
    finally:
        Path("diagnostico_comprar.json").write_text(
            json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    return 0 if "error" not in salida else 1

if __name__ == "__main__":
    raise SystemExit(diagnosticar())
