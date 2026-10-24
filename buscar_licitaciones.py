
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse

URL_CAMMESA = "https://cammesaweb.cammesa.com/inicio-licitaciones/"
URL_CONTRATAR = "https://contratar.gob.ar/BuscarAvanzado.aspx"

TERMINOS = [
    "amba", "almasadi", "almacenamiento", "bess",
    "transporte", "hidroelectric", "subestacion",
    "transformadora", "energia", "potencia",
    "electrica", "grandes demandas"
]


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


def main():
    fuentes = []
    licitaciones = []

    try:
        licitaciones = buscar_cammesa()
        fuentes.append({
            "nombre": "CAMMESA - Convocatorias",
            "url": URL_CAMMESA,
            "estado": "consultada",
            "registros": len(licitaciones)
        })
        print("CAMMESA: referencias:", len(licitaciones))

    except Exception as error:
        print("CAMMESA: error:", error)

        # Evitar borrar resultados anteriores si falla la web.
        archivo = Path("licitaciones.json")
        if archivo.exists():
            try:
                anterior = json.loads(
                    archivo.read_text(encoding="utf-8")
                )
                licitaciones = [
                    item for item in anterior.get("licitaciones", [])
                    if item.get("fuente") == "CAMMESA"
                ]
            except (ValueError, OSError):
                licitaciones = []

        fuentes.append({
            "nombre": "CAMMESA - Convocatorias",
            "url": URL_CAMMESA,
            "estado": "error",
            "detalle": str(error),
            "registros": len(licitaciones)
        })

    # CONTRAT.AR tiene búsqueda pública por número,
    # pero su extracción automática aún no está validada.
    # No generar expedientes ni fechas sin verificarlos.
    fuentes.append({
        "nombre": "CONTRAT.AR - Obra pública",
        "url": URL_CONTRATAR,
        "estado": "consulta_manual_disponible",
        "registros": 0,
        "detalle": (
            "Búsqueda pública por número disponible. "
            "Extracción automática pendiente de validación."
        )
    })

    resultado = {
        "actualizado": datetime.now(
            timezone.utc
        ).isoformat(),
        "estado": (
            "referencias_detectadas"
            if licitaciones
            else "sin_registros_verificados"
        ),
        "fuentes": fuentes,
        "licitaciones": licitaciones
    }

    Path("licitaciones.json").write_text(
        json.dumps(
            resultado, ensure_ascii=False, indent=2
        ),
        encoding="utf-8"
    )

    print("licitaciones.json generado.")
    print("Referencias CAMMESA:", len(licitaciones))
    print("CONTRAT.AR: búsqueda manual disponible.")
    print("Extracción automática CONTRAT.AR: pendiente.")


if __name__ == "__main__":
    main()
