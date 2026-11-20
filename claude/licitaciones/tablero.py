# DEEP S.A. — tablero con puntuación comercial P1/P2/P3.
# ÚNICO ARCHIVO A REEMPLAZAR: claude/licitaciones/tablero.py
# No altera SQLite, fuentes, workflows, obras.py ni la pestaña de 67 obras.
"""Genera HTML de licitaciones vigentes y potenciales por verificar."""
from __future__ import annotations
import json
import re
import unicodedata
from datetime import datetime
from collections import Counter
from html import escape as html_escape
from pathlib import Path
from .filtros import Filtro

# Términos y puntuación: la coincidencia genérica nunca equivale a convocatoria abierta.
P1 = ("ups industrial", "ups trifasica", "sai industrial", "sistema de alimentacion ininterrumpida", "fuente de alimentacion ininterrumpida", "alimentacion ininterrumpida", "rectificador", "cargador de baterias", "cargador rectificador", "banco de baterias", "baterias estacionarias", "baterias industriales", "inversor industrial", "convertidor cc/cc", "convertidor cc/ca", "sistema de corriente continua", "tablero de corriente continua", "sistema de energia segura", "alimentacion de emergencia")
P2 = ("estacion transformadora", "subestacion electrica", "subestacion", "servicios auxiliares", "ssaa", "proteccion y control", "automatizacion de subestaciones", "central hidroelectrica", "central termoelectrica", "parque solar", "fotovoltaico", "parque eolico", "almacenamiento energetico", "bess", "infraestructura electrica industrial", "distribucion de energia", "transmision electrica")
P3 = ("planta industrial", "ampliacion de capacidad", "modernizacion electrica", "repotenciacion", "renovacion de equipamiento", "mantenimiento de sistemas electricos", "automatizacion industrial", "infraestructura minera", "proyecto minero", "planta de tratamiento", "gasoducto", "oleoducto", "estacion de bombeo", "estacion compresora", "refineria", "planta petroquimica")
SECTORES = ("energia", "mineria", "petroleo", "oil & gas", "petroquimica", "siderurgia", "ferrocarril", "transmision electrica", "distribucion electrica")
TECNICAS = ("24 vcc", "48 vcc", "110 vcc", "125 vcc", "220 vcc", "220 vca", "230 vca", "380 vca", "400 vca", "vrla", "agm", "gel", "pb-ca", "ni-cd", "ni cd", "plomo-acido", "niquel-cadmio", "doble conversion", "redundancia n+1", "cargador dual", "trifasico", "unifilar", "pdtg", "fat", "sat", "retrofit")
SUMINISTRO = ("suministro", "adquisicion", "provision", "instalacion", "puesta en marcha", "mantenimiento", "reparacion", "reemplazo", "renovacion")
EXCLUSION = ("uso aeronautico", "aeronautica", "aeronave", "aviones", "helicoptero", "fuerza aerea", "bateria automotriz", "baterias automotrices", "bateria de motocicleta", "arranque vehicular", "baterias para vehiculos", "baterias para camiones", "power bank", "cargador de celular", "pila domestica", "pilas domesticas", "toner", "mobiliario de oficina", "cartuchos de bateria de recambio", "fiscalizacion tecnica", "servicio de fiscalizacion", "inspeccion de obra", "supervision de obra")
EXCLUSION_INFORMATICA = ("ups para pc", "ups para computadora", "ups informatica", "ups de uso informatico", "ups uso informatico", "ups informatico", "ups de escritorio", "ups para servidores", "ups para rack informatico", "ups para data center", "ups para centro de computos", "sai informatico", "sai para pc", "notebooks", "computadoras personales", "perifericos", "impresoras")
CERRADOS = ("adjudic", "preadjudic", "desiert", "anulad", "cancelad", "finalizad", "cerrad", "sin efecto", "revocad")

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)

def contiene(t, term):
    # Límites de palabra: evita coincidencias parciales absurdas.
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", t) is not None

def coincide(t, terminos):
    return any(contiene(t, x) for x in terminos)

