"""Utilidades de texto: normalización, fechas en español, provincia y sector."""
from __future__ import annotations

import re
from datetime import datetime

_SIN_TILDES = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios simples (para comparar sin errores de tipeo)."""
    return re.sub(r"\s+", " ", (texto or "").translate(_SIN_TILDES).lower()).strip()


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_RE_NUM = re.compile(
    r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})(?!\d)"
    r"(?:\s*(?:a\s+las|,|-)?\s*(\d{1,2})[:.](\d{2})(?::\d{2})?)?",
    re.IGNORECASE,
)
_RE_LARGA = re.compile(
    r"(?<!\d)(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")\s+(?:de\s+|del\s+)?(\d{4})"
    r"(?:\s*(?:a\s+las|,|-)?\s*(\d{1,2})[:.](\d{2}))?",
    re.IGNORECASE,
)


def _armar(d: int, m: int, a: int, hh: str | None, mm: str | None) -> datetime | None:
    if a < 100:
        a += 2000
    try:
        return datetime(a, m, d, int(hh) if hh else 0, int(mm) if mm else 0)
    except ValueError:
        return None


def buscar_fechas(texto: str) -> list[tuple[int, datetime]]:
    """Todas las fechas del texto con su posición, en orden de aparición."""
    encontradas: list[tuple[int, datetime]] = []
    for m in _RE_NUM.finditer(texto):
        f = _armar(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4), m.group(5))
        if f:
            encontradas.append((m.start(), f))
    t = texto.translate(_SIN_TILDES)  # mismo largo que el original: las posiciones coinciden
    for m in _RE_LARGA.finditer(t):
        f = _armar(int(m.group(1)), MESES[m.group(2).lower()], int(m.group(3)), m.group(4), m.group(5))
        if f:
            encontradas.append((m.start(), f))
    encontradas.sort(key=lambda x: x[0])
    return encontradas


def primera_fecha(texto: str) -> datetime | None:
    f = buscar_fechas(texto)
    return f[0][1] if f else None


# ---------------------------------------------------------------------------
# Provincia y sector
# ---------------------------------------------------------------------------
PROVINCIAS = {
    "Buenos Aires": ["provincia de buenos aires", "pcia. de buenos aires", "pba", "la plata", "bahia blanca",
                     "mar del plata", "san justo", "lomas de zamora", "campana", "zarate", "san nicolas"],
    "CABA": ["ciudad autonoma de buenos aires", "c.a.b.a", "caba", "capital federal"],
    "Catamarca": ["catamarca"], "Chaco": ["chaco", "resistencia"], "Chubut": ["chubut", "comodoro rivadavia", "rawson", "trelew", "puerto madryn"],
    "Córdoba": ["cordoba", "rio cuarto", "embalse"], "Corrientes": ["corrientes", "ituzaingo"],
    "Entre Ríos": ["entre rios", "parana", "concordia"], "Formosa": ["formosa"], "Jujuy": ["jujuy"],
    "La Pampa": ["la pampa", "santa rosa"], "La Rioja": ["la rioja"], "Mendoza": ["mendoza", "lujan de cuyo"],
    "Misiones": ["misiones", "posadas"], "Neuquén": ["neuquen", "vaca muerta", "anelo", "añelo"],
    "Río Negro": ["rio negro", "bariloche", "viedma", "allen"], "Salta": ["salta"],
    "San Juan": ["san juan"], "San Luis": ["san luis", "villa mercedes"],
    "Santa Cruz": ["santa cruz", "rio gallegos", "el calafate", "caleta olivia"],
    "Santa Fe": ["santa fe", "rosario"], "Santiago del Estero": ["santiago del estero"],
    "Tierra del Fuego": ["tierra del fuego", "ushuaia", "rio grande"], "Tucumán": ["tucuman"],
}


def detectar_provincia(texto: str) -> str:
    t = normalizar(texto)
    mejor, pos = "", len(t) + 1
    for prov, claves in PROVINCIAS.items():
        for c in claves:
            m = re.search(r"\b" + re.escape(normalizar(c)) + r"\b", t)
            if m and m.start() < pos:
                mejor, pos = prov, m.start()
    return mejor or "Nacional / sin dato"


def detectar_sector(texto: str, sectores: dict[str, list[str]]) -> str:
    """Devuelve el sector cuyo vocabulario aparece más veces (energía, minería, oil & gas...)."""
    t = normalizar(texto)
    conteo: dict[str, int] = {}
    for sector, claves in sectores.items():
        n = sum(len(re.findall(r"\b" + re.escape(normalizar(c)), t)) for c in claves)
        if n:
            conteo[sector] = n
    if not conteo:
        return "Otros"
    return max(conteo, key=conteo.get)
