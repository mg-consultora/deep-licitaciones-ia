"""Prueba aislada de COMPR.AR con navegador real; no publica oportunidades."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PATRON = re.compile(r"\b\d{2,3}(?:/\d+)?-\d{4}-[A-Z]{3}\d{2}\b", re.I)
CIERRE = re.compile(r"(fin de recepci[oó]n|cierre de ofertas|fecha l[ií]mite de presentaci[oó]n|fin de presentaci[oó]n|presentaci[oó]n de ofertas)", re.I)
ESTADO = re.compile(r"(adjudicad|desiert|anulad|finalizad|sin efecto|publicad|convocad|apertura)", re.I)
def seguro(url):
    p=urlparse(url)
    return p.scheme=="https" and p.hostname=="comprar.gob.ar"
def main():
    informe={"fecha_utc":datetime.now(timezone.utc).isoformat(),"herramienta":"Playwright Chromium",
             "fichas":[],"busquedas":[],"cobertura_exhaustiva":False,"publicacion_autorizada":False}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--disable-dev-shm-usage"])
        page=browser.new_page(locale="es-AR",timezone_id="America/Argentina/Buenos_Aires",
                              viewport={"width":1366,"height":900})
        page.set_default_timeout(12000)
        try:
            page.goto("https://comprar.gob.ar/",wait_until="domcontentloaded",timeout=60000)
            if not seguro(page.url): raise ValueError("Redireccion fuera de dominio oficial")
            # El portal WebForms necesita ejecutar los enlaces reales con JS.
            opciones=[
                page.get_by_text(re.compile("PROCESOS CON APERTURA PR[OÓ]XIMA",re.I)),
                page.get_by_text(re.compile("B[UÚ]SQUEDA DE PROCESOS",re.I))]
            for i, opcion in enumerate(opciones):
                try:
                    if i:
                        page.goto("https://comprar.gob.ar/",wait_until="domcontentloaded",timeout=45000)
                    opcion.first.click(timeout=12000)
                    page.wait_for_load_state("domcontentloaded",timeout=25000)
                    if not seguro(page.url): raise ValueError("Destino no oficial")
                    filas=page.locator("tr").filter(has_text=PATRON)
                    total=filas.count()
                    informe["busquedas"].append({"consulta":"apertura_proxima" if i==0 else "avanzada",
                        "url":page.url,"filas_pagina":total,"muestra":PATRON.findall(page.locator("body").inner_text())[:15]})
                    if i==0 and total:
                        # Abrir un maximo de tres fichas; cada ficha se comprueba sin suponer vigencia.
                        for j in range(min(3,total)):
                            fila=filas.nth(j)
                            numero=PATRON.search(fila.inner_text())
                            if not numero: continue
                            try:
                                fila.get_by_text(numero.group(0),exact=True).first.click(timeout=10000)
                                page.wait_for_load_state("domcontentloaded",timeout=20000)
                                if not seguro(page.url): raise ValueError("Ficha fuera de COMPR.AR")
                                texto=page.locator("body").inner_text()
                                informe["fichas"].append({"numero":numero.group(0),"url":page.url,
                                    "numero_coincide":numero.group(0) in texto,
                                    "lineas_cierre":[line.strip()[:240] for line in texto.splitlines() if CIERRE.search(line)][:12],
                                    "lineas_estado":[line.strip()[:180] for line in texto.splitlines() if ESTADO.search(line)][:12],
                                    "vigencia_certificada":False})
                            except Exception as exc:
                                informe["fichas"].append({"numero":numero.group(0),"error":type(exc).__name__})
                            finally:
                                page.go_back(wait_until="domcontentloaded",timeout=25000)
                except Exception as exc:
                    informe["busquedas"].append({"consulta":"apertura_proxima" if i==0 else "avanzada",
                                                  "error":type(exc).__name__,"detalle":str(exc)[:160]})
        except Exception as exc:
            informe["error_general"]=type(exc).__name__ + ": " + str(exc)[:160]
        finally:
            browser.close()
    Path("informe_playwright_comprar.json").write_text(json.dumps(informe,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(informe,ensure_ascii=False,indent=2),flush=True)
    if not informe["busquedas"] or all("error" in b for b in informe["busquedas"]):
        raise SystemExit("No se pudo verificar navegacion real de COMPR.AR")
if __name__=="__main__":
    main()
