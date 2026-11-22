"""Páginas públicas de licitaciones que no pasan por el Boletín Oficial nacional
(CAMMESA, empresas del Estado, portales provinciales). Se configuran en config.yaml.

Para cada página: baja el HTML, toma cada fila o enlace que mencione los rubros y arma una
oportunidad con el texto, las fechas que encuentre y el link. Si la página no tiene filas
(tabla o lista), usa los enlaces."""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

from ..modelo import Oportunidad
from ..texto import buscar_fechas, normalizar
from .base import USER_AGENT, Fuente, ResultadoFuente
from .comprar_webforms import buscar_procesos_avanzado, abrir_detalle_postback, buscar_aperturas_proximas
from ..filtros import Filtro
from ..verificacion_comprar import motivo_descarte, ficha_oficial_verificada


def _fecha_valida(fecha):
    if fecha is None:
        return None
    return fecha if 2000 <= fecha.year <= datetime.now().year + 5 else None


def _limpiar_titulo(texto):
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"^\d{1,7}\s+\d{1,2}/\d{1,2}/\d{2,4}\s+", "", texto)
    return re.sub(r"\s+Ver$", "", texto, flags=re.I).strip()


def extraer_items(html: str, url_base: str, nombre: str) -> list[Oportunidad]:
    soup = BeautifulSoup(html, "html.parser")
    for basura in soup(["script", "style", "nav", "footer", "header"]):
        basura.decompose()
    bloques = soup.find_all("tr") or soup.find_all(["li", "article"])
    if not bloques:
        bloques = soup.find_all("a")
    items, vistos = [], set()
    for b in bloques:
        texto = re.sub(r"\s+", " ", b.get_text(" ", strip=True))
        if len(texto) < 15 or texto in vistos:
            continue
        vistos.add(texto)
        enlaces = [b] if b.name == "a" and b.get("href") else b.find_all("a", href=True)
        # Priorizar enlace a detalle del proceso frente a enlaces genéricos de navegación.
        a = next((x for x in enlaces if re.search(r"detalle|proceso|licitacion|convocatoria|expediente|ver", (x.get("href") or "") + " " + x.get_text(" ", strip=True), re.I)), None)
        a = a or (enlaces[0] if enlaces else None)
        href = a.get("href", "") if a is not None else ""
        # Nunca publicar javascript:__doPostBack como enlace al proceso.
        # El enlace a la página oficial de origen es una referencia, no una ficha verificada.
        link = urljoin(url_base, href) if href and urlparse(urljoin(url_base, href)).scheme in ("https", "http") else url_base
        # COMPR.AR: las filas del inicio incluyen el identificador del proceso
        # y la fecha de apertura; no confundirlas con publicaciones.
        es_comprar = "comprar.gob.ar" in url_base.lower()
        numero = re.search(r"\b\d{2,3}(?:/\d+)?-\d{4}-[A-Z]{3}\d{2}\b", texto, re.I)
        if es_comprar and (b.name != "tr" or not numero):
            continue
        fechas = [f for _, f in buscar_fechas(texto) if _fecha_valida(f)]
        norm = normalizar(texto)
        ap = None
        cierre = None
        m = re.search(r"apertura[^0-9]{0,40}", norm)
        if m:
            despues = [f for p, f in buscar_fechas(texto) if p >= m.start() and _fecha_valida(f)]
            ap = despues[0] if despues else None
        if es_comprar:
            # No asignar fechas sin cabecera de columna verificable: una fila
            # puede incluir publicación, consulta, cierre y apertura.
            tabla = b.find_parent("table")
            cabeceras = [normalizar(x.get_text(" ", strip=True)) for x in tabla.find_all("th")] if tabla else []
            celdas = b.find_all("td", recursive=False)
            columnas = dict(zip(cabeceras, celdas)) if len(cabeceras) == len(celdas) else {}
            apertura = next((celda for titulo, celda in columnas.items() if "apertura" in titulo), None)
            fechas_apertura = [f for _, f in buscar_fechas(apertura.get_text(" ", strip=True)) if _fecha_valida(f)] if apertura else []
            ap = fechas_apertura[0] if fechas_apertura else None
            celda_estado = next((celda for titulo, celda in columnas.items()
                                 if "estado" in titulo or "situacion" in titulo), None)
            estado_oficial = celda_estado.get_text(" ", strip=True) if celda_estado else "Sin verificar"
            # Cierre/presentación es diferente de apertura: no inferir fechas.
            celda_cierre = next((celda for titulo, celda in columnas.items()
                                 if "presentacion" in titulo or "cierre" in titulo
                                 or "recepcion de ofertas" in titulo), None)
            fechas_cierre = [f for _, f in buscar_fechas(celda_cierre.get_text(" ", strip=True))
                             if _fecha_valida(f)] if celda_cierre else []
            cierre = fechas_cierre[0] if fechas_cierre else None
        items.append(Oportunidad(
            numero_proceso=numero.group(0) if es_comprar and numero else "",
            fuente=f"Página: {nombre}",
            titulo=_limpiar_titulo(texto)[:220],
            organismo=nombre,
            estado=(estado_oficial if es_comprar else ("Circular" if "circular" in norm else "Publicada")),
            fecha_publicacion=None if es_comprar else (fechas[0] if fechas and fechas[0] != ap else None),
            # Nunca inferir apertura desde una fecha arbitraria del aviso.
            fecha_apertura=ap,
            fecha_presentacion=cierre,
            link=link,
            texto=texto,
            es_circular="circular" in norm,
        ))
    return items


