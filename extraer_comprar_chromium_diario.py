"""Consulta diaria de COMPR.AR con Chromium: solo guarda fichas industriales con cierre acreditado."""
import json
import re
from datetime import datetime
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from claude.licitaciones.fuentes.comprar_ficha_playwright import extraer_ficha
from claude.licitaciones.verificacion_comprar import INDUSTRIAL, INFORMATICOS

NUM=re.compile(r"\b\d{2,3}(?:/\d+)?-\d{4}-[A-Z]{3}\d{2}\b",re.I)
DESTINO=Path("claude/salida/comprar_playwright_verificado.json")

def main():
    informe={"estado":"sin_verificar","fecha":datetime.now().isoformat(),"fichas_revisadas":0,
             "oportunidades":[],"descartadas":[],"circulares":[]}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
            page=browser.new_page(locale="es-AR",timezone_id="America/Argentina/Buenos_Aires")
            page.set_default_timeout(12000)
            try:
                for intento in range(3):
                    try:
                        page.goto("https://comprar.gob.ar/",wait_until="commit",timeout=30000)
                        page.wait_for_load_state("domcontentloaded",timeout=20000)
                        break
                    except Exception:
                        if intento == 2:
                            raise
                        time.sleep(3 * (intento + 1))
                page.get_by_text(re.compile("PROCESOS CON APERTURA PR[OÓ]XIMA",re.I)).first.click(timeout=15000)
                page.wait_for_load_state("domcontentloaded",timeout=25000)
                if urlparse(page.url).hostname!="comprar.gob.ar": raise ValueError("Dominio no oficial")
                filas=page.locator("tr").filter(has_text=NUM)
                candidatos=[]
                for j in range(min(filas.count(),50)):
                    fila=filas.nth(j)
                    t=fila.inner_text()
                    m=NUM.search(t)
                    if m and m.group(0) not in [c[0] for c in candidatos]:
                        candidatos.append((m.group(0),t[:2000]))
                for numero,titulo in candidatos:
                    if not INDUSTRIAL.search(titulo.casefold()) or INFORMATICOS.search(titulo.casefold()):
                        continue
                    try:
                        fila=page.locator("tr").filter(has_text=numero).first
                        fila.get_by_text(numero,exact=True).first.click(timeout=12000)
                        page.wait_for_load_state("domcontentloaded",timeout=25000)
                        if urlparse(page.url).scheme!="https" or urlparse(page.url).hostname!="comprar.gob.ar":
                            raise ValueError("Ficha fuera de dominio oficial")
                        d=extraer_ficha(page.content(),numero)
                        informe["fichas_revisadas"]+=1
                        if d["vigencia_certificada"]:
                            informe["oportunidades"].append({
                                "numero_proceso":numero,"titulo":titulo[:220],
                                "fuente":"Página: COMPR.AR (Playwright verificado)",
                                "organismo":"COMPR.AR","estado":d.get("estado") or "Vigente verificada",
                                "fecha_presentacion":d["fecha_cierre"],
                                "fecha_apertura":d["fecha_apertura"],
                                "link":page.url,"texto":titulo,
                                "circulares_oficiales":d["circulares"]})
                        else:
                            informe["descartadas"].append({"numero":numero,"motivo":d["motivo"]})
                        if d["circulares"]:
                            informe["circulares"].append({"numero":numero,"items":d["circulares"],"url":page.url})
                    except Exception as exc:
                        informe["descartadas"].append({"numero":numero,"motivo":type(exc).__name__})
                    finally:
                        page.goto("https://comprar.gob.ar/",wait_until="domcontentloaded",timeout=45000)
                        page.get_by_text(re.compile("PROCESOS CON APERTURA PR[OÓ]XIMA",re.I)).first.click(timeout=15000)
                        page.wait_for_load_state("domcontentloaded",timeout=25000)
                informe["estado"]="consultado"
                informe["cobertura_exhaustiva"]=False
            finally:
                browser.close()
    except Exception as exc:
        informe["estado"]="error"
        informe["error"]=type(exc).__name__
    DESTINO.parent.mkdir(parents=True,exist_ok=True)
    DESTINO.write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"estado":informe["estado"],"fichas_revisadas":informe["fichas_revisadas"],
                      "verificadas":len(informe["oportunidades"]),
                      "circulares":len(informe["circulares"]),"error":informe.get("error")},ensure_ascii=False))
if __name__=="__main__":
    main()
    if json.loads(DESTINO.read_text(encoding="utf-8"))["estado"] == "error":
        sys.exit(2)
