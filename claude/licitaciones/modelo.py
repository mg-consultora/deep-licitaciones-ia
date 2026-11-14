from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Oportunidad:
    """Una licitación u oportunidad comercial, venga de la fuente que venga."""

    fuente: str                      # "Boletín Oficial", "Correo (Ariba)", "Página: CAMMESA"...
    titulo: str                      # nombre de la obra / objeto
    organismo: str = ""
    numero_proceso: str = ""
    tipo_contratacion: str = ""      # Licitación Pública, Privada, Concurso...
    estado: str = ""                 # Convocatoria, Circular, Preadjudicación, Adjudicación...
    provincia: str = ""
    sector: str = ""
    rubro: str = ""
    expediente: str = ""
    fecha_publicacion: datetime | None = None
    fecha_limite_consultas: datetime | None = None
    fecha_presentacion: datetime | None = None
    fecha_apertura: datetime | None = None
    link: str = ""
    texto: str = ""                  # texto completo del aviso (para auditar el filtro)
    es_circular: bool = False
    terminos: list[str] = field(default_factory=list)   # rubros que la hicieron relevante
    puntaje: int = 0

    @property
    def clave(self) -> str:
        """Identifica el proceso para seguirlo entre avisos (convocatoria, circulares, prórrogas)."""
        base = f"{self.organismo}|{self.numero_proceso}".lower()
        if not self.numero_proceso:
            base = f"{self.fuente}|{self.titulo}".lower()
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

    def como_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat(timespec="minutes")
        d["clave"] = self.clave
        return d
