import http.cookiejar
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from urllib.request import (
    HTTPCookieProcessor, Request, build_opener, urlopen
)
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError

URL_CAMMESA = "https://cammesaweb.cammesa.com/inicio-licitaciones/"
URL_CONTRATAR_INICIO = "https://contratar.gob.ar/"
URL_CONTRATAR = "https://contratar.gob.ar/ListarAperturaProxima.aspx"

TERMINOS = ["ups", "rectificador", "cargador de bateria", "banco de bateria", "baterias estacionarias", "corriente continua", "energia critica", "subestacion", "estacion transformadora", "transporte de energia electrica", "sistema de transporte de energia", "bess", "almacenamiento de energia"]
PUBLICAR_CAMMESA = False
VERSION_AGENTE = "DEEP-CONTRATAR-ESTABLE-V2-20261025"



# ---------------------------------------------------------------
# Utilidades comunes (sin cambios)
# ---------------------------------------------------------------

class LectorEnlaces(HTMLParser):
    def __init__(self):
        super().__init__()
        self.enlaces = []
        self.url_actual = None
        self.texto_actual = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.url_actual = dict(attrs).get("href", "")
            self.texto_actual = []

    def handle_data(self, data):
        if self.url_actual is not None:
            self.texto_actual.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.url_actual is not None:
            texto = " ".join(" ".join(self.texto_actual).split())
            if texto and self.url_actual:
                self.enlaces.append((texto, self.url_actual))
            self.url_actual = None
            self.texto_actual = []


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(
        c for c in texto if not unicodedata.combining(c)
    )


def obtener_html(url):
    solicitud = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html"
        }
    )
    with urlopen(solicitud, timeout=35) as respuesta:
        if respuesta.status != 200:
            raise RuntimeError(
                f"Respuesta HTTP {respuesta.status}"
            )
        return respuesta.read().decode(
            "utf-8", errors="replace"
        )


# ---------------------------------------------------------------
# CAMMESA (sin cambios)
# ---------------------------------------------------------------

def buscar_cammesa():
    html = obtener_html(URL_CAMMESA)
    lector = LectorEnlaces()
    lector.feed(html)

    resultados = []
    vistos = set()

    for titulo, href in lector.enlaces:
        nombre = normalizar(titulo)
        if not any(t in nombre for t in TERMINOS):
            continue

        enlace = urljoin(URL_CAMMESA, href)
        dominio = urlparse(enlace).hostname or ""
        ruta = urlparse(enlace).path.lower()

        if dominio != "cammesaweb.cammesa.com":
            continue
        if re.search(r"\.(pdf|docx?|xlsx?|csv|zip|rar)$", ruta):
            continue
        if "/download/" in ruta:
            continue
        if enlace.rstrip("/") == URL_CAMMESA.rstrip("/"):
            continue
        if "/complejoshidrolectricos/" in ruta:
            continue

        clave = normalizar(titulo)
        if clave in vistos:
            continue
        vistos.add(clave)

        identificador = "CAMMESA-" + re.sub(
            r"[^A-Z0-9]+", "-",
            normalizar(titulo).upper()
        ).strip("-")[:65]

        resultados.append({
            "numero": identificador,
            "nombre": titulo,
            "organismo": "CAMMESA",
            "sector": "Energía",
            "fuente": "CAMMESA",
            "estadoOficial": "Pendiente de verificar",
            "publicacion": None,
            "consultas": None,
            "cierreOfertas": None,
            "documentacionFisica": None,
            "apertura": None,
            "plazoVerificado": False,
            "enlace": enlace,
            "observaciones": (
                "Referencia detectada en el portal oficial. "
                "Verificar vigencia, alcance y plazos."
            )
        })

    return resultados


# ---------------------------------------------------------------
# CONTRAT.AR: listado oficial de próximas aperturas
# ---------------------------------------------------------------

