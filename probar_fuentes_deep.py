
"""Diagnostico estructural de tablas HTML publicas de AMBA I.
No descarga pliegos, no publica resultados en el tablero.
"""
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

FUENTES = {
    "CONTRAT.AR - AMBA I": "https://contratar.gob.ar/PLIEGO/VistaPreviaPliegoCiudadano.aspx?qs=BQoBkoMoEhyeqdlsIRjlbVzpmYCDKQ1YOo1f39Qg%7Cky815ZCD%7CkfxdssdIaOnmLmI4ts42%2FeS0aiuALKYAdQz06KinBOvULkr%2FDpt5kPBe0%3D",
    "CAMMESA - AMBA I": "https://cammesaweb.cammesa.com/ambai/",
    "CAMMESA - Convocatorias": "https://cammesaweb.cammesa.com/inicio-licitaciones/",
}

FECHA = re.compile(
    r"\b(?:0?[1-9]|[12][0-9]|3[01])[/\-](?:0?[1-9]|1[0-2])[/\-]20\d{2}(?:\s+\d{1,2}:\d{2})?\b"
)

ETIQUETAS = (
    "fecha", "apertura", "presentacion", "publicacion",
    "consulta", "circular", "prorroga", "proceso",
    "expediente", "organismo", "contratacion"
)


class TablaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tablas = []
        self.tabla = None
        self.fila = None
        self.celda = None
        self.saltar = 0
        self.textos = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.saltar += 1
        if tag == "table":
            if self.tabla is None:
                self.tabla = []
        elif tag == "tr" and self.tabla is not None:
            self.fila = []
        elif tag in ("td", "th") and self.fila is not None:
            self.celda = []

    def handle_data(self, data):
        if self.saltar or not data.strip():
            return
        valor = " ".join(data.split())
        self.textos.append(valor)
        if self.celda is not None:
            self.celda.append(valor)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.saltar:
            self.saltar -= 1
        elif tag in ("td", "th") and self.celda is not None:
            self.fila.append(" ".join(self.celda).strip())
            self.celda = None
        elif tag == "tr" and self.fila is not None:
            if any(self.fila):
                self.tabla.append(self.fila)
            self.fila = None
        elif tag == "table" and self.tabla is not None:
            if self.tabla:
                self.tablas.append(self.tabla)
            self.tabla = None


def probar(nombre, url):
    salida = {
        "fuente": nombre,
        "url": url,
        "http": None,
        "numero_proceso": None,
        "filas_con_etiquetas": [],
        "filas_con_fechas": [],
        "alertas": [],
    }

    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; DEEP-Licitaciones/1.0)"
            },
        )

        with urlopen(req, timeout=30) as resp:
            salida["http"] = resp.status
            raw = resp.read(2_000_000)
            charset = resp.headers.get_content_charset() or "utf-8"

        parser = TablaParser()
        parser.feed(raw.decode(charset, errors="replace"))

        texto = " ".join(parser.textos)
        match = re.search(r"\b34-0003-LPU26\b", texto, re.I)
        salida["numero_proceso"] = match.group(0) if match else None
        salida["total_tablas"] = len(parser.tablas)

        for i, tabla in enumerate(parser.tablas):
            for j, fila in enumerate(tabla):
                if not any(fila):
                    continue

                plano = " | ".join(fila)
                registro = {
                    "tabla": i + 1,
                    "fila": j + 1,
                    "celdas": fila[:8],
                }

                if (
                    any(p in plano.lower() for p in ETIQUETAS)
                    and len(salida["filas_con_etiquetas"]) < 45
                ):
                    salida["filas_con_etiquetas"].append(registro)

                if (
                    FECHA.search(plano)
                    and len(salida["filas_con_fechas"]) < 35
                ):
                    salida["filas_con_fechas"].append(registro)

        if not parser.tablas:
            salida["alertas"].append(
                "No hay tablas HTML detectables: podria requerir otro metodo de extraccion."
            )

        salida["alertas"].append(
            "Las filas son evidencia estructural, NO plazos confirmados sin validar su etiqueta."
        )

    except Exception as exc:
        salida["alertas"].append(
            f"Error: {type(exc).__name__}: {exc}"
        )

    return salida


def main():
    reporte = {
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "resultados": [],
    }

    for nombre, url in FUENTES.items():
        r = probar(nombre, url)
        reporte["resultados"].append(r)

        print(
            "\nFUENTE:", nombre,
            "HTTP:", r["http"],
            "TABLAS:", r.get("total_tablas", 0),
        )

        print(
            "PROCESO:",
            r["numero_proceso"] or "no detectado",
        )

        print("FILAS DE FECHAS (celdas separadas):")

        for fila in r["filas_con_fechas"][:12]:
            print(
                " - Tabla", fila["tabla"],
                "fila", fila["fila"],
                ":", " | ".join(fila["celdas"])[:350],
            )

        print("OTRAS FILAS RELEVANTES:")

        for fila in r["filas_con_etiquetas"][:12]:
            print(
                " - Tabla", fila["tabla"],
                "fila", fila["fila"],
                ":", " | ".join(fila["celdas"])[:350],
            )

        for alerta in r["alertas"]:
            print("AVISO:", alerta)

    Path("prueba_tablas_deep.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        "\nDiagnostico: prueba_tablas_deep.json. No se modifico el tablero."
    )


if __name__ == "__main__":
    main()
