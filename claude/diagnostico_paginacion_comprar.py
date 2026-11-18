"""Diagnóstico conservador de paginación real COMPR.AR.

No almacena cookies ni VIEWSTATE en artefactos. Solo registra controles,
números de proceso y evidencia de diferencias entre páginas.
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from licitaciones.fuentes.comprar_webforms import (
    acciones_paginacion, campos_formulario, paginas_postback, es_pantalla_error
)
from licitaciones.fuentes.paginas_web import extraer_items

URL = "https://comprar.gob.ar/"
NUMERO = re.compile(r"\b\d{2,3}(?:/\d+)?-\d{4}-[A-Z]{3}\d{2}\b", re.I)

def procesos(html):
    return sorted(set(NUMERO.findall(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))))

def diagnosticar():
    sesion = requests.Session()
    sesion.headers["User-Agent"] = "Mozilla/5.0 (compatible; DEEP-Diagnostico/1.0)"
    salida = {"url_inicial": URL, "cobertura_total_acreditada": False}
    try:
        # Reintentos limitados ante fallas transitorias de red, sin fingir cobertura.
        errores_conexion = []
        for intento in range(1, 4):
            try:
                r = sesion.get(URL, timeout=(15, 30))
                r.raise_for_status()
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                errores_conexion.append({"intento": intento, "tipo": type(exc).__name__})
                if intento == 3:
                    salida["estado"] = "FUENTE_NO_DISPONIBLE"
                    salida["intentos_conexion"] = errores_conexion
                    salida["error"] = "COMPR.AR no respondió después de 3 intentos; extracción y paginación no verificadas"
                    raise
                time.sleep(intento * 2)
        if errores_conexion:
            salida["intentos_conexion"] = errores_conexion
        soup = BeautifulSoup(r.text, "html.parser")
        acciones = acciones_paginacion(r.text)
        form = soup.find("form")
        salida.update({
            "url_final": r.url,
            "http": r.status_code,
            "titulo": soup.title.get_text(" ", strip=True)[:150] if soup.title else "",
            "form_action": form.get("action", "") if form else None,
            "formularios": len(soup.select("form")),
            "viewstate_presente": bool(soup.select_one('input[name="__VIEWSTATE"]')),
            "eventvalidation_presente": bool(soup.select_one('input[name="__EVENTVALIDATION"]')),
            "eventos_paginacion": [{"target": t, "argument": a} for t,a in acciones[:25]],
            "links_postback": [
                {"texto": a.get_text(" ", strip=True)[:70], "href_patron": (a.get("href") or "")[:150]}
                for a in soup.select("a[href]") if "__doPostBack" in (a.get("href") or "")
            ][:35],
            "procesos_pagina_1": procesos(r.text)[:100],
            "cantidad_procesos_pagina_1": len(procesos(r.text))
        })
        if urlparse(r.url).hostname != "comprar.gob.ar":
            salida["advertencia"] = "Redireccion a dominio distinto"
        paginas, detalle = paginas_postback(sesion, r.url, r.text, max_paginas=5)
        salida["diagnostico_webforms"] = detalle
        salida["paginas_adicionales"] = []
        previos = set(procesos(r.text))
        for i, (url, html) in enumerate(paginas, 2):
            actuales = set(procesos(html))
            salida["paginas_adicionales"].append({
                "pagina": i, "url": url, "cantidad_procesos": len(actuales),
                "procesos_nuevos": sorted(actuales - previos)[:100],
                "cantidad_nuevos": len(actuales - previos)
            })
            previos |= actuales
        salida["segunda_pagina_distinta_verificada"] = any(
            p["cantidad_nuevos"] > 0 for p in salida["paginas_adicionales"]
        )
        # Paso 1b: entrar al listado real mediante el enlace de consultas frecuentes.
        # La portada muestra cinco procesos destacados, NO la lista paginada.
        from licitaciones.fuentes.comprar_webforms import POSTBACK
        frecuente = next((
            POSTBACK.search((a.get("href") or "") + " " + (a.get("onclick") or ""))
            for a in soup.select("a[href],a[onclick]")
            if "PROCESOS CON APERTURA PRÓXIMA" in a.get_text(" ", strip=True).upper()
            or "PROCESOS CON APERTURA PROXIMA" in a.get_text(" ", strip=True).upper()
        ), None)
        if frecuente:
            datos = campos_formulario(r.text)
            if datos and "__VIEWSTATE" in datos:
                datos["__EVENTTARGET"], datos["__EVENTARGUMENT"] = frecuente.groups()
                action = urljoin(r.url, form.get("action", "") if form else "")
                try:
                    rf = sesion.post(action, data=datos, timeout=(8, 30),
                                    headers={"Referer": r.url})
                    rf.raise_for_status()
                    if urlparse(rf.url).hostname != "comprar.gob.ar":
                        raise ValueError("Redireccion fuera de COMPR.AR")
                    sf = BeautifulSoup(rf.text, "html.parser")
                    iniciales = set(procesos(rf.text))
                    extras, estado = paginas_postback(sesion, rf.url, rf.text, max_paginas=5)
                    vistos = set(iniciales)
                    adicionales = []
                    for indice, (pagina_url, pagina_html) in enumerate(extras, 2):
                        nuevos = set(procesos(pagina_html)) - vistos
                        adicionales.append({"pagina": indice, "cantidad_procesos": len(procesos(pagina_html)),
                                            "cantidad_nuevos": len(nuevos), "ejemplos_nuevos": sorted(nuevos)[:8]})
                        vistos.update(procesos(pagina_html))
                    salida["consulta_apertura_proxima"] = {
                        "http": rf.status_code, "url": rf.url,
                        "error_funcional_aspnet": es_pantalla_error(rf.url, rf.text),
                        "resultado_valido": not es_pantalla_error(rf.url, rf.text),
                        "titulo": sf.title.get_text(" ", strip=True)[:120] if sf.title else "",
                        "procesos_primera_pagina": len(iniciales),
                        "ejemplos": sorted(iniciales)[:8],
                        "eventos_paginacion": [
                            {"target": t, "argument": a}
                            for t, a in acciones_paginacion(rf.text)[:20]
                        ],
                        "paginacion": estado,
                        "paginas_adicionales": adicionales,
                        "segunda_pagina_distinta_verificada": any(x["cantidad_nuevos"] > 0 for x in adicionales),
                        "cobertura_total_acreditada": False,
                    }
                except Exception as exc:
                    salida["consulta_apertura_proxima"] = {
                        "error": type(exc).__name__ + ": " + str(exc)[:200],
                        "cobertura_total_acreditada": False
                    }
            else:
                salida["consulta_apertura_proxima"] = {"error": "Formulario inicial sin VIEWSTATE"}
        else:
            salida["consulta_apertura_proxima"] = {"error": "No se encontro enlace de apertura proxima"}
        # Paso 2: activar el botón real "BÚSQUEDA DE PROCESOS" de la portada.
        # El evento fue observado en los logs oficiales de GitHub Actions.
        from licitaciones.fuentes.comprar_webforms import POSTBACK
        boton = next((
            POSTBACK.search((a.get("href") or "") + " " + (a.get("onclick") or ""))
            for a in soup.select("a[href],a[onclick]")
            if "BÚSQUEDA DE PROCESOS" in a.get_text(" ", strip=True).upper()
        ), None)
        if boton:
            datos = campos_formulario(r.text)
            if datos and "__VIEWSTATE" in datos:
                datos["__EVENTTARGET"], datos["__EVENTARGUMENT"] = boton.groups()
                action = urljoin(r.url, form.get("action", "") if form else "")
                try:
                    rr = sesion.post(action, data=datos, timeout=(8, 30),
                                    headers={"Referer": r.url})
                    rr.raise_for_status()
                    if not (urlparse(rr.url).hostname or "").endswith("comprar.gob.ar"):
                        raise ValueError("Redireccion fuera de COMPR.AR")
                    bs = BeautifulSoup(rr.text, "html.parser")
                    salida["busqueda_procesos"] = {
                        "http": rr.status_code, "url": rr.url,
                        "error_funcional_aspnet": es_pantalla_error(rr.url, rr.text),
                        "resultado_valido": not es_pantalla_error(rr.url, rr.text),
                        "titulo": bs.title.get_text(" ", strip=True)[:120] if bs.title else "",
                        "formularios": len(bs.select("form")),
                        "procesos_visibles": procesos(rr.text)[:100],
                        "cantidad_procesos": len(procesos(rr.text)),
                        "eventos_paginacion": [
                            {"target": t, "argument": a}
                            for t,a in acciones_paginacion(rr.text)[:30]
                        ],
                        "campos_busqueda": [
                            {"nombre": x.get("name", "")[:120], "tipo": x.get("type", "")}
                            for x in bs.select("input[name],select[name]")[:60]
                            if x.get("type", "").lower() != "hidden"
                        ]
                    }
                    # Detectar controles de búsqueda reales, sin disparar postbacks
                    # de autenticación ni ejecutar una consulta de forma especulativa.
                    controles = []
                    for tag in bs.select("input,button,a[href],a[onclick]"):
                        texto = tag.get_text(" ", strip=True)
                        nombre = tag.get("name", "") or tag.get("id", "")
                        if re.search(r"buscar|consultar|filtrar|resultado", texto + " " + nombre, re.I):
                            href = (tag.get("href") or "") + " " + (tag.get("onclick") or "")
                            m = POSTBACK.search(href)
                            controles.append({
                                "etiqueta": tag.name,
                                "texto": texto[:100],
                                "nombre": nombre[:130],
                                "tipo": tag.get("type", ""),
                                "evento": {"target": m.group(1), "argument": m.group(2)} if m else None
                            })
                    salida["busqueda_procesos"]["controles_accion_busqueda"] = controles[:30]
                    salida["busqueda_procesos"]["selectores"] = [
                        {"nombre": s.get("name", ""), "opciones": [
                            {"valor": o.get("value", ""), "texto": o.get_text(" ", strip=True)[:65]}
                            for o in s.select("option")[:15]
                        ]}
                        for s in bs.select("select[name]")[:15]
                    ]
                    extras, estado = paginas_postback(sesion, rr.url, rr.text, max_paginas=5)
                    salida["busqueda_procesos"]["paginacion"] = estado
                    vistos = set(procesos(rr.text))
                    salida["busqueda_procesos"]["paginas_adicionales"] = []
                    for i, (url2, html2) in enumerate(extras, 2):
                        nuevos = set(procesos(html2)) - vistos
                        salida["busqueda_procesos"]["paginas_adicionales"].append(
                            {"pagina": i, "nuevos": sorted(nuevos)[:50], "cantidad_nuevos": len(nuevos)}
                        )
                        vistos.update(procesos(html2))
                    salida["busqueda_procesos"]["segunda_pagina_distinta_verificada"] = any(
                        x["cantidad_nuevos"] > 0 for x in salida["busqueda_procesos"]["paginas_adicionales"]
                    )
                except Exception as exc:
                    salida["busqueda_procesos"] = {"error": type(exc).__name__ + ": " + str(exc)[:200]}
        else:
            salida["busqueda_procesos"] = {"error": "No se encontro el evento de busqueda en el HTML"}
        # Paso 3: ejecutar el formulario de búsqueda avanzada, no la portada.
        # Una página con HTTP 200 pero PantallaError.aspx NO es un resultado.
        if salida.get("busqueda_procesos", {}).get("resultado_valido") and "rr" in locals():
            try:
                avanzado = campos_formulario(rr.text)
                if not avanzado or "__VIEWSTATE" not in avanzado:
                    raise ValueError("Búsqueda avanzada sin VIEWSTATE")
                bs_form = BeautifulSoup(rr.text, "html.parser").find("form")
                control = BeautifulSoup(rr.text, "html.parser").find(
                    id="ctl00_CPH1_btnListarPliegoAvanzado")
                if control is None:
                    control = BeautifulSoup(rr.text, "html.parser").find(
                        attrs={"name": "ctl00$CPH1$btnListarPliegoAvanzado"})
                if control is None:
                    raise ValueError("Botón de búsqueda avanzada no encontrado")
                evento = POSTBACK.search((control.get("href") or "") + " " +
                                        (control.get("onclick") or ""))
                if evento:
                    avanzado["__EVENTTARGET"], avanzado["__EVENTARGUMENT"] = evento.groups()
                else:
                    avanzado["__EVENTTARGET"] = "ctl00$CPH1$btnListarPliegoAvanzado"
                    avanzado["__EVENTARGUMENT"] = ""
                destino = urljoin(rr.url, bs_form.get("action", "") if bs_form else "")
                resultado = sesion.post(destino, data=avanzado, timeout=(12, 45),
                                        headers={"Referer": rr.url})
                resultado.raise_for_status()
                error = es_pantalla_error(resultado.url, resultado.text)
                primera = set(procesos(resultado.text))
                adicionales, diagnostico = ([], "Error ASP.NET; sin paginación") if error else paginas_postback(
                    sesion, resultado.url, resultado.text, max_paginas=5)
                vistos = set(primera)
                detalle_paginas = []
                for indice, (u, h) in enumerate(adicionales, 2):
                    nuevos = set(procesos(h)) - vistos
                    detalle_paginas.append({"pagina": indice, "nuevos": sorted(nuevos)[:12],
                                           "cantidad_nuevos": len(nuevos)})
                    vistos.update(procesos(h))
                salida["busqueda_avanzada_ejecutada"] = {
                    "http": resultado.status_code, "url": resultado.url,
                    "error_funcional_aspnet": error, "procesos_primera_pagina": len(primera),
                    "ejemplos": sorted(primera)[:12],
                    "paginacion": diagnostico, "paginas_adicionales": detalle_paginas,
                    "segunda_pagina_distinta_verificada": any(
                        x["cantidad_nuevos"] > 0 for x in detalle_paginas),
                    "cobertura_total_acreditada": False}
            except Exception as exc:
                salida["busqueda_avanzada_ejecutada"] = {
                    "error": type(exc).__name__ + ": " + str(exc)[:200],
                    "cobertura_total_acreditada": False}
        if not acciones:
            salida["hipotesis"] = "No hay Page$Next visible en la portada; investigar formulario de búsqueda y postbacks numéricos"
    except Exception as e:
        salida.setdefault("estado", "ERROR_DIAGNOSTICO")
        salida.setdefault("error", type(e).__name__ + ": " + str(e)[:250])
    finally:
        Path("diagnostico_comprar.json").write_text(
            json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    return 0 if "error" not in salida else 1

if __name__ == "__main__":
    raise SystemExit(diagnosticar())
