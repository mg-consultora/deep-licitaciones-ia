
import json
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

def main():
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