class LectorTablaContratar(HTMLParser):
    """Lee exclusivamente las seis columnas del listado oficial de próximas aperturas."""

    def __init__(self):
        super().__init__()
        self.en_tabla = False
        self.en_fila = False
        self.en_celda = False
        self.celda = []
        self.fila = []
        self.filas = []
        self.href_celda = None
        self.href_fila = None
        self.enlaces = {}

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "table" and "gridlistapliegos" in atributos.get("id", "").lower():
            self.en_tabla = True
        elif self.en_tabla and tag == "tr":
            self.en_fila, self.fila = True, []
            self.href_fila = None
        elif self.en_fila and tag == "td":
            self.en_celda, self.celda = True, []
        elif self.en_celda and tag == "a":
            href = atributos.get("href", "")
            if href and not self.href_fila:
                self.href_fila = href

    def handle_data(self, data):
        if self.en_celda:
            self.celda.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.en_celda:
            self.fila.append(" ".join(" ".join(self.celda).split()))
            self.en_celda = False
        elif tag == "tr" and self.en_fila:
            if len(self.fila) >= 6:
                self.filas.append(self.fila[:6])
                if self.href_fila:
                    self.enlaces[self.fila[0]] = self.href_fila
            self.en_fila = False
        elif tag == "table" and self.en_tabla:
            self.en_tabla = False


def sesion_contratar():
    cabeceras = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
        "Accept-Language": "es-AR,es;q=0.9",
    }
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with opener.open(Request(URL_CONTRATAR_INICIO, headers=cabeceras), timeout=30) as resp:
        resp.read(200000)
    return opener, cabeceras


def descargar_contratar(opener, cabeceras, url, referer=URL_CONTRATAR):
    headers = dict(cabeceras, Referer=referer)
    with opener.open(Request(url, headers=headers), timeout=35) as respuesta:
        if respuesta.status != 200:
            raise RuntimeError(f"HTTP {respuesta.status}")
        return respuesta.read().decode("utf-8-sig", errors="replace")


def obtener_html_contratar(url):
    ultimo_error = None
    for intento in (1, 2):
        try:
            opener, cabeceras = sesion_contratar()
            return descargar_contratar(opener, cabeceras, url), opener, cabeceras
        except Exception as error:
            ultimo_error = error
            if intento == 1:
                time.sleep(3)
    raise RuntimeError(f"No se pudo leer CONTRAT.AR: {ultimo_error}")


class LectorDetalle(HTMLParser):
    """Extrae texto visible, pares etiqueta/valor y filas de circulares."""
    def __init__(self):
        super().__init__()
        self.bloques = []
        self.actual = []
        self.nivel = 0
        self.filas = []
        self.fila = None
        self.celda = None
        self.enlaces = []

    def handle_starttag(self, tag, attrs):
        if tag in ('div', 'span', 'label', 'td', 'th', 'p', 'h3', 'h4'):
            self.actual.append(' ')
        if tag == 'tr':
            self.fila = []
        if tag in ('td', 'th') and self.fila is not None:
            self.celda = []
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if href:
                self.enlaces.append(href)

    def handle_data(self, data):
        self.actual.append(data)
        if self.celda is not None:
            self.celda.append(data)

    def handle_endtag(self, tag):
        if tag in ('div', 'span', 'label', 'td', 'th', 'p', 'h3', 'h4'):
            self.actual.append('\n')
        if tag in ('td', 'th') and self.celda is not None:
            self.fila.append(' '.join(''.join(self.celda).split()))
            self.celda = None
        if tag == 'tr' and self.fila is not None:
            if self.fila:
                self.filas.append(self.fila)
            self.fila = None


def fecha_iso(texto):
    m = re.search(r'(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?', texto)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + ' ' + (m.group(2) or '00:00'), '%d/%m/%Y %H:%M').strftime('%Y-%m-%dT%H:%M:00')
    except ValueError:
        return None


def obtener_campo(texto, etiquetas):
    """Busca la fecha junto a una etiqueta exacta, incluso si está en la línea siguiente."""
    lineas = [normalizar(' '.join(linea.split())).strip(' :') for linea in texto.splitlines()]
    etiquetas = [normalizar(etiqueta) for etiqueta in etiquetas]
    for i, linea in enumerate(lineas):
        if not any(linea.startswith(etiqueta) for etiqueta in etiquetas):
            continue
        # La página oficial separa etiqueta y fecha con etiquetas HTML.
        for candidato in [linea] + lineas[i + 1:i + 5]:
            fecha = fecha_iso(candidato)
            if fecha:
                return fecha
            if candidato != linea and candidato and any(c.isalpha() for c in candidato) and not re.match(r'^\d{2}/\d{2}/\d{4}', candidato):
                break
    return None


