"""Genera el tablero: un único archivo HTML que se abre en cualquier navegador (también en el celular)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .filtros import Filtro


def _dt(v):
    """Ignora fechas imposibles o fuera del período de seguimiento."""
    if not v:
        return None
    try:
        fecha = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if fecha.year not in (2026, 2027):
            return None
        return fecha.replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _normalizar(s):
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", s)


# Exclusiones específicas: una coincidencia en el título/organismo descarta el aviso.
EXCLUIR = (
    "aeronautic", "aeronautica", "aeronave", "avion", "helicopter", "fuerza aerea",
    "aeropuerto", "aerolinea", "automotor", "vehiculo", "automovil", "camion",
    "motociclet", "maquinaria vial", "cartucho de bateria", "bateria de recambio en ups",
    "computadora", "notebook", "pc de escritorio", "impresora", "informatica",
    "toner", "telefonia celular", "telefono movil", "materiales de construccion",
    "fiscalizacion tecnica", "servicio de fiscalizacion", "servicio de limpieza",
    "servicio de vigilancia", "articulos de oficina",
)

# Un término genérico como 'batería' o 'subestación' no basta para adjudicar
# relevancia comercial. Exigimos una descripción industrial reconocible.
INDUSTRIALES = (
    "ups industrial", "ups trifasic", "sai industrial", "energia critica",
    "rectificador", "cargador de bateria", "cargadores de bateria",
    "banco de bateria", "bancos de bateria", "bateria estacionaria",
    "baterias estacionarias", "ni-cd", "ni cd", "nicd", "plomo calcio",
    "plomo-calcio", "vrla", "inversor industrial", "inversores industriales",
    "convertidor industrial", "convertidores industriales",
    "110 vcc", "125 vcc", "220 vcc", "48 vcc",
)


def _relevante(p):
    titulo = _normalizar(" ".join(str(p.get(k) or "") for k in ("titulo", "organismo", "tipo_contratacion")))
    if any(t in titulo for t in EXCLUIR):
        return False
    detalle = _normalizar(" ".join(str(p.get(k) or "") for k in ("titulo", "terminos", "sector")))
    return any(t in detalle for t in INDUSTRIALES)


def preparar(procesos: list[dict], filtro: Filtro, ahora: datetime | None = None) -> list[dict]:
    ahora = (ahora or datetime.now()).replace(tzinfo=None)
    filas = []
    for original in procesos:
        p = dict(original)
        if not _relevante(p):
            continue
        # La fecha de PRESENTACIÓN es el plazo relevante, no la apertura de sobres.
        cierre = _dt(p.get("fecha_presentacion"))
        apertura = _dt(p.get("fecha_apertura"))
        publicacion = _dt(p.get("fecha_publicacion"))
        if not cierre or cierre <= ahora:
            continue
        if publicacion and publicacion > ahora:
            continue
        estado = _normalizar(p.get("estado"))
        if any(x in estado for x in ("adjudic", "preadjudic", "desierta", "anulad", "cancelad", "finalizad", "cerrad", "sin efecto")):
            continue
        p["semaforo"] = "amarillo" if (cierre - ahora).total_seconds() <= filtro.dias_amarillo * 86400 else "verde"
        p["dias"] = (cierre.date() - ahora.date()).days
        p["circulares"] = [h for h in p.get("historial", []) if "ircular" in _normalizar(h.get("estado"))]
        filas.append(p)
    filas.sort(key=lambda f: (0 if f["semaforo"] == "amarillo" else 1, f["dias"]))
    return filas


def _alertas_relevantes(alertas, procesos):
    """Solo noticias asociadas a procesos realmente visibles; sin falsos positivos."""
    import re
    ids = {str(p.get("numero_proceso") or "").strip().lower() for p in procesos}
    enlaces = {str(p.get("link") or "").strip() for p in procesos if p.get("link")}
    titulos = {_normalizar(p.get("titulo")) for p in procesos if p.get("titulo")}
    resultado = []
    for a in alertas:
        mensaje = _normalizar(a.get("mensaje"))
        enlace = str(a.get("link") or "").strip()
        coincide = (enlace and enlace in enlaces) or any(len(t) >= 18 and t in mensaje for t in titulos)
        if not coincide:
            coincide = any(len(i) >= 7 and re.search(r"(?<!\w)" + re.escape(i) + r"(?!\w)", mensaje) for i in ids if i)
        if coincide:
            resultado.append(a)
    return resultado[:30]


def generar(ruta: Path, procesos: list[dict], alertas: list[dict], fuentes: list[dict], filtro: Filtro,
            titulo: str = "Tablero de licitaciones", nota: str = "", ahora: datetime | None = None) -> Path:
    ahora = ahora or datetime.now()
    vigentes = preparar(procesos, filtro, ahora)
    datos = {
        "generado": ahora.strftime("%d/%m/%Y %H:%M"),
        "dias_amarillo": filtro.dias_amarillo,
        "procesos": vigentes,
        "alertas": _alertas_relevantes(alertas, vigentes),
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
<details id="control-deep" style="position:fixed;top:12px;right:12px;z-index:9999;background:var(--card);border:1px solid var(--ln);border-radius:10px;padding:7px 12px;box-shadow:0 2px 8px #0002;font-size:12px;max-width:300px">
  <summary style="cursor:pointer;font-weight:600">⚪ Control</summary>
  <div id="control-detalle" style="margin-top:10px">Verificando procesos...</div>
</details>
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
const activos = new Set(["verde","amarillo"]);
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
  document.querySelectorAll(".kpi").forEach(k=>k.onclick=()=>{const c=k.dataset.c; if(c==="verde"||c==="amarillo"){activos.has(c)?activos.delete(c):activos.add(c); pintar();}}); }
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
// CONTROL DEEP: estado real de los agentes en GitHub
(async function verificarControlDEEP() {
  const repo = "mg-consultora/deep-licitaciones-ia";
  const procesos = [
    { nombre: "Tablero Claude", archivo: "actualizar-claude.yml", maxHoras: 36 },
    { nombre: "Licitaciones (control estricto)", archivo: "actualizar-licitaciones.yml", maxHoras: 36 },
    { nombre: "Obras futuras", archivo: "obras.yml", maxHoras: 72 }
  ];

  const detalle = document.getElementById("control-detalle");
  const indicador = document.querySelector("#control-deep summary");
  let hayError = false;
  const resultados = [];

  for (const proceso of procesos) {
    const url = `https://api.github.com/repos/${repo}/actions/workflows/${proceso.archivo}/runs?per_page=1&branch=main`;

    try {
      const respuesta = await fetch(url, { cache: "no-store" });
      if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);

      const datos = await respuesta.json();
      const ejecucion = datos.workflow_runs?.[0];
      if (!ejecucion) throw new Error("Sin ejecuciones");

      const fecha = new Date(ejecucion.created_at);
      const horas = (Date.now() - fecha.getTime()) / 3600000;
      const correcto = ejecucion.status === "completed"
        && ejecucion.conclusion === "success"
        && horas <= proceso.maxHoras;

      if (!correcto) hayError = true;

      const estado = correcto ? "🟢" : "🔴";
      const fechaTexto = fecha.toLocaleString("es-AR");

      resultados.push(
        `<div style="padding:6px 0;border-bottom:1px solid var(--ln)">
          ${estado} <b>${proceso.nombre}</b><br>
          <small>Última ejecución: ${fechaTexto}</small><br>
          <a href="${ejecucion.html_url}" target="_blank" rel="noopener">Ver ejecución</a>
        </div>`
      );
    } catch (error) {
      hayError = true;
      resultados.push(
        `<div style="padding:6px 0">🔴 <b>${proceso.nombre}</b><br>
        <small>No se pudo verificar: ${error.message}</small></div>`
      );
    }
  }

  indicador.textContent = hayError ? "🔴 Control" : "🟢 Control";
  detalle.innerHTML = resultados.join("");
})();
</script>
</body>
</html>
"""
