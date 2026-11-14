"""Agrega la pestaña "Obras futuras y oportunidades privadas" al tablero ya generado.

No reescribe el tablero de licitaciones: inserta un bloque entre marcas <!--OBRAS-INICIO--> y
<!--OBRAS-FIN-->. Si el bloque ya existe (corrida anterior), lo reemplaza. Así la pestaña de
licitaciones públicas queda exactamente como la genera el agente original.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .texto_base import buscar_fechas
from .extraer import EN_EJECUCION, LIC_ABIERTA, LIC_ANUNCIADA, LIC_CERRADA, PROYECTO

INICIO, FIN = "<!--OBRAS-INICIO-->", "<!--OBRAS-FIN-->"
ORDEN = {LIC_ABIERTA: 0, LIC_ANUNCIADA: 1, EN_EJECUCION: 2, PROYECTO: 3, LIC_CERRADA: 4}


def preparar(proyectos: list[dict], mostrar_propias: bool, ahora: datetime | None = None) -> list[dict]:
    ahora = ahora or datetime.now()
    filas = []
    for p in proyectos:
        p = dict(p)
        # Una licitación "abierta" cuya fecha ya pasó se muestra como cerrada.
        if p.get("tipo") == LIC_ABIERTA:
            lic = p.get("fechas", {}).get("lic_obra") or p.get("fechas", {}).get("lic_productos")
            f = [d for _, d in buscar_fechas(lic["texto"])] if lic else []
            if f and f[0] < ahora:
                p["tipo"] = LIC_CERRADA
        # Privacidad: si no se muestran nombres de la lista propia, solo queda la cantidad.
        p["propias_n"] = len(p.get("propias") or [])
        if not mostrar_propias:
            p["propias"] = []
        filas.append(p)
        # Prioridad comercial orientativa; no confundir con una compra confirmada.
        tipo = p.get("tipo", "")
        if tipo == LIC_ABIERTA and (p.get("fechas") or {}).get("lic_productos"):
            p["prioridad_comercial"] = "ALTA"
            p["motivo_prioridad"] = "Licitación de productos identificada; verificar vigencia y alcance en la fuente"
        elif tipo in (LIC_ABIERTA, LIC_ANUNCIADA, EN_EJECUCION):
            p["prioridad_comercial"] = "MEDIA"
            p["motivo_prioridad"] = "Obra o proceso identificado; verificar compras y responsables"
        else:
            p["prioridad_comercial"] = "BAJA"
            p["motivo_prioridad"] = "Seguimiento estratégico; sin compra de equipos confirmada"
    rango = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
    filas.sort(key=lambda p: (rango[p["prioridad_comercial"]], ORDEN.get(p.get("tipo"), 9), not p.get("verificado_manual")))
    return filas


def insertar(html: str, proyectos: list[dict], novedades: list[dict], fuentes: list[dict],
             mostrar_propias: bool, nota: str = "") -> str:
    datos = {"proyectos": preparar(proyectos, mostrar_propias), "novedades": novedades,
             "fuentes": fuentes, "nota": nota, "generado": datetime.now().strftime("%d/%m/%Y %H:%M")}
    bloque = BLOQUE.replace("__DATOS__", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
    html = re.sub(re.escape(INICIO) + r".*?" + re.escape(FIN), "", html, flags=re.S)
    if "</body>" in html:
        return html.replace("</body>", f"{INICIO}{bloque}{FIN}</body>", 1)
    return html + f"{INICIO}{bloque}{FIN}"


def pagina_sola(ruta: Path, *args, **kwargs) -> None:
    """Si todavía no existe el tablero de licitaciones, arma una página solo con la pestaña de obras."""
    base = ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><title>Tablero</title></head><body><main></main></body></html>')
    ruta.write_text(insertar(base, *args, **kwargs), encoding="utf-8")


BLOQUE = r"""
<style>
.pestanas{display:flex;gap:6px;flex-wrap:wrap;max-width:1200px;margin:6px auto 0;padding:0 20px}
.pestanas button{font:inherit;font-weight:600;padding:9px 14px;border-radius:10px 10px 0 0;border:1px solid var(--ln,#e4e7ec);border-bottom:0;background:transparent;color:var(--mut,#667085);cursor:pointer}
.pestanas button.on{background:var(--card,#fff);color:var(--tx,#1d2330)}
.pestanas .n{display:inline-block;min-width:20px;padding:0 6px;border-radius:99px;background:#1f4e79;color:#fff;font-size:12px;margin-left:4px}
body.ver-obras header ~ main > *:not(#obras){display:none!important}
body.ver-obras main > *:not(#obras){display:none!important}
body:not(.ver-obras) #obras{display:none}
#obras{--o-card:var(--card,#fff);--o-ln:var(--ln,#e4e7ec);--o-mut:var(--mut,#667085);--o-tx:var(--tx,#1d2330);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--o-tx)}
#obras .intro{color:var(--o-mut);font-size:13px;margin:10px 0}
#obras .kp{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:12px 0}
#obras .k{background:var(--o-card);border:1px solid var(--o-ln);border-radius:12px;padding:10px 12px;cursor:pointer;user-select:none}
#obras .k.on{border:2px solid #1f4e79;background:#e8eef6;box-shadow:0 0 0 1px #1f4e79}#obras .k.off{opacity:.65}#obras .k b{font-size:22px;display:block}#obras .k span{font-size:12px;color:var(--o-mut)}
@media(max-width:700px){#obras .kp{grid-template-columns:repeat(2,1fr)}}
#obras .pn{background:var(--o-card);border:1px solid var(--o-ln);border-radius:12px;padding:12px 16px;margin:12px 0}
#obras .pn h2{font-size:15px;margin:0 0 8px}
#obras .fl{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;align-items:center}
#obras .fl input[type=search],#obras .fl input[type=date],#obras .fl select{font:inherit;padding:8px 10px;border:1px solid var(--o-ln);border-radius:8px;background:var(--o-card);color:var(--o-tx)}
#obras .fl input[type=search]{flex:1;min-width:200px}
#obras .fl select{max-width:220px}
#obras .prioridad{display:inline-block;border-radius:6px;padding:3px 8px;font-weight:700;font-size:12px;margin:4px 6px 0 0}
#obras .prioridad.ALTA{background:#fce5e3;color:#9b2525}#obras .prioridad.MEDIA{background:#fff0c7;color:#775000}#obras .prioridad.BAJA{background:#edf0f3;color:#52606d}
#obras .fl label{font-size:13px;color:var(--o-mut);display:flex;gap:4px;align-items:center}
#obras button.b{font:inherit;padding:8px 12px;border-radius:8px;border:1px solid var(--o-ln);background:var(--o-card);color:var(--o-tx);cursor:pointer}
#obras .c{background:var(--o-card);border:1px solid var(--o-ln);border-left:6px solid #98a2b3;border-radius:12px;padding:14px 16px;margin:10px 0;overflow-wrap:anywhere}
