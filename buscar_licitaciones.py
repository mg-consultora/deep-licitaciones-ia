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


def buscar_contratar():
    html = obtener_html(URL_CONTRATAR)
    lector = LectorTablaContratar()
    lector.feed(html)
    if not lector.filas:
        raise RuntimeError("No se encontraron filas en la tabla oficial; revisar estructura del portal")

    resultados = []
    vistos = set()
    for numero, nombre, tipo, apertura_texto, estado, organismo in lector.filas:
        if not re.fullmatch(r"[0-9]+(?:/[0-9]+)?-[0-9]+-[A-Z]+[0-9]+", numero):
            continue
        if not any(termino in normalizar(nombre) for termino in TERMINOS):
            continue
        if numero in vistos:
            continue
        vistos.add(numero)
        apertura = None
        coincidencia = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", apertura_texto)
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
    return resultados

def main():
    fuentes = []
    licitaciones = []