def fecha(v):
    if not v: return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.replace(tzinfo=None) if datetime.now().year - 1 <= d.year <= datetime.now().year + 2 else None
    except (ValueError, TypeError, OverflowError):
        return None

# Catálogo DEEP R4: solo productos y servicios concretos de electrónica de potencia.
# Las obras, industrias y ubicaciones NO son criterios de admisión.
PRODUCTOS_EXACTOS = (
    "ups industrial", "ups de grado industrial", "ups trifasica",
    "sai industrial", "sistema de alimentacion ininterrumpida industrial",
    "rectificador", "rectificadores", "cargador rectificador",
    "cargador de baterias", "cargadores de baterias",
    "banco de baterias", "bancos de baterias",
    "bateria estacionaria", "baterias estacionarias",
    "bateria industrial", "baterias industriales",
    "celda plomo acido", "celdas plomo acido",
    "celda niquel cadmio", "celdas niquel cadmio",
    "inversor industrial", "inversor de tension", "inversores de tension",
    "convertidor dc/dc", "convertidores dc/dc", "convertidor cc/cc",
    "convertidores cc/cc", "convertidor dc/ac", "convertidores dc/ac",
    "convertidor cc/ca", "convertidor de frecuencia",
    "convertidores de frecuencia", "llave estatica", "llaves estaticas",
    "tablero de distribucion de cc", "tableros de distribucion de cc",
    "tablero de distribucion de ca", "tableros de distribucion de ca",
    "rectificador de traccion", "inversor traccionario",
    "convertidor ferroviario", "cargador ferroviario",
    "revamping de rectificadores", "revamping de ups",
    "revamping de inversores", "revamping de convertidores",
    "tiristores", "fusibles ur", "fusibles ultrarrapidos",
    "igbt", "columna de potencia", "columnas de potencia",
    "diodos de potencia", "capacitores de potencia",
)
# Términos genéricos que solo se admiten con evidencia industrial explícita.
PRODUCTOS_CON_CONTEXTO = (
    "ups", "sai", "inversor", "inversores", "convertidor", "convertidores",
    "cargador", "cargadores", "baterias", "bateria",
    "monoblock", "monoblocks", "tablero", "tableros",
    "capacitores", "diodos", "fusibles", "microswitch",
)
CONTEXTO_INDUSTRIAL = (
    "industrial", "estacionaria", "estacionarias", "trifasico",
    "trifasica", "110 vcc", "125 vcc", "220 vcc",
    "48 vcc", "ni-cd", "ni cd", "niquel cadmio",
    "plomo acido", "plomo-acido", "vrla", "agm",
    "electroobtencion", "galvanoplastia", "anodizado",
    "traccion ferroviaria", "material rodante", "electroquimico",
    "electronica de potencia", "corriente continua industrial",
)
EXCLUSIONES_CATALOGO = (
    "cable", "cables", "terminal", "terminales", "termocontraible",
    "termocontraibles", "conductor electrico", "conductores electricos",
    "bateria para movil", "baterias para moviles", "baterias para vehiculos",
    "baterias para motocicletas", "bateria para motocicleta",
    "bateria automotriz", "baterias automotrices",
    "bateria de celular", "baterias de celular",
    "bateria para notebook", "baterias para notebook",
    "bateria para pc", "baterias para pc", "bateria de litio para herramientas",
    "pilas", "pila", "power bank", "baterias para radio",
    "baterias para equipos portatiles", "baterias para alarmas",
    "baterias para juguetes", "bateria para ups informatica",
    "baterias para ups informaticas", "bateria de respaldo para pc",
    "cubiertas", "camara para motovehiculos", "camara para motocicletas",
    "articulos de limpieza", "mobiliario", "toner",
)
def evaluar(p):
    # Solo datos del objeto contractual; organismo/sector/tags no prueban producto.
    # Evaluar el alcance completo del aviso, no únicamente el título.
    # Si menciona un equipo industrial en una obra grande, también cuenta.
    texto = norm(" ".join(str(p.get(k) or "") for k in (
        "titulo", "objeto", "descripcion", "especificaciones", "texto")))
    # El Boletín conserva el texto completo en el registro original, pero
    # SQLite guarda solo el título: no inferir productos desde el organismo.
    # Los términos de sector y ubicación nunca bastan como evidencia.
    # Normalizar grafías para reconocer Plomo-Ácido y DC/DC sin aceptar
    # coincidencias parciales en palabras ajenas.
    canon = texto.replace("-", " ")
    canon = re.sub(r"\s*/\s*", "/", canon)
    # Rechazo absoluto de UPS informáticas aunque el aviso mencione bancos de baterías.
    if coincide(norm(" ".join(str(p.get(k) or "") for k in ("titulo", "objeto"))), EXCLUSION_INFORMATICA):
        return 0, "UPS/equipamiento informático fuera del catálogo DEEP"
    exclusion = coincide(texto, EXCLUSION)
    exclusion = exclusion or coincide(texto, EXCLUSIONES_CATALOGO)
    # En avisos mixtos, una exclusión no debe ocultar un equipo DEEP
    # explícitamente identificado (p.ej. UPS industrial con cables incluidos).
    exactos = [t for t in PRODUCTOS_EXACTOS if contiene(texto, t) or contiene(canon, t)]
    genericos = [t for t in PRODUCTOS_CON_CONTEXTO if contiene(texto, t)]
    # El contexto industrial debe estar junto al producto, no en la dirección
    # del organismo ni en otra sección remota del aviso.
    ventanas = []
    for termino in PRODUCTOS_CON_CONTEXTO:
        for match in re.finditer(r"(?<![a-z0-9])" + re.escape(termino) + r"(?![a-z0-9])", canon):
            ventanas.append(canon[max(0, match.start()-200):match.end()+200])
    industrial = any(coincide(ventana, CONTEXTO_INDUSTRIAL) for ventana in ventanas)
    # Excluir baterías vehiculares y UPS de oficina aunque se mencione
    # accidentalmente un parque industrial o subestación en el mismo aviso.
    objeto = norm(" ".join(str(p.get(k) or "") for k in ("titulo", "objeto")))
    exclusiones_duras = (
        "bateria automotor", "baterias automotor", "bateria automotriz",
        "baterias automotrices", "bateria para camioneta",
        "baterias para camionetas", "bateria para camion",
        "baterias para camiones", "baterias para vehiculos",
        "baterias para motocicletas", "ups para computadoras",
        "ups para equipos informaticos", "ups para computadoras de oficina",
    )
    if coincide(objeto, exclusiones_duras) and not any(
        contiene(objeto, t) for t in PRODUCTOS_EXACTOS
    ):
        return 0, "Equipamiento automotor o informático fuera del catálogo DEEP"
    # "Baterías" a secas o "UPS" sin grado industrial nunca son suficientes.
    valido = bool(exactos) or (bool(genericos) and industrial)
    if not valido:
        return 0, "Sin producto DEEP explícito"
    if exclusion and not exactos:
        return 0, "Excluida por catálogo"
    # Componentes genéricos requieren especificación de potencia.
    if not exactos and genericos and not industrial:
        return 0, "Sin especificación industrial"
    puntos = min(100, (75 if exactos else 45) +
                 (15 if industrial else 0) +
                 (10 if coincide(texto, SUMINISTRO) else 0))
    return puntos, ("Alta" if puntos >= 75 else "Media")

