import http.cookiejar
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import (
    HTTPCookieProcessor, Request, build_opener, urlopen
)
from urllib.parse import urljoin, urlparse

URL_CAMMESA = "https://cammesaweb.cammesa.com/inicio-licitaciones/"
URL_CONTRATAR_INICIO = "https://contratar.gob.ar/"
URL_CONTRATAR = "https://contratar.gob.ar/ListarAperturaProxima.aspx"

TERMINOS = [
    "amba", "almasadi", "almacenamiento", "bess",
    "transporte", "hidroelectric", "subestacion",
    "transformadora", "energia", "potencia",
    "electrica", "grandes demandas"
]


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

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "table" and atributos.get("id") == "ctl00_CPH1_GridListaPliegos":
            self.en_tabla = True
        elif self.en_tabla and tag == "tr":
            self.en_fila, self.fila = True, []
        elif self.en_fila and tag == "td":
            self.en_celda, self.celda = True, []

    def handle_data(self, data):
        if self.en_celda:
            self.celda.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.en_celda:
            self.fila.append(" ".join(" ".join(self.celda).split()))
            self.en_celda = False
        elif tag == "tr" and self.en_fila:
            if len(self.fila) == 6:
                self.filas.append(self.fila)
            self.en_fila = False
        elif tag == "table" and self.en_tabla:
            self.en_tabla = False


def obtener_html_contratar(url):
    """Abre primero el inicio (para recibir las cookies de sesión) y luego el listado.
    Reintenta una vez. Si no se logra, lanza un error claro."""
    cabeceras = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
        "Accept-Language": "es-AR,es;q=0.9"
    }
    ultimo_error = None
    for intento in (1, 2):
        try:
            jar = http.cookiejar.CookieJar()
            opener = build_opener(HTTPCookieProcessor(jar))
            with opener.open(
                Request(URL_CONTRATAR_INICIO, headers=cabeceras), timeout=30
            ) as inicio:
                inicio.read(200000)
            time.sleep(2)
            cabeceras_listado = dict(cabeceras)
            cabeceras_listado["Referer"] = URL_CONTRATAR_INICIO
            with opener.open(
                Request(url, headers=cabeceras_listado), timeout=30
            ) as respuesta:
                if respuesta.status != 200:
                    raise RuntimeError(f"Respuesta HTTP {respuesta.status}")
                return respuesta.read().decode("utf-8", errors="replace")
        except Exception as error:
            ultimo_error = error
            if intento == 1:
                time.sleep(5)
    raise RuntimeError(
        "No se pudo leer CONTRAT.AR: "
        f"{type(ultimo_error).__name__}: {ultimo_error}"
    )


def buscar_contratar():
    html = obtener_html_contratar(URL_CONTRATAR)
    if "ctl00_CPH1_GridListaPliegos" not in html:
        raise RuntimeError(
            "El portal no devolvió el listado de próximas aperturas "
            "(posible redirección al inicio o cambio de estructura)"
        )

    lector = LectorTablaContratar()
    lector.feed(html)
    if not lector.filas:
        raise RuntimeError(
            "No se encontraron filas de seis columnas en la tabla oficial; "
            "revisar estructura del portal"
        )

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

        resultados.append({
            "numero": numero,
            "nombre": nombre,
            "organismo": organismo,
            "sector": "Obra pública / posible energía",
            "fuente": "CONTRAT.AR",
            "estadoOficial": estado,
            "publicacion": None,
            "consultas": None,
            "cierreOfertas": None,
            "documentacionFisica": None,
            "apertura": apertura,
            "plazoVerificado": False,
            "enlace": URL_CONTRATAR,
            "observaciones": (
                "Referencia detectada en listado oficial de próximas aperturas. "
                "El enlace lleva al listado, no al expediente. "
                "Fecha de apertura distinta del cierre de ofertas; "
                "vigencia, alcance y documentación pendientes de verificar. "
                "Tipo: " + tipo
            )
        })

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
     buscar_contratar, False),
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
        previos = anteriores.pop(clave, [])
        try:
            registros, detalle = funcion()
            if not registros and previos and vacio_sospechoso:
                raise RuntimeError(
                    "La consulta no devolvió ningún registro; "
                    "se considera anómalo"
                )
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
            licitaciones.extend(previos)
            mensaje = f"{type(error).__name__}: {error}"
            fuentes.append({
                "nombre": nombre,
                "url": url,
                "estado": "error",
                "detalle": (
                    f"{mensaje}. Se conservan {len(previos)} registros "
                    "de la consulta anterior, sin verificar en esta corrida."
                ),
                "registros": len(previos)
            })
            print(f"{clave}: ERROR: {mensaje}")
            print(f"::warning title={clave} no se pudo actualizar::{mensaje}")

    # Registros de cualquier otra fuente: se conservan sin tocar.
    for restantes in anteriores.values():
        licitaciones.extend(restantes)

    resultado = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "estado": (
            "referencias_detectadas"
            if licitaciones
            else "sin_registros_verificados"
        ),
        "fuentes": fuentes,
        "licitaciones": licitaciones
    }

    Path("licitaciones.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("licitaciones.json generado.")
    print("Total de registros:", len(licitaciones))

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

    # Si fallaron TODAS las fuentes, la corrida debe verse en rojo.
    if fallidas == len(FUENTES):
        print("::error title=Sin datos nuevos::Fallaron todas las fuentes.")
        sys.exit(1)


if __name__ == "__main__":
    main()
