"""Navegación ASP.NET WebForms para COMPR.AR: POST de paginadores visibles.

No presume cobertura total ni fecha de cierre. Mantiene cookies y campos
ocultos por respuesta, y evita repetir páginas por huella de procesos.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

POSTBACK = re.compile(r"__doPostBack\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)", re.I)
MAX_PAGINAS = 15


def es_pantalla_error(url, html):
    """Detecta errores funcionales aun cuando ASP.NET responde HTTP 200."""
    ruta = (urlparse(url).path or "").lower()
    if "pantallaerror.aspx" in ruta or ruta.endswith("/error.aspx"):
        return True
    soup = BeautifulSoup(html, "html.parser")
    titulo = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    return bool(re.search(r"error (?:de|del|en) (?:la )?(?:aplicaci[oó]n|servidor)", titulo))


def acciones_paginacion(html):
    soup = BeautifulSoup(html, "html.parser")
    acciones = []
    for a in soup.select("a[href],a[onclick]"):
        etiqueta = a.get_text(" ", strip=True).lower()
        href = a.get("href", "") + " " + a.get("onclick", "")
        m = POSTBACK.search(href)
        if not m:
            continue
        target, arg = m.groups()
        # El paginador GridView suele usar Page$N o Page$Next.
        # No ejecutar otros postbacks (búsquedas, formularios, login).
        if not (re.search(r"page\$(?:\d+|next|last)", arg, re.I)
                or (re.fullmatch(r"\d+|siguiente|next|>", etiqueta)
                    and re.search(r"page|pager|grid", target, re.I))):
            continue
        if re.search(r"page\$(?:prev|previous|first|1)$", arg, re.I):
            continue
        acciones.append((target, arg))
    return list(dict.fromkeys(acciones))


def campos_formulario(html):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if form is None:
        return None
    datos = {}
    for field in form.select("input[name]"):
        tipo = field.get("type", "text").lower()
        if tipo in ("hidden", "text", "search"):
            datos[field["name"]] = field.get("value", "")
    return datos


def paginas_postback(sesion, url, html_inicial, max_paginas=MAX_PAGINAS):
    """Retorna páginas adicionales realmente obtenidas, y diagnóstico.

    Solo ejecuta postbacks del paginador; no crea URL ni fechas sintéticas.
    """
    if urlparse(url).scheme != "https" or not (urlparse(url).hostname or "").endswith("comprar.gob.ar"):
        return [], "Origen COMPR.AR no seguro"
    if es_pantalla_error(url, html_inicial):
        return [], "Página de error ASP.NET detectada; cobertura total no acreditada"
    paginas = []
    visitadas = {hashlib.sha256(html_inicial.encode("utf-8")).hexdigest()}
    # La navegación WebForms es secuencial: usar Next desde el estado actual.
    actual = html_inicial
    errores = []
    for _ in range(max(0, max_paginas - 1)):
        opciones = acciones_paginacion(actual)
        if not opciones:
            break
        siguiente = next((x for x in opciones if re.search(r"page\$next", x[1], re.I)), None)
        if siguiente is None:
            # Elegir un número solo cuando el servidor expone una página siguiente
            # inequívoca; de otro modo detenerse sin declarar cobertura completa.
            break
        datos = campos_formulario(actual)
        if datos is None or "__VIEWSTATE" not in datos:
            errores.append("Formulario sin __VIEWSTATE; no se puede continuar")
            break
        datos["__EVENTTARGET"], datos["__EVENTARGUMENT"] = siguiente
        try:
            respuesta = sesion.post(url, data=datos, timeout=(8, 25),
                                    headers={"Referer": url})
            respuesta.raise_for_status()
            if urlparse(respuesta.url).hostname != urlparse(url).hostname:
                errores.append("Redirección fuera de COMPR.AR")
                break
            if es_pantalla_error(respuesta.url, respuesta.text):
                errores.append("COMPR.AR devolvió PantallaError.aspx (HTTP 200 no implica éxito)")
                break
            if "html" not in respuesta.headers.get("Content-Type", "").lower():
                errores.append("Respuesta no HTML")
                break
        except Exception as exc:
            errores.append(type(exc).__name__)
            break
        firma = hashlib.sha256(respuesta.text.encode("utf-8")).hexdigest()
        if firma in visitadas:
            errores.append("Respuesta repetida; paginación detenida")
            break
        visitadas.add(firma)
        paginas.append((respuesta.url, respuesta.text))
        actual = respuesta.text
    estado = f"{1 + len(paginas)} página(s) WebForms recorridas; cobertura total no acreditada"
    if errores:
        estado += "; " + ", ".join(errores)
    return paginas, estado
