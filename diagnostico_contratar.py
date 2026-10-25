#!/usr/bin/env python3
"""Diagnóstico AISLADO de la navegación de CONTRAT.AR (manual, pocos pedidos, con pausas).

No modifica licitaciones.json, el tablero ni CAMMESA. No usa usuario ni clave: abre una sesión
pública (cookies) igual que cualquier visitante. Cada prueba queda registrada como:
  OK / FALLA            -> se ejecutó y ese fue el resultado
  NO EJECUTADA          -> no se pudo ejecutar (se explica por qué)
Nada se da por verificado si no se ejecutó realmente.
"""
import http.cookiejar
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from bs4 import BeautifulSoup

BASE = os.environ.get("CONTRATAR_BASE_URL", "https://contratar.gob.ar").rstrip("/")
PAUSA = float(os.environ.get("DIAG_PAUSA", "2"))
MAX_PEDIDOS = int(os.environ.get("DIAG_MAX_PEDIDOS", "14"))
SALIDA = Path(os.environ.get("DIAG_SALIDA", "diagnostico-contratar"))
UA = "Mozilla/5.0 (compatible; DEEP-diagnostico/2.0; +https://github.com/mg-consultora/deep-licitaciones-ia)"
NUM_RE = re.compile(r"^[0-9]+(?:/[0-9]+)?-[0-9]+-[A-Za-z]+[0-9]+$")
POSTBACK_RE = re.compile(r"__doPostBack\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)")
FECHA_RE = re.compile(r"\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2})?")
CAMPOS_ESTADO = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__VIEWSTATEENCRYPTED", "__PREVIOUSPAGE", "__LASTFOCUS")

pruebas, solicitudes, observaciones = [], [], {}
pedidos = 0
ultimo = 0.0


def registrar(id_, titulo, resultado, detalle):
    pruebas.append({"id": id_, "titulo": titulo, "resultado": resultado, "detalle": detalle})
    print("[%s] %s: %s" % (resultado, titulo, detalle), flush=True)


# ---------------------------------------------------------------- pedidos

def nuevo_opener():
    return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))


def pedir(opener, url, datos=None, cab=None, referer=None, etiqueta=""):
    """Un pedido HTTP con pausa y tope global. Devuelve dict o None si no hay respuesta."""
    global pedidos, ultimo
    if pedidos >= MAX_PEDIDOS:
        observaciones.setdefault("limite", "Se alcanzó el tope de %d pedidos; lo que sigue no se ejecutó." % MAX_PEDIDOS)
        return None
    if pedidos and PAUSA - (time.time() - ultimo) > 0:
        time.sleep(PAUSA - (time.time() - ultimo))
    pedidos += 1
    cabeceras = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "es-AR,es;q=0.9"}
    if referer:
        cabeceras["Referer"] = referer
    cabeceras.update(cab or {})
    t0 = ultimo = time.time()
    r = {"etiqueta": etiqueta, "metodo": "POST" if datos else "GET", "url": url, "status": None, "url_final": None,
         "segundos": None, "bytes": 0, "texto": "", "error": None, "cabeceras": {}}
    try:
        with opener.open(Request(url, data=datos, headers=cabeceras), timeout=35) as resp:
            crudo = resp.read(6_000_000)
            r.update(status=resp.status, url_final=resp.geturl(), bytes=len(crudo),
                     texto=crudo.decode(resp.headers.get_content_charset() or "utf-8", errors="replace").lstrip("\ufeff"))
            r["cabeceras"] = {k: resp.headers.get(k) for k in ("Content-Type", "Server", "X-Powered-By", "X-AspNet-Version", "Cache-Control") if resp.headers.get(k)}
    except HTTPError as e:
        r.update(status=e.code, error="HTTP %s %s" % (e.code, e.reason))
    except (URLError, TimeoutError, OSError) as e:
        r["error"] = "%s: %s" % (type(e).__name__, e)
    r["segundos"] = round(time.time() - t0, 2)
    solicitudes.append({k: r[k] for k in ("etiqueta", "metodo", "url", "status", "url_final", "segundos", "bytes", "error")})
    return r