def ficha_comercial(p):
    """Evidencia comercial derivada del texto del aviso, sin inventar datos."""
    texto = norm(" ".join(str(p.get(k) or "") for k in
                     ("titulo", "objeto", "descripcion", "especificaciones", "texto")))
    canon = texto.replace("-", " ")
    productos = list(dict.fromkeys(
        x for x in PRODUCTOS_EXACTOS if contiene(texto, x) or contiene(canon, x)
    ))
    if not productos:
        productos = list(dict.fromkeys(
            x for x in PRODUCTOS_CON_CONTEXTO if contiene(texto, x)
        ))
    fragmento = ""
    for termino in productos[:1]:
        pos = canon.find(termino)
        if pos >= 0:
            fragmento = texto[max(0, pos - 90):pos + len(termino) + 110].strip()
    return {
        "cliente": p.get("organismo") or "No informado",
        "provincia": p.get("provincia") or "No informada",
        "productos_detectados": productos[:8],
        "evidencia": fragmento or "No hay fragmento técnico verificable",
        "motivo": ("Producto industrial mencionado en el aviso" if productos
                   else "Requiere revisión técnica"),
        "fecha_limite": p.get("fecha_presentacion") or "",
        "enlace_oficial": p.get("link") or "",
        "vigencia": ("Plazo de presentación informado" if p.get("fecha_presentacion")
                    else "Plazo de presentación sin confirmar"),
    }


