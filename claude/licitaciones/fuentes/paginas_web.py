"""Páginas públicas de licitaciones que no pasan por el Boletín Oficial nacional
(CAMMESA, empresas del Estado, portales provinciales). Se configuran en config.yaml.

Para cada página: baja el HTML, toma cada fila o enlace que mencione los rubros y arma una
oportunidad con el texto, las fechas que encuentre y el link. Si la página no tiene filas
(tabla o lista), usa los enlaces."""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..modelo import Oportunidad
from ..texto import buscar_fechas, normalizar
from .base import USER_AGENT, Fuente, ResultadoFuente


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
        a = b if b.name == "a" else b.find("a", href=True)
        link = urljoin(url_base, a["href"]) if a is not None and a.get("href") else url_base
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
            # La tabla oficial rotula la columna como Fecha de Apertura.
            # No asignar una fecha de publicación inexistente.
            ap = fechas[0] if fechas else None
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
                items = extraer_items(r.text, p["url"], p["nombre"])
                ops += items
                detalle_fuentes.append(f"{p['nombre']}: {len(items)} registros HTML (sin validar vigencia)")
            except Exception as e:
                errores.append(f"{p['nombre']}: {e.__class__.__name__}")
        detalle = f"{len(paginas) - len(errores)}/{len(paginas)} páginas leídas"
        if detalle_fuentes:
            detalle += " — " + "; ".join(detalle_fuentes)
        if errores:
            detalle += " — fallaron: " + "; ".join(errores)
        return ResultadoFuente(self.nombre, "ok" if len(errores) < len(paginas) else "error", detalle, ops)
