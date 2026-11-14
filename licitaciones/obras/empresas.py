"""Reconoce empresas en el texto de una nota.

- Empresas prioritarias (datos/empresas_prioritarias.yaml): nombres públicos, se muestran.
- Empresas propias (datos/empresas_propias.txt): salen del Excel de contactos y se guardan
  como huellas cifradas. Así el repositorio no expone la cartera: el agente solo sabe que una
  empresa "es de la lista" cuando su nombre aparece escrito en una noticia.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SAL = "deep-licitaciones-v1"
_SUFIJOS = re.compile(
    r"\b(s\.?\s?a\.?\s?u\.?|s\.?\s?a\.?\s?i\.?\s?c\.?|s\.?\s?a\.?\s?c\.?\s?i\.?\s?s\.?|s\.?\s?a\.?\s?c\.?\s?i\.?|"
    r"s\.?\s?r\.?\s?l\.?|s\.?\s?a\.?\s?s\.?|s\.?\s?a\.?|sociedad anonima|ltda\.?|inc\.?|llc|y\s+cia\.?|cia\.?|"
    r"sacifi|saic|sacis|srl|sas|sa)\s*$"
)


def norm_empresa(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^\w&\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for _ in range(2):
        s = _SUFIJOS.sub("", s).strip(" -,.")
    return s


def huella(nombre_normalizado: str) -> str:
    return hashlib.sha256((SAL + nombre_normalizado).encode()).hexdigest()[:20]


@dataclass
class Empresa:
    nombre: str
    sector: str
    portal: str = ""
    origen: str = ""
    patrones: list[re.Pattern] = field(default_factory=list)


class Catalogo:
    def __init__(self, raiz: Path):
        datos = yaml.safe_load((raiz / "datos" / "empresas_prioritarias.yaml").read_text(encoding="utf-8"))
        self.prioritarias: list[Empresa] = []
        for sector, lista in datos.items():
            for e in lista:
                emp = Empresa(e["nombre"], sector, e.get("portal", ""), e.get("origen", ""))
                for alias in [e["nombre"], *e.get("alias", [])]:
                    # Nombres de una palabra ("Vista", "Mega", "Shell") o siglas ("YPF") se buscan
                    # respetando mayúsculas, para no confundirlos con palabras comunes.
                    texto = re.escape(alias).replace("\\ ", r"\s+")
                    flags = re.IGNORECASE if " " in alias else 0
                    emp.patrones.append(re.compile(r"(?<![\w])" + texto + r"(?![\w])", flags))
                self.prioritarias.append(emp)
        ruta = raiz / "datos" / "empresas_propias.txt"
        self.huellas_propias: set[str] = set()
        if ruta.exists():
            self.huellas_propias = {l.strip() for l in ruta.read_text(encoding="utf-8").splitlines()
                                    if l.strip() and not l.startswith("#")}

    def prioritarias_en(self, texto: str) -> list[tuple[int, Empresa]]:
        """Empresas prioritarias mencionadas, con la posición de la primera mención."""
        res = []
        for emp in self.prioritarias:
            pos = min((m.start() for p in emp.patrones for m in [p.search(texto)] if m), default=None)
            if pos is not None:
                res.append((pos, emp))
        res.sort(key=lambda x: x[0])
        return res

    def propias_en(self, texto: str) -> list[str]:
        """Nombres (tal como aparecen en la nota) de empresas de la lista propia."""
        if not self.huellas_propias:
            return []
        # Candidatos: secuencias de 1 a 6 palabras que empiezan con mayúscula (nombres propios).
        palabras = list(re.finditer(r"[A-ZÁÉÍÓÚÑ0-9][\w&.\-]*", texto))
        encontrados: dict[str, str] = {}
        for i in range(len(palabras)):
            for largo in range(1, 7):
                j = i + largo - 1
                if j >= len(palabras):
                    break
                # Solo palabras contiguas (separadas por espacios simples o "y"/"de").
                tramo = texto[palabras[i].start(): palabras[j].end()]
                if len(tramo) > 70 or re.search(r"[,;:()\n]", tramo):
                    break
                n = norm_empresa(tramo)
                if len(n) >= 6 and huella(n) in self.huellas_propias:
                    encontrados[n] = tramo
        return sorted(set(encontrados.values()))
