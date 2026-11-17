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


def _candidatos_para_tablero(procesos: list[dict]) -> list[dict]:
    """No descartar prematuramente los registros sin fecha de cierre.

    La clasificación P1/P2/P3, la vigencia y el estado gris corresponden
    exclusivamente a licitaciones.tablero.preparar(). No modifica SQLite.
    """
    hoy = datetime.now()
    candidatos = []
    anteriores = futuros = 0
    for original in procesos:
        p = dict(original)
        publicacion_raw = p.get("fecha_publicacion")
        publicacion = _fecha_segura(publicacion_raw)
        # Publicación antigua o fecha imposible: no tratar como proyecto nuevo.
        if publicacion_raw and publicacion is None:
            anteriores += 1
            continue
        if publicacion and publicacion > hoy:
            futuros += 1
            continue
        # No usar apertura como cierre ni inventar fecha de presentación.
        candidatos.append(p)
    print(f"Entrada a clasificador P1/P2/P3: {len(candidatos)} registros; "
          f"publicaciones fuera de 2026-2027 o inválidas: {anteriores}; "
          f"publicaciones futuras: {futuros}")
    return candidatos


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



# --- Seguimiento verificable de la base maestra y fuentes oficiales ---
def seguimiento_fuentes_maestras() -> dict:
    """Releva páginas HTML públicas; NO equipara mención a convocatoria abierta.

    No descarga pliegos, no altera la base SQLite y no inventa cierres.
    """
    import json
    from urllib.parse import urljoin, urlparse
    import requests
    from bs4 import BeautifulSoup

    rutas = (RAIZ / "licitaciones" / "base_maestra_deep.json",
             RAIZ / "datos" / "base_maestra_deep.json")
    ruta = next((r for r in rutas if r.is_file()), None)
    if ruta is None:
        return {"estado": "base_maestra_no_encontrada", "fuentes": [], "referencias": [], "hallazgos": []}
    maestro = json.loads(ruta.read_text(encoding="utf-8"))
    referencias = maestro.get("licitaciones", [])
    fuentes = maestro.get("fuentes", [])
    empresas = maestro.get("empresas", [])
    urls = {}
    for item in fuentes + empresas:
        url = item.get("URL") or item.get("Portal / URL")
        if url and url.startswith("https://"):
            urls.setdefault(url, item.get("Entidad") or item.get("Empresa") or "Fuente oficial")
    # Limitar volumen y tiempo de cada ejecución diaria; las URLs sin consulta se declaran pendientes.
    max_fuentes = int(os.getenv("DEEP_MAX_FUENTES", "18"))
    session = requests.Session()
    session.headers.update({"User-Agent": "DEEP-Seguimiento-Comercial/1.0 (+consulta de fuentes publicas)"})
    revisadas, hallazgos, textos = [], [], []
    p1 = ("ups industrial", "ups trifas", "rectificador", "cargador de bater", "banco de bater",
          "baterias estacionarias", "baterias industriales", "inversor industrial", "convertidor cc")
    # Una obra no prueba suministro de equipos DEEP; excluir candidatos por sector solamente.
    p2 = ()
    excluir = ("aeronautic", "automotriz", "motociclet", "bateria para vehicul",
               "cartucho de toner", "articulos de limpieza")
    # Buscar identificadores exactos en páginas institucionales y fichas HTML
    # enlazadas. Nunca interpretar fechas de la base maestra como verificadas.
    from collections import deque
    from urllib.parse import urldefrag
    def numero_en_texto(numero, texto):
        n = _sin_acentos(numero).strip()
        if not n or n == "pabra / ariba":
            return False
        # El identificador no debe formar parte de otro número.
        patron = r"(?<![a-z0-9])" + re.escape(n).replace(r"\-", r"[\s\-–]+").replace(r"\/", r"\s*/\s*") + r"(?![a-z0-9])"
        return re.search(patron, _sin_acentos(texto)) is not None

    # Priorizar el portal indicado en cada referencia; excluir enlaces
    # secundarios como indicadores.ar de la condición "oficial".
    for lic in referencias:
        url = lic.get("URL / fuente", "")
        if isinstance(url, str) and url.startswith("https://"):
            host = urlparse(url).hostname or ""
            if host and not host.endswith("indicadores.ar"):
                urls.setdefault(url, lic.get("Empresa", "Organismo"))

    coincidencias = {}
    total_paginas = 0
    max_paginas = max(1, min(12, int(os.getenv("DEEP_PAGINAS_POR_FUENTE", "6"))))
    for url, nombre in list(urls.items())[:max_fuentes]:
        info = {"nombre": nombre, "url": url, "estado": "error",
                "detalle": "No consultada", "paginas_html": 0}
        host_raiz = (urlparse(url).hostname or "").lower().removeprefix("www.")
        cola = deque([(url, 0)])
        visitadas = set()
        errores = []
        while cola and info["paginas_html"] < max_paginas:
            pagina, profundidad = cola.popleft()
            pagina = urldefrag(pagina)[0]
            if pagina in visitadas:
                continue
            visitadas.add(pagina)
            try:
                r = session.get(pagina, timeout=(5, 12), allow_redirects=True)
                r.raise_for_status()
                host_final = (urlparse(r.url).hostname or "").lower().removeprefix("www.")
                if host_final != host_raiz:
                    continue
                if "html" not in r.headers.get("Content-Type", "").lower():
                    continue
                soup = BeautifulSoup(r.text[:850000], "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                contenido = _sin_acentos(soup.get_text(" ", strip=True))[:140000]
                info["paginas_html"] += 1
                total_paginas += 1
                textos.append((r.url, nombre, contenido))
                # Coincidencia exacta en página del organismo, sin inferir vigencia.
                for lic in referencias:
                    numero = str(lic.get("N.º proceso", "")).strip()
                    empresa = str(lic.get("Empresa", "")).strip()
                    # El contexto institucional debe ser el organismo o el
                    # portal explícitamente declarado en la referencia.
                    portal_lic = lic.get("URL / fuente", "")
                    host_lic = (urlparse(portal_lic).hostname or "").lower().removeprefix("www.")
                    pertenece = (host_lic == host_raiz and bool(host_lic)) or (
                        _sin_acentos(empresa) == _sin_acentos(nombre))
                    if pertenece and numero_en_texto(numero, contenido):
                        clave = (empresa, numero)
                        coincidencias.setdefault(clave, set()).add(r.url)
                # Enlaces: seguir páginas de licitaciones y fichas del mismo
                # dominio, no descargar PDFs ni rastrear sitios completos.
                enlaces = []
                for a in soup.find_all("a", href=True):
                    etiqueta = a.get_text(" ", strip=True)[:220]
                    destino = urldefrag(urljoin(r.url, a.get("href", "")))[0]
                    u = urlparse(destino)
                    if u.scheme != "https" or not u.hostname:
                        continue
                    if u.hostname.lower().removeprefix("www.") != host_raiz:
                        continue
                    if re.search(r"\.(pdf|zip|rar|docx?|xlsx?)(?:$|\?)", u.path, re.I):
                        continue
                    normal = _sin_acentos(etiqueta + " " + u.path)
                    if any(x in normal for x in excluir):
                        continue
                    prioridad = "P1" if any(x in normal for x in p1) else (
                        "P2" if any(x in normal for x in p2) else "")
                    coincide_proceso = any(
                        numero_en_texto(str(lic.get("N.º proceso", "")), normal)
                        for lic in referencias)
                    if prioridad or coincide_proceso:
                        hallazgos.append({
                            "fuente": nombre, "titulo": etiqueta or destino,
                            "url": destino, "prioridad": prioridad or "REFERENCIA",
                            "estado": "PENDIENTE DE VERIFICAR",
                            "cierre": "NO INFORMADA", "circular": "NO VERIFICADA"})
                    # Fichas candidatas, paginación y secciones de licitaciones.
                    if profundidad < 2 and (
                        prioridad or coincide_proceso or
                        any(k in normal for k in (
                            "licitacion", "contratacion", "convocatoria",
                            "procesos", "publicaciones", "compras",
                            "pliegos", "ver detalle", "detalle",
                            "siguiente", "pagina"))):
                        enlaces.append(destino)
                for destino in enlaces[:25]:
                    if destino not in visitadas:
                        cola.append((destino, profundidad + 1))
                info.update(estado="consultada",
                            detalle="HTML institucional leído; vigencia no acreditada")
            except requests.RequestException as exc:
                errores.append(type(exc).__name__)
        if not info["paginas_html"]:
            info["detalle"] = ", ".join(errores[:3]) or "Sin HTML público accesible"
        revisadas.append(info)
    comprobaciones = []
    for lic in referencias:
        numero = str(lic.get("N.º proceso", "")).strip()
        organismo = str(lic.get("Empresa", "")).strip()
        encontrados = sorted(coincidencias.get((organismo, numero), set()))
        comprobaciones.append({
            "organismo": organismo, "proceso": numero,
            "objeto": lic.get("Objeto", ""),
            "estado": "REFERENCIA EN PORTAL; VALIDAR FICHA Y PLAZO"
                      if encontrados else "NO VERIFICADA",
            "enlaces": encontrados[:3],
            "cierre": "NO INFORMADA", "circulares": "NO VERIFICADAS"})
    print(f"Consulta institucional: {total_paginas} páginas HTML leídas; "
          f"{sum(bool(x['enlaces']) for x in comprobaciones)} referencias con coincidencia "
          f"(sin validar cierres ni circulares)")
    # Deduplicación por enlace, sin crear ni actualizar convocatorias en SQLite.
    unicos = {h["url"]: h for h in hallazgos}
    resultado = {"estado": "relevamiento_preliminar", "fecha": datetime.now().isoformat(timespec="seconds"),
                 "fuentes": revisadas, "referencias": comprobaciones,
                 "hallazgos": list(unicos.values())[:100], "fuentes_configuradas": len(urls)}
    (SALIDA / "seguimiento_fuentes_deep.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado


def anexar_seguimiento_html(ruta_html: Path, resultado: dict) -> None:
    """Anexa una sección separada, sin alterar el tablero de licitaciones ni obras."""
    from html import escape
    if not ruta_html.is_file():
        return
    refs = resultado.get("referencias", [])
    fuentes = resultado.get("fuentes", [])
    hallazgos = resultado.get("hallazgos", [])
    ok = sum(f["estado"] == "consultada" for f in fuentes)
    contenido = ['<section id="deep-seguimiento-fuentes" style="margin:24px auto;max-width:1400px;padding:20px;background:white;border:1px solid #ddd;border-radius:12px">',
                 '<h2>Seguimiento de fuentes y procesos DEEP</h2>',
                 '<p><b>Relevamiento preliminar:</b> ninguna coincidencia textual acredita una convocatoria vigente. '
                 'Los cierres y las circulares requieren comprobación en la ficha oficial. '
                 'No se descargaron pliegos.</p>',
                 f'<p>Fuentes HTML consultadas: {ok}/{len(fuentes)}; referencias maestras: {len(refs)}; enlaces candidatos: {len(hallazgos)}.</p>',
                 '<details open><summary><b>Procesos de la base maestra</b></summary><div style="overflow-x:auto"><table style="width:100%;text-align:left"><thead><tr><th>Organismo</th><th>Proceso</th><th>Objeto</th><th>Verificación</th><th>Fuente</th></tr></thead><tbody>']
    for x in refs:
        enlaces = " ".join(f'<a href="{escape(u, quote=True)}" target="_blank" rel="noopener noreferrer">Ver fuente</a>' for u in x["enlaces"])
        contenido.append('<tr>' + ''.join(f'<td style="padding:7px;border-top:1px solid #eee">{escape(str(v))}</td>' for v in
                          (x["organismo"], x["proceso"], x["objeto"], x["estado"])) + f'<td>{enlaces or "Sin coincidencia verificada"}</td></tr>')
    contenido += ['</tbody></table></div></details>', '<details><summary><b>Enlaces candidatos detectados en portales</b></summary><ul>']
    for x in hallazgos:
        contenido.append(f'<li>{escape(x["prioridad"])} · <a href="{escape(x["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{escape(x["titulo"])}</a> · {escape(x["fuente"])} · POR VERIFICAR</li>')
    contenido += ['</ul></details>', '<details><summary><b>Estado de consulta por fuente</b></summary><ul>']
    for f in fuentes:
        contenido.append(f'<li>{escape(f["nombre"])}: {escape(f["estado"])} ({escape(f["detalle"])})</li>')
    contenido += ['</ul></details></section>']
    html = ruta_html.read_text(encoding="utf-8")
    bloque = "\n".join(contenido)
    # Mostrar el seguimiento dentro del tablero, antes del cierre de <main>.
    # Sigue siendo una sección separada: NO altera el semáforo de convocatorias.
    if "</main>" in html:
        html = html.replace("</main>", bloque + "\n</main>", 1)
    elif "</body>" in html:
        html = html.replace("</body>", bloque + "\n</body>", 1)
    else:
        html += bloque
    ruta_html.write_text(html, encoding="utf-8")


def anexar_obras_para_revision(ruta_html: Path, resultados: list[ResultadoFuente]) -> None:
    """Detecta obras potenciales sin afirmar que contienen equipos DEEP.

    Solo utiliza objeto y texto de cada aviso. Nunca convierte una apertura
    en fecha de cierre ni declara una obra como suministro confirmado.
    """
    from html import escape
    from licitaciones.tablero import evaluar, norm, EXCLUSION_INFORMATICA, coincide
    import re
    from datetime import datetime
    claves = (
        "subestacion", "estacion transformadora", "sistema de transporte de energia",
        "central hidroelectrica", "central termoelectrica", "planta minera",
        "parque solar", "parque eolico", "servicios auxiliares", "bess",
        "ampliacion electrica", "planta industrial", "refineria",
        "linea de alta tension", "transmision electrica", "planta de tratamiento",
        "central de generacion", "estacion de bombeo", "distribucion electrica"
    )
    vistos, candidatos = set(), []
    ahora = datetime.now()
    for r in resultados:
        for op in r.oportunidades:
            texto = norm(" ".join((op.titulo or "", op.texto or "")))
            # Los avisos largos pueden contener productos informáticos accesorios;
            # la exclusión se aplica al objeto/título, no a toda la obra.
            if coincide(norm(op.titulo or ""), EXCLUSION_INFORMATICA):
                continue
            razones = [x for x in claves if re.search(r"(?<!\\w)" + re.escape(x) + r"(?!\\w)", texto)]
            if not razones:
                continue
            if evaluar({"titulo": op.titulo, "texto": op.texto})[0]:
                continue
            if op.fecha_apertura and op.fecha_apertura < ahora:
                continue
            clave = (op.numero_proceso or op.titulo or "").strip().lower()
            if not clave or clave in vistos:
                continue
            vistos.add(clave)
            candidatos.append((op, razones))
    candidatos.sort(key=lambda item: (item[0].fecha_apertura is None,
                                      item[0].fecha_apertura or datetime.max))
    total = len(candidatos)
    filas = []
    for op, razones in candidatos[:100]:
        titulo = escape((op.titulo or "Obra sin título")[:180])
        numero = escape(op.numero_proceso or "Número no informado")
        fuente = escape(op.fuente or "")
        fecha = op.fecha_apertura.strftime("%d/%m/%Y") if op.fecha_apertura else "No informada"
        evidencia = escape(", ".join(razones[:3]))
        enlace = (f'<a href="{escape(op.link, quote=True)}" target="_blank" rel="noopener noreferrer">Ver fuente</a>'
                  if op.link and op.link.startswith(("https://", "http://")) else "Sin enlace")
        filas.append(f"<tr><td>{numero}</td><td>{titulo}</td><td>{evidencia}</td>"
                    f"<td>{fecha}</td><td>{fuente}</td><td>{enlace}</td></tr>")
    bloque = ('<section class="panel" id="obras-revision-tecnica">'
              '<details open><summary><b>Oportunidades potenciales DEEP '
              f'({total})</b></summary>'
              '<p>Detección automática de obras de infraestructura que podrían requerir '
              'UPS industriales, cargadores, rectificadores o bancos de baterías. '
              '<b>Potencial no equivale a producto confirmado.</b> '
              'La fecha indicada es de apertura, no cierre de ofertas. '
              'Se muestran hasta 100 procesos, ordenados por apertura.</p>'
              '<div style="overflow-x:auto"><table><thead><tr><th>Proceso</th>'
              '<th>Obra</th><th>Motivo detectado</th><th>Apertura</th>'
              '<th>Fuente</th><th>Enlace</th></tr></thead>'
              '<tbody>' + "".join(filas) + '</tbody></table></div></details></section>')
    html = ruta_html.read_text(encoding="utf-8")
    if "</main>" in html:
        ruta_html.write_text(html.replace("</main>", bloque + "\\n</main>", 1), encoding="utf-8")
    print(f"Oportunidades potenciales DEEP: {total}; mostradas {len(filas)}")



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
    candidatos = _candidatos_para_tablero(base.procesos()) if not args.demo else base.procesos()
    clasificados = tablero.preparar(candidatos, filtro)
    from collections import Counter
    resumen = Counter(p.get("semaforo") for p in clasificados)
    print("Clasificación final: " + ", ".join(
        f"{nombre}={resumen.get(color, 0)}" for color, nombre in
        (("verde", "en_plazo"), ("amarillo", "por_vencer"), ("gris", "por_verificar"))))
    tablero.generar(salida_html, candidatos, base.alertas_recientes(), estado_fuentes, filtro, nota=nota)
    if not args.demo:
        anexar_obras_para_revision(salida_html, resultados)
        _anexar_maestra_si_existe(salida_html)
        try:
            seguimiento = seguimiento_fuentes_maestras()
            anexar_seguimiento_html(salida_html, seguimiento)
            print(f"Seguimiento DEEP: {len(seguimiento.get('referencias', []))} procesos de base maestra; "
                  f"{len(seguimiento.get('hallazgos', []))} enlaces candidatos; "
                  f"{sum(f['estado'] == 'consultada' for f in seguimiento.get('fuentes', []))} fuentes HTML consultadas")
        except Exception as exc:
            print(f"AVISO: seguimiento de fuentes no completado ({type(exc).__name__}: {exc}); "
                  "el tablero principal permanece disponible")
    print(f"Tablero: {salida_html}")
    if args.abrir:
        webbrowser.open(salida_html.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
