
import json
import csv
import io
from urllib.request import urlopen
from datetime import datetime, timezone
from pathlib import Path

# Productos y servicios de interes comercial

PALABRAS_CLAVE = [
    "UPS industrial",
    "UPS trifasica",
    "sistema de alimentacion ininterrumpida",
    "rectificador industrial",
    "cargador de baterias",
    "banco de baterias",
    "baterias estacionarias",
    "baterias industriales",
    "baterias ni-cd",
    "energia critica",
    "corriente continua",
    "48 VCC",
    "110 VCC",
    "125 VCC",
    "220 VCC",
    "subestacion electrica",
    "estacion transformadora",
    "central electrica",
    "parque solar",
    "planta fotovoltaica",
    "parque eolico",
    "almacenamiento energetico",
    "BESS",
    "mineria",
    "oil and gas",
    "petroquimica",
]

# Terminos que indican equipamiento informatico o domestico
PALABRAS_EXCLUIDAS = [
    "bateria automotor",
    "bateria para auto",
    "bateria para moto",
    "bateria para camion",
    "bateria de arranque",
    "bateria para vehiculo",
    "bateria para maquinaria vial",
    "notebook",
    "laptop",
    "celular",
    "tablet",
    "ups para pc",
    "ups domestica",
    "bateria para computadora",
    "bateria para notebook",
    "pila alcalina",
]


# Fuentes oficiales pendientes de integracion
FUENTES = [
    {
        "nombre": "COMPR.AR - Convocatorias CSV",
        "url": "https://infra.datos.gob.ar/catalog/jgm/dataset/4/distribution/4.21/download/Convocatorias.csv",
        "estado": "pendiente",
    },

    {
        "nombre": "COMPR.AR",
        "url": "https://comprar.gob.ar/",
        "estado": "pendiente",
    },
    {
        "nombre": "CONTRAT.AR",
        "url": "https://contratar.gob.ar/",
        "estado": "pendiente",
    },
]

def es_licitacion_industrial(descripcion):
    texto = descripcion.lower()

    # Excluir baterias informaticas y de vehiculos
    if any(palabra in texto for palabra in PALABRAS_EXCLUIDAS):
        return False

    # Buscar equipos y sectores industriales
    return any(palabra.lower() in texto for palabra in PALABRAS_CLAVE)


def descargar_convocatorias():
    url = "https://comprar.gob.ar/"

    with urlopen(url, timeout=60) as respuesta:
        contenido = respuesta.read()
        print("Estado HTTP:", respuesta.status)

    texto = contenido.decode("utf-8-sig", errors="replace")
    print("Página descargada. Caracteres:", len(texto))

    return []
    




def main():
    
    try:
        convocatorias = descargar_convocatorias()
        print("Total de registros leídos:", len(convocatorias))
    except Exception as error:
        print("Error al consultar COMPR.AR:", error)
        raise
    resultado = {
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "estado": "sin_fuentes_conectadas",
        "fuentes": FUENTES,
        "licitaciones": [],
    }

    Path("licitaciones.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Archivo de datos generado.")
    print("Licitaciones verificadas: 0")
    print("Pendiente: integrar consultas a fuentes oficiales.")

if __name__ == "__main__":
    main()
