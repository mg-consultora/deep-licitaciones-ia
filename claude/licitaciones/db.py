"""Base de datos local (SQLite): recuerda cada proceso, sus fechas y los avisos ya vistos,
para detectar circulares nuevas y cambios de fecha entre una corrida y la siguiente."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .modelo import Oportunidad
from .texto import normalizar

ESQUEMA = """
CREATE TABLE IF NOT EXISTS procesos (
    clave TEXT PRIMARY KEY,
    datos TEXT NOT NULL,
    historial TEXT NOT NULL DEFAULT '[]',
    primera_vez TEXT NOT NULL,
    ultima_vez TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avisos (
    id TEXT PRIMARY KEY,
    clave TEXT NOT NULL,
    visto TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    clave TEXT NOT NULL,
    tipo TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    link TEXT,
    notificada INTEGER NOT NULL DEFAULT 0
);
"""

CAMPOS_FECHA = ("fecha_publicacion", "fecha_limite_consultas", "fecha_presentacion", "fecha_apertura")
NOMBRES = {"fecha_apertura": "apertura de sobres", "fecha_presentacion": "presentación de ofertas",
           "fecha_limite_consultas": "límite de consultas"}


def _fmt(v: str | None) -> str:
    if not v:
        return "sin fecha"
    return datetime.fromisoformat(v).strftime("%d/%m/%Y %H:%M").replace(" 00:00", "")


class Base:
    def __init__(self, ruta: Path):
        self.con = sqlite3.connect(ruta)
        self.con.executescript(ESQUEMA)

    def conoce(self, clave: str) -> bool:
        return self.con.execute("SELECT 1 FROM procesos WHERE clave=?", (clave,)).fetchone() is not None

    def registrar(self, op: Oportunidad, avisar_nuevas: bool = False) -> list[dict]:
        """Guarda la oportunidad y devuelve las alertas que genera (circular nueva, fecha cambiada)."""
        id_aviso = hashlib.sha1(normalizar(op.texto or op.titulo).encode()).hexdigest()
        if self.con.execute("SELECT 1 FROM avisos WHERE id=?", (id_aviso,)).fetchone():
            return []          # el mismo aviso republicado otro día: ya lo procesamos
        ahora = datetime.now().isoformat(timespec="minutes")
        nuevo = op.como_dict()
        nuevo.pop("texto", None)
        clave = op.clave
        alertas: list[dict] = []
        hito = {"fecha": nuevo["fecha_publicacion"] or ahora, "estado": op.estado, "link": op.link}

        fila = self.con.execute("SELECT datos, historial FROM procesos WHERE clave=?", (clave,)).fetchone()
        if fila is None:
            if op.es_circular:
                alertas.append(self._alerta(clave, "Circular nueva", f"Circular publicada: {op.titulo}", op.link))
            elif avisar_nuevas:
                alertas.append(self._alerta(clave, "Oportunidad nueva", op.titulo, op.link))
            self.con.execute("INSERT INTO procesos VALUES (?,?,?,?,?)",
                             (clave, json.dumps(nuevo, ensure_ascii=False), json.dumps([hito]), ahora, ahora))
        else:
            viejo = json.loads(fila[0])
            historial = json.loads(fila[1])
            if op.es_circular:
                alertas.append(self._alerta(clave, "Circular nueva", f"{viejo['titulo'][:120].rstrip()} — nueva circular", op.link))
            for campo in ("fecha_apertura", "fecha_presentacion", "fecha_limite_consultas"):
                if nuevo[campo] and viejo.get(campo) and nuevo[campo] != viejo[campo]:
                    alertas.append(self._alerta(
                        clave, "Fecha modificada",
                        f"{viejo['titulo'][:120].rstrip()} — {NOMBRES[campo]}: {_fmt(viejo[campo])} → {_fmt(nuevo[campo])}",
                        op.link))
            # Combinar. Una circular solo actualiza plazos; un aviso completo actualiza todo lo que traiga.
            combinado = dict(viejo)
            if op.es_circular:
                for k in ("fecha_limite_consultas", "fecha_presentacion", "fecha_apertura"):
                    if nuevo[k]:
                        combinado[k] = nuevo[k]
                if combinado.get("estado") in (None, "", "Convocatoria", "Circular"):
                    combinado["estado"] = "Convocatoria con circulares"
            else:
                vacios = (None, "", [], "Otros", "Nacional / sin dato")
                for k, v in nuevo.items():
                    if v in vacios or (k == "fecha_publicacion" and viejo.get(k)):
                        continue
                    combinado[k] = v
            historial.append(hito)
            self.con.execute("UPDATE procesos SET datos=?, historial=?, ultima_vez=? WHERE clave=?",
                             (json.dumps(combinado, ensure_ascii=False), json.dumps(historial), ahora, clave))
        self.con.execute("INSERT INTO avisos VALUES (?,?,?)", (id_aviso, clave, ahora))
        self.con.commit()
        return alertas

    def _alerta(self, clave: str, tipo: str, mensaje: str, link: str) -> dict:
        ahora = datetime.now().isoformat(timespec="minutes")
        self.con.execute("INSERT INTO alertas (fecha, clave, tipo, mensaje, link) VALUES (?,?,?,?,?)",
                         (ahora, clave, tipo, mensaje, link))
        return {"fecha": ahora, "clave": clave, "tipo": tipo, "mensaje": mensaje, "link": link}

    def procesos(self) -> list[dict]:
        res = []
        for datos, historial, primera, ultima in self.con.execute(
                "SELECT datos, historial, primera_vez, ultima_vez FROM procesos"):
            d = json.loads(datos)
            d["historial"] = json.loads(historial)
            d["detectado"] = primera
            res.append(d)
        return res

    def alertas_recientes(self, limite: int = 50) -> list[dict]:
        cur = self.con.execute("SELECT fecha, clave, tipo, mensaje, link FROM alertas ORDER BY id DESC LIMIT ?", (limite,))
        return [dict(zip(("fecha", "clave", "tipo", "mensaje", "link"), f)) for f in cur]

    def pendientes_de_notificar(self) -> list[dict]:
        cur = self.con.execute("SELECT id, fecha, tipo, mensaje, link FROM alertas WHERE notificada=0 ORDER BY id")
        return [dict(zip(("id", "fecha", "tipo", "mensaje", "link"), f)) for f in cur]

    def marcar_notificadas(self, ids: list[int]) -> None:
        self.con.executemany("UPDATE alertas SET notificada=1 WHERE id=?", [(i,) for i in ids])
        self.con.commit()