def es_default(url):
    return urlparse(url or "").path.lower().endswith("/default.aspx")


def cookies_de(opener):
    for h in opener.handlers:
        if isinstance(h, HTTPCookieProcessor):
            return sorted(c.name for c in h.cookiejar)
    return []


# ---------------------------------------------------------------- HTML

def sanitizar(texto):
    """Quita valores de estado ASP.NET y correos antes de guardar. No hay cookies en el HTML."""
    def input_(m):
        tag = m.group(0)
        if re.search(r"name=[\"']__\w+[\"']", tag):
            return re.sub(r"(value=[\"'])([^\"']*)([\"'])", lambda v: v.group(1) + "[omitido %d caracteres]" % len(v.group(2)) + v.group(3), tag)
        return tag
    texto = re.sub(r"<input[^>]*>", input_, texto, flags=re.I)
    texto = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[correo omitido]", texto)
    return texto


def guardar(nombre, texto):
    (SALIDA / "html").mkdir(parents=True, exist_ok=True)
    (SALIDA / "html" / nombre).write_text(sanitizar(texto), encoding="utf-8")


def campos_formulario(sopa):
    form = sopa.find("form", id=re.compile("aspnetform|form1", re.I)) or sopa.find("form")
    campos = {}
    if form is None:
        return campos, ""
    for el in form.find_all(["input", "select", "textarea"]):
        nombre = el.get("name")
        if not nombre:
            continue
        if el.name == "input":
            tipo = (el.get("type") or "text").lower()
            if tipo in ("submit", "button", "image", "reset", "file"):
                continue
            if tipo in ("checkbox", "radio") and not el.has_attr("checked"):
                continue
            campos[nombre] = el.get("value", "on" if tipo in ("checkbox", "radio") else "")
        elif el.name == "select":
            ops = el.find_all("option")
            sel = next((o for o in ops if o.has_attr("selected")), ops[0] if ops else None)
            if sel is not None:
                campos[nombre] = sel.get("value", sel.get_text(strip=True))
        else:
            campos[nombre] = el.get_text()
    return campos, form.get("action", "")


def grilla(sopa):
    for t in sopa.find_all("table"):
        if "gridlistapliegos" in (t.get("id") or "").lower():
            return t
    mejor, cuenta = None, 0
    for t in sopa.find_all("table"):
        c = 0
        for tr in t.find_all("tr"):
            if tr.find_parent("table") is t:
                td = tr.find(["td", "th"])
                if td is not None and NUM_RE.match(td.get_text(" ", strip=True)):
                    c += 1
        if c > cuenta:
            mejor, cuenta = t, c
    return mejor


def tipo_href(href):
    href = (href or "").strip()
    if not href or href.startswith("#"):
        return "ninguno", None
    if href.lower().startswith("javascript:"):
        m = POSTBACK_RE.search(href)
        return ("postback", (m.group(1), m.group(2))) if m else ("javascript_otro", None)
    return "directo", href


def filas(tabla):
    salida, encabezados = [], []
    for tr in tabla.find_all("tr"):
        if tr.find_parent("table") is not tabla:
            continue
        celdas = tr.find_all(["td", "th"], recursive=False)
        if not celdas:
            continue
        textos = [c.get_text(" ", strip=True) for c in celdas]
        if all(c.name == "th" for c in celdas):
            encabezados = textos
            continue
        if len(celdas) >= 6 and NUM_RE.match(textos[0]):
            enlaces = [tipo_href(a.get("href")) for c in celdas for a in c.find_all("a", href=True)]
            salida.append({"numero": textos[0], "nombre": textos[1], "tipo": textos[2], "apertura": textos[3],
                           "estado": textos[4], "organismo": textos[5], "enlaces": enlaces})
    return salida, encabezados


def paginador(sopa):
    out = []
    for a in sopa.find_all("a", href=True):
        m = POSTBACK_RE.search(a["href"])
        if m and m.group(2).lower().startswith("page$"):
            out.append((m.group(1), m.group(2), a.get_text(" ", strip=True)))
    return out


