"""Decide si un aviso le interesa a la empresa (UPS, baterías estacionarias, energía crítica)
y le pone el semáforo según las fechas."""
from __future__ import annotations

import re
from datetime import datetime

from .modelo import Oportunidad
from .texto import detectar_provincia, detectar_sector, normalizar


def _patron(termino: str) -> re.Pattern:
    """Los términos del config son texto común; 'regex:' al principio permite expresiones regulares."""
    if termino.startswith("regex:"):
        return re.compile(termino[6:], re.IGNORECASE)
    return re.compile(r"\b" + re.escape(normalizar(termino)), re.IGNORECASE)


def _etiqueta(termino: str) -> str:
    """Nombre legible para mostrar en el tablero."""
    if termino.startswith("regex:"):
        if "cc" in termino:
            return "tensión Vcc"
        return re.sub(r"\\[bs]\*?", "", termino[6:]).upper()
    return termino


class Filtro:
    def __init__(self, config: dict):
        rubros = config["rubros"]
        self.terminos = [(t, _patron(t), int(peso)) for t, peso in rubros["terminos"].items()]
        self.excluir = [(t, _patron(t)) for t in rubros.get("excluir", [])]
        self.excluir_titulo = [(t, _patron(t)) for t in rubros.get("excluir_titulo", [])]
        self.umbral = rubros.get("puntaje_minimo", 2)
        self.sectores: dict[str, list[str]] = config["sectores"]
        self.prioritarios = set(config.get("sectores_prioritarios", []))
        self.dias_amarillo = config.get("semaforo", {}).get("dias_amarillo", 7)

    def evaluar(self, op: Oportunidad) -> bool:
        """Calcula puntaje, sector y provincia. Devuelve True si la oportunidad es relevante."""
        t = normalizar(f"{op.titulo} {op.rubro} {op.organismo} {op.texto}")
        terminos, puntaje, fuerte = [], 0, False
        for nombre, p, peso in self.terminos:
            if p.search(t):
                terminos.append(_etiqueta(nombre))
                puntaje += peso
                fuerte = fuerte or peso >= 3
        titulo_rubro = normalizar(f"{op.titulo} {op.rubro}")
        exclusion_especifica = any(p.search(titulo_rubro) for _, p in self.excluir_titulo)
        if exclusion_especifica or (any(p.search(t) for _, p in self.excluir) and not fuerte):
            # Una exclusión específica en título/rubro prevalece incluso sobre
            # palabras fuertes; las exclusiones generales conservan el criterio anterior.
            puntaje = 0
        op.sector = op.sector or detectar_sector(t, self.sectores)
        if op.sector in self.prioritarios and puntaje:
            puntaje += 2
        op.provincia = op.provincia or detectar_provincia(f"{op.titulo} {op.organismo} {op.texto}")
        op.terminos, op.puntaje = terminos, puntaje
        return puntaje >= self.umbral

    def semaforo(self, op: Oportunidad, ahora: datetime | None = None) -> str:
        """verde = en plazo; amarillo = vence pronto; rojo = vencida; gris = sin fecha (verificar)."""
        ahora = ahora or datetime.now()
        limite = op.fecha_apertura or op.fecha_presentacion
        if op.estado in ("Adjudicación", "Preadjudicación", "Dictamen de evaluación"):
            return "rojo"
        if limite is None:
            return "gris"
        if limite < ahora:
            return "rojo"
        if (limite - ahora).days < self.dias_amarillo:
            return "amarillo"
        return "verde"