def _clasificar(procesos, filtro, ahora):
    ahora = (ahora or datetime.now()).replace(tzinfo=None)
    salida, motivos = {}, Counter()
    ejemplos = {}
    for original in procesos:
        p = dict(original)
        puntos, prioridad = evaluar(p)
        if not puntos:
            motivos["sin_evidencia_o_excluido"] += 1
            if len(ejemplos) < 8:
                ejemplos[str(p.get("titulo") or "Sin título")[:95]] = prioridad
            continue
        estado = norm(p.get("estado"))
        if any(x in estado for x in CERRADOS):
            motivos["cerrado_o_adjudicado"] += 1
            continue
        raw_pub = p.get("fecha_publicacion")
        raw_cierre = p.get("fecha_presentacion")
        raw_apertura = p.get("fecha_apertura")
        publicacion = fecha(raw_pub)
        cierre = fecha(raw_cierre)
        apertura = fecha(raw_apertura)
        # Una fecha explícita de presentación inválida no puede acreditarse
        # como cierre vigente, ni convertirse en convocatoria abierta.
        if raw_cierre and cierre is None:
            motivos["cierre_invalido"] += 1
            continue
        if cierre and cierre <= ahora:
            motivos["vencido"] += 1
            continue
        if publicacion and publicacion > ahora:
            motivos["publicacion_futura"] += 1
            continue
        if cierre:
            semaforo = "amarillo" if (cierre - ahora).total_seconds() <= filtro.dias_amarillo * 86400 else "verde"
            dias = max(0, (cierre.date() - ahora.date()).days)
        else:
            # No declarar abierta una convocatoria sin cierre oficial.
            # Tampoco mostrar una apertura pasada como potencial vigente.
            if apertura and apertura <= ahora:
                motivos["apertura_pasada_sin_cierre"] += 1
                continue
            if not (publicacion or apertura):
                motivos["sin_evidencia_temporal"] += 1
                continue
            # Fecha antigua explícita: no inferir una convocatoria nueva.
            if raw_pub and not publicacion and not apertura:
                motivos["publicacion_fuera_periodo"] += 1
                continue
            semaforo, dias = "gris", None
        p.update(semaforo=semaforo, dias=dias, puntaje=puntos, prioridad=prioridad)
        p["ficha_comercial"] = ficha_comercial(p)
        p["circulares"] = [h for h in p.get("historial", []) if "circular" in norm(h.get("estado"))]
        clave = (norm(p.get("organismo")), norm(p.get("numero_proceso")) or norm(p.get("titulo")))
        anterior = salida.get(clave)
        if anterior is None or (bool(cierre), puntos) > (anterior["semaforo"] != "gris", anterior["puntaje"]):
            salida[clave] = p
        motivos["admitido_" + semaforo] += 1
    orden = {"amarillo": 0, "verde": 1, "gris": 2}
    filas = sorted(salida.values(), key=lambda p: (orden[p["semaforo"]], -p["puntaje"], p["dias"] if p["dias"] is not None else 9999))
    motivos["ejemplos"] = ejemplos
    return filas, motivos


def preparar(procesos: list[dict], filtro: Filtro, ahora: datetime | None = None) -> list[dict]:
    return _clasificar(procesos, filtro, ahora)[0]