def extraer_detalle(html, numero):
    lector = LectorDetalle()
    lector.feed(html)
    texto = unescape(''.join(lector.actual))
    if numero.lower() not in texto.lower():
        raise RuntimeError('El detalle no contiene el número de proceso solicitado')
    campos = {
        'consultas': obtener_campo(texto, ['fecha y hora final de consultas']),
        'documentacionFisica': obtener_campo(texto, ['fecha y hora fin recepcion de documentos en soporte fisico']),
        'apertura': obtener_campo(texto, ['fecha y hora del 1', 'fecha y hora primer acto de apertura']),
        'publicacion': obtener_campo(texto, ['fecha y hora estimada de publicacion en el portal', 'fecha de publicacion', 'fecha y hora de publicacion']),
        'cierreOfertas': obtener_campo(texto, ['fecha y hora limite de presentacion de ofertas', 'fecha limite de presentacion de ofertas', 'fecha y hora de cierre de ofertas', 'fecha de cierre de ofertas', 'fin de recepcion de ofertas']),
    }
    circulares = []
    # Solo filas de tabla que parecen circulares (número + fecha + tipo).
    for fila in lector.filas:
        if len(fila) >= 3 and re.fullmatch(r'\d{1,3}', fila[0]) and re.fullmatch(r'\d{2}/\d{2}/\d{4}', fila[1]):
            tipo = normalizar(fila[2])
            if 'consulta' in tipo:
                circulares.append({'numero': fila[0], 'publicacion': fila[1], 'tipo': fila[2]})
    return campos, circulares


def enlace_expediente(href):
    # Solo se siguen enlaces HTTPS del portal oficial, nunca archivos adjuntos.
    href = unescape(href).replace('&amp;', '&')
    if href.lower().startswith('javascript:') or href.startswith('#'):
        return None
    url = urljoin(URL_CONTRATAR, href)
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'contratar.gob.ar':
        return None
    if re.search(r'\.(pdf|zip|docx?|xlsx?)$', parsed.path, re.I):
        return None
    return url


# URL de ficha oficial contrastada para el expediente de prueba AMBA I.
# No se inventan URLs para otros procesos: se utilizan sus enlaces del listado.
FICHAS_VERIFICADAS = {
    '34-0003-LPU26': 'https://contratar.gob.ar/PLIEGO/VistaPreviaPliegoCiudadano.aspx?qs=BQoBkoMoEhyeqdlsIRjlbVzpmYCDKQ1YOo1f39Qg%7Cky815ZCD%7CkfxdssdIaOnmLmI4ts42%2FeS0aiuALKYAdQz06KinBOvULkr%2FDpt5kPBe0%3D',
}


def resolver_ficha(numero, href):
    enlace = enlace_expediente(href)
    if enlace and ('VistaPreviaPliegoCiudadano' in enlace or 'VistaPrevia' in enlace):
        return enlace
    return FICHAS_VERIFICADAS.get(numero) or enlace


