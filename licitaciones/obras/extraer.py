"""Convierte una nota en un registro de obra.

Regla central: NO INVENTAR. Cada dato sale escrito en la nota; si no está, queda "No informado".
Las fechas se guardan tal como las escribe la nota ("segundo semestre de 2027") y se marcan:
  - confirmada: día exacto y sin palabras de previsión (prevé, estima, se espera…);
  - estimada: todo lo demás.
Los equipos DEEP son POTENCIALES: se deducen del tipo de obra y se rotulan así.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import requests

from .texto_base import buscar_fechas, detectar_provincia, normalizar
from .empresas import Catalogo
from .fuentes import Nota

NO_INFO = "No informado"

# --- Tipos de oportunidad (condición 4: diferenciar) ------------------------
LIC_ABIERTA = "Licitación abierta"
LIC_ANUNCIADA = "Licitación anunciada / registro de proveedores"
PROYECTO = "Proyecto anunciado"
EN_EJECUCION = "Adjudicado / en ejecución"
LIC_CERRADA = "Licitación cerrada"

_MES = r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
_EXPR_FECHA = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    rf"|\b\d{{1,2}}\s+de\s+{_MES}\s+(?:de|del)\s+\d{{4}}"
    r"|\b(?:primer|segundo|tercer|cuarto|1er|2do|3er|4to)\s+(?:semestre|trimestre|cuatrimestre)\s+(?:de|del)\s+(?:año\s+)?\d{4}"
    r"|\b(?:fines|finales|principios|comienzos|mediados|inicios)\s+(?:de|del)\s+(?:año\s+)?\d{4}"
    rf"|\b{_MES}\s+(?:de|del)\s+\d{{4}}"
    r"|\b(?:en|durante|para|hacia|hasta|desde)\s+(?:el\s+)?(?:año\s+)?20\d{2}\b",
    re.IGNORECASE,
)
_FECHA_DIA = re.compile(rf"^\d{{1,2}}/\d{{1,2}}/\d{{2,4}}$|^\d{{1,2}}\s+de\s+{_MES}\s+(?:de|del)\s+\d{{4}}$", re.I)
_PREVISION = re.compile(
    r"\b(preve|prevé|previst[oa]s?|estim\w*|se espera|esperan?|proyect\w*|planea\w*|apunta\w*|podr[ií]a\w*|"
    r"tentativ\w*|aproximadamente|objetivo|meta|calcula\w*|anticip\w*|deber[ií]a\w*|ser[aá]\s+en)\b", re.I)

CAMPOS_FECHA = {
    "lic_productos": ("Licitación de productos", r"licitaci[oó]n\s+(?:de|para\s+la\s+(?:compra|provisi[oó]n)\s+de)\s+(?:equipos|productos|materiales|suministros)|provisi[oó]n\s+de\s+equipos|compra\s+de\s+equipos|adquisici[oó]n\s+de\s+equipos"),
    "inicio_compras": ("Inicio de compras", r"inicio\s+de\s+(?:las\s+)?compras|proceso\s+de\s+compras|procurement|registro\s+de\s+proveedores|ronda\s+de\s+proveedores|compras?\s+de\s+largo\s+plazo"),
    "lic_obra": ("Licitación de obra", r"licitaci[oó]n|recepci[oó]n\s+de\s+ofertas|apertura\s+de\s+(?:sobres|ofertas)|presentaci[oó]n\s+de\s+ofertas|cierre\s+de\s+ofertas|pliego"),
    "inicio_obra": ("Inicio de obra", r"inicio\s+de\s+(?:la\s+|las\s+)?(?:obra|obras|construcci[oó]n)|comenzar[aá]n?\s+(?:la\s+|las\s+)?(?:construcci[oó]n|obras?)|iniciar[aá]n?\s+(?:la\s+|las\s+)?(?:construcci[oó]n|obras?)|empezar[aá]n?\s+a\s+construir|primera\s+piedra|arranque\s+de\s+(?:la\s+)?obra"),
    "fin_obra": ("Fin de obra / puesta en marcha", r"finaliza\w*|terminar[aá]|concluir\w*|habilitaci[oó]n\s+comercial|entrar[aá]\s+en\s+operaci[oó]n|entrada\s+en\s+operaci[oó]n|puesta\s+en\s+marcha|\bCOD\b|estar[aá]\s+operativ|primera\s+producci[oó]n|primer\s+(?:litio|cobre|petr[oó]leo|gas)"),
}

_NOMBRE = r"([A-ZÁÉÍÓÚÑ][\w&.\-]*(?:\s+(?:(?:y|&|de|del)\s+)?[A-ZÁÉÍÓÚÑ0-9][\w&.\-]*){0,5})"
_ROLES = {
    "epc": [
        r"adjudic\w*\s+(?:la\s+obra\s+|el\s+contrato\s+|la\s+construcci[oó]n\s+)?(?:a|al\s+consorcio|a\s+la\s+empresa|a\s+la\s+UTE|a\s+la\s+firma|a\s+la\s+constructora)\s+(?:la\s+)?" + _NOMBRE,
        r"contratista\s+(?:principal\s+)?(?:ser[aá]\s+|es\s+|elegid[oa]\s+es\s+)?(?:la\s+empresa\s+)?" + _NOMBRE,
        r"contrato\s+EPC\s+(?:con|a)\s+(?:la\s+empresa\s+)?" + _NOMBRE,
        r"(?:construcci[oó]n|obra|obras)\s+(?:estar[aá]n?|qued[oó]|quedaron)\s+a\s+cargo\s+de\s+(?:la\s+empresa\s+|la\s+UTE\s+|la\s+firma\s+)?" + _NOMBRE,
    ],
    "desarrolladora": [r"desarrollad[oa]s?\s+por\s+(?:la\s+empresa\s+|la\s+compa[ñn][ií]a\s+)?" + _NOMBRE, r"desarrolladora\s+" + _NOMBRE],
    "ingenieria": [r"ingenier[ií]a\s+(?:de\s+detalle\s+|b[aá]sica\s+|conceptual\s+)?(?:estar[aá]\s+)?(?:a\s+cargo\s+de|por|de\s+la\s+firma)\s+(?:la\s+empresa\s+|la\s+firma\s+)?" + _NOMBRE],
    "operadora": [_NOMBRE + r"\s+adjudic\w+\s+(?:a|al)\s", r"(?:operad[oa]|liderad[oa]|impulsad[oa]|propiedad\s+de)\s+por\s+(?:la\s+empresa\s+|la\s+compa[ñn][ií]a\s+|la\s+petrolera\s+|la\s+minera\s+)?" + _NOMBRE],
}
_NO_NOMBRES = {"el", "la", "los", "las", "argentina", "gobierno", "estado", "nacion", "provincia", "secretaria", "ministerio"}

_TIPO_OBRA_NOMBRE = re.compile(
    r"((?i:parque\s+(?:solar|e[oó]lico|fotovoltaico)|central\s+(?:t[eé]rmica|hidroel[eé]ctrica|nuclear)|planta\s+compresora|"
    r"gasoducto|oleoducto|poliducto|estaci[oó]n\s+transformadora|l[ií]nea\s+de\s+alta\s+tensi[oó]n|proyecto|mina|"
    r"yacimiento|subestaci[oó]n|terminal|represa|aprovechamiento|planta))\s+"
    r"([A-ZÁÉÍÓÚÑ0-9][\w\-]*(?:\s+(?:de|del|la|las|los|y|[A-ZÁÉÍÓÚÑ0-9][\w\-]*)){0,5})"
)
_SUBOBRAS = ["estación de bombeo", "planta compresora", "subestación", "estación transformadora", "línea de alta tensión",
             "tanques de almacenamiento", "terminal", "campamento", "planta de tratamiento", "planta de procesamiento",
             "acueducto", "línea eléctrica", "sala de control", "monoboya", "planta de carbonato", "planta concentradora",
             "almacenamiento en baterías", "planta de licuefacción"]
_MONTO = re.compile(
    r"(?:US\$|USD|U\$S|u\$s|US\s\$)\s?[\d.,]+\s*(?:mil\s+millones|millones|MM|M\b|bn)?"
    r"|[\d.,]+\s+(?:mil\s+)?millones\s+de\s+d[oó]lares", re.I)
_LOCALIDAD = re.compile(r"(?:localidad|ciudad|departamento|paraje|cercan[ií]as)\s+de\s+([A-ZÁÉÍÓÚÑ][\w]+(?:\s+(?:de\s+|del\s+)?[A-ZÁÉÍÓÚÑ][\w]+){0,3})")


def _oraciones(texto: str) -> list[str]:
    return [o.strip() for o in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿\"“])", texto) if o.strip()]


def _limpiar_nombre(n: str) -> str:
    n = re.split(r"\.\s", n)[0]
    n = re.sub(r"\s+(?:y|de|del|la|las|los|en|para|por)$", "", n.strip(" .,;:"))
    return "" if normalizar(n) in _NO_NOMBRES or len(n) < 3 else n


def _patron_lista(claves: list[str]) -> re.Pattern:
    return re.compile("|".join(r"\b" + re.escape(normalizar(c)) for c in claves))


class Extractor:
    def __init__(self, config: dict, catalogo: Catalogo, ahora: datetime | None = None):
        self.cfg = config
        self.cat = catalogo
        self.ahora = ahora or datetime.now()
        self.tipos = {t: (_patron_lista(d["claves"]), d["equipos"]) for t, d in config["tipos_de_obra"].items()}
        self.senales = {s: _patron_lista(c) for s, c in config["senales"].items()}
        self.excluir = _patron_lista(config.get("excluir", []))
        self.minimo = config.get("puntaje_minimo", 5)

    # ------------------------------------------------------------------
    def relevante(self, nota: Nota) -> tuple[bool, dict]:
        t = normalizar(nota.contenido)
        tipos = [nombre for nombre, (p, _) in self.tipos.items() if p.search(t)]
        senales = [s for s, p in self.senales.items() if p.search(t)]
        prioritarias = self.cat.prioritarias_en(nota.contenido)
        propias = self.cat.propias_en(nota.contenido)
        puntaje = 2 * min(len(tipos), 2) + len(senales) + (2 if prioritarias else 0) + (1 if propias else 0)
        if self.excluir.search(t) and puntaje < self.minimo + 2:
            puntaje = 0
        if not tipos and "inversion" not in senales:
            puntaje = 0
        return puntaje >= self.minimo, {"tipos": tipos, "senales": senales, "prioritarias": prioritarias,
                                        "propias": propias, "puntaje": puntaje}

    # ------------------------------------------------------------------
    def nombre_obra(self, nota: Nota) -> str:
        """El nombre propio más repetido después de un tipo de obra ("Parque Solar El Quemado")."""
        conteo: dict[str, int] = {}
        for m in _TIPO_OBRA_NOMBRE.finditer(nota.contenido):
            nombre = _limpiar_nombre(f"{m.group(1)} {m.group(2)}")
            if nombre and len(m.group(2)) > 2:
                nombre = nombre[0].upper() + nombre[1:]
                conteo[nombre] = conteo.get(nombre, 0) + 1 + (2 if m.start() < len(nota.titulo) + 2 else 0)
        return max(conteo, key=conteo.get) if conteo else ""

    def extraer(self, nota: Nota, info: dict) -> dict:
        texto = nota.contenido
        norm = normalizar(texto)
        oraciones = _oraciones(texto)

        obra = self.nombre_obra(nota)
        subobras = [s for s in _SUBOBRAS
                    if re.search(r"\b" + r"\s+".join(re.escape(w) + r"(?:e?s)?" for w in normalizar(s).split()) + r"\b", norm)
                    and normalizar(s) not in normalizar(obra)]

        roles = {}
        for rol, patrones in _ROLES.items():
            for p in patrones:
                m = re.search(p, texto)
                if m and _limpiar_nombre(m.group(1)):
                    roles[rol] = _limpiar_nombre(m.group(1))
                    break
        prioritarias = info["prioritarias"]
        if "operadora" not in roles:
            dueñas = [e for _, e in prioritarias if e.sector != "Contratistas y EPC"]
            if dueñas:
                roles["operadora"] = dueñas[0].nombre
        if "epc" not in roles:
            epcs = [e for _, e in prioritarias if e.sector == "Contratistas y EPC"]
            if epcs and self.senales["adjudicacion"].search(norm):
                roles["epc"] = epcs[0].nombre

        # Fechas: una por campo, en la misma oración que la palabra clave.
        fechas: dict[str, dict] = {}
        for o in oraciones:
            claves = sorted((m.end(), campo) for campo, (_, patron) in CAMPOS_FECHA.items()
                            for m in re.finditer(patron, o, re.I))
            for m in _EXPR_FECHA.finditer(o):
                # La fecha se asigna a la palabra clave más cercana que la precede (máx. 140 caracteres).
                previas = [(fin, campo) for fin, campo in claves if fin <= m.start() and m.start() - fin <= 140]
                if not previas:
                    continue
                campo = previas[-1][1]
                if campo in fechas:
                    continue
                expr = m.group(0).strip()
                tramo = o[previas[-1][0] - 60 if previas[-1][0] > 60 else 0: m.end()]
                exacta = bool(_FECHA_DIA.match(expr))
                tipo = "confirmada" if exacta and not _PREVISION.search(tramo) and not _PREVISION.search(o[:m.start()]) else "estimada"
                fechas[campo] = {"texto": expr, "tipo": tipo, "fuente": nota.link, "frase": o[:300]}

        tipo_oportunidad, estado = self._clasificar(norm, fechas)
        tipos_obra = info["tipos"]
        equipos: list[str] = []
        for t in tipos_obra:
            for e in self.tipos[t][1]:
                if e not in equipos:
                    equipos.append(e)
        sector = self._sector(tipos_obra, prioritarias)
        provincia = detectar_provincia(texto)
        loc = _LOCALIDAD.search(texto)
        monto = _MONTO.search(texto)

        return {
            "obra": obra or nota.titulo[:140],
            "obra_identificada": bool(obra),
            "subobras": subobras,
            "operadora": roles.get("operadora", NO_INFO),
            "desarrolladora": roles.get("desarrolladora", NO_INFO),
            "ingenieria": roles.get("ingenieria", NO_INFO),
            "epc": roles.get("epc", NO_INFO),
            "provincia": NO_INFO if provincia.startswith("Nacional") else provincia,
            "localidad": loc.group(1) if loc else NO_INFO,
            "sector": sector,
            "tipo_obra": tipos_obra,
            "tipo": tipo_oportunidad,
            "estado": estado,
            "presupuesto": monto.group(0).strip() if monto else NO_INFO,
            "fechas": fechas,
            "equipos": equipos,
            "empresas": [e.nombre for _, e in prioritarias][:8],
            "propias": info["propias"],
            "fuentes": [{"titulo": nota.titulo, "link": nota.link, "medio": nota.medio,
                         "fecha_nota": nota.fecha.strftime("%Y-%m-%d") if nota.fecha else "",
                         "fecha_verificacion": self.ahora.strftime("%Y-%m-%d")}],
            "verificado_manual": False,
            "lectura": "reglas",
        }

    def _clasificar(self, norm: str, fechas: dict) -> tuple[str, str]:
        estados = []
        if "rigi" in norm and re.search(r"aprob", norm):
            estados.append("RIGI aprobado")
        elif "rigi" in norm and re.search(r"solicit|present|evaluaci|adhesion", norm):
            estados.append("RIGI en evaluación")
        if re.search(r"\badjudic", norm):
            estados.append("Adjudicada")
        if re.search(r"en construccion|avance de obra|% de avance|inicio la construccion|comenzo la construccion|obras en marcha", norm):
            estados.append("En construcción")
        lic = fechas.get("lic_obra") or fechas.get("lic_productos")
        if lic and lic["tipo"] == "confirmada":
            f = [d for _, d in buscar_fechas(lic["texto"])]
            if f and f[0] >= self.ahora:
                return LIC_ABIERTA, " · ".join(["Convocatoria con fecha límite"] + estados)
            if f:
                return LIC_CERRADA, " · ".join(["Plazo vencido según la nota"] + estados)
        if "Adjudicada" in estados or "En construcción" in estados:
            return EN_EJECUCION, " · ".join(estados)
        if re.search(r"lanzar[aá]?\s+(?:la\s+|una\s+)?licitacion|licitara|convocara|llamara a licitacion|registro de proveedores|ronda de proveedores|encuentro de proveedores|abrira la licitacion", norm):
            return LIC_ANUNCIADA, " · ".join(["Licitación o compras anunciadas"] + estados)
        return PROYECTO, " · ".join(estados) or "Anunciado en medios"

    def _sector(self, tipos: list[str], prioritarias) -> str:
        mapa = {"Parque solar": "Energía eléctrica", "Parque eólico": "Energía eléctrica", "Almacenamiento (BESS)": "Energía eléctrica",
                "Subestación / transmisión": "Energía eléctrica", "Central térmica / hidro / nuclear": "Energía eléctrica",
                "Oleoducto / gasoducto": "Oil & Gas", "Planta compresora / tratamiento": "Oil & Gas", "Puerto / terminal": "Oil & Gas",
                "Refinería / petroquímica": "Petroquímica", "Mina / planta minera": "Minería", "Industria / data center": "Industria"}
        for _, e in prioritarias:
            if e.sector not in ("Contratistas y EPC",):
                return {"Midstream": "Oil & Gas", "Downstream y petroquímica": "Petroquímica"}.get(e.sector, e.sector)
        return mapa.get(tipos[0], "Otros") if tipos else "Otros"


# ---------------------------------------------------------------------------
# Lectura con IA (opcional). Solo completa campos vacíos y solo si la cita está en la nota.
# ---------------------------------------------------------------------------
_PROMPT = """Leé la nota y devolvé SOLO un JSON. Regla absoluta: cada valor debe estar escrito en la nota.
Si un dato no está, usá null. No deduzcas, no completes con conocimiento propio.
Para cada dato devolvé {"valor": "...", "cita": "frase exacta de la nota de donde sale"}.
Campos: obra, subobra, operadora, desarrolladora, ingenieria, epc, localidad, presupuesto,
fecha_lic_productos, fecha_lic_obra, fecha_inicio_compras, fecha_inicio_obra, fecha_fin_obra.
En las fechas agregá "estimada": true si la nota la presenta como previsión o estimación.

