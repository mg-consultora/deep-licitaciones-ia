from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..modelo import Oportunidad

USER_AGENT = "agente-licitaciones/1.0 (seguimiento comercial; uso personal)"


@dataclass
class ResultadoFuente:
    nombre: str
    estado: str                       # "ok", "error", "pendiente_credenciales", "desactivada"
    detalle: str = ""
    oportunidades: list[Oportunidad] = field(default_factory=list)


class Fuente:
    """Interfaz común. Cada fuente devuelve oportunidades crudas; el filtro decide cuáles sirven."""

    nombre = "fuente"
    publica = True
    credenciales: list[str] = []      # variables de entorno que necesita (fuentes privadas)

    def __init__(self, config: dict):
        self.config = config

    def faltan_credenciales(self) -> list[str]:
        return [v for v in self.credenciales if not os.environ.get(v)]

    def obtener(self) -> ResultadoFuente:
        raise NotImplementedError