def buscar_contratar():
    html, opener, cabeceras = obtener_html_contratar(URL_CONTRATAR)
    lector = LectorTablaContratar()
    lector.feed(html)
    if not lector.filas:
        raise RuntimeError(f"No se pudo leer la tabla de CONTRAT.AR (HTML: {len(html)} caracteres, tabla esperada: {'ctl00_CPH1_GridListaPliegos' in html}). Revisar sesión, estructura y enlaces.")

    resultados = []
    vistos = set()
    sin_numero_valido = 0
    sin_coincidencia = 0

    for numero, nombre, tipo, apertura_texto, estado, organismo in lector.filas:
        if not re.fullmatch(r"[0-9]+(?:/[0-9]+)?-[0-9]+-[A-Z]+[0-9]+", numero):
            sin_numero_valido += 1
            continue
        if not any(termino in normalizar(nombre) for termino in TERMINOS):
            sin_coincidencia += 1
            continue
        if numero in vistos:
            continue
        vistos.add(numero)

        apertura = None
        coincidencia = re.search(
            r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", apertura_texto
        )
        if coincidencia:
            try:
                apertura = datetime.strptime(
                    " ".join(coincidencia.groups()), "%d/%m/%Y %H:%M"
                ).strftime("%Y-%m-%dT%H:%M:00")
            except ValueError:
                pass

        detalle_url = resolver_ficha(numero, lector.enlaces.get(numero, ''))
        campos = {}
        circulares = []
        detalle_verificado = False
        if detalle_url:
            try:
                pagina = descargar_contratar(opener, cabeceras, detalle_url)
                campos, circulares = extraer_detalle(pagina, numero)
                detalle_verificado = any(campos.values())
            except Exception as error:
                print(f"CONTRAT.AR {numero}: detalle pendiente: {error}")

        resultados.append({
            "clasificacionDEEP": ("Coincidencia directa" if any(t in normalizar(nombre) for t in ["ups", "rectificador", "cargador", "bateria", "corriente continua", "bess", "energia critica"]) else "Obra contextual: revisar pliego"),
            "numero": numero,
            "nombre": nombre,
            "organismo": organismo,
            "sector": "Obra pública / posible energía",
            "fuente": "CONTRAT.AR",
            "estadoOficial": estado,
            "publicacion": campos.get("publicacion"),
            "consultas": campos.get("consultas"),
            "cierreOfertas": campos.get("cierreOfertas"),
            "documentacionFisica": campos.get("documentacionFisica"),
            "apertura": campos.get("apertura") or apertura,
            "detalleVerificado": detalle_verificado,
            "circulares": circulares,
            "enlaceCirculares": detalle_url,
            "revisionCirculares": "verificada" if detalle_verificado else "pendiente",
            "plazoVerificado": bool(campos.get("cierreOfertas")),
            "enlace": detalle_url or URL_CONTRATAR,
            "observaciones": (
                "Referencia detectada en listado oficial de próximas aperturas. "
                "Fechas y circulares tomadas del detalle cuando se pudo acceder. "
                "La apertura no equivale al cierre de ofertas. "
                "Tipo: " + tipo
            )
        })

    ahora = datetime.now()
    def vencida(valor):
        try:
            return bool(valor) and datetime.fromisoformat(valor) < ahora
        except ValueError:
            return False
    # No excluir por fecha de apertura: NO es el cierre de ofertas.
    resultados = [r for r in resultados if not vencida(r.get("cierreOfertas"))]
    detalle = (
        f"Filas leídas: {len(lector.filas)}; "
        f"sin número de proceso válido: {sin_numero_valido}; "
        f"sin términos de interés: {sin_coincidencia}; "
        f"registrados: {len(resultados)}."
    )
    return resultados, detalle


# ---------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------

# (clave en "fuente", nombre en el tablero, URL, función,
#  ¿un resultado vacío es sospechoso?)
FUENTES = [
    ("CAMMESA", "CAMMESA - Convocatorias", URL_CAMMESA,
     lambda: (buscar_cammesa(), None), True),
    ("CONTRAT.AR", "CONTRAT.AR - Obra pública", URL_CONTRATAR,
     buscar_contratar, True),
]


def cargar_anterior():
    archivo = Path("licitaciones.json")
    if archivo.exists():
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
            lista = datos.get("licitaciones", [])
            if isinstance(lista, list):
                return [item for item in lista if isinstance(item, dict)]
        except (ValueError, OSError, AttributeError):
            pass
    return []


