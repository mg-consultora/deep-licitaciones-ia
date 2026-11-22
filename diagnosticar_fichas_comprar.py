"""Inspeccion de eventos dinamicos reales COMPR.AR; no publica ni guarda credenciales."""
import json
from pathlib import Path
import requests
from claude.licitaciones.fuentes.comprar_webforms import (
    buscar_procesos_avanzado, diagnosticar_filas_dinamicas, abrir_detalle_postback
)
from claude.licitaciones.verificacion_comprar import _vigencia_en_ficha

def main():
    sesion=requests.Session()
    sesion.headers.update({"User-Agent":"Mozilla/5.0 (compatible; DEEP-Auditoria/1.0)"})
    inicio=sesion.get("https://comprar.gob.ar/",timeout=(8,25))
    inicio.raise_for_status()
    paginas, estado=buscar_procesos_avanzado(sesion,inicio.url,inicio.text,max_paginas=2)
    salida={"buscador":estado,"paginas":len(paginas),"filas":[],"detalles":[],"cobertura_total":False}
    for url,html in paginas:
        filas=diagnosticar_filas_dinamicas(html,limite=8)
        salida["filas"].extend(filas)
        for fila in filas[:3]:
            detalle,motivo=abrir_detalle_postback(sesion,url,html,fila["numero"])
            verificacion=_vigencia_en_ficha(detalle[1],fila["numero"]) if detalle else (False,motivo)
            salida["detalles"].append({"numero":fila["numero"],"resultado":motivo,
                 "url":detalle[0] if detalle else None,"vigencia":verificacion[1],
                 "vigente_verificada":verificacion[0]})
    Path("diagnostico_fichas_dinamicas.json").write_text(
        json.dumps(salida,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(salida,ensure_ascii=False,indent=2),flush=True)
    if not paginas:
        raise SystemExit("Buscador sin paginas reales")
if __name__=="__main__":
    main()
