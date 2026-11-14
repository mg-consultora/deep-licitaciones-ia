"""Boletín Oficial de la República Argentina — Tercera Sección (Contrataciones).

Por ley, las licitaciones públicas nacionales se publican acá: las que se gestionan en
COMPR.AR (bienes y servicios), en CONTRAT.AR (obra pública) y las de empresas y entes del
Estado (Energía Argentina, Nucleoeléctrica, CNEA, Trenes, Yacyretá, universidades, etc.).

En vez de pelear con los formularios de COMPR.AR (que es lo que suele dar error), el agente
baja el PDF oficial de cada día desde el listado público https://otslist.boletinoficial.gob.ar/ots/
(el Boletín publica ahí cada sección con su hash SHA-256), verifica el hash, extrae el texto y
separa los avisos uno por uno.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..modelo import Oportunidad
from ..texto import normalizar, primera_fecha
from .base import USER_AGENT, Fuente, ResultadoFuente

OTS_URL = "https://otslist.boletinoficial.gob.ar"
SECCION_TERCERA = "3"

SECCIONES = {
    "SUMINISTROS": "Convocatoria",
    "OBRAS": "Convocatoria",
    "SERVICIOS": "Convocatoria",
    "LOCACIONES": "Convocatoria",
    "VENTAS Y OFRECIMIENTOS DEL ESTADO": "Convocatoria",
    "CONCESIONES": "Convocatoria",
    "CIRCULARES": "Circular",
    "PRORROGAS": "Circular",
    "PREADJUDICACIONES": "Preadjudicación",
    "ADJUDICACIONES": "Adjudicación",
    "DICTAMENES DE EVALUACION": "Dictamen de evaluación",
    "DICTAMEN DE EVALUACION": "Dictamen de evaluación",
}

RUBROS_CONOCIDOS = [
    "CABLES ELECTRICOS Y EQ. P/ GENERAR Y DISTRIBUIR ELECTRICIDAD",
    "ELECTRICIDAD Y FERRETERIA ELECTRICA",
    "EQ. PROC. AUTOMATICO DE DATOS, SOFT., SUM. Y EQ. APOYO",
    "EQ. REFRIG. ACONDICIONAMIENTO Y CIRCULACION DE AIRE",
    "EQ. Y SUM. MEDICINA, ODONTOLOGIA Y VETERINARIA",
    "EQUIPOS FERROVIARIOS, REPUESTOS Y SUMINISTROS",
    "EQUIPOS Y SUMINISTROS PARA LIMPIEZA",
    "COMBUSTIBLES, LUBRICANTES Y ACEITES",
    "COMPONENTES Y ACCESORIOS DE AERONAVES",
    "EFECTOS VARIOS", "CIVILES", "ELECTRICAS", "ELECTROMECANICAS", "HIDRAULICAS", "VIALES",
    "SERVICIOS DIVERSOS", "IMPRESOS (MANO DE OBRA)", "SEGURIDAD, VIGILANCIA E INVESTIGACION",
    "SEGUROS", "INMUEBLES (LOC)", "VARIOS", "MAQUINARIAS Y EQUIPOS", "HERRAMIENTAS",
    "INSTRUMENTOS DE MEDICION", "TELECOMUNICACIONES", "MATERIALES DE CONSTRUCCION",
    "CONSULTORIA", "MANTENIMIENTO", "REPARACION Y MANTENIMIENTO",
]

_RE_ENCABEZADO = re.compile(r"BOLET[IÍ]N OFICIAL\s+N[ºo°]\s*[\d.]+\s*-\s*Tercera Secci[oó]n", re.IGNORECASE)
_RE_MARCA = re.compile(r"^#[IF]\d+[IF]#$")
_RE_FIN = re.compile(
    r"^e\.\s*(\d{1,2}/\d{1,2}/\d{4})\s*N[°º]\s*([\d.]+/\d{2})\s*v\.\s*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE
)
_RE_PROCESO = re.compile(
    r"^(licitaci[oó]n\s+(p[uú]blica|privada)|concurso\s+(p[uú]blico|privado)(\s+de\s+precios)?|"
    r"contrataci[oó]n\s+directa|compulsa(\s+abreviada)?|subasta|adjudicaci[oó]n\s+simple|"
    r"concurso\s+de\s+precios|llamado\s+a\s+licitaci[oó]n)\b",
    re.IGNORECASE,
)
_BLOQUES = [
    ("consultas", re.compile(r"consulta(s)?\s+(del\s+pliego|de\s+pliegos|y\s+pedido)|consultas\s*:|limite\s+de\s+consultas|consultas\s+hasta", re.I)),
    ("presentacion", re.compile(r"presentaci[oó]n\s+de\s+(las\s+)?ofertas", re.I)),
    ("apertura", re.compile(r"acto\s+de\s+apertura|apertura\s+de\s+(las\s+)?ofertas|fecha\s+de\s+apertura|apertura\s*:|apertura\s+de\s+sobres", re.I)),
]
_RE_CIRCULAR = re.compile(
    r"tipo de circular|circular (modificatoria|aclaratoria|sin consulta|con consulta|n[°º]?\s*\d)|"
    r"numero de circular|texto de la circular|se prorroga|prorroga de (la )?fecha|nueva fecha de apertura"
)
_RE_ETIQUETA = re.compile(r"\n\s*(?:[A-ZÁÉÍÓÚ][A-Za-zÁÉÍÓÚáéíóúñÑ°º ./()]{2,45}:|Retiro|Consulta|Presentaci|Acto de Apertura|Lugar)")


def _es_mayusculas(linea: str) -> bool:
    letras = [c for c in linea if c.isalpha()]
    return len(letras) >= 3 and sum(c.isupper() for c in letras) / len(letras) > 0.85


def _clave_rubro(linea: str) -> str:
    return normalizar(linea).upper()


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
def parsear_listado(html: str) -> dict[date, dict[str, str]]:
    """{fecha: {"1": hash, "3": hash, ...}} a partir del HTML de /ots/."""
    soup = BeautifulSoup(html, "html.parser")
    ediciones: dict[date, dict[str, str]] = {}
    for h4 in soup.find_all("h4"):
        try:
            dia = datetime.strptime(h4.get_text(strip=True), "%d-%m-%Y").date()
        except ValueError:
            continue
        tabla = h4.find_next("table")
        if tabla is None:
            continue
        secciones = {}
        for fila in tabla.find_all("tr"):
            celdas = [c.get_text(strip=True) for c in fila.find_all("td")]
            if len(celdas) >= 2 and re.fullmatch(r"[0-9a-f]{64}", celdas[1]):
                secciones[celdas[0]] = celdas[1]
        ediciones[dia] = secciones
    return ediciones


def extraer_paginas(pdf: bytes) -> list[str]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Separar avisos
# ---------------------------------------------------------------------------
def _fechas_por_bloque(texto: str) -> dict[str, datetime | None]:
    """Busca la fecha que sigue a cada etiqueta (consultas, presentación, apertura)."""
    res: dict[str, datetime | None] = {"consultas": None, "presentacion": None, "apertura": None}
    for clave, patron in _BLOQUES:
        for m in patron.finditer(texto):
            # El bloque termina donde empieza el siguiente bloque de fechas (o 350 caracteres).
            fin = len(texto)
            for _, otro in _BLOQUES:
                n = otro.search(texto, m.end())
                if n and n.start() < fin and otro is not patron:
                    fin = n.start()
            ventana = texto[m.end(): min(fin, m.end() + 350)]
            f = primera_fecha(ventana)
            if f:
                res[clave] = f
                break
    return res


def _objeto(texto: str, despues_de: int) -> str:
    m = re.search(r"\bobjeto\s*(de\s+la\s+(licitaci[oó]n|contrataci[oó]n))?\s*:\s*", texto, re.I)
    if m:
        resto = texto[m.end():]
        corte = _RE_ETIQUETA.search("\n" + resto)
        valor = resto[: corte.start() - 1 if corte else 400]
        return re.sub(r"\s+", " ", valor).strip(" .-\"“”")[:300]
    comillas = re.search(r"[\"“]([^\"”]{8,250})[\"”]", texto[despues_de:])
    if comillas:
        return re.sub(r"\s+", " ", comillas.group(1)).strip()
    for linea in texto[despues_de:].splitlines()[1:6]:
        linea = linea.strip()
        if len(linea) > 15 and ":" not in linea[:30]:
            return linea[:300]
    return ""


def parsear_avisos(paginas: list[str], url_pdf: str = "", fecha_edicion: date | None = None) -> list[Oportunidad]:
    lineas: list[tuple[int, str]] = []
    for nro, pag in enumerate(paginas, start=1):
        for linea in pag.replace("\r", "\n").split("\n"):
            linea = linea.strip()
            if not linea or _RE_MARCA.match(linea) or _RE_ENCABEZADO.search(linea) or re.fullmatch(r"\d{1,3}", linea):
                continue
            lineas.append((nro, linea))

    avisos: list[Oportunidad] = []
    seccion, rubro, rubro_txt, estado_seccion = "", "", "", "Convocatoria"
    buffer: list[tuple[int, str]] = []
    esperando_rubro = False
    empezo = False

    for nro, linea in lineas:
        clave = _clave_rubro(linea)
        if clave in SECCIONES:
            seccion, estado_seccion, rubro, rubro_txt = clave, SECCIONES[clave], "", ""
            esperando_rubro, empezo, buffer = True, True, []
            continue
        if not empezo:
            continue
        if esperando_rubro and not buffer and _es_mayusculas(linea):
            candidato = (rubro + " " + clave).strip() if rubro else clave
            if any(r.startswith(candidato) for r in RUBROS_CONOCIDOS):
                rubro = candidato
                rubro_txt = (rubro_txt + " " + linea).strip()
                if candidato in RUBROS_CONOCIDOS:
                    esperando_rubro = False
                continue
            esperando_rubro = False
        elif esperando_rubro and buffer:
            esperando_rubro = False

        buffer.append((nro, linea))
        fin = _RE_FIN.match(linea)
        if fin:
            op = _armar_aviso(buffer, rubro_txt, estado_seccion, fin, url_pdf, fecha_edicion)
            if op:
                avisos.append(op)
            buffer = []
            esperando_rubro = False
    return avisos


def _armar_aviso(buffer, rubro, estado_seccion, fin, url_pdf, fecha_edicion) -> Oportunidad | None:
    textos = [l for _, l in buffer]
    texto = "\n".join(textos)
    pagina = buffer[0][0]

    idx_proc = next((i for i, l in enumerate(textos) if _RE_PROCESO.match(l)), None)
    if idx_proc is not None:
        # Organismo = líneas en mayúscula justo arriba del tipo de proceso (máximo 3).
        org: list[str] = []
        for l in reversed(textos[:idx_proc]):
            if _es_mayusculas(l) and len(org) < 3:
                org.insert(0, l)
            else:
                break
        organismo = re.sub(r"\s*-\s*$", "", " ".join(org)).replace(" - ", " – ").strip()
        numero = textos[idx_proc]
        tipo = _RE_PROCESO.match(numero).group(0)
        tipo = tipo[0].upper() + tipo[1:].lower()
        pos_proc = texto.find(numero)
    else:
        organismo = textos[0] if textos and _es_mayusculas(textos[0]) else ""
        numero, tipo, pos_proc = "", "", 0

    titulo = _objeto(texto, pos_proc)
    norm = normalizar(texto)
    es_circular = estado_seccion == "Circular" or bool(_RE_CIRCULAR.search(norm))
    estado = "Circular" if es_circular and estado_seccion == "Convocatoria" else estado_seccion

    # La última línea ("e. 10/11/2026 N° ... v. ...") es la de publicación: no cuenta para plazos.
    fechas = _fechas_por_bloque("\n".join(textos[:-1]))
    exp = re.search(r"Expediente\s*N?[°º]?\s*:?\s*([A-Z0-9][\w\-# /.]{3,60})", texto, re.I)
    fecha_pub = datetime.strptime(fin.group(1), "%d/%m/%Y")

    return Oportunidad(
        fuente="Boletín Oficial (3ª sección)",
        titulo=titulo or numero or organismo,
        organismo=organismo,
        numero_proceso=numero,
        tipo_contratacion=tipo,
        estado=estado,
        rubro=rubro.capitalize() if rubro else "",
        expediente=exp.group(1).strip() if exp else "",
        fecha_publicacion=fecha_pub,
        fecha_limite_consultas=fechas["consultas"],
        fecha_presentacion=fechas["presentacion"],
        fecha_apertura=fechas["apertura"],
        link=f"{url_pdf}#page={pagina}" if url_pdf else "",
        texto=texto,
        es_circular=es_circular,
    )


# ---------------------------------------------------------------------------
# Fuente
# ---------------------------------------------------------------------------
class BoletinOficial(Fuente):
    nombre = "Boletín Oficial – 3ª sección (COMPR.AR, CONTRAT.AR y empresas del Estado)"

    def __init__(self, config: dict, cache_dir: Path, dias: int):
        super().__init__(config)
        self.cache = cache_dir / "boletin"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.dias = dias
        self.sesion = requests.Session()
        self.sesion.headers["User-Agent"] = USER_AGENT

    def _listado(self, dia: date) -> dict[date, dict[str, str]]:
        r = self.sesion.get(f"{OTS_URL}/ots/", params={"date_filter": dia.strftime("%d-%m-%Y")}, timeout=60)
        r.raise_for_status()
        return parsear_listado(r.text)

    def _pdf(self, hash_pdf: str) -> bytes:
        archivo = self.cache / f"{hash_pdf}.pdf"
        if archivo.exists():
            return archivo.read_bytes()
        r = self.sesion.get(f"{OTS_URL}/ots/download/{hash_pdf}/0/", timeout=120)
        r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest() != hash_pdf:
            raise ValueError("El PDF descargado no coincide con el hash publicado por el Boletín")
        archivo.write_bytes(r.content)
        return r.content

    def obtener(self) -> ResultadoFuente:
        hoy = date.today()
        ops: list[Oportunidad] = []
        leidas, errores = 0, []
        for atras in range(self.dias):
            dia = hoy - timedelta(days=atras)
            if dia.weekday() >= 5:      # sábados y domingos no hay edición
                continue
            try:
                hash_pdf = self._listado(dia).get(dia, {}).get(SECCION_TERCERA)
                if not hash_pdf:
                    continue
                url = f"{OTS_URL}/ots/download/{hash_pdf}/0/"
                ops += parsear_avisos(extraer_paginas(self._pdf(hash_pdf)), url, dia)
                leidas += 1
            except Exception as e:  # una edición rota no frena el resto
                errores.append(f"{dia:%d/%m}: {e.__class__.__name__}")
        estado = "ok" if leidas else "error"
        detalle = f"{leidas} ediciones leídas, {len(ops)} avisos"
        if errores:
            detalle += f" — sin leer: {', '.join(errores[:5])}"
        return ResultadoFuente(self.nombre, estado, detalle, ops)