def script_manager(html):
    m = re.search(r"PageRequestManager\._initialize\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][^'\"]*['\"]\s*,\s*\[(.*?)\]", html, re.S)
    if not m:
        return None
    paneles = re.findall(r"['\"][tf]?([^'\"]+)['\"]", m.group(2))
    return {"id": m.group(1), "paneles": paneles}


def parsear_delta(texto):
    piezas, i = [], 0
    while i < len(texto):
        j = texto.index("|", i); largo = int(texto[i:j])
        k = texto.index("|", j + 1); tipo = texto[j + 1:k]
        l = texto.index("|", k + 1); ident = texto[k + 1:l]
        contenido = texto[l + 1:l + 1 + largo]
        if texto[l + 1 + largo:l + 2 + largo] != "|":
            raise ValueError("formato asíncrono inválido")
        piezas.append((tipo, ident, contenido)); i = l + 2 + largo
    return piezas


def resumen_pagina(nombre, r):
    """Inspección estructural de un listado. Devuelve (sopa, info)."""
    sopa = BeautifulSoup(r["texto"], "html.parser")
    campos, action = campos_formulario(sopa)
    tabla = grilla(sopa)
    info = {"pagina": nombre, "http": r["status"], "url_final": r["url_final"], "redirige_a_default": es_default(r["url_final"]),
            "titulo": sopa.title.get_text(strip=True) if sopa.title else None, "cabeceras": r["cabeceras"],
            "formulario_action": action, "campos_estado": {k: ("presente, %d caracteres" % len(campos[k])) if k in campos else "ausente" for k in CAMPOS_ESTADO},
            "total_campos_formulario": len(campos), "script_manager": script_manager(r["texto"]),
            "apariciones_doPostBack": len(POSTBACK_RE.findall(r["texto"])), "grilla_id": tabla.get("id") if tabla else None}
    if tabla is not None:
        fs, enc = filas(tabla)
        info.update(encabezados=enc, filas=len(fs), controles_paginacion=paginador(sopa),
                    enlaces_por_fila={k: sum(1 for f in fs for e in f["enlaces"] if e[0] == k) for k in ("directo", "postback", "javascript_otro", "ninguno")},
                    filas_sin_enlace=sum(1 for f in fs if not f["enlaces"]),
                    muestra=[{"numero": f["numero"], "nombre": f["nombre"][:90], "tipo": f["tipo"], "apertura": f["apertura"], "estado": f["estado"],
                              "enlaces": [e[0] for e in f["enlaces"]]} for f in fs[:5]])
        info["_filas"] = fs
    return sopa, campos, info


# ---------------------------------------------------------------- pruebas

