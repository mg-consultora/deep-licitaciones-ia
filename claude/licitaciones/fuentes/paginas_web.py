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
from .comprar_webforms import paginas_postback


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
        items.append(Oportunidad(
            numero_proceso=numero.group(0) if es_comprar and numero else "",
            fuente=f"Página: {nombre}",
            titulo=_limpiar_titulo(texto)[:220],
            organismo=nombre,
            estado="Circular" if "circular" in norm else "Publicada",
            fecha_publicacion=None if es_comprar else (fechas[0] if fechas and fechas[0] != ap else None),
            # Nunca inferir apertura desde una fecha arbitraria del aviso.
            fecha_apertura=ap,
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
    return list(dict.fromkeys(enlaces))[:12]


class PaginasWeb(Fuente):
    nombre = "Páginas públicas configuradas"

    def obtener(self) -> ResultadoFuente:
        paginas = [p for p in self.config.get("paginas_publicas", []) if p.get("activa", True)]
        if not paginas:
            return ResultadoFuente(self.nombre, "desactivada", "No hay páginas cargadas en config.yaml")
        ops, errores, detalle_fuentes = [], [], []
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        for p in paginas:
            try:
                # Evitar que un portal inaccesible bloquee la actualización diaria.
                # Tiempo de conexión corto y lectura acotada por fuente.
                r = s.get(p["url"], timeout=(8, 20))
                r.raise_for_status()
                items = extraer_items(r.text, r.url, p["nombre"])
                paginas_leidas = 1
                if "comprar.gob.ar" in (urlparse(r.url).hostname or "").lower():
                    # Solo páginas realmente enlazadas y accesibles. No inventar
                    # cobertura total cuando el portal pagina mediante JavaScript.
                    # COMPR.AR WebForms: conservar estado del formulario entre POST.
                    paginas_js, diagnostico_js = paginas_postback(s, r.url, r.text)
                    for url_js, html_js in paginas_js:
                        items.extend(extraer_items(html_js, url_js, p["nombre"]))
                    paginas_leidas += len(paginas_js)
                    visitadas = {r.url}
                    cola = paginas_enlazadas(r.text, r.url)
                    while cola and paginas_leidas < 15:
                        destino = cola.pop(0)
                        if destino in visitadas:
                            continue
                        visitadas.add(destino)
                        try:
                            sub = s.get(destino, timeout=(8, 20))
                            sub.raise_for_status()
                            if "html" not in sub.headers.get("Content-Type", "").lower():
                                continue
                            paginas_leidas += 1
                            items.extend(extraer_items(sub.text, sub.url, p["nombre"]))
                            for link in paginas_enlazadas(sub.text, sub.url):
                                if link not in visitadas and link not in cola:
                                    cola.append(link)
                        except requests.RequestException:
                            continue
                unicos = {}
                for item in items:
                    clave = (item.numero_proceso or "", item.titulo, item.link)
                    unicos.setdefault(clave, item)
                ops.extend(unicos.values())
                detalle_fuentes.append(
                    f"{p['nombre']}: {len(unicos)} registros de {paginas_leidas} página(s) HTML; "
                    "cobertura total y vigencia NO acreditadas" + (f"; {diagnostico_js}" if "comprar.gob.ar" in (urlparse(r.url).hostname or "").lower() else ""))
            except Exception as e:
                errores.append(f"{p['nombre']}: {e.__class__.__name__}")
        detalle = f"{len(paginas) - len(errores)}/{len(paginas)} páginas leídas"
        if detalle_fuentes:
            detalle += " — " + "; ".join(detalle_fuentes)
        if errores:
            detalle += " — fallaron: " + "; ".join(errores)
        return ResultadoFuente(self.nombre, "ok" if len(errores) < len(paginas) else "error", detalle, ops)
