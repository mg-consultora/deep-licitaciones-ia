
#!/usr/bin/env python3
"""Consulta pública por número en CONTRAT.AR. No modifica el tablero."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin
from buscar_licitaciones import SesionContratar, configuracion, ErrorPortal

CAMPO = 'ctl00$CPH1$txtNumeroProceso'
BOTON = 'ctl00$CPH1$btnListarPliegoNumero'
URL = 'https://contratar.gob.ar/BuscarAvanzado.aspx'


def consultar(numero):
    cfg = configuracion()
    cfg['max_pedidos'] = max(cfg['max_pedidos'], 6)
    sesion = SesionContratar(cfg)
    sesion.abrir()
    pagina = sesion.leer_pagina(URL, referer=cfg['base'] + '/')
    if CAMPO not in pagina.campos:
        raise ErrorPortal('No apareció el campo oficial de número de proceso')
    if '__VIEWSTATE' not in pagina.campos:
        raise ErrorPortal('Falta el estado ASP.NET del formulario')
    pagina.campos[CAMPO] = numero
    respuesta = sesion.postback(pagina, BOTON, '')
    resultado, redireccion = sesion.respuesta_a_pagina(respuesta, pagina)
    if redireccion:
        resultado = sesion.leer_pagina(redireccion, referer=pagina.url)
    if resultado is None:
        raise ErrorPortal('No se recibió página de resultados')
    texto = resultado.raiz.texto() if hasattr(resultado.raiz, 'texto') else re.sub(r'<[^>]+>', ' ', resultado.html)
    texto = re.sub(r'\s+', ' ', texto)
    coincide = bool(re.search(r'(?<![\w/-])' + re.escape(numero) + r'(?![\w/-])', texto, re.I))
    enlaces = []
    for nodo in resultado.raiz.descendientes():
        if nodo.tag != 'a':
            continue
        href = nodo.attrs.get('href', '')
        if not href or href.lower().startswith(('javascript:', '#')):
            continue
        if 'contratar.gob.ar' in urljoin(resultado.url, href):
            enlaces.append({'texto': nodo.texto()[:120], 'url': urljoin(resultado.url, href)})
    salida = {
        'numero_solicitado': numero,
        'url_consultada': URL,
        'url_resultado': resultado.url,
        'numero_visible_en_respuesta': coincide,
        'estado': 'RESPUESTA_CON_NUMERO' if coincide else 'SIN_COINCIDENCIA_VERIFICADA',
        'aviso': 'La presencia del número no verifica fechas ni confirma que la ficha sea correcta.',
        'texto_respuesta': texto[:12000],
        'enlaces': enlaces[:50],
        'pedidos_http': sesion.pedidos,
    }
    Path('resultado_busqueda_avanzada.json').write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Consulta completada. Número visible:', coincide)
    print('Archivo: resultado_busqueda_avanzada.json')
    print('URL resultado:', resultado.url)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--numero', required=True)
    args = parser.parse_args()
    numero = args.numero.strip().upper()
    if not re.fullmatch(r'\d+(?:/\d+)?-\d+-[A-Z]+\d+', numero):
        parser.error('Número inválido; ejemplo: 34-0003-LPU26')
    consultar(numero)
