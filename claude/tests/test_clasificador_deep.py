"""Casos de regresión del catálogo comercial DEEP."""
from licitaciones.tablero import evaluar

def test_rechaza_ups_oficina_en_parque_industrial():
    puntos, _ = evaluar({"titulo": "UPS para computadoras de oficina", "texto": "Entrega en Parque Industrial"})
    assert puntos == 0

def test_rechaza_baterias_camionetas():
    puntos, _ = evaluar({"titulo": "Adquisición de baterías para camionetas", "texto": "Parque industrial de Neuquén"})
    assert puntos == 0

def test_admite_rectificador_y_banco_industrial():
    puntos, _ = evaluar({"titulo": "Suministro de rectificador y banco de baterías 110 Vcc"})
    assert puntos > 0

def test_rechaza_ups_generica_con_industrial_lejano():
    puntos, _ = evaluar({"titulo": "UPS para sala de reuniones", "texto": "UPS " + "x" * 500 + " industrial"})
    assert puntos == 0
