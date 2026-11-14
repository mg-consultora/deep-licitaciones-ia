"""Agente de licitaciones — UPS, baterías estacionarias, rectificadores y energía crítica.

Uso:
    python agente.py              revisa todas las fuentes, actualiza el tablero y avisa novedades
    python agente.py --dias 5     revisa solo los últimos 5 días del Boletín Oficial
    python agente.py --demo       arma un tablero de muestra con datos de ejemplo (sin internet)
    python agente.py --abrir      además abre el tablero en el navegador
"""
from __future__ import annotations

import argparse
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
    tablero.generar(salida_html, base.procesos(), base.alertas_recientes(), estado_fuentes, filtro, nota=nota)
    print(f"Tablero: {salida_html}")
    if args.abrir:
        webbrowser.open(salida_html.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