def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    inicio = datetime.now(timezone.utc).isoformat()
    print("Diagnóstico CONTRAT.AR - %s - tope %d pedidos, pausa %.1f s" % (BASE, MAX_PEDIDOS, PAUSA))

    # T1: ¿hace falta sesión? Pedido directo, sin cookies y sin pasar por la home.
    r = pedir(nuevo_opener(), BASE + "/ListarAperturaProxima.aspx", etiqueta="T1 listado sin sesión")
    if r is None or r["error"] and r["status"] is None:
        registrar("T1", "Listado sin sesión previa", "NO EJECUTADA", "Sin respuesta: %s" % (r and r["error"]))
        sesion_necesaria = None
    else:
        hay_grilla = "gridlistapliegos" in r["texto"].lower()
        sesion_necesaria = es_default(r["url_final"]) or not hay_grilla
        registrar("T1", "Listado sin sesión previa", "OK",
                  "HTTP %s, URL final %s, tabla del listado: %s => %s" % (r["status"], urlparse(r["url_final"] or "").path, "sí" if hay_grilla else "no",
                                                                        "SE NECESITA sesión" if sesion_necesaria else "el listado se obtuvo sin sesión"))
    observaciones["sesion_necesaria"] = sesion_necesaria

    # T2: abrir sesión pública (home) y ver cookies.
    op = nuevo_opener()
    home = pedir(op, BASE + "/", etiqueta="T2 home")
    if home is None or home["status"] != 200:
        registrar("T2", "Abrir sesión pública (home)", "FALLA", "No se pudo abrir la home: %s" % (home and (home["error"] or home["status"])))
        return cerrar(inicio, False)
    guardar("home.html", home["texto"])
    cookies = cookies_de(op)
    registrar("T2", "Abrir sesión pública (home)", "OK", "HTTP 200. Cookies recibidas (solo nombres): %s. Sin usuario ni clave." % (", ".join(cookies) or "ninguna"))
    observaciones["cookies"] = cookies

    # T3/T4: listados con la sesión abierta.
    paginas = {}
    for id_, clave, ruta, titulo in (("T3", "proximas", "/ListarAperturaProxima.aspx", "Próximas aperturas"),
                                     ("T4", "ultimos90", "/ListarAperturaUltimos30Dias.aspx", "Aperturas de los últimos 90 días")):
        r = pedir(op, BASE + ruta, referer=BASE + "/", etiqueta="%s %s" % (id_, titulo))
        if r is None:
            registrar(id_, titulo, "NO EJECUTADA", observaciones.get("limite", "sin respuesta"))
            continue
        if r["status"] != 200:
            registrar(id_, titulo, "FALLA", r["error"] or "HTTP %s" % r["status"])
            continue
        guardar("%s_p1.html" % clave, r["texto"])
        sopa, campos, info = resumen_pagina(titulo, r)
        paginas[clave] = (r, sopa, campos, info)
        observaciones["listado_" + clave] = {k: v for k, v in info.items() if not k.startswith("_")}
        if info["redirige_a_default"] or info["grilla_id"] is None:
            registrar(id_, titulo, "FALLA", "No se obtuvo la tabla del listado (URL final: %s)" % urlparse(r["url_final"]).path)
        else:
            registrar(id_, titulo, "OK", "Tabla %s con %d filas en la primera página; paginador: %d controles; ScriptManager: %s; filas con enlace directo/postback/ninguno: %s/%s/%s"
                      % (info["grilla_id"], info["filas"], len(info["controles_paginacion"]), "sí" if info["script_manager"] else "no",
                         info["enlaces_por_fila"]["directo"], info["enlaces_por_fila"]["postback"], info["filas_sin_enlace"]))

    # T5: ¿el analizador de producción lee lo mismo que BeautifulSoup?
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import buscar_licitaciones as bl
        if not hasattr(bl, "Pagina"):
            raise ImportError("el buscar_licitaciones.py del repositorio es la versión anterior")
    except Exception as e:  # noqa
        bl = None
        registrar("T5", "Comparar con el analizador de producción", "NO EJECUTADA", "No se pudo importar buscar_licitaciones.py (%s: %s)" % (type(e).__name__, e))
    if bl is not None:
        for clave, (r, sopa, campos, info) in paginas.items():
            if info.get("grilla_id") is None:
                continue
            pag = bl.Pagina.desde_html(r["url_final"], r["texto"])
            g = bl.encontrar_grilla(pag.raiz)
            fp, _, _ = bl.leer_filas(g) if g is not None else ([], 0, [])
            ctr = bl.controles_paginacion(pag.raiz)
            coincide = len(fp) == info["filas"] and len(ctr) == len(info["controles_paginacion"]) and len(pag.campos) == info["total_campos_formulario"]
            registrar("T5", "Analizador de producción vs BeautifulSoup (%s)" % clave, "OK" if coincide else "FALLA",
                      "filas %d/%d, controles de paginación %d/%d, campos de formulario %d/%d (producción/bs4)"
                      % (len(fp), info["filas"], len(ctr), len(info["controles_paginacion"]), len(pag.campos), info["total_campos_formulario"]))

    # T6/T7: un único avance de página (POST normal) y, si hay ScriptManager, uno asíncrono.
    if "proximas" in paginas and paginas["proximas"][3].get("grilla_id"):
        r1, sopa1, campos1, info1 = paginas["proximas"]
        numeros1 = {f["numero"] for f in info1["_filas"]}
        controles = info1["controles_paginacion"]
        destino = next(((t, a) for t, a, _ in controles if a.lower() == "page$2"), None) or next(((t, a) for t, a, _ in controles if a.lower() == "page$next"), None)
        if destino is None:
            motivo = "el listado no muestra controles de página (puede tener una sola página)" if not controles else "no hay control Page$2 ni Page$Next"
            registrar("T6", "Avance de página con POST normal", "NO EJECUTADA", motivo)
            registrar("T7", "Avance de página con POST asíncrono", "NO EJECUTADA", motivo)
            observaciones["una_sola_pagina"] = not controles
        else:
            url_post = urljoin(r1["url_final"], info1["formulario_action"]) if info1["formulario_action"] else r1["url_final"]
            def datos(asinc):
                c = dict(campos1)
                c["__EVENTTARGET"], c["__EVENTARGUMENT"] = destino
                cab = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
                if asinc:
                    sm = info1["script_manager"]
                    c[sm["id"]] = "%s|%s" % (sm["paneles"][0], destino[0]); c["__ASYNCPOST"] = "true"
                    cab.update({"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest", "Cache-Control": "no-cache", "Accept": "*/*"})
                return urlencode(c).encode("utf-8"), cab
            if "__VIEWSTATE" not in campos1:
                registrar("T6", "Avance de página con POST normal", "NO EJECUTADA", "la página no trae __VIEWSTATE")
            else:
                d, cab = datos(False)
                r2 = pedir(op, url_post, datos=d, cab=cab, referer=r1["url_final"], etiqueta="T6 página 2 POST normal")
                if r2 is None or r2["status"] != 200:
                    registrar("T6", "Avance de página con POST normal", "FALLA", (r2 and (r2["error"] or "HTTP %s" % r2["status"])) or "sin respuesta")
                else:
                    guardar("proximas_p2_post_normal.html", r2["texto"])
                    es_delta = bool(re.match(r"^\d+\|[A-Za-z]+\|", r2["texto"]))
                    sopa2 = BeautifulSoup(r2["texto"], "html.parser"); t2 = grilla(sopa2)
                    if t2 is None or es_delta:
                        registrar("T6", "Avance de página con POST normal", "FALLA", "la respuesta %s" % ("tiene formato asíncrono" if es_delta else "no contiene la tabla del listado"))
                    else:
                        f2, _ = filas(t2); n2 = {f["numero"] for f in f2}
                        cambio = bool(n2) and n2 != numeros1
                        registrar("T6", "Avance de página con POST normal", "OK" if cambio else "FALLA",
                                  "página 2 con %d filas; filas distintas de la página 1: %s; solapadas: %d" % (len(f2), "sí" if cambio else "no", len(n2 & numeros1)))
                        observaciones["post_normal_funciona"] = cambio
            if info1["script_manager"]:
                d, cab = datos(True)
                r3 = pedir(op, url_post, datos=d, cab=cab, referer=r1["url_final"], etiqueta="T7 página 2 POST asíncrono")
                if r3 is None or r3["status"] != 200:
                    registrar("T7", "Avance de página con POST asíncrono", "FALLA", (r3 and (r3["error"] or "HTTP %s" % r3["status"])) or "sin respuesta")
                else:
                    guardar("proximas_p2_async.txt", r3["texto"])
                    try:
                        piezas = parsear_delta(r3["texto"]); tipos = sorted({t for t, _, _ in piezas})
                        html = " ".join(c for t, _, c in piezas if t == "updatePanel")
                        t3 = grilla(BeautifulSoup(html, "html.parser"))
                        f3 = filas(t3)[0] if t3 is not None else []
                        registrar("T7", "Avance de página con POST asíncrono", "OK" if f3 else "FALLA",
                                  "respuesta en formato asíncrono con piezas %s; filas en el panel: %d; campos de estado devueltos: %s"
                                  % (tipos, len(f3), [i for t, i, _ in piezas if t == "hiddenField"]))
                        observaciones["post_async_funciona"] = bool(f3)
                    except (ValueError, IndexError):
                        registrar("T7", "Avance de página con POST asíncrono", "FALLA", "la respuesta no tiene formato asíncrono (¿HTML completo? ver proximas_p2_async.txt)")
            else:
                registrar("T7", "Avance de página con POST asíncrono", "NO EJECUTADA", "la página no tiene ScriptManager/UpdatePanel detectable")
    else:
        for id_, t in (("T6", "Avance de página con POST normal"), ("T7", "Avance de página con POST asíncrono")):
            registrar(id_, t, "NO EJECUTADA", "no se obtuvo el listado de próximas aperturas")

    # T8/T9: abrir fichas (un enlace directo y un postback, si existen) y leer fechas y circulares.
    if "proximas" in paginas and paginas["proximas"][3].get("grilla_id"):
        r1, sopa1, campos1, info1 = paginas["proximas"]
        fs = info1["_filas"]
        directa = next((f for f in fs if any(e[0] == "directo" for e in f["enlaces"])), None)
        postb = next((f for f in fs if any(e[0] == "postback" for e in f["enlaces"]) and f is not directa), None)

        def evaluar(id_, titulo, nombre_html, r, numero):
            if r is None or r["status"] != 200:
                registrar(id_, titulo, "FALLA", (r and (r["error"] or "HTTP %s" % r["status"])) or "sin respuesta"); return
            guardar(nombre_html, r["texto"])
            texto_pagina = BeautifulSoup(r["texto"], "html.parser").get_text("\n", strip=True)
            contiene = numero.lower() in texto_pagina.lower()
            fechas = len(FECHA_RE.findall(texto_pagina))
            detalle = "URL final %s; contiene el número %s: %s; fechas en la página: %d" % (urlparse(r["url_final"]).path, numero, "sí" if contiene else "no", fechas)
            if bl is not None and contiene:
                try:
                    campos, circ = bl.extraer_detalle(r["texto"], numero)
                    detalle += "; extractor de producción: %s; circulares: %d" % (json.dumps({k: bool(v) for k, v in campos.items()}, ensure_ascii=False), len(circ))
                    observaciones.setdefault("fichas", []).append({"numero": numero, "campos_encontrados": {k: bool(v) for k, v in campos.items()}, "circulares": len(circ)})
                except Exception as e:  # noqa
                    detalle += "; extractor de producción falló: %s" % e
            registrar(id_, titulo, "OK" if contiene and fechas else "FALLA", detalle)

        if directa is None:
            registrar("T8", "Abrir ficha por enlace directo", "NO EJECUTADA", "ninguna fila de la primera página trae enlace directo")
        else:
            href = next(e[1] for e in directa["enlaces"] if e[0] == "directo")
            url = urljoin(r1["url_final"], href)
            if urlparse(url).hostname != urlparse(BASE).hostname:
                registrar("T8", "Abrir ficha por enlace directo", "NO EJECUTADA", "el enlace apunta fuera del portal")
            else:
                evaluar("T8", "Abrir ficha por enlace directo", "ficha_directa.html", pedir(op, url, referer=r1["url_final"], etiqueta="T8 ficha directa"), directa["numero"])
        if postb is None:
            registrar("T9", "Abrir ficha por postback", "NO EJECUTADA", "ninguna fila de la primera página trae enlace tipo __doPostBack")
        elif "__VIEWSTATE" not in campos1:
            registrar("T9", "Abrir ficha por postback", "NO EJECUTADA", "la página no trae __VIEWSTATE")
        else:
            t, a = next(e[1] for e in postb["enlaces"] if e[0] == "postback")
            c = dict(campos1); c["__EVENTTARGET"], c["__EVENTARGUMENT"] = t, a
            url_post = urljoin(r1["url_final"], info1["formulario_action"]) if info1["formulario_action"] else r1["url_final"]
            rp = pedir(op, url_post, datos=urlencode(c).encode("utf-8"), cab={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                       referer=r1["url_final"], etiqueta="T9 ficha por postback")
            if rp is not None and rp["status"] == 200:
                observaciones["ficha_postback_url_final"] = urlparse(rp["url_final"]).path
            evaluar("T9", "Abrir ficha por postback", "ficha_postback.html", rp, postb["numero"])
    else:
        for id_, t in (("T8", "Abrir ficha por enlace directo"), ("T9", "Abrir ficha por postback")):
            registrar(id_, t, "NO EJECUTADA", "no se obtuvo el listado de próximas aperturas")

    ok = any(p["id"] == "T3" and p["resultado"] == "OK" for p in pruebas)
    return cerrar(inicio, ok)


def cerrar(inicio, listado_ok):
    ejecutadas = [p for p in pruebas if p["resultado"] in ("OK", "FALLA")]
    pendientes = [p for p in pruebas if p["resultado"] == "NO EJECUTADA"]
    informe = {"inicio": inicio, "fin": datetime.now(timezone.utc).isoformat(), "base": BASE, "pedidos_realizados": pedidos,
               "tope_pedidos": MAX_PEDIDOS, "pausa_segundos": PAUSA, "pruebas": pruebas, "observaciones": observaciones, "solicitudes": solicitudes}
    (SALIDA / "informe_diagnostico.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    md = ["# Diagnóstico de navegación de CONTRAT.AR", "",
          "Ejecutado: %s UTC · Pedidos HTTP: %d de %d permitidos · Pausa: %.1f s · Sin usuario ni clave." % (inicio[:19], pedidos, MAX_PEDIDOS, PAUSA), "",
          "## Pruebas ejecutadas", "", "| Prueba | Resultado | Detalle |", "|---|---|---|"]
    for p in pruebas:
        md.append("| %s %s | **%s** | %s |" % (p["id"], p["titulo"], p["resultado"], p["detalle"].replace("|", "/")))
    md += ["", "## Qué quedó pendiente (no se afirma como verificado)", ""]
    md += ["- %s %s: %s" % (p["id"], p["titulo"], p["detalle"]) for p in pendientes] or ["- Ninguna prueba quedó sin ejecutar."]
    md += ["", "## Lectura de resultados (solo con lo ejecutado)", ""]
    sn = observaciones.get("sesion_necesaria")
    md.append("- Sesión/cookies: %s." % ("necesarias (el pedido sin sesión no devolvió el listado)" if sn is True else "no se comprobó la necesidad" if sn is None else "el listado se obtuvo sin sesión"))
    for clave, texto in (("post_normal_funciona", "POST normal"), ("post_async_funciona", "POST asíncrono")):
        if clave in observaciones:
            md.append("- Avance de página con %s: %s." % (texto, "funcionó" if observaciones[clave] else "NO funcionó"))
    if observaciones.get("una_sola_pagina"):
        md.append("- El listado de próximas aperturas no mostró paginador: sería una sola página en este momento.")
    if observaciones.get("limite"):
        md.append("- " + observaciones["limite"])
    md += ["", "## Pedidos realizados", "", "| # | Etiqueta | Método | HTTP | URL final | Segundos |", "|---|---|---|---|---|---|"]
    for i, s in enumerate(solicitudes, 1):
        md.append("| %d | %s | %s | %s | %s | %s |" % (i, s["etiqueta"], s["metodo"], s["status"] or s["error"], urlparse(s["url_final"] or s["url"]).path, s["segundos"]))
    md += ["", "Los HTML guardados en `html/` no contienen cookies; los valores de __VIEWSTATE/__EVENTVALIDATION y los correos están omitidos."]
    (SALIDA / "informe_diagnostico.md").write_text("\n".join(md), encoding="utf-8")
    print("\n" + "\n".join(md))
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    print("\nEjecutadas: %d (OK: %d, FALLA: %d) · No ejecutadas: %d" % (len(ejecutadas), sum(p["resultado"] == "OK" for p in ejecutadas),
                                                                      sum(p["resultado"] == "FALLA" for p in ejecutadas), len(pendientes)))
    if not listado_ok:
        print("::error title=CONTRAT.AR::No se obtuvo el listado de próximas aperturas; ver el informe.")
        return 1
    print("::notice title=Diagnóstico CONTRAT.AR::Listado obtenido. Revisar qué pruebas quedaron en FALLA o NO EJECUTADA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
