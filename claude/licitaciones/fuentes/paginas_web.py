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
        fechas = [f for _, f in buscar_fechas(texto)]
        norm = normalizar(texto)
        ap = None
        m = re.search(r"apertura[^0-9]{0,40}", norm)
        if m:
            despues = [f for p, f in buscar_fechas(texto) if p >= m.start()]
            ap = despues[0] if despues else None
        items.append(Oportunidad(
            fuente=f"Página: {nombre}",
            titulo=texto[:220],
            organismo=nombre,
            estado="Circular" if "circular" in norm else "Publicada",
            fecha_publicacion=fechas[0] if fechas and fechas[0] != ap else None,
            fecha_apertura=ap or (fechas[-1] if len(fechas) > 1 else None),
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
        ops, errores = [], []
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        for p in paginas:
            try:
                r = s.get(p["url"], timeout=45)
                r.raise_for_status()
                ops += extraer_items(r.text, p["url"], p["nombre"])
            except Exception as e:
                errores.append(f"{p['nombre']}: {e.__class__.__name__}")
        detalle = f"{len(paginas) - len(errores)}/{len(paginas)} páginas leídas"
        if errores:
            detalle += " — fallaron: " + "; ".join(errores)
        return ResultadoFuente(self.nombre, "ok" if len(errores) < len(paginas) else "error", detalle, ops)