def paginas_enlazadas(html: str, origen: str) -> list[str]:
    """Paginación HTML explícita; no presume que se accedió a páginas JS."""
    soup = BeautifulSoup(html, "html.parser")
    host = (urlparse(origen).hostname or "").lower()
    enlaces = []
    for a in soup.find_all("a", href=True):
        etiqueta = normalizar(a.get_text(" ", strip=True))
        destino = urldefrag(urljoin(origen, a["href"]))[0]
        u = urlparse(destino)
        if u.scheme != "https" or (u.hostname or "").lower() != host:
            continue
        if destino == origen:
            continue
        if (re.search(r"^(siguiente|next|[2-9]|[1-9][0-9]|>)$", etiqueta)
                or re.search(r"(?:[?&](?:page|pagina|pageno|pageindex)=\d+)", destino, re.I)):
            enlaces.append(destino)
    return list(dict.fromkeys(enlaces))


class PaginasWeb(Fuente):
    nombre = "Páginas públicas configuradas"

    def obtener(self) -> ResultadoFuente:
        paginas = [p for p in self.config.get("paginas_publicas", []) if p.get("activa", True)]
        if not paginas:
            return ResultadoFuente(self.nombre, "desactivada", "No hay páginas cargadas en config.yaml")
        ops, errores, detalle_fuentes = [], [], []
        parciales = []
        max_paginas = max(1, min(200, int(self.config.get("max_paginas_por_fuente", 50))))
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        for p in paginas:
            try:
                # Evitar que un portal inaccesible bloquee la actualización diaria.
                # Tiempo de conexión corto y lectura acotada por fuente.
                r = s.get(p["url"], timeout=(8, 20))
                r.raise_for_status()
                items = [] if "comprar.gob.ar" in (urlparse(r.url).hostname or "").lower() else extraer_items(r.text, r.url, p["nombre"])
                paginas_leidas = 1
                diagnostico_js = ""
                errores_pagina = []
                visitadas = {r.url}
                cola = paginas_enlazadas(r.text, r.url)
                if "comprar.gob.ar" in (urlparse(r.url).hostname or "").lower():
                    # Solo páginas realmente enlazadas y accesibles. No inventar
                    # cobertura total cuando el portal pagina mediante JavaScript.
                    # COMPR.AR WebForms: conservar estado del formulario entre POST.
                    paginas_js, diagnostico_js = buscar_aperturas_proximas(s, r.url, r.text, max_paginas=max_paginas)
                    if not paginas_js:
                        paginas_js, diagnostico_respaldo = buscar_procesos_avanzado(s, r.url, r.text, max_paginas=max_paginas)
                        diagnostico_js += '; respaldo historico: ' + diagnostico_respaldo
                    for url_js, html_js in paginas_js:
                        nuevos = extraer_items(html_js, url_js, p["nombre"])
                        if not self.config.get("auditoria_comprar_sin_publicar"):
                            filtro_comprar = Filtro(self.config)
                            for op in nuevos:
                                if motivo_descarte(op) or not filtro_comprar.evaluar(op):
                                    continue
                                detalle, razon = abrir_detalle_postback(s, url_js, html_js, op.numero_proceso)
                                if detalle:
                                    from ..verificacion_comprar import _vigencia_en_ficha
                                    confirmado, razon = _vigencia_en_ficha(detalle[1], op.numero_proceso)
                                    if confirmado:
                                        op.link = detalle[0]
                                        op.estado = "Vigente verificada"
                        items.extend(nuevos)
                    paginas_leidas += len(paginas_js)
                # Recorrer paginacion HTML en TODAS las fuentes configuradas.
                # Limite de seguridad: no afirmar cobertura total al alcanzarlo.
                while cola and paginas_leidas < max_paginas:
                    destino = cola.pop(0)
                    if destino in visitadas:
                        continue
                    visitadas.add(destino)
                    try:
                        sub = s.get(destino, timeout=(8, 20))
                        sub.raise_for_status()
                        if (urlparse(sub.url).hostname or "").lower() != (urlparse(r.url).hostname or "").lower():
                            errores_pagina.append(f"{destino}: redireccion fuera de fuente")
                            continue
                        if "html" not in sub.headers.get("Content-Type", "").lower():
                            errores_pagina.append(f"{destino}: respuesta no HTML")
                            continue
                        paginas_leidas += 1
                        items.extend(extraer_items(sub.text, sub.url, p["nombre"]))
                        for link in paginas_enlazadas(sub.text, sub.url):
                            if link not in visitadas and link not in cola:
                                cola.append(link)
                    except requests.RequestException as exc:
                        errores_pagina.append(f"{destino}: {type(exc).__name__}")
                if cola or errores_pagina or diagnostico_js:
                    parciales.append(p["nombre"])
                unicos = {}
                for item in items:
                    clave = (item.numero_proceso or "", item.titulo, item.link)
                    unicos.setdefault(clave, item)
                if "comprar.gob.ar" in (urlparse(r.url).hostname or "").lower():
                    filtro = Filtro(self.config)
                    aprobadas = []
                    rechazadas = {}
                    for op in unicos.values():
                        if self.config.get("auditoria_comprar_sin_publicar"):
                            continue
                        motivo = motivo_descarte(op)
                        if not motivo and not filtro.evaluar(op):
                            motivo = "no_relevante_deep"
                        if not motivo:
                            confirmado, motivo = ficha_oficial_verificada(op, s)
                            if confirmado:
                                aprobadas.append(op)
                        if motivo:
                            rechazadas[motivo] = rechazadas.get(motivo, 0) + 1
                    detalle_fuentes.append(
                        f"COMPR.AR: {len(aprobadas)} fichas verificadas para DEEP; "
                        f"descartes={rechazadas}; resultados sin ficha NO publicados")
                    ops.extend(unicos.values() if self.config.get("auditoria_comprar_sin_publicar") else aprobadas)
                else:
                    ops.extend(unicos.values())
                detalle_fuentes.append(
                    f"{p['nombre']}: {len(unicos)} registros de {paginas_leidas} página(s) HTML; "
                    f"enlaces pendientes={len(cola)}; errores secundarios={len(errores_pagina)}; "
                    f"limite paginas={max_paginas}; "
                    "cobertura total y vigencia NO acreditadas" + (f"; {diagnostico_js}" if diagnostico_js else ""))
            except Exception as e:
                errores.append(f"{p['nombre']}: {e.__class__.__name__}")
        detalle = f"{len(paginas) - len(errores)}/{len(paginas)} páginas leídas"
        if detalle_fuentes:
            detalle += " — " + "; ".join(detalle_fuentes)
        if errores:
            detalle += " — fallaron: " + "; ".join(errores)
        if parciales:
            detalle += " — paginacion parcial: " + ", ".join(parciales)
        estado = "error" if len(errores) == len(paginas) else ("parcial" if errores or parciales else "ok")
        return ResultadoFuente(self.nombre, estado, detalle, ops)