NOTA:
"""


def completar_con_ia(registro: dict, nota: Nota, modelo: str) -> dict:
    clave = os.environ.get("ANTHROPIC_API_KEY")
    if not clave:
        return registro
    texto = nota.contenido[:12000]
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=90, headers={
        "x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": modelo, "max_tokens": 1500, "messages": [{"role": "user", "content": _PROMPT + texto}]})
    r.raise_for_status()
    salida = "".join(b.get("text", "") for b in r.json().get("content", []))
    m = re.search(r"\{.*\}", salida, re.S)
    if not m:
        return registro
    datos = json.loads(m.group(0))
    base = normalizar(texto)

    def valido(item) -> str | None:
        if not isinstance(item, dict) or not item.get("valor") or not item.get("cita"):
            return None
        cita, valor = normalizar(str(item["cita"])), normalizar(str(item["valor"]))
        # La cita tiene que estar en la nota y el valor dentro de la cita: si no, se descarta.
        if len(cita) < 8 or cita not in base or valor not in cita:
            return None
        return str(item["valor"]).strip()

    for campo, destino in [("operadora", "operadora"), ("desarrolladora", "desarrolladora"), ("ingenieria", "ingenieria"),
                           ("epc", "epc"), ("localidad", "localidad"), ("presupuesto", "presupuesto")]:
        v = valido(datos.get(campo))
        if v and registro.get(destino) in (None, "", NO_INFO):
            registro[destino] = v
    v = valido(datos.get("obra"))
    if v and not registro.get("obra_identificada"):
        registro["obra"], registro["obra_identificada"] = v, True
    v = valido(datos.get("subobra"))
    if v and v not in registro["subobras"]:
        registro["subobras"].append(v)
    for campo_ia, campo in [("fecha_lic_productos", "lic_productos"), ("fecha_lic_obra", "lic_obra"),
                            ("fecha_inicio_compras", "inicio_compras"), ("fecha_inicio_obra", "inicio_obra"),
                            ("fecha_fin_obra", "fin_obra")]:
        item = datos.get(campo_ia)
        v = valido(item)
        if v and campo not in registro["fechas"]:
            exacta = bool(_FECHA_DIA.match(v))
            registro["fechas"][campo] = {"texto": v, "tipo": "estimada" if item.get("estimada") or not exacta else "confirmada",
                                         "fuente": nota.link, "frase": str(item["cita"])[:300]}
    registro["lectura"] = "reglas + IA (verificada contra la nota)"
    return registro