def filtrar_alertas(alertas, procesos):
    # Vincular solo a avisos realmente seleccionados; evitar noticias aeronáuticas.
    validos = [p for p in procesos if p["semaforo"] in ("verde", "amarillo", "gris")]
    links = {str(p.get("link") or "").strip() for p in validos if p.get("link")}
    titulos = {norm(p.get("titulo")) for p in validos if len(norm(p.get("titulo"))) >= 18}
    numeros = {norm(p.get("numero_proceso")) for p in validos if len(norm(p.get("numero_proceso"))) >= 7}
    resultado = []
    for a in alertas:
        m = norm(" ".join(str(a.get(k) or "") for k in ("mensaje", "titulo", "organismo")))
        if coincide(m, EXCLUSION) or coincide(m, EXCLUSION_INFORMATICA): continue
        link = str(a.get("link") or "").strip()
        if (link and link in links) or any(t in m for t in titulos) or any(contiene(m, n) for n in numeros):
            resultado.append(a)
    return resultado[:30]

def generar(ruta: Path, procesos: list[dict], alertas: list[dict], fuentes: list[dict], filtro: Filtro,
            titulo: str = "Tablero de licitaciones", nota: str = "", ahora: datetime | None = None) -> Path:
    ahora = ahora or datetime.now()
    filas, motivos = _clasificar(procesos, filtro, ahora)
    # Diagnóstico estructurado y visible en una sección independiente.
    # No mezclarlo con nota: otras integraciones pueden reescribir ese campo.
    diagnostico = {
        "recibidos": len(procesos),
        "visibles": len(filas),
        "sin_evidencia": motivos["sin_evidencia_o_excluido"],
        "cerrados": motivos["cerrado_o_adjudicado"],
        "vencidos": motivos["vencido"],
        "cierre_invalido": motivos["cierre_invalido"],
        "apertura_pasada": motivos["apertura_pasada_sin_cierre"],
        "sin_fecha": motivos["sin_evidencia_temporal"],
        "publicacion_fuera_periodo": motivos["publicacion_fuera_periodo"],
        "ejemplos": motivos["ejemplos"],
    }
    print("DIAGNOSTICO TABLERO DEEP: " + json.dumps(diagnostico, ensure_ascii=False))
    datos = {"generado": ahora.strftime("%d/%m/%Y %H:%M"), "dias_amarillo": filtro.dias_amarillo,
             "procesos": filas, "alertas": filtrar_alertas(alertas, filas), "fuentes": fuentes, "nota": nota, "diagnostico": diagnostico}
    html = PLANTILLA.replace("__TITULO__", titulo).replace("__DATOS__", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
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
<div id="nota"></div><div class="panel" id="diagnostico-deep"><b>Control de clasificación</b><p>Esperando diagnóstico de la ejecución…</p></div><div class="panel"><b>Dos circuitos:</b> verde/amarillo = convocatoria vigente con cierre de ofertas confirmado; gris = oportunidad relevante pendiente de verificar. Las vencidas quedan fuera del listado activo. Las obras privadas mantienen su pestaña independiente.</div>
<div class="kpis" id="kpis"></div>
<div class="panel" id="alertas"></div>
<div class="filtros">
  <input id="q" placeholder="Buscar: rectificador, YPF, Neuquén, 110 Vcc…">
  <select id="sector"></select><select id="prov"></select><select id="fuente"></select>
  <button id="buscar-deep" type="button" style="background:#1f4e79;color:white;font-weight:650">🔎 Buscar</button>
  <button id="csv">Descargar CSV</button>
</div>
<div id="lista"></div>
<div class="panel" id="resultados-potenciales" aria-live="polite"></div>
<div class="panel" id="fuentes"></div>
</main>
<script>
const D = __DATOS__;
// Los registros ya fueron clasificados en Python. No descartar oportunidades
// potenciales por ausencia de cierre: se presentan en gris, NO como abiertas.
const COL = {verde:"En plazo",amarillo:"Vence pronto",rojo:"Vencida",gris:"Potencial / verificar"};
const activos = new Set(["verde","amarillo","gris"]);
const $ = id => document.getElementById(id);
const esc = s => (s ?? "").toString().replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const f = v => { if(!v) return "—"; const d=new Date(v); const t=d.toLocaleDateString("es-AR",{day:"2-digit",month:"2-digit",year:"numeric"});
  return (d.getHours()||d.getMinutes()) ? t+" "+d.toLocaleTimeString("es-AR",{hour:"2-digit",minute:"2-digit"}) : t; };
$("sub").textContent = `Actualizado ${D.generado} · amarillo = vence en menos de ${D.dias_amarillo} días`;
if (D.nota) $("nota").innerHTML = `<div class="nota">${D.nota}</div>`;
const diag=D.diagnostico||{};
const n=(k)=>Number(diag[k]||0);
$("diagnostico-deep").innerHTML=`<b>Control de clasificación DEEP</b>
 <p><b>${n("recibidos")}</b> registros recibidos; <b>${n("visibles")}</b> oportunidades visibles;
 <b>${n("sin_evidencia")}</b> sin evidencia industrial suficiente;
 <b>${n("vencidos")}</b> vencidos; <b>${n("cerrados")}</b> cerrados/adjudicados;
 <b>${n("apertura_pasada")}</b> con apertura pasada sin cierre confirmado;
 <b>${n("sin_fecha")}</b> sin fecha verificable.</p>
 <small>La lectura de fuentes no equivale a encontrar convocatorias abiertas. Los avisos sin evidencia suficiente no se publican como oportunidades vigentes.</small>`;

const catalogos={sector:["Energía eléctrica","Minería","Oil & Gas","Industria","Telecom y datos","Transporte","Salud","Gobierno y educación"],prov:["Buenos Aires","CABA","Catamarca","Chubut","Córdoba","Corrientes","Entre Ríos","Jujuy","La Pampa","La Rioja","Mendoza","Misiones","Neuquén","Río Negro","Salta","San Juan","San Luis","Santa Cruz","Santa Fe","Santiago del Estero","Tierra del Fuego","Tucumán","Chaco","Formosa"]};
function opciones(id, campo, rot){ const vals=[...new Set([...(catalogos[id]||[]),...D.procesos.map(p=>p[campo]).filter(Boolean)])].sort((a,b)=>a.localeCompare(b,"es"));
  $(id).innerHTML = `<option value="">${rot}: todos</option>` + vals.map(v=>`<option value="${esc(v)}">${esc(v)} (${D.procesos.filter(p=>p[campo]===v).length})</option>`).join(""); }
opciones("sector","sector","Sector"); opciones("prov","provincia","Provincia"); opciones("fuente","fuente","Fuente");
function kpis(){ $("kpis").innerHTML = ["verde","amarillo","rojo","gris"].map(c=>{
  const n=D.procesos.filter(p=>p.semaforo===c).length;
  return `<div class="kpi ${activos.has(c)?"":"off"}" data-c="${c}"><b>${n}</b><span><i style="background:var(--${c})"></i>${COL[c]}</span></div>`}).join("");
  document.querySelectorAll(".kpi").forEach(k=>k.onclick=()=>{const c=k.dataset.c; if(c!=="rojo"){activos.has(c)?activos.delete(c):activos.add(c); pintar();}}); }
function visibles(){ const q=$("q").value.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"");
  return D.procesos.filter(p=>activos.has(p.semaforo) && (!$("sector").value||p.sector===$("sector").value)
    && (!$("prov").value||p.provincia===$("prov").value) && (!$("fuente").value||p.fuente===$("fuente").value)
    && (!q || JSON.stringify([p.titulo,p.organismo,p.numero_proceso,p.provincia,p.sector,p.terminos]).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"").includes(q))); }
