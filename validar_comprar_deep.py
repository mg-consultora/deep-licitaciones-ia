"""Prueba real del extractor COMPR.AR y filtro comercial DEEP; no publica ofertas."""
import json
from datetime import datetime, timezone
from pathlib import Path
import yaml
from claude.licitaciones.fuentes.paginas_web import PaginasWeb
from claude.licitaciones.filtros import Filtro

def main():
    cfg = yaml.safe_load(Path("claude/config.yaml").read_text(encoding="utf-8"))
    cfg["paginas_publicas"] = [p for p in cfg["paginas_publicas"] if "comprar.gob.ar" in p["url"]]
    cfg["max_paginas_por_fuente"] = 50
    resultado = PaginasWeb(cfg).obtener()
    filtro = Filtro(cfg)
    unicos = {}
    for op in resultado.oportunidades:
        unicos.setdefault(op.numero_proceso or op.clave, op)
    relevantes = []
    for op in unicos.values():
        if filtro.evaluar(op):
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
        "relevantes": relevantes,
        "cobertura_exhaustiva_verificada": False,
        "advertencia": "No se consideran plazos verificados ni se publican licitaciones sin comprobar detalle oficial."
    }
    Path("informe_comprar_deep.json").write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k:v for k,v in informe.items() if k != "relevantes"}, ensure_ascii=False, indent=2), flush=True)
    if resultado.estado == "error" or not unicos:
        raise SystemExit("COMPR.AR no produjo procesos: revisar informe_comprar_deep.json")
    if resultado.estado == "parcial":
        print("AVISO: cobertura parcial; el flujo termina con diagnostico, no certifica exhaustividad.")
if __name__ == "__main__":
    main()
