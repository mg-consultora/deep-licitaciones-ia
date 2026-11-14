"""Módulo "Obras futuras y oportunidades privadas".

Corre DESPUÉS del agente de licitaciones y agrega su pestaña al mismo tablero.
No modifica ningún archivo del agente original ni su base de datos.

Uso:
    python obras.py                          actualiza obras y agrega la pestaña a salida/tablero.html
    python obras.py --html docs/index.html   lo mismo sobre el tablero publicado (lo usa GitHub)
    python obras.py --demo                   muestra con notas de ejemplo (sin internet)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

import yaml

from licitaciones.obras.texto_base import normalizar
from licitaciones.obras import seccion
from licitaciones.obras.empresas import Catalogo
from licitaciones.obras.extraer import NO_INFO, Extractor, completar_con_ia
from licitaciones.obras.fuentes import Lector, Nota
from licitaciones.obras.registro import Registro, clave_obra

RAIZ = Path(__file__).resolve().parent
SALIDA = RAIZ / "salida"


def cargar_env(ruta: Path) -> None:
    """Lee .env (claves locales). Copia propia para no depender de agente.py."""
    import os
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def registros_manuales(ahora: datetime) -> list[dict]:
    ruta = RAIZ / "datos" / "obras_verificadas.yaml"
    if not ruta.exists():
        return []
    res = []
    for o in yaml.safe_load(ruta.read_text(encoding="utf-8")) or []:
        fechas = {}
        for tipo, grupo in (("confirmada", o.get("fechas_confirmadas") or {}), ("estimada", o.get("fechas_estimadas") or {})):
            for campo, texto in grupo.items():
                fechas[campo] = {"texto": str(texto), "tipo": tipo, "fuente": o.get("fuente", ""), "frase": ""}
        fuentes = [{"titulo": "Fuente verificada", "link": o.get("fuente", ""), "medio": "Registro manual",
                    "fecha_nota": "", "fecha_verificacion": str(o.get("fecha_verificacion", ""))}]
        fuentes += [{"titulo": "Fuente adicional", "link": l, "medio": "Registro manual", "fecha_nota": "",
                     "fecha_verificacion": str(o.get("fecha_verificacion", ""))} for l in o.get("fuentes_extra", [])]
        res.append({
            "obra": o["obra"], "obra_identificada": True, "subobras": o.get("subobras", []),
            "operadora": o.get("operadora", NO_INFO), "desarrolladora": o.get("desarrolladora", NO_INFO),
            "ingenieria": o.get("ingenieria", NO_INFO), "epc": o.get("epc", NO_INFO),
            "provincia": o.get("provincia", NO_INFO), "localidad": o.get("localidad", NO_INFO),
            "sector": o.get("sector", NO_INFO), "tipo_obra": o.get("tipo_obra", []),
            "tipo": o.get("tipo", "Proyecto anunciado"), "estado": o.get("estado", ""),
            "presupuesto": o.get("presupuesto", NO_INFO), "fechas": fechas,
            "equipos": o.get("equipos", []), "empresas": [], "propias": [], "fuentes": fuentes,
            "verificado_manual": True, "lectura": "manual", "nota": o.get("nota", ""),
        })
    return res


def completar_equipos(reg: dict, extractor: Extractor) -> None:
    """Para registros manuales sin equipos cargados, los deduce del tipo de obra (rotulados como potenciales)."""
    if reg.get("equipos"):
        return
    info = extractor.relevante(Nota(reg["obra"], "", "", None, f"{reg['obra']} {reg.get('estado', '')} {reg.get('sector', '')}"))[1]
    reg["tipo_obra"] = reg.get("tipo_obra") or info["tipos"]
    for t in reg["tipo_obra"]:
        for e in extractor.tipos.get(t, (None, []))[1]:
            if e not in reg["equipos"]:
                reg["equipos"].append(e)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", help="tablero al que se agrega la pestaña (por defecto salida/tablero.html)")
    ap.add_argument("--demo", action="store_true", help="notas de ejemplo, sin internet")
    args = ap.parse_args()

    config = yaml.safe_load((RAIZ / "config_obras.yaml").read_text(encoding="utf-8"))
    if not config.get("activo", True):
        print("Módulo de obras desactivado en config_obras.yaml")
        return 0
    cargar_env(RAIZ / ".env")
    SALIDA.mkdir(exist_ok=True)
    ahora = datetime.now()
    catalogo = Catalogo(RAIZ)
    extractor = Extractor(config, catalogo, ahora)

    if args.demo:
        ruta_db = SALIDA / "obras_demo.db"
        ruta_db.unlink(missing_ok=True)
        ejemplos = json.loads((RAIZ / "tests" / "notas_ejemplo.json").read_text(encoding="utf-8"))
        notas = [Nota(n["titulo"], n["link"], n["medio"], datetime.fromisoformat(n["fecha"]), "", n["texto"]) for n in ejemplos]
        lector = None
        estado_fuentes = [{"nombre": "Notas de ejemplo (DEMO)", "estado": "ok", "detalle": f"{len(notas)} notas inventadas para mostrar el funcionamiento"}]
        html_destino = Path(args.html) if args.html else SALIDA / "tablero_demo.html"
        nota_pantalla = ("<b>Pestaña de muestra.</b> Las obras marcadas (EJEMPLO) salen de notas inventadas para mostrar cómo se ve. "
                         "Las marcadas <i>Verificado manualmente</i> son reales, con su fuente.")
    else:
        ruta_db = SALIDA / "obras.db"
        lector = Lector(config, ahora)
        print("→ Leyendo medios y búsquedas…", flush=True)
        notas = lector.notas()
        estado_fuentes = lector.estado
        html_destino = Path(args.html) if args.html else SALIDA / "tablero.html"
        nota_pantalla = ""

    reg = Registro(ruta_db)
    for manual in registros_manuales(ahora):
        completar_equipos(manual, extractor)
        reg.guardar(manual)

    nuevas = relevantes = con_ia = 0
    max_ia = config.get("ia", {}).get("max_notas_por_corrida", 40)
    for nota in notas:
        if reg.nota_vista(nota.link):
            continue
        nuevas += 1
        ok, info = extractor.relevante(nota)
        # Una nota sobre una obra que ya seguimos entra aunque repita poco (por ejemplo, una postergación).
        conocida = bool(info["tipos"]) and reg._buscar(clave_obra(extractor.nombre_obra(nota))) is not None \
            if extractor.nombre_obra(nota) else False
        if not ok and not conocida:
            continue
        if lector and not conocida:
            lector.completar_texto(nota)            # texto completo para extraer mejor
            ok, info = extractor.relevante(nota)
            if not ok:
                continue
        relevantes += 1
        registro = extractor.extraer(nota, info)
        if con_ia < max_ia:
            try:
                antes = registro.get("lectura")
                registro = completar_con_ia(registro, nota, config.get("ia", {}).get("modelo", "claude-haiku-5-5"))
                if registro.get("lectura") != antes:
                    con_ia += 1
                    registro["tipo"], registro["estado"] = extractor._clasificar(normalizar(nota.contenido), registro["fechas"])
            except Exception as e:
                print(f"   (IA no disponible para una nota: {e.__class__.__name__})")
        reg.guardar(registro, nota.link)

    proyectos = reg.proyectos()
    print(f"{len(notas)} notas leídas · {nuevas} nuevas · {relevantes} con obras · {con_ia} leídas con IA · {len(proyectos)} obras en memoria")

    if html_destino.exists():
        html = html_destino.read_text(encoding="utf-8")
        html = seccion.insertar(html, proyectos, reg.novedades(), estado_fuentes,
                                config.get("mostrar_nombres_empresas_propias", False), nota_pantalla)
        html_destino.write_text(html, encoding="utf-8")
    else:
        html_destino.parent.mkdir(parents=True, exist_ok=True)
        seccion.pagina_sola(html_destino, proyectos, reg.novedades(), estado_fuentes,
                            config.get("mostrar_nombres_empresas_propias", False), nota_pantalla)
    print(f"Pestaña de obras agregada a: {html_destino}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Si el módulo nuevo falla, el tablero de licitaciones públicas queda intacto.
        traceback.print_exc()
        print("El módulo de obras falló; el tablero de licitaciones públicas no se modificó.")
        sys.exit(1)