function diasTxt(p){ if(p.dias===null) return "Por verificar"; if(p.dias<0) return "Vencida"; if(p.dias===0) return "Hoy"; return p.dias===1?"Mañana":`${p.dias} días`; }
function pintar(){ kpis(); const L=visibles();
  $("lista").innerHTML = L.length ? L.map(p=>`<div class="item ${p.semaforo}">
   <div class="top"><div><div class="tit">${esc(p.titulo)}</div>
   <div class="org">${esc(p.organismo)} · ${esc(p.prioridad||"Potencial")} (${Number(p.puntaje||0)} puntos)${p.numero_proceso?" · "+esc(p.numero_proceso):""}</div></div>
   <div class="dias">${diasTxt(p)}</div></div>
   <div class="grid">
    <div><span>Apertura de sobres</span><b>${f(p.fecha_apertura)}</b></div>
    <div><span>Presentación</span>${f(p.fecha_presentacion)}</div>
    <div><span>Límite consultas</span>${f(p.fecha_limite_consultas)}</div>
    <div><span>Publicación</span>${f(p.fecha_publicacion)}</div>
    <div><span>Provincia</span>${esc(p.provincia)}</div><div><span>Sector</span>${esc(p.sector)}</div>
    <div><span>Tipo</span>${esc(p.tipo_contratacion)||"—"}</div><div><span>Estado</span>${esc(p.estado)}</div>
   </div>
   <details style="margin-top:12px;padding:9px;border:1px solid var(--ln);border-radius:8px">
    <summary><b>Ficha comercial DEEP</b></summary>
    <div class="grid">
      <div><span>Cliente</span>${esc(p.ficha_comercial?.cliente||"No informado")}</div>
      <div><span>Provincia</span>${esc(p.ficha_comercial?.provincia||"No informada")}</div>
      <div><span>Producto detectado</span>${esc((p.ficha_comercial?.productos_detectados||[]).join(", ")||"Por revisar")}</div>
      <div><span>Vigencia</span>${esc(p.ficha_comercial?.vigencia||"Sin confirmar")}</div>
    </div>
    <p><b>Motivo:</b> ${esc(p.ficha_comercial?.motivo||"Sin clasificar")}</p>
    <p><b>Evidencia textual:</b> ${esc(p.ficha_comercial?.evidencia||"No disponible")}</p>
    <p><b>Presentación:</b> ${f(p.ficha_comercial?.fecha_limite)} · ${p.link?`<a href="${esc(p.link)}" target="_blank" rel="noopener">Consultar fuente</a>`:"Sin enlace"}</p>
   </details>
   <div class="pie">${p.link?`<a href="${esc(p.link)}" target="_blank" rel="noopener">Ver aviso ↗</a>`:""}
    ${p.circulares.map((c,i)=>`<a href="${esc(c.link)}" target="_blank" rel="noopener">Circular ${i+1} (${f(c.fecha)}) ↗</a>`).join("")}
    <span class="mut">${esc(p.fuente)}</span>
    ${(p.terminos||[]).slice(0,5).map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>
  </div>`).join("") : `<div class="vacio">${D.procesos.length===0?"No hay licitaciones DEEP verificadas para mostrar. Los filtros están disponibles, pero esta actualización no contiene oportunidades. Revisá las fuentes y el seguimiento de procesos más abajo.":"Ninguna oportunidad coincide con los filtros seleccionados. Elegí Todos para ampliar la búsqueda."}</div>`; }
