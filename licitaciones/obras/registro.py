"""Memoria del módulo de obras (salida/obras.db). Separada de la base de licitaciones públicas.

- Nunca borra registros (condición 7).
- Une duplicados: la misma obra contada por varios medios queda en un solo registro con todas sus fuentes.
- Si una fecha cambia, guarda la anterior en el historial y genera una novedad.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .texto_base import normalizar
from .extraer import EN_EJECUCION, LIC_ABIERTA, LIC_ANUNCIADA, LIC_CERRADA, NO_INFO, PROYECTO

ESQUEMA = """
CREATE TABLE IF NOT EXISTS proyectos (clave TEXT PRIMARY KEY, datos TEXT NOT NULL, primera_vez TEXT NOT NULL, ultima_vez TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notas (link TEXT PRIMARY KEY, clave TEXT, vista TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS novedades (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, clave TEXT, tipo TEXT, mensaje TEXT, link TEXT);
"""
RANGO = {PROYECTO: 0, LIC_CERRADA: 1, LIC_ANUNCIADA: 2, EN_EJECUCION: 3, LIC_ABIERTA: 4}
_GENERICAS = r"\b(proyecto|obra|obras|mina|yacimiento|cobre|litio|oro|plata)\b"


def clave_obra(obra: str) -> str:
    n = normalizar(re.sub(r"\(.*?\)", " ", obra))
    n = re.sub(_GENERICAS, " ", n)
    n = re.sub(r"[^\w ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


class Registro:
    def __init__(self, ruta: Path):
        self.con = sqlite3.connect(ruta)
        self.con.executescript(ESQUEMA)
        self.ahora = datetime.now().isoformat(timespec="minutes")

    def nota_vista(self, link: str) -> bool:
        return self.con.execute("SELECT 1 FROM notas WHERE link=?", (link,)).fetchone() is not None

    def _buscar(self, clave: str) -> tuple[str, dict] | None:
        fila = self.con.execute("SELECT clave, datos FROM proyectos WHERE clave=?", (clave,)).fetchone()
        if fila:
            return fila[0], json.loads(fila[1])
        if len(clave) >= 8:
            for k, d in self.con.execute("SELECT clave, datos FROM proyectos"):
                corta, larga = sorted([k, clave], key=len)
                if len(corta) >= 8 and re.search(r"\b" + re.escape(corta) + r"\b", larga):
                    return k, json.loads(d)
        return None

    def _novedad(self, clave: str, tipo: str, mensaje: str, link: str) -> None:
        self.con.execute("INSERT INTO novedades (fecha, clave, tipo, mensaje, link) VALUES (?,?,?,?,?)",
                         (self.ahora, clave, tipo, mensaje, link))

    def guardar(self, reg: dict, link_nota: str = "") -> str:
        """Agrega o une un registro. Devuelve la clave con la que quedó guardado."""
        if reg.get("obra_identificada", True):
            clave = clave_obra(reg["obra"])
        else:
            clave = "nota-" + hashlib.sha1(link_nota.encode()).hexdigest()[:12]
        existente = self._buscar(clave) if clave else None
        if existente is None:
            self.con.execute("INSERT INTO proyectos VALUES (?,?,?,?)",
                             (clave, json.dumps(reg, ensure_ascii=False), self.ahora, self.ahora))
            if not reg.get("verificado_manual"):
                tipo = "Licitación abierta" if reg["tipo"] == LIC_ABIERTA else "Obra nueva detectada"
                self._novedad(clave, tipo, reg["obra"], link_nota)
        else:
            clave, viejo = existente
            unido = self._unir(clave, viejo, reg, link_nota)
            self.con.execute("UPDATE proyectos SET datos=?, ultima_vez=? WHERE clave=?",
                             (json.dumps(unido, ensure_ascii=False), self.ahora, clave))
        if link_nota:
            self.con.execute("INSERT OR IGNORE INTO notas VALUES (?,?,?)", (link_nota, clave, self.ahora))
        self.con.commit()
        return clave

    def _unir(self, clave: str, viejo: dict, nuevo: dict, link: str) -> dict:
        r = dict(viejo)
        manual = viejo.get("verificado_manual")
        if nuevo.get("verificado_manual"):
            # El registro manual manda: reemplaza los campos, conserva las fuentes y fechas leídas en medios.
            fuentes_auto = [f for f in viejo.get("fuentes", []) if f.get("link") not in {x["link"] for x in nuevo["fuentes"]}]
            r = dict(nuevo)
            r["fuentes"] = nuevo["fuentes"] + fuentes_auto
            r["fechas"] = {**viejo.get("fechas", {}), **nuevo.get("fechas", {})}
            r["empresas"] = sorted(set(viejo.get("empresas", [])) | set(nuevo.get("empresas", [])))
            r["propias"] = sorted(set(viejo.get("propias", [])) | set(nuevo.get("propias", [])))
            return r
        for k in ("operadora", "desarrolladora", "ingenieria", "epc", "provincia", "localidad", "presupuesto", "sector"):
            if r.get(k) in (None, "", NO_INFO, "Otros") and nuevo.get(k) not in (None, "", NO_INFO):
                r[k] = nuevo[k]
        for k in ("subobras", "tipo_obra", "equipos", "empresas", "propias"):
            r[k] = list(dict.fromkeys((r.get(k) or []) + (nuevo.get(k) or [])))
        links = {f["link"] for f in r.get("fuentes", [])}
        r["fuentes"] = r.get("fuentes", []) + [f for f in nuevo.get("fuentes", []) if f["link"] not in links]
        fechas = dict(r.get("fechas", {}))
        historial = list(r.get("historial_fechas", []))
        for campo, f in nuevo.get("fechas", {}).items():
            previa = fechas.get(campo)
            if previa is None:
                fechas[campo] = f
            elif normalizar(previa["texto"]) != normalizar(f["texto"]):
                historial.append({"campo": campo, "antes": previa["texto"], "despues": f["texto"], "fuente": f["fuente"], "fecha": self.ahora[:10]})
                fechas[campo] = f
                self._novedad(clave, "Fecha modificada", f"{r['obra']}: {previa['texto']} → {f['texto']}", f["fuente"])
        r["fechas"], r["historial_fechas"] = fechas, historial
        if not manual and RANGO.get(nuevo["tipo"], 0) > RANGO.get(r.get("tipo"), 0):
            if nuevo["tipo"] == LIC_ABIERTA:
                self._novedad(clave, "Licitación abierta", r["obra"], link)
            r["tipo"], r["estado"] = nuevo["tipo"], nuevo["estado"]
        elif not manual and nuevo.get("estado") and nuevo["estado"] not in (r.get("estado") or ""):
            partes = [p for p in (r.get("estado") or "").split(" · ") + nuevo["estado"].split(" · ") if p and p != "Anunciado en medios"]
            r["estado"] = " · ".join(dict.fromkeys(partes)) or r.get("estado")
        return r

    def proyectos(self) -> list[dict]:
        res = []
        for clave, datos, primera, ultima in self.con.execute("SELECT clave, datos, primera_vez, ultima_vez FROM proyectos"):
            d = json.loads(datos)
            d.update({"clave": clave, "detectado": primera[:10], "actualizado": ultima[:10]})
            res.append(d)
        return res

    def novedades(self, limite: int = 25) -> list[dict]:
        cur = self.con.execute("SELECT fecha, tipo, mensaje, link FROM novedades ORDER BY id DESC LIMIT ?", (limite,))
        return [dict(zip(("fecha", "tipo", "mensaje", "link"), f)) for f in cur]
