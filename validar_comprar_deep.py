"""Prueba real del extractor COMPR.AR y filtro comercial DEEP; no publica ofertas."""
import json
import os
from collections import Counter
import requests
from datetime import datetime, timezone
from pathlib import Path
import yaml
from claude.licitaciones.fuentes.paginas_web import PaginasWeb
from claude.licitaciones.filtros import Filtro
from claude.licitaciones.verificacion_comprar import motivo_descarte, ficha_oficial_verificada

def main():
    cfg = yaml.safe_load(Path("claude/config.yaml").read_text(encoding="utf-8"))
    cfg["paginas_publicas"] = [p for p in cfg["paginas_publicas"] if "comprar.gob.ar" in p["url"]]
    cfg["max_paginas_por_fuente"] = int(os.getenv("DEEP_COMPRAR_MAX_PAGINAS", "200"))
    cfg["auditoria_comprar_sin_publicar"] = True
    resultado = PaginasWeb(cfg).obtener()
    filtro = Filtro(cfg)
    unicos = {}
    for op in resultado.oportunidades:
        unicos.setdefault(op.numero_proceso or op.clave, op)
    relevantes = []
    pendientes = []
    muestra = []
    descartes = Counter()
    sesion = requests.Session()
    for op in sorted(unicos.values(), key=lambda o: (o.numero_proceso[-2:] == str(datetime.now().year)[-2:], o.numero_proceso), reverse=True):
        if len(muestra) < 100:
            muestra.append({"numero": op.numero_proceso, "titulo": op.titulo, "estado": op.estado, "enlace": op.link, "apertura": op.fecha_apertura.isoformat() if op.fecha_apertura else None})
        motivo = motivo_descarte(op)
        if motivo:
            descartes[motivo] += 1
            continue
        if not filtro.evaluar(op):
            descartes["no_relevante_deep"] += 1
            continue
        confirmado, motivo = ((True, "detalle_postback_verificado")
                              if getattr(op, "_ficha_verificada", False)
                              else ficha_oficial_verificada(op, sesion))
        if not confirmado:
            descartes[motivo] += 1
            pendientes.append({"numero": op.numero_proceso, "titulo": op.titulo,
                               "enlace_referencia": op.link, "motivo": motivo,
                               "puntaje": op.puntaje, "terminos": op.terminos})
            continue
        if confirmado:
            relevantes.append({
                "numero": op.numero_proceso, "titulo": op.titulo,
                "puntaje": op.puntaje, "terminos": op.terminos,
                "sector": op.sector, "enlace": op.link,
                "fecha_presentacion": op.fecha_presentacion.isoformat() if op.fecha_presentacion else None,
                "fecha_apertura": op.fecha_apertura.isoformat() if op.fecha_apertura else None,
            })
    informe = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "fuente": "COMPR.AR busqueda avanzada",
        "estado_fuente": resultado.estado,
        "detalle": resultado.detalle,
        "candidatos_extraidos": len(resultado.oportunidades),
        "procesos_unicos": len(unicos),
        "relevantes_deep": len(relevantes),
        "candidatos_industriales_pendientes": len(pendientes),
        "pendientes_verificacion": pendientes[:200],
        "muestra_diagnostica": muestra,
        "descartes_por_motivo": dict(descartes),
        "fichas_verificadas": len(relevantes),
        "relevantes": relevantes,
        "cobertura_exhaustiva_verificada": False,
        "validacion_de_vigencia_completa": False,
        "advertencia": "No se consideran plazos verificados ni se publican licitaciones sin comprobar detalle oficial."
    }
    Path("informe_comprar_deep.json").write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k:v for k,v in informe.items() if k != "relevantes"}, ensure_ascii=False, indent=2), flush=True)
    if resultado.estado == "error" or not unicos:
        print("FUENTE_NO_DISPONIBLE: sin certificacion de cobertura", flush=True)
        raise SystemExit(2)
    if resultado.estado == "parcial":
        print("AVISO: cobertura parcial; el flujo termina con diagnostico, no certifica exhaustividad.")
if __name__ == "__main__":
    main()