$("alertas").innerHTML = `<h2>Novedades: circulares y cambios de fecha</h2>` + (D.alertas.length ? D.alertas.map(a=>
  `<div class="alerta"><span class="tag">${esc(a.tipo)}</span>${esc(a.mensaje)} ${a.link?`<a href="${esc(a.link)}" target="_blank" rel="noopener">abrir ↗</a>`:""} <span class="mut">· ${f(a.fecha)}</span></div>`).join("")
  : `<div class="mut">Sin novedades desde la última revisión.</div>`);
const EST={ok:"Funcionando",error:"Con error",pendiente_credenciales:"Pendiente de usuario y clave",desactivada:"Desactivada"};
const fuentesConError=(D.fuentes||[]).filter(s=>s.estado!=="ok" && s.estado!=="desactivada");
if(fuentesConError.length){
  const aviso=document.createElement("div"); aviso.className="nota";
  aviso.textContent="Atención: "+fuentesConError.length+" fuente(s) sin verificación satisfactoria en esta actualización. El tablero puede estar incompleto; controlá los portales oficiales.";
  $("nota").appendChild(aviso);
}
$("fuentes").innerHTML = `<h2>Fuentes</h2>` + D.fuentes.map(s=>`<div class="fuente"><div><b>${esc(s.nombre)}</b><br><span class="mut">${esc(s.detalle)}</span></div>
  <div class="est ${s.estado}">${EST[s.estado]||s.estado}</div></div>`).join("");