def main():
    anteriores = {}
    for item in cargar_anterior():
        anteriores.setdefault(item.get("fuente"), []).append(item)

    fuentes = []
    licitaciones = []
    fallidas = 0

    for clave, nombre, url, funcion, vacio_sospechoso in FUENTES:
        if clave == "CAMMESA" and not PUBLICAR_CAMMESA:
            fuentes.append({"nombre": nombre, "url": url, "estado": "en pausa", "registros": 0})
            anteriores.pop(clave, None)
            continue
        previos = anteriores.pop(clave, [])
        try:
            registros, detalle = funcion()
            if not registros and previos and vacio_sospechoso:
                raise RuntimeError(
                    "La consulta no devolvió ningún registro; "
                    "se considera anómalo"
                )
            if clave == "CONTRAT.AR":
                por_numero = {r.get('numero'): r for r in previos}
                for registro in registros:
                    previo = por_numero.get(registro['numero'], {})
                    if not registro.get('detalleVerificado'):
                        # No borrar fechas oficiales verificadas en una ejecución previa.
                        for campo in ('publicacion', 'consultas', 'cierreOfertas', 'documentacionFisica', 'apertura'):
                            if not registro.get(campo) and previo.get('detalleVerificado'):
                                registro[campo] = previo.get(campo)
                        registro['circulares'] = previo.get('circulares', [])
                        registro['revisionCirculares'] = 'pendiente'
                        registro['alertas'] = previo.get('alertas', [])
                        registro['detalleVerificado'] = bool(previo.get('detalleVerificado'))
                        registro['plazoVerificado'] = bool(registro.get('cierreOfertas'))
                    else:
                        alertas = []
                        for campo, etiqueta in (
                            ('consultas', 'Fin de consultas'),
                            ('documentacionFisica', 'Fin de documentación física'),
                            ('apertura', 'Primer acto de apertura'),
                        ):
                            antes, despues = previo.get(campo), registro.get(campo)
                            if antes and despues and antes != despues:
                                alertas.append(f'{etiqueta}: {antes} → {despues}')
                        anteriores_circ = {str(c.get('numero')) + ':' + str(c.get('publicacion')) for c in previo.get('circulares', [])}
                        for circular in registro.get('circulares', []):
                            identificador = str(circular['numero']) + ':' + str(circular['publicacion'])
                            if previos and identificador not in anteriores_circ:
                                alertas.append('Circular nueva N° ' + circular['numero'] + ' (' + circular['publicacion'] + ')')
                        registro['alertas'] = alertas
                    if registro.get('alertas'):
                        print('::warning title=CONTRAT.AR novedad ' + registro['numero'] + '::' + '; '.join(registro['alertas']))
            licitaciones.extend(registros)
            fuente = {
                "nombre": nombre,
                "url": url,
                "estado": "consultada",
                "registros": len(registros)
            }
            if detalle:
                fuente["detalle"] = detalle
            fuentes.append(fuente)
            print(f"{clave}: referencias: {len(registros)}")
            if detalle:
                print(f"{clave}: {detalle}")
        except Exception as error:
            fallidas += 1
            mensaje = f"{type(error).__name__}: {error}"
            fuentes.append({
                "nombre": nombre,
                "url": url,
                "estado": "error",
                "detalle": f"{mensaje}. Se conservan registros previos no vencidos cuando existan.",
                "registros": len(previos)
            })
            if clave == "CONTRAT.AR":
                licitaciones.extend(previos)
            print(f"{clave}: ERROR: {mensaje}")
            print(f"::warning title={clave} no se pudo actualizar::{mensaje}")

    # Nunca incluir CAMMESA sin verificación de convocatorias vigentes.
    licitaciones = [r for r in licitaciones if r.get("fuente") == "CONTRAT.AR"]
    ahora = datetime.now()
    def vigente(r):
        fecha = r.get("cierreOfertas")
        if fecha:
            try:
                return datetime.fromisoformat(fecha) >= ahora
            except ValueError:
                pass
        return True
    licitaciones = [r for r in licitaciones if vigente(r)]


    resultado = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "versionAgente": VERSION_AGENTE,
        "estado": (
            "oportunidades_pendientes_de_verificacion"
            if licitaciones
            else "sin_registros_verificados"
        ),
        "fuentes": fuentes,
        "licitaciones": licitaciones
    }

    print(f"VERSION ACTIVA: {VERSION_AGENTE}", flush=True)
    print(f"CAMMESA PUBLICADA: {any(r.get('fuente') == 'CAMMESA' for r in licitaciones)}", flush=True)
    print(f"CONTRAT.AR: {sum(r.get('fuente') == 'CONTRAT.AR' for r in licitaciones)}", flush=True)
    Path("licitaciones.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("licitaciones.json generado.")
    print("Total de registros:", len(licitaciones))
    # Control crítico: impide que se dé por válida una ejecución que conserva CAMMESA.
    comprobacion = json.loads(Path("licitaciones.json").read_text(encoding="utf-8"))
    if any(x.get("fuente") == "CAMMESA" for x in comprobacion["licitaciones"]):
        raise RuntimeError("ERROR: CAMMESA sigue presente en el JSON")

    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write("## Resultado de la actualización\n\n")
            f.write("| Fuente | Estado | Registros |\n|---|---|---|\n")
            for fuente in fuentes:
                f.write(
                    f"| {fuente['nombre']} | {fuente['estado']} "
                    f"| {fuente['registros']} |\n"
                )

    # Si falló la única fuente activa, la corrida debe verse en rojo.
    if fallidas >= sum(clave != "CAMMESA" or PUBLICAR_CAMMESA for clave, *_ in FUENTES):
        print("::error title=Sin datos nuevos::Fallaron todas las fuentes.")
        sys.exit(1)


if __name__ == "__main__":
    main()
