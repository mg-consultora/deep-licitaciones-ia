"""Lectura de notas: canales RSS de los medios, búsquedas de Google Noticias y texto de cada nota."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


NAVEGADOR = "Mozilla/5.0 (compatible; agente-licitaciones/1.0; seguimiento comercial)"


@dataclass
class Nota:
    titulo: str
    link: str
    medio: str
    fecha: datetime | None
    resumen: str
    texto: str = ""

    @property
    def contenido(self) -> str:
        return f"{self.titulo}. {self.texto or self.resumen}"


def _limpiar(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html or "", "html.parser").get_text(" ")).strip()


def _fecha(txt: str | None) -> datetime | None:
    if not txt:
        return None
    try:
        return parsedate_to_datetime(txt).replace(tzinfo=None)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def parsear_rss(xml: str | bytes, medio: str) -> list[Nota]:
    """RSS 2.0 o Atom. Google Noticias agrega <source> con el medio original."""
    raiz = ET.fromstring(xml)
    ns = {"a": "http://www.w3.org/2005/Atom", "c": "http://purl.org/rss/1.0/modules/content/"}
    notas = []
    for it in raiz.iter("item"):
        fuente = it.find("source")
        contenido = it.find("c:encoded", ns)
        notas.append(Nota(
            titulo=_limpiar(it.findtext("title", "")),
            link=(it.findtext("link") or "").strip(),
            medio=(fuente.text.strip() if fuente is not None and fuente.text else medio),
            fecha=_fecha(it.findtext("pubDate")),
            resumen=_limpiar(it.findtext("description", "")),
            texto=_limpiar(contenido.text) if contenido is not None and contenido.text else "",
        ))
    for en in raiz.iter("{http://www.w3.org/2005/Atom}entry"):
        link = en.find("a:link", ns)
        notas.append(Nota(
            titulo=_limpiar(en.findtext("a:title", "", ns)),
            link=link.get("href", "") if link is not None else "",
            medio=medio,
            fecha=_fecha(en.findtext("a:updated", None, ns) or en.findtext("a:published", None, ns)),
            resumen=_limpiar(en.findtext("a:summary", "", ns)),
            texto=_limpiar(en.findtext("a:content", "", ns)),
        ))
    return notas


def url_google_noticias(consulta: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(consulta)}&hl=es-419&gl=AR&ceid=AR:es-419"


def texto_de_nota(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for basura in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        basura.decompose()
    zona = soup.find("article") or soup.find("main") or soup
    parrafos = [re.sub(r"\s+", " ", p.get_text(" ")).strip() for p in zona.find_all(["p", "li", "h2", "h3"])]
    return " ".join(p for p in parrafos if len(p) > 40)[:15000]


class Lector:
    def __init__(self, config: dict, ahora: datetime | None = None):
        self.config = config
        self.ahora = ahora or datetime.now()
        self.desde = self.ahora - timedelta(days=config.get("dias_hacia_atras", 45))
        self.s = requests.Session()
        self.s.headers["User-Agent"] = NAVEGADOR
        self.estado: list[dict] = []

    def _rss(self, url: str, medio: str) -> list[Nota]:
        r = self.s.get(url, timeout=30)
        r.raise_for_status()
        return parsear_rss(r.content, medio)

    def notas(self) -> list[Nota]:
        todas: list[Nota] = []
        for m in self.config.get("medios", []):
            leidas, errores = 0, []
            if m.get("rss"):
                try:
                    n = self._rss(m["rss"], m["nombre"])
                    todas += n
                    leidas += len(n)
                except Exception as e:
                    errores.append(f"RSS: {e.__class__.__name__}")
            try:
                n = self._rss(url_google_noticias(f"site:{m['sitio']} (obra OR licitación OR proyecto OR inversión)"), m["nombre"])
                todas += n
                leidas += len(n)
            except Exception as e:
                errores.append(f"Google Noticias: {e.__class__.__name__}")
            self.estado.append({"nombre": m["nombre"], "estado": "ok" if leidas else "error",
                                "detalle": f"{leidas} notas" + (f" — {'; '.join(errores)}" if errores else "")})
        total_busq, err = 0, 0
        for q in self.config.get("busquedas", []):
            try:
                n = self._rss(url_google_noticias(q), "Google Noticias")
                todas += n
                total_busq += len(n)
            except Exception:
                err += 1
        if self.config.get("busquedas"):
            self.estado.append({"nombre": "Búsquedas generales (Google Noticias)", "estado": "ok" if total_busq else "error",
                                "detalle": f"{total_busq} notas" + (f", {err} búsquedas fallaron" if err else "")})
        # Fecha y duplicados por link
        vistas, res = set(), []
        for n in todas:
            if not n.link or n.link in vistas:
                continue
            if n.fecha and n.fecha < self.desde:
                continue
            vistas.add(n.link)
            res.append(n)
        return res

    def completar_texto(self, nota: Nota) -> None:
        """Baja el texto completo de la nota (si el link es directo al medio)."""
        if nota.texto or "news.google.com" in nota.link:
            return
        try:
            r = self.s.get(nota.link, timeout=25)
            if r.ok and "html" in r.headers.get("content-type", ""):
                nota.texto = texto_de_nota(r.text)
        except Exception:
            pass
