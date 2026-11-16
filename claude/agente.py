"""Agente de licitaciones — UPS, baterías estacionarias, rectificadores y energía crítica.

Uso:
    python agente.py              revisa todas las fuentes, actualiza el tablero y avisa novedades
    python agente.py --dias 5     revisa solo los últimos 5 días del Boletín Oficial
    python agente.py --demo       arma un tablero de muestra con datos de ejemplo (sin internet)
    python agente.py --abrir      además abre el tablero en el navegador
"""
from __future__ import annotations

import argparse
import re
import unicodedata
from datetime import timedelta
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import yaml

from licitaciones import notificar, tablero
from licitaciones.db import Base
from licitaciones.filtros import Filtro
from licitaciones.fuentes.base import ResultadoFuente
from licitaciones.fuentes.boletin_oficial import BoletinOficial, parsear_avisos
from licitaciones.fuentes.paginas_web import PaginasWeb
from licitaciones.fuentes.privadas import CorreoInvitaciones, portales_privados

RAIZ = Path(__file__).resolve().parent
SALIDA = RAIZ / "salida"


def cargar_env(ruta: Path) -> None:
    """Lee el archivo .env (usuarios y claves) sin depender de librerías extra."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def fuentes_activas(config: dict, dias: int) -> list:
    activas = config.get("fuentes", {})
    lista = []
    if activas.get("boletin_oficial", True):
        lista.append(BoletinOficial(config, SALIDA / "cache", dias))
    if activas.get("paginas_publicas", True):
        lista.append(PaginasWeb(config))
    if activas.get("correo_invitaciones", True):
        lista.append(CorreoInvitaciones(config))
    if activas.get("portales_privados", True):
        lista += portales_privados(config)
    return lista


def procesar(resultados: list[ResultadoFuente], config: dict, base: Base, filtro: Filtro) -> tuple[int, int, list[dict]]:
    ops = [op for r in resultados for op in r.oportunidades]
    for op in ops:
        op._relevante = filtro.evaluar(op)
    # Primero los avisos más viejos: así la convocatoria entra antes que sus circulares.
    ops.sort(key=lambda o: o.fecha_publicacion or datetime.min)
    alertas, relevantes = [], 0
    for op in ops:
        # Una circular casi nunca repite los rubros ("se prorroga la apertura…"): si es de un
        # proceso que ya seguimos, entra igual.
        if op._relevante or (op.es_circular and base.conoce(op.clave)):
            relevantes += 1
            alertas += base.registrar(op, config.get("avisar_nuevas", False))
    return len(ops), relevantes, alertas



def _sin_acentos(valor: object) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(valor or "").lower()) if not unicodedata.combining(c))


def _fecha_segura(valor: object):
    if not valor:
        return None
    try:
        fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if fecha.year not in (2026, 2027):
            return None
        return fecha.replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _publicables(procesos: list[dict]) -> list[dict]:
    """Filtra SOLO la vista pública; no borra SQLite ni el historial de circulares."""
    hoy = datetime.now()
    salida = []
    descartes = {"fuera_de_rubro": 0, "sin_plazo_verificable": 0, "vencidas": 0}
    prohibidos = (
        r"\baeronautic", r"\bavion(?:es)?\b", r"\baeronave", r"\baeroespacial",
        r"\bhelicopter", r"\bautomotor", r"\bvehicul", r"\bmotocicl",
        r"\bcamion(?:es)?\b", r"\bpatruller", r"\bmoviles policial",
        r"\bcartuchos? de bateria", r"\bups informatic", r"\bcomputador",
        r"\bnotebook", r"\bimpresora", r"\btelefonos? celulares?",
    )
    for p in procesos:
        texto = _sin_acentos(" ".join(str(p.get(k) or "") for k in
                            ("titulo", "organismo", "rubro", "tipo_contratacion")))
        if any(re.search(patron, texto) for patron in prohibidos):
            descartes["fuera_de_rubro"] += 1
            continue
        estado = _sin_acentos(p.get("estado"))
        if any(t in estado for t in ("adjudic", "preadjudic", "finaliz", "desiert", "anulad", "cancelad", "cerrad")):
            descartes["vencidas"] += 1
            continue
        # El cierre de PRESENTACION tiene prioridad sobre apertura de sobres.
        presentacion = _fecha_segura(p.get("fecha_presentacion"))
        apertura = _fecha_segura(p.get("fecha_apertura"))
        limite = presentacion or apertura
        if not limite:
            descartes["sin_plazo_verificable"] += 1
            continue
        if limite < hoy:
            descartes["vencidas"] += 1
            continue
        limpio = dict(p)
        # La plantilla antigua prioriza apertura; unificamos el plazo de referencia
        # sin alterar los datos persistidos en SQLite.
        limpio["fecha_apertura"] = limite.isoformat(timespec="minutes")
        if not presentacion:
            limpio["fecha_presentacion"] = None
        # No mostrar una fecha de publicación imposible o anterior a 2026.
        if not _fecha_segura(p.get("fecha_publicacion")):
            limpio["fecha_publicacion"] = None
        salida.append(limpio)
    print(f"Vista pública: {len(salida)} vigentes; descartes: {descartes}")
    return salida


def _anexar_maestra_si_existe(ruta_html: Path) -> None:
    # Compatibilidad con la ubicación indicada inicialmente y con la del ZIP.
    rutas = (RAIZ / "datos" / "base_maestra_deep.json",
             RAIZ / "licitaciones" / "base_maestra_deep.json")
    for ruta in rutas:
        if ruta.is_file():
            try:
                from licitaciones.base_maestra import anexar_base_maestra
                anexar_base_maestra(ruta_html, ruta)
                print(f"Base maestra de referencia cargada: {ruta}")
            except Exception as exc:
                print(f"AVISO: no se pudo anexar la base maestra: {exc}")
            return
    print("AVISO: base maestra JSON no encontrada; se conserva el tablero sin el anexo")

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, help="días hacia atrás en el Boletín Oficial")
    ap.add_argument("--demo", action="store_true", help="tablero de muestra con datos de ejemplo")
    ap.add_argument("--sin-avisos", action="store_true", help="no mandar correo ni Telegram")
    ap.add_argument("--abrir", action="store_true", help="abrir el tablero al terminar")
    args = ap.parse_args()

    config = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    cargar_env(RAIZ / ".env")
    SALIDA.mkdir(exist_ok=True)
    filtro = Filtro(config)

    if args.demo:
        ruta_db = SALIDA / "demo.db"
        ruta_db.unlink(missing_ok=True)
        base = Base(ruta_db)
        paginas = (RAIZ / "tests" / "boletin_ejemplo.txt").read_text(encoding="utf-8").split("=====PAGINA=====")
        avisos = parsear_avisos(paginas, "https://otslist.boletinoficial.gob.ar/ots/")
        resultados = [ResultadoFuente("Boletín Oficial – 3ª sección (DATOS DE EJEMPLO)", "ok",
                                      f"{len(avisos)} avisos de ejemplo", avisos)]
        resultados += [f.obtener() for f in [CorreoInvitaciones(config)] + portales_privados(config)]
        nota = ("<b>Tablero de muestra con datos de ejemplo.</b> Los organismos marcados (EJEMPLO) no son "
                "licitaciones reales: sirven para ver cómo se ve el semáforo, las circulares y los filtros. "
                "Los datos reales aparecen al correr el agente sin <code>--demo</code>.")
        salida_html = SALIDA / "tablero_demo.html"
    else:
        base = Base(SALIDA / "licitaciones.db")
        dias = args.dias or config.get("dias_hacia_atras", 30)
        resultados = []
        for fuente in fuentes_activas(config, dias):
            print(f"→ {fuente.nombre}…", flush=True)
            r = fuente.obtener()
            print(f"   {r.estado}: {r.detalle}")
            resultados.append(r)
        nota = ""
        salida_html = SALIDA / "tablero.html"

    total, relevantes, alertas = procesar(resultados, config, base, filtro)
    print(f"\n{total} avisos revisados · {relevantes} relevantes para UPS/baterías/energía · {len(alertas)} novedades")

    if not args.demo and not args.sin_avisos:
        pendientes = base.pendientes_de_notificar()
        try:
            canales = notificar.enviar(pendientes)
            if canales:
                base.marcar_notificadas([a["id"] for a in pendientes])
                print(f"Avisos enviados por {', '.join(canales)}")
        except Exception as e:
            print(f"No se pudieron mandar los avisos: {e}")

    estado_fuentes = [{"nombre": r.nombre, "estado": r.estado, "detalle": r.detalle} for r in resultados]
    tablero.generar(salida_html, _publicables(base.procesos()) if not args.demo else base.procesos(),
                   base.alertas_recientes(), estado_fuentes, filtro, nota=nota)
    if not args.demo:
        _anexar_maestra_si_existe(salida_html)
    print(f"Tablero: {salida_html}")
    if args.abrir:
        webbrowser.open(salida_html.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