// Búsqueda unificada: licitaciones verificadas + obras potenciales existentes en este tablero.
function buscarDEEP(){
  pintar();
  const q=($("q").value||"").trim().toLocaleLowerCase("es").normalize("NFD").replace(/[\u0300-\u036f]/g,"");
  const sector=$("sector").value, prov=$("prov").value, fuente=$("fuente").value;
  const tabla=document.querySelector("#obras-revision-tecnica tbody");
  const filas=tabla?Array.from(tabla.querySelectorAll("tr")):[];
  const normalizar=s=>(s||"").toLocaleLowerCase("es").normalize("NFD").replace(/[\u0300-\u036f]/g,"");
  const potenciales=filas.filter(tr=>{
    const c=Array.from(tr.cells).map(td=>td.textContent.trim());
    const texto=normalizar(c.join(" "));
    // La tabla de potenciales no trae provincia/sector estructurados: no afirmar coincidencias desconocidas.
    return (!q||texto.includes(q)) && (!fuente||c[4]===fuente) && (!prov||texto.includes(normalizar(prov))) && (!sector||texto.includes(normalizar(sector)));
  });
  const destino=$("resultados-potenciales");
  const encabezado='<h2>Oportunidades potenciales (sin vigencia confirmada)</h2><p class="mut">Estas coincidencias proceden de obras detectadas, no son licitaciones abiertas verificadas. Revisá el aviso oficial antes de cotizar.</p>';
  destino.innerHTML=encabezado+(potenciales.length?'<div style="overflow-x:auto"><table><thead><tr><th>Proceso</th><th>Obra</th><th>Motivo</th><th>Fecha informada</th><th>Fuente</th><th>Enlace</th></tr></thead><tbody></tbody></table></div>':'<p class="mut">No hay obras potenciales que coincidan con esta búsqueda.</p>');
  const cuerpo=destino.querySelector("tbody");
  if(cuerpo) potenciales.forEach(tr=>cuerpo.appendChild(tr.cloneNode(true)));
}
$("buscar-deep").addEventListener("click",buscarDEEP);
$("q").addEventListener("keydown",e=>{if(e.key==="Enter")buscarDEEP();});
["q","sector","prov","fuente"].forEach(id=>$(id).addEventListener("input",buscarDEEP));


$("csv").onclick=()=>{ const cols=["semaforo","titulo","organismo","numero_proceso","tipo_contratacion","estado","provincia","sector","fecha_publicacion","fecha_limite_consultas","fecha_presentacion","fecha_apertura","link","fuente"];
  const rows=[cols.join(";")].concat(visibles().map(p=>cols.map(c=>`"${(p[c]??"").toString().replace(/"/g,'""')}"`).join(";")));
  const b=new Blob(["﻿"+rows.join("\n")],{type:"text/csv"}); const a=document.createElement("a"); a.href=URL.createObjectURL(b); a.download="licitaciones.csv"; a.click(); };
buscarDEEP();
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

  if(fuentesConError.length){hayError=true;resultados.push(`<div style="padding:6px 0"><b>Fuentes de licitaciones</b>: ${fuentesConError.length} sin verificación satisfactoria</div>`);}
  indicador.textContent = hayError ? "🔴 Control" : "🟢 Control";
  detalle.innerHTML = resultados.join("");
})();
</script>
</body>
</html>
"""
