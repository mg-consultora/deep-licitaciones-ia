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
    filas.sort(key=lambda p: (ORDEN.get(p.get("tipo"), 9), not p.get("verificado_manual"), p.get("actualizado", "")), reverse=False)
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
#obras .k.off{opacity:.4}#obras .k b{font-size:22px;display:block}#obras .k span{font-size:12px;color:var(--o-mut)}
@media(max-width:700px){#obras .kp{grid-template-columns:repeat(2,1fr)}}
#obras .pn{background:var(--o-card);border:1px solid var(--o-ln);border-radius:12px;padding:12px 16px;margin:12px 0}
#obras .pn h2{font-size:15px;margin:0 0 8px}
#obras .fl{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;align-items:center}
#obras .fl input[type=search],#obras .fl select{font:inherit;padding:8px 10px;border:1px solid var(--o-ln);border-radius:8px;background:var(--o-card);color:var(--o-tx)}
#obras .fl input[type=search]{flex:1;min-width:200px}
#obras .fl label{font-size:13px;color:var(--o-mut);display:flex;gap:4px;align-items:center}
#obras button.b{font:inherit;padding:8px 12px;border-radius:8px;border:1px solid var(--o-ln);background:var(--o-card);color:var(--o-tx);cursor:pointer}
#obras .c{background:var(--o-card);border:1px solid var(--o-ln);border-left:6px solid #98a2b3;border-radius:12px;padding:14px 16px;margin:10px 0;overflow-wrap:anywhere}
#obras .c.t0{border-left-color:#1e9e5a}#obras .c.t1{border-left-color:#e0a100}#obras .c.t2{border-left-color:#1f4e79}#obras .c.t3{border-left-color:#98a2b3}#obras .c.t4{border-left-color:#d1433a;opacity:.8}
#obras .tt{font-weight:650;font-size:16px}#obras .st{color:var(--o-mut);font-size:13px;margin-top:2px}
#obras .bd{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px;color:#fff;margin:4px 6px 0 0}
#obras .b0{background:#1e9e5a}#obras .b1{background:#e0a100}#obras .b2{background:#1f4e79}#obras .b3{background:#98a2b3}#obras .b4{background:#d1433a}
#obras .bv{background:#5b3fa8}#obras .bp{background:#b7791f}
#obras .g{display:grid;grid-template-columns:repeat(4,1fr);gap:6px 16px;margin-top:10px;font-size:13px}
#obras .g div>span:first-child,#obras .lbl{display:block;color:var(--o-mut);font-size:11px;text-transform:uppercase;letter-spacing:.03em}
@media(max-width:700px){#obras .g{grid-template-columns:repeat(2,1fr)}}
#obras .ni{color:var(--o-mut)}
#obras table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
#obras td{padding:4px 6px;border-top:1px solid var(--o-ln);vertical-align:top}
#obras .fc{font-size:10px;font-weight:700;padding:1px 6px;border-radius:99px;margin-left:6px;white-space:nowrap}
#obras .fc.confirmada{background:#dcf3e6;color:#11643a}#obras .fc.estimada{background:#fff0c7;color:#7a5600}
#obras .eq{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;background:#e8eef6;color:#1f4e79;margin:3px 4px 0 0}
#obras .fu{font-size:13px;margin-top:8px}#obras .fu a{color:#1f4e79}
#obras .nv{padding:6px 0;border-top:1px solid var(--o-ln);font-size:14px}#obras .nv:first-of-type{border-top:0}
#obras .ok{color:#1e9e5a}#obras .error{color:#d1433a}
#obras .nota{background:#fff4d6;color:#5c4400;border-radius:10px;padding:10px 14px;margin:10px 0;font-size:14px}
#obras .vacio{text-align:center;color:var(--o-mut);padding:30px}
</style>
<section id="obras">
  <div id="o-nota"></div>
  <p class="intro">Proyectos de inversión, obras futuras y compras privadas detectadas en sitios de empresas y medios especializados.
  Cada dato sale de la fuente citada; lo que la fuente no dice figura como <i>No informado</i>.
  Las fechas se marcan <span class="fc confirmada">confirmada</span> (día exacto, sin previsión) o
  <span class="fc estimada">estimada</span> (previsiones, meses, semestres o años). Los equipos DEEP son potenciales, según el tipo de obra.</p>
  <div class="kp" id="o-kp"></div>
  <div class="pn" id="o-nov"></div>
  <div class="fl">
    <input type="search" id="o-q" placeholder="Buscar: YPF, gasoducto, Neuquén, subestación, litio…">
    <select id="o-sec"></select><select id="o-prov"></select>
    <label><input type="checkbox" id="o-man"> Solo verificadas</label>
    <label><input type="checkbox" id="o-pro"> ⭐ Con empresas de mi lista</label>
    <button class="b" id="o-csv">Descargar CSV</button>
  </div>
  <div id="o-lista"></div>
  <div class="pn" id="o-fu"></div>
</section>
<script>
(function(){
const D = __DATOS__;
const T = ["Licitación abierta","Licitación anunciada / registro de proveedores","Adjudicado / en ejecución","Proyecto anunciado","Licitación cerrada"];
const CAMPOS = [["lic_productos","Licitación de productos"],["lic_obra","Licitación de obra"],["inicio_compras","Inicio de compras"],["inicio_obra","Inicio de obra"],["fin_obra","Fin de obra / puesta en marcha"],["aprobacion_rigi","Aprobación RIGI"]];
const on = new Set(T);
const $ = id => document.getElementById(id);
const e = s => (s ?? "").toString().replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ni = v => (!v || v==="No informado") ? '<span class="ni">No informado</span>' : e(v);
const sinT = s => (s||"").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"");
const main = document.querySelector("main") || document.body;
const sec = $("obras"); main.appendChild(sec);
const nav = document.createElement("nav"); nav.className = "pestanas";
nav.innerHTML = `<button data-p="lic">Licitaciones públicas</button><button data-p="obras">Obras futuras y oportunidades privadas <span class="n">${D.proyectos.length}</span></button>`;
main.parentNode.insertBefore(nav, main);
function ver(p){ document.body.classList.toggle("ver-obras", p==="obras"); nav.querySelectorAll("button").forEach(b=>b.classList.toggle("on", b.dataset.p===p));
  try{ history.replaceState(null,"", p==="obras" ? "#obras" : location.pathname); }catch(_){} }
nav.querySelectorAll("button").forEach(b=>b.onclick=()=>ver(b.dataset.p));
ver(location.hash==="#obras" || !document.getElementById("lista") ? "obras" : "lic");
if (D.nota) $("o-nota").innerHTML = `<div class="nota">${D.nota}</div>`;
function sel(id,campo,rot){ const v=[...new Set(D.proyectos.map(p=>p[campo]).filter(x=>x&&x!=="No informado"))].sort();
  $(id).innerHTML=`<option value="">${rot}: todos</option>`+v.map(x=>`<option>${e(x)}</option>`).join(""); }
sel("o-sec","sector","Sector"); sel("o-prov","provincia","Provincia");
function kp(){ $("o-kp").innerHTML = T.map((t,i)=>`<div class="k ${on.has(t)?"":"off"}" data-t="${e(t)}"><b>${D.proyectos.filter(p=>p.tipo===t).length}</b><span>${e(t)}</span></div>`).join("");
  document.querySelectorAll("#o-kp .k").forEach(k=>k.onclick=()=>{const t=k.dataset.t; on.has(t)?on.delete(t):on.add(t); pintar();}); }
function vis(){ const q=sinT($("o-q").value);
  return D.proyectos.filter(p=>on.has(p.tipo) && (!$("o-sec").value||p.sector===$("o-sec").value) && (!$("o-prov").value||p.provincia===$("o-prov").value)
   && (!$("o-man").checked||p.verificado_manual) && (!$("o-pro").checked||p.propias_n>0)
   && (!q || sinT(JSON.stringify([p.obra,p.operadora,p.epc,p.desarrolladora,p.ingenieria,p.provincia,p.localidad,p.sector,p.empresas,p.subobras,p.tipo_obra])).includes(q))); }
function fechas(p){ const f=p.fechas||{}; const con=CAMPOS.filter(([k])=>f[k]); const sin=CAMPOS.filter(([k])=>!f[k]&&k!=="aprobacion_rigi");
  return (con.length?`<table>${con.map(([k,l])=>`<tr><td style="width:42%">${l}</td><td>${e(f[k].texto)}<span class="fc ${f[k].tipo}">${f[k].tipo}</span></td></tr>`).join("")}</table>`:"")
  + (sin.length?`<div class="fu ni">Fechas no informadas por la fuente: ${sin.map(([,l])=>l).join(" · ")}</div>`:"")
  + ((p.historial_fechas||[]).length?`<div class="fu"><span class="lbl">Cambios de fecha</span>${p.historial_fechas.map(h=>`${e(h.antes)} → ${e(h.despues)} (${e(h.fecha)})`).join("<br>")}</div>`:""); }
function pintar(){ kp(); const L=vis();
  $("o-lista").innerHTML = L.length ? L.map(p=>{ const i=T.indexOf(p.tipo); return `<div class="c t${i}">
   <div class="tt">${e(p.obra)}</div>
   <div><span class="bd b${i}">${e(p.tipo)}</span>${p.verificado_manual?'<span class="bd bv">Verificado manualmente</span>':''}${p.propias_n?`<span class="bd bp">⭐ ${p.propias.length?e(p.propias.join(", ")):p.propias_n+" empresa(s) de tu lista"}</span>`:''}</div>
   <div class="st">${e(p.estado||"")}</div>
   ${(p.subobras||[]).length?`<div class="st"><b>Subobras:</b> ${e(p.subobras.join(" · "))}</div>`:""}
   <div class="g"><div><span>Operadora / titular</span>${ni(p.operadora)}</div><div><span>Desarrolladora</span>${ni(p.desarrolladora)}</div>
    <div><span>Ingeniería</span>${ni(p.ingenieria)}</div><div><span>Contratista / EPC</span>${ni(p.epc)}</div>
    <div><span>Provincia</span>${ni(p.provincia)}</div><div><span>Localidad</span>${ni(p.localidad)}</div>
    <div><span>Presupuesto</span>${ni(p.presupuesto)}</div><div><span>Sector</span>${ni(p.sector)}</div></div>
   ${fechas(p)}
   ${(p.equipos||[]).length?`<div class="fu"><span class="lbl">Equipos DEEP potenciales (según tipo de obra)</span>${p.equipos.map(x=>`<span class="eq">${e(x)}</span>`).join("")}</div>`:""}
   ${p.nota?`<div class="fu">${e(p.nota)}</div>`:""}
   <div class="fu"><span class="lbl">Fuentes</span>${(p.fuentes||[]).slice(0,6).map(f=>`<a href="${e(f.link)}" target="_blank" rel="noopener">${e(f.medio||"Fuente")}${f.titulo?": "+e(f.titulo.slice(0,110)):""} ↗</a> <span class="ni">${f.fecha_nota?"· nota "+e(f.fecha_nota):""} · verificado ${e(f.fecha_verificacion)}</span>`).join("<br>")}</div>
  </div>`}).join("") : `<div class="vacio">No hay obras con estos filtros.</div>`; }
$("o-nov").innerHTML = `<h2>Novedades: obras nuevas, licitaciones abiertas y cambios de fecha</h2>` + (D.novedades.length ? D.novedades.map(n=>
  `<div class="nv"><b>${e(n.tipo)}:</b> ${e(n.mensaje)} ${n.link?`<a href="${e(n.link)}" target="_blank" rel="noopener">abrir ↗</a>`:""} <span class="ni">· ${e((n.fecha||"").slice(0,10))}</span></div>`).join("") : `<div class="ni">Sin novedades todavía.</div>`);
$("o-fu").innerHTML = `<h2>Fuentes del módulo de obras</h2><div class="ni" style="font-size:13px">Actualizado ${e(D.generado)}</div>` + D.fuentes.map(s=>`<div class="nv"><b>${e(s.nombre)}</b> <span class="${s.estado==="ok"?"ok":"error"}">${s.estado==="ok"?"Funcionando":"Sin respuesta"}</span><br><span class="ni">${e(s.detalle)}</span></div>`).join("");
["o-q","o-sec","o-prov","o-man","o-pro"].forEach(id=>$(id).addEventListener("input",pintar));
$("o-csv").onclick=()=>{ const cols=["tipo","obra","estado","operadora","desarrolladora","ingenieria","epc","provincia","localidad","sector","presupuesto"];
  const fl=["lic_productos","lic_obra","inicio_compras","inicio_obra","fin_obra"];
  const q=v=>`"${(v??"").toString().replace(/"/g,'""')}"`;
  const rows=[cols.concat(fl,["equipos","fuente"]).join(";")].concat(vis().map(p=>cols.map(c=>q(p[c])).concat(fl.map(k=>q(p.fechas&&p.fechas[k]?p.fechas[k].texto+" ("+p.fechas[k].tipo+")":"")),[q((p.equipos||[]).join(", ")),q(p.fuentes&&p.fuentes[0]?p.fuentes[0].link:"")]).join(";")));
  const b=new Blob(["﻿"+rows.join("\n")],{type:"text/csv"}); const a=document.createElement("a"); a.href=URL.createObjectURL(b); a.download="obras_futuras.csv"; a.click(); };
pintar();
})();
</script>
"""
