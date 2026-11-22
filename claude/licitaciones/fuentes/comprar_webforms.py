"""Navegación ASP.NET WebForms para COMPR.AR: POST de paginadores visibles.

No presume cobertura total ni fecha de cierre. Mantiene cookies y campos
ocultos por respuesta, y evita repetir páginas por huella de procesos.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

POSTBACK = re.compile(r"__doPostBack\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)", re.I)
MAX_PAGINAS = 200


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
        if tipo in ("hidden", "text", "search", "date"):
            datos[field["name"]] = field.get("value", "")
        elif tipo in ("checkbox", "radio") and field.has_attr("checked"):
            datos[field["name"]] = field.get("value", "on")
    # WebForms requiere los valores seleccionados de los desplegables.
    for field in form.select("select[name]"):
        seleccion = field.select_one("option[selected]") or field.select_one("option")
        if seleccion is not None:
            datos[field["name"]] = seleccion.get("value", seleccion.get_text(" ", strip=True))
    for field in form.select("textarea[name]"):
        datos[field["name"]] = field.get_text()
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
    # Tramos de 25: se conserva VIEWSTATE y sesion entre tramos.
    # El limite es una cota de seguridad, nunca prueba de exhaustividad.
    for indice in range(max(0, max_paginas - 1)):
        if indice and indice % 25 == 0:
            print(f"COMPR.AR: tramo completado, {indice + 1} paginas; continuando", flush=True)
        opciones = acciones_paginacion(actual)
        if not opciones:
            break
        siguiente = next((x for x in opciones if re.search(r"page\$next", x[1], re.I)), None)
        if siguiente is None:
            # Algunos GridView muestran Page$2, Page$3 sin Page$Next.
            numero_siguiente = str(2 + len(paginas))
            siguiente = next((x for x in opciones
                              if x[1].lower() == "page$" + numero_siguiente), None)
            if siguiente is None:
                break
        datos = campos_formulario(actual)
        if datos is None or "__VIEWSTATE" not in datos:
            errores.append("Formulario sin __VIEWSTATE; no se puede continuar")
            break
        datos["__EVENTTARGET"], datos["__EVENTARGUMENT"] = siguiente
        formulario = BeautifulSoup(actual, "html.parser").find("form")
        destino = urljoin(url, formulario.get("action", "") if formulario else "")
        if urlparse(destino).hostname != urlparse(url).hostname:
            errores.append("Acción de formulario fuera de COMPR.AR")
            break
        try:
            respuesta = sesion.post(destino, data=datos, timeout=(8, 25),
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


def buscar_procesos_avanzado(sesion, url, html, max_paginas=50):
    """Entrar por el buscador real y ejecutar Buscar. No usa la portada como listado."""
    if urlparse(url).hostname != "comprar.gob.ar" or es_pantalla_error(url, html):
        return [], "Origen invalido o pantalla de error"
    soup = BeautifulSoup(html, "html.parser")
    enlace = next((a for a in soup.select("a[href],a[onclick]")
                   if "busqueda de procesos" in __import__("unicodedata").normalize(
                       "NFKD", a.get_text(" ", strip=True).lower()).encode("ascii", "ignore").decode()), None)
    if enlace is None:
        return [], "No se encontro acceso al buscador avanzado"
    m = POSTBACK.search((enlace.get("href") or "") + " " + (enlace.get("onclick") or ""))
    datos = campos_formulario(html)
    if m is None or not datos or "__VIEWSTATE" not in datos:
        return [], "Falta evento o VIEWSTATE del acceso al buscador"
    datos["__EVENTTARGET"], datos["__EVENTARGUMENT"] = m.groups()
    form = soup.find("form")
    destino = urljoin(url, form.get("action", "") if form else "")
    if urlparse(destino).hostname != "comprar.gob.ar":
        return [], "Accion fuera de COMPR.AR"
    try:
        r = sesion.post(destino, data=datos, timeout=(10, 30), headers={"Referer": url})
        r.raise_for_status()
        if urlparse(r.url).hostname != "comprar.gob.ar" or es_pantalla_error(r.url, r.text):
            return [], "Buscador avanzado devolvio error o redireccion"
        bs = BeautifulSoup(r.text, "html.parser")
        control = bs.find(id="ctl00_CPH1_btnListarPliegoAvanzado") or bs.find(
            attrs={"name": "ctl00$CPH1$btnListarPliegoAvanzado"})
        datos = campos_formulario(r.text)
        if control is None or not datos or "__VIEWSTATE" not in datos:
            return [], "Falta boton Buscar o VIEWSTATE"
        evento = POSTBACK.search((control.get("href") or "") + " " + (control.get("onclick") or ""))
        datos["__EVENTTARGET"], datos["__EVENTARGUMENT"] = evento.groups() if evento else (
            "ctl00$CPH1$btnListarPliegoAvanzado", "")
        form = bs.find("form")
        destino = urljoin(r.url, form.get("action", "") if form else "")
        if urlparse(destino).hostname != "comprar.gob.ar":
            return [], "Accion Buscar fuera de COMPR.AR"
        resultado = sesion.post(destino, data=datos, timeout=(10, 45), headers={"Referer": r.url})
        resultado.raise_for_status()
        if urlparse(resultado.url).hostname != "comprar.gob.ar" or es_pantalla_error(resultado.url, resultado.text):
            return [], "Busqueda avanzada devolvio error o redireccion"
        adicionales, estado = paginas_postback(sesion, resultado.url, resultado.text, max_paginas=max_paginas)
        return [(resultado.url, resultado.text)] + adicionales, "Busqueda avanzada: " + estado
    except Exception as exc:
        return [], "Busqueda avanzada fallo: " + type(exc).__name__ + ": " + str(exc)[:120]


def diagnosticar_filas_dinamicas(html, limite=12):
    """Evidencia segura de controles WebForms sin guardar VIEWSTATE ni cookies."""
    soup = BeautifulSoup(html, "html.parser")
    salida = []
    for tr in soup.select("tr"):
        texto = tr.get_text(" ", strip=True)
        numero = re.search(r"\b\d{2,3}(?:/\d+)?-\d{4}-[A-Z]{3}\d{2}\b", texto, re.I)
        if not numero:
            continue
        eventos = []
        for tag in tr.select("[href], [onclick], input[type=submit], button"):
            script = (tag.get("href") or "") + " " + (tag.get("onclick") or "")
            m = POSTBACK.search(script)
            eventos.append({
                "etiqueta": tag.get_text(" ", strip=True)[:60],
                "tipo": tag.name,
                "evento": list(m.groups()) if m else None,
                "control": (tag.get("name") or tag.get("id") or "")[:120],
                "ruta": (tag.get("href") or "")[:160] if not m else "postback"
            })
        salida.append({"numero": numero.group(0), "eventos": eventos[:8],
                       "columnas": [x.get_text(" ", strip=True)[:80] for x in tr.find_all("td", recursive=False)][:12]})
        if len(salida) >= limite:
            break
    return salida


def abrir_detalle_postback(sesion, url, html, numero):
    """Ejecuta exclusivamente el evento de detalle asociado a la fila solicitada."""
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "comprar.gob.ar":
        return None, "origen_no_oficial"
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.select("tr"):
        if numero not in tr.get_text(" ", strip=True):
            continue
        for tag in tr.select("[href], [onclick]"):
            texto = tag.get_text(" ", strip=True).lower()
            script = (tag.get("href") or "") + " " + (tag.get("onclick") or "")
            m = POSTBACK.search(script)
            if not m or not re.search(r"ver|detalle|consultar|proceso|pliego", texto + " " + script, re.I):
                continue
            datos = campos_formulario(html)
            if not datos or "__VIEWSTATE" not in datos:
                return None, "sin_viewstate"
            datos["__EVENTTARGET"], datos["__EVENTARGUMENT"] = m.groups()
            form = soup.find("form")
            destino = urljoin(url, form.get("action", "") if form else "")
            if urlparse(destino).hostname != "comprar.gob.ar":
                return None, "accion_externa"
            try:
                r = sesion.post(destino, data=datos, headers={"Referer": url},
                                timeout=(8, 25), allow_redirects=False)
                if r.status_code in (301, 302, 303):
                    destino = urljoin(url, r.headers.get("Location", ""))
                    if urlparse(destino).hostname != "comprar.gob.ar":
                        return None, "redireccion_externa"
                    r = sesion.get(destino, timeout=(8, 25), allow_redirects=False)
                if r.status_code != 200 or urlparse(r.url).hostname != "comprar.gob.ar":
                    return None, "http_" + str(r.status_code)
                if es_pantalla_error(r.url, r.text):
                    return None, "error_webforms"
                contenido = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
                if numero not in contenido:
                    return None, "detalle_sin_numero"
                return (r.url, r.text), "detalle_abierto"
            except Exception as exc:
                return None, type(exc).__name__
        return None, "fila_sin_evento_detalle"
    return None, "proceso_no_encontrado"
