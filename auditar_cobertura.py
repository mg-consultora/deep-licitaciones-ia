"""Auditoría de cobertura real de portales públicos; no modifica datos publicados."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests
import yaml
from bs4 import BeautifulSoup
from claude.licitaciones.fuentes.paginas_web import extraer_items, paginas_enlazadas
from claude.licitaciones.fuentes.comprar_webforms import paginas_postback

MAX_PAGINAS = 50
def auditar(p, session):
    nombre, url = p["nombre"], p["url"]
    d = {"fuente": nombre, "url": url, "paginas": 0, "registros": 0,
         "procesos_unicos": 0, "pendientes": 0, "cobertura": "no_acreditada",
         "errores": [], "paginas_detalle": []}
    try:
        inicial = session.get(url, timeout=(8, 20))
        inicial.raise_for_status()
        host = urlparse(inicial.url).hostname
        if host != urlparse(url).hostname:
            raise ValueError("Redireccion inicial a otro host")
        cola = [(inicial.url, inicial.text)]
        pendientes = paginas_enlazadas(inicial.text, inicial.url)
        visitadas = set()
        if "comprar.gob.ar" in (host or ""):
            adicionales, diagnostico = paginas_postback(session, inicial.url, inicial.text, max_paginas=MAX_PAGINAS)
            cola.extend(adicionales)
            d["errores"].append("WebForms: " + diagnostico)
        registros = set()
        while cola and d["paginas"] < MAX_PAGINAS:
            pagina_url, html = cola.pop(0)
            if pagina_url in visitadas and not ("comprar.gob.ar" in (host or "")):
                continue
            visitadas.add(pagina_url)
            items = extraer_items(html, pagina_url, nombre)
            d["paginas"] += 1
            d["registros"] += len(items)
            for item in items:
                registros.add(item.numero_proceso or (item.titulo, item.link))
            d["paginas_detalle"].append({"url": pagina_url, "registros": len(items)})
            if "comprar.gob.ar" not in (host or ""):
                for enlace in paginas_enlazadas(html, pagina_url):
                    if enlace not in visitadas and enlace not in pendientes:
                        pendientes.append(enlace)
            while not cola and pendientes and d["paginas"] < MAX_PAGINAS:
                siguiente = pendientes.pop(0)
                if siguiente in visitadas:
                    continue
                try:
                    r = session.get(siguiente, timeout=(8, 20))
                    r.raise_for_status()
                    if urlparse(r.url).hostname != host:
                        raise ValueError("Redireccion fuera del host")
                    if "html" not in r.headers.get("Content-Type", "").lower():
                        raise ValueError("Respuesta no HTML")
                    cola.append((r.url, r.text))
                except Exception as e:
                    d["errores"].append(siguiente + ": " + type(e).__name__ + ": " + str(e)[:120])
                time.sleep(0.2)
        d["procesos_unicos"] = len(registros)
        d["pendientes"] = len(pendientes) + len(cola)
        if d["pendientes"]:
            d["errores"].append("Limite alcanzado; quedan paginas pendientes")
        if not d["errores"]:
            d["cobertura"] = "paginacion_visible_recorrida_no_exhaustividad"
    except Exception as e:
        d["errores"].append(type(e).__name__ + ": " + str(e)[:180])
    return d

def main():
    config = yaml.safe_load(Path("claude/config.yaml").read_text(encoding="utf-8"))
    fuentes = [p for p in config["paginas_publicas"] if p.get("activa", True)]
    resultados = []
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; DEEP-Auditoria/1.0)"
    for p in fuentes:
        resultado = auditar(p, session)
        resultados.append(resultado)
        print(json.dumps({k:v for k,v in resultado.items() if k != "paginas_detalle"}, ensure_ascii=False), flush=True)
    salida = {"fecha_utc": datetime.now(timezone.utc).isoformat(),
              "nota": "Registros son candidatos crudos, no licitaciones verificadas. No demuestra cobertura total de portales JS, filtros ni fuentes privadas.",
              "fuentes": resultados}
    Path("auditoria_cobertura.json").write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    lineas = ["# Auditoría real de cobertura DEEP", "", "Fecha UTC: " + salida["fecha_utc"], "",
              "| Fuente | Páginas | Registros crudos | Únicos | Pendientes | Cobertura |",
              "|---|---:|---:|---:|---:|---|"]
    for x in resultados:
        lineas.append(f'| {x["fuente"]} | {x["paginas"]} | {x["registros"]} | {x["procesos_unicos"]} | {x["pendientes"]} | {x["cobertura"]} |')
        if x["errores"]:
            lineas.append("  - Incidencias: " + "; ".join(x["errores"]))
    lineas += ["", "**Importante:** los resultados no prueban cobertura total ni validan plazos. CONTRAT.AR tiene extractor independiente y requiere auditoría propia."]
    Path("auditoria_cobertura.md").write_text("\n".join(lineas)+"\n", encoding="utf-8")

if __name__ == "__main__":
    main()
