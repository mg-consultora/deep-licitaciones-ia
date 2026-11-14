"""Genera el tablero: un único archivo HTML que se abre en cualquier navegador (también en el celular)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .filtros import Filtro


def _dt(v):
    return datetime.fromisoformat(v) if v else None


def preparar(procesos: list[dict], filtro: Filtro, ahora: datetime | None = None) -> list[dict]:
    ahora = ahora or datetime.now()
    filas = []
    for p in procesos:
        ns = SimpleNamespace(estado=p.get("estado", ""), fecha_apertura=_dt(p.get("fecha_apertura")),
                             fecha_presentacion=_dt(p.get("fecha_presentacion")))
        p = dict(p)
        p["semaforo"] = filtro.semaforo(ns, ahora)
        limite = ns.fecha_apertura or ns.fecha_presentacion
        p["dias"] = (limite.date() - ahora.date()).days if limite else None
        p["circulares"] = [h for h in p.get("historial", []) if "ircular" in (h.get("estado") or "")]
        filas.append(p)
    orden = {"amarillo": 0, "verde": 1, "gris": 2, "rojo": 3}
    filas.sort(key=lambda f: (orden[f["semaforo"]], f["dias"] if f["dias"] is not None else 9999))
    return filas


def generar(ruta: Path, procesos: list[dict], alertas: list[dict], fuentes: list[dict], filtro: Filtro,
            titulo: str = "Tablero de licitaciones", nota: str = "", ahora: datetime | None = None) -> Path:
    ahora = ahora or datetime.now()
    datos = {
        "generado": ahora.strftime("%d/%m/%Y %H:%M"),
        "dias_amarillo": filtro.dias_amarillo,
        "procesos": preparar(procesos, filtro, ahora),
        "alertas": alertas[:30],
        "fuentes": fuentes,
        "nota": nota,
    }
    html = PLANTILLA.replace("__TITULO__", titulo).replace(
        "__DATOS__", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
    ruta.write_text(html, encoding="utf-8")
    return ruta


PLANTILLA = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1d2330;--mut:#667085;--ln:#e4e7ec;--ac:#1f4e79;
--verde:#1e9e5a;--amarillo:#e0a100;--rojo:#d1433a;--gris:#98a2b3}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029;--tx:#e8eaee;--mut:#98a2b3;--ln:#2b313c;--ac:#7fb0e0}}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--tx)}
header{padding:20px 20px 8px;max-width:1200px;margin:auto}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);font-size:13px}
main{max-width:1200px;margin:auto;padding:0 20px 40px}
.nota{background:#fff4d6;color:#5c4400;border-radius:10px;padding:10px 14px;margin:10px 0;font-size:14px}
@media (prefers-color-scheme:dark){.nota{background:#3a3010;color:#f3dc9a}}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}
.kpi{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:12px 14px;cursor:pointer;user-select:none}
.kpi.off{opacity:.4}.kpi b{font-size:26px;display:block}.kpi span{font-size:13px;color:var(--mut)}
.kpi i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
@media(max-width:640px){.kpis{grid-template-columns:repeat(2,1fr)}}
.panel{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:12px 16px;margin:12px 0}
.panel h2{font-size:15px;margin:0 0 8px}
.alerta{padding:7px 0;border-top:1px solid var(--ln);font-size:14px}.alerta:first-of-type{border-top:0}
.tag{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px;background:#e8eef6;color:var(--ac);margin-right:6px}
@media (prefers-color-scheme:dark){.tag{background:#22344a}}
.filtros{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.filtros input,.filtros select{font:inherit;padding:8px 10px;border:1px solid var(--ln);border-radius:8px;background:var(--card);color:var(--tx)}
.filtros input{flex:1;min-width:200px}
button{font:inherit;padding:8px 12px;border-radius:8px;border:1px solid var(--ln);background:var(--card);color:var(--tx);cursor:pointer}
.item{background:var(--card);border:1px solid var(--ln);border-left:6px solid var(--gris);border-radius:12px;padding:14px 16px;margin:10px 0}
.item.verde{border-left-color:var(--verde)}.item.amarillo{border-left-color:var(--amarillo)}.item.rojo{border-left-color:var(--rojo);opacity:.75}
.top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.tit{font-weight:650;font-size:16px}.org{color:var(--mut);font-size:13px;margin-top:2px}
.dias{white-space:nowrap;font-weight:700;font-size:14px;padding:3px 10px;border-radius:99px;color:#fff;background:var(--gris)}
.verde .dias{background:var(--verde)}.amarillo .dias{background:var(--amarillo)}.rojo .dias{background:var(--rojo)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px 16px;margin-top:10px;font-size:13px}
.grid div span{display:block;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.03em}
@media(max-width:640px){.grid{grid-template-columns:repeat(2,1fr)}}
.pie{margin-top:10px;font-size:13px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
a{color:var(--ac)}.mut{color:var(--mut)}
.fuente{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-top:1px solid var(--ln);font-size:14px}
.fuente:first-of-type{border-top:0}.fuente>div:first-child{min-width:0;overflow-wrap:anywhere}
.item,.alerta,.tit{overflow-wrap:anywhere}.top>div:first-child{min-width:0}
.est{font-size:12px;font-weight:600;white-space:nowrap}.ok{color:var(--verde)}.error{color:var(--rojo)}.pendiente_credenciales{color:var(--amarillo)}.desactivada{color:var(--gris)}
.vacio{text-align:center;color:var(--mut);padding:30px}
</style>
</head>
<body>
<header><h1>__TITULO__</h1><div class="sub" id="sub"></div></header>
<main>
<div id="nota"></div>
<div class="kpis" id="kpis"></div>
<div class="panel" id="alertas"></div>
<div class="filtros">
  <input id="q" placeholder="Buscar: rectificador, YPF, Neuquén, 110 Vcc…">
  <select id="sector"></select><select id="prov"></select><select id="fuente"></select>
  <button id="csv">Descargar CSV</button>
</div>
<div id="lista"></div>
<div class="panel" id="fuentes"></div>
</main>
<script>
const D = __DATOS__;
const COL = {verde:"En plazo",amarillo:"Vence pronto",rojo:"Vencida",gris:"Sin fecha (verificar)"};
const activos = new Set(["verde","amarillo","gris"]);
const $ = id => document.getElementById(id);
const esc = s => (s ?? "").toString().replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const f = v => { if(!v) return "—"; const d=new Date(v); const t=d.toLocaleDateString("es-AR",{day:"2-digit",month:"2-digit",year:"numeric"});
  return (d.getHours()||d.getMinutes()) ? t+" "+d.toLocaleTimeString("es-AR",{hour:"2-digit",minute:"2-digit"}) : t; };
$("sub").textContent = `Actualizado ${D.generado} · amarillo = vence en menos de ${D.dias_amarillo} días`;
if (D.nota) $("nota").innerHTML = `<div class="nota">${D.nota}</div>`;
function opciones(id, campo, rot){ const vals=[...new Set(D.procesos.map(p=>p[campo]).filter(Boolean))].sort();
  $(id).innerHTML = `<option value="">${rot}: todos</option>` + vals.map(v=>`<option>${esc(v)}</option>`).join(""); }
opciones("sector","sector","Sector"); opciones("prov","provincia","Provincia"); opciones("fuente","fuente","Fuente");
function kpis(){ $("kpis").innerHTML = ["verde","amarillo","rojo","gris"].map(c=>{
  const n=D.procesos.filter(p=>p.semaforo===c).length;
  return `<div class="kpi ${activos.has(c)?"":"off"}" data-c="${c}"><b>${n}</b><span><i style="background:var(--${c})"></i>${COL[c]}</span></div>`}).join("");
  document.querySelectorAll(".kpi").forEach(k=>k.onclick=()=>{const c=k.dataset.c; activos.has(c)?activos.delete(c):activos.add(c); pintar();}); }
function visibles(){ const q=$("q").value.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"");
  return D.procesos.filter(p=>activos.has(p.semaforo) && (!$("sector").value||p.sector===$("sector").value)
    && (!$("prov").value||p.provincia===$("prov").value) && (!$("fuente").value||p.fuente===$("fuente").value)
    && (!q || JSON.stringify([p.titulo,p.organismo,p.numero_proceso,p.provincia,p.sector,p.terminos]).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"").includes(q))); }
function diasTxt(p){ if(p.dias===null) return "Verificar"; if(p.dias<0) return "Vencida"; if(p.dias===0) return "Hoy"; return p.dias===1?"Mañana":`${p.dias} días`; }
function pintar(){ kpis(); const L=visibles();
  $("lista").innerHTML = L.length ? L.map(p=>`<div class="item ${p.semaforo}">
   <div class="top"><div><div class="tit">${esc(p.titulo)}</div>
   <div class="org">${esc(p.organismo)}${p.numero_proceso?" · "+esc(p.numero_proceso):""}</div></div>
   <div class="dias">${diasTxt(p)}</div></div>
   <div class="grid">
    <div><span>Apertura de sobres</span><b>${f(p.fecha_apertura)}</b></div>
    <div><span>Presentación</span>${f(p.fecha_presentacion)}</div>
    <div><span>Límite consultas</span>${f(p.fecha_limite_consultas)}</div>
    <div><span>Publicación</span>${f(p.fecha_publicacion)}</div>
    <div><span>Provincia</span>${esc(p.provincia)}</div><div><span>Sector</span>${esc(p.sector)}</div>
    <div><span>Tipo</span>${esc(p.tipo_contratacion)||"—"}</div><div><span>Estado</span>${esc(p.estado)}</div>
   </div>
   <div class="pie">${p.link?`<a href="${esc(p.link)}" target="_blank" rel="noopener">Ver aviso ↗</a>`:""}
    ${p.circulares.map((c,i)=>`<a href="${esc(c.link)}" target="_blank" rel="noopener">Circular ${i+1} (${f(c.fecha)}) ↗</a>`).join("")}
    <span class="mut">${esc(p.fuente)}</span>
    ${(p.terminos||[]).slice(0,5).map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>
  </div>`).join("") : `<div class="vacio">No hay oportunidades con estos filtros.</div>`; }
$("alertas").innerHTML = `<h2>Novedades: circulares y cambios de fecha</h2>` + (D.alertas.length ? D.alertas.map(a=>
  `<div class="alerta"><span class="tag">${esc(a.tipo)}</span>${esc(a.mensaje)} ${a.link?`<a href="${esc(a.link)}" target="_blank" rel="noopener">abrir ↗</a>`:""} <span class="mut">· ${f(a.fecha)}</span></div>`).join("")
  : `<div class="mut">Sin novedades desde la última revisión.</div>`);
const EST={ok:"Funcionando",error:"Con error",pendiente_credenciales:"Pendiente de usuario y clave",desactivada:"Desactivada"};
$("fuentes").innerHTML = `<h2>Fuentes</h2>` + D.fuentes.map(s=>`<div class="fuente"><div><b>${esc(s.nombre)}</b><br><span class="mut">${esc(s.detalle)}</span></div>
  <div class="est ${s.estado}">${EST[s.estado]||s.estado}</div></div>`).join("");
["q","sector","prov","fuente"].forEach(id=>$(id).addEventListener("input",pintar));
$("csv").onclick=()=>{ const cols=["semaforo","titulo","organismo","numero_proceso","tipo_contratacion","estado","provincia","sector","fecha_publicacion","fecha_limite_consultas","fecha_presentacion","fecha_apertura","link","fuente"];
  const rows=[cols.join(";")].concat(visibles().map(p=>cols.map(c=>`"${(p[c]??"").toString().replace(/"/g,'""')}"`).join(";")));
  const b=new Blob(["﻿"+rows.join("\n")],{type:"text/csv"}); const a=document.createElement("a"); a.href=URL.createObjectURL(b); a.download="licitaciones.csv"; a.click(); };
pintar();
</script>
</body>
</html>
"""
