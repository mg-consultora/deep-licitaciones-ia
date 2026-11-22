"""Extractor seguro de fechas y circulares desde fichas COMPR.AR con Chromium.
Nunca interpreta apertura como cierre ni 'acepta prórroga' como prórroga otorgada.
"""
import re
from datetime import datetime
from bs4 import BeautifulSoup

NUMERO = re.compile(r"\b\d{2,3}(?:/\d+)?-\d{4}-[A-Z]{3}\d{2}\b", re.I)
FECHA = re.compile(r"(?<!\d)(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}))?",re.I)
ETIQUETAS_CIERRE = ("fin de recepción de ofertas","fin de recepcion de ofertas",
 "fecha límite de presentación","fecha limite de presentacion","cierre de ofertas",
 "fin de presentación de ofertas","fin de presentacion de ofertas")
ETIQUETAS_APERTURA = ("fecha y hora acto de apertura","fecha de apertura","acto de apertura")
CERRADOS = re.compile(r"\b(adjudicad[oa]s?|preadjudicad[oa]s?|desiert[oa]s?|anulad[oa]s?|finalizad[oa]s?|fracasad[oa]s?)\b",re.I)

def parse_fecha(texto):
    m=FECHA.search(texto or "")
    if not m: return None
    try: return datetime.strptime(m.group(1)+" "+(m.group(2) or "00:00"),"%d/%m/%Y %H:%M")
    except ValueError: return None

def extraer_ficha(html, numero):
    soup=BeautifulSoup(html,"html.parser")
    texto=soup.get_text("\n",strip=True)
    if numero not in texto: return {"numero":numero,"verificada":False,"motivo":"numero_no_coincide"}
    lineas=[s.strip() for s in texto.splitlines() if s.strip()]
    cierre,apertura,estado=None,None,None
    for i,linea in enumerate(lineas):
        etiqueta=linea.casefold()
        # El valor aparece en la misma línea o en la siguiente celda visible.
        ventana=" ".join(lineas[i:i+3])
        if any(e in etiqueta for e in ETIQUETAS_CIERRE) and len(linea)<110:
            cierre=cierre or parse_fecha(ventana)
        if any(e in etiqueta for e in ETIQUETAS_APERTURA) and len(linea)<110:
            apertura=apertura or parse_fecha(ventana)
        if etiqueta in ("estado","estado del proceso","situación","situacion") and i+1<len(lineas):
            candidato=lineas[i+1][:100]
            if re.search(r"^(publicad|convocad|adjudicad|preadjudicad|desiert|anulad|finalizad|en evaluaci[oó]n|apertura)", candidato, re.I):
                estado=candidato
    circulares=[]
    # Solo registros de la sección Circulares, no el campo 'Acepta prórroga'.
    seccion=soup.find(string=lambda t: bool(t and t.strip().casefold()=="circulares"))
    if seccion:
        tabla=seccion.find_parent().find_next("table") if seccion.find_parent() else None
        if tabla:
            for fila in tabla.select("tr"):
                celdas=[x.get_text(" ",strip=True) for x in fila.find_all(["td","th"],recursive=False)]
                if len(celdas)>=2 and celdas[0].strip().isdigit() and parse_fecha(celdas[1]):
                    circulares.append({"numero":celdas[0],"publicacion":celdas[1],
                                      "tipo":celdas[2] if len(celdas)>2 else ""})
    vigencia=bool(cierre and cierre>datetime.now() and not CERRADOS.search(estado or ""))
    return {"numero":numero,"verificada":True,"fecha_apertura":apertura.isoformat() if apertura else None,
            "fecha_cierre":cierre.isoformat() if cierre else None,"estado":estado,
            "circulares":circulares,"prorroga_confirmada":False,
            "vigencia_certificada":vigencia,
            "motivo":"cierre_futuro_confirmado" if vigencia else "cierre_no_acreditado_o_vencido"}
