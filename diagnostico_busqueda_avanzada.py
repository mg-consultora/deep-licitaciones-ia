#!/usr/bin/env python3
"""Diagnóstico de campos públicos del buscador avanzado de CONTRAT.AR.
No envía búsquedas, no descarga pliegos y no imprime tokens ASP.NET."""
import json, os, re, sys
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from buscar_licitaciones import SesionContratar, configuracion, parsear, formulario, ErrorPortal

def main():
    cfg=configuracion()
    cfg["timeout"]=15
    cfg["pausa"]=1
    sesion=SesionContratar(cfg)
    try:
        sesion.abrir()
        pagina=sesion.leer_pagina(cfg["base"]+"/BuscarAvanzado.aspx",referer=cfg["base"]+"/")
    except Exception as e:
        print("ERROR DE CONEXION:",type(e).__name__,str(e)[:160])
        return 1
    raiz=pagina.raiz
    f=formulario(raiz)
    if f is None:
        print("ERROR: no hay formulario; URL final:",pagina.url)
        return 2
    campos=[]
    for n in f.descendientes():
        if n.tag not in ("input","select","textarea","button"): continue
        name=n.attrs.get("name","")
        if name.startswith("__") or "viewstate" in name.lower() or "eventvalidation" in name.lower():continue
        tipo=n.attrs.get("type",n.tag)
        if tipo.lower() in ("hidden","password"):continue
        anc=n.padre
        contexto=[]
        for _ in range(2):
            if anc is None:break
            contexto.append(anc.texto()[:130])
            anc=anc.padre
        opciones=[]
        if n.tag=="select":
            opciones=[{"valor":o.attrs.get("value",""),"texto":o.texto()[:65]} for o in n.descendientes() if o.tag=="option"][:25]
        campos.append({"tipo":tipo,"name":name,"id":n.attrs.get("id",""),
                       "texto_cercano":contexto[0][:130] if contexto else "",
                       "opciones":opciones})
    salida={"url_final":pagina.url,"form_action":f.attrs.get("action",""),
            "total_campos_publicos":len(campos),"campos":campos}
    Path("diagnostico_busqueda_avanzada.json").write_text(json.dumps(salida,ensure_ascii=False,indent=2),encoding="utf-8")
    print("OK: diagnostico_busqueda_avanzada.json generado; campos:",len(campos))
    print("No se enviaron formularios ni se extrajeron credenciales o tokens.")
    return 0

if __name__=="__main__":raise SystemExit(main())
