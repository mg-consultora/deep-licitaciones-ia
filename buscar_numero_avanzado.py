
#!/usr/bin/env python3
"""Consulta experimental CONTRAT.AR por número; no modifica el tablero.

Distingue un resultado oficial de un número repetido en el formulario.
Registra enlaces y acciones JavaScript para investigar el acceso
a la ficha individual de cada proceso.
"""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from buscar_licitaciones import (
    SesionContratar,
    configuracion,
    ErrorPortal,
)

URL = 'https://contratar.gob.ar/BuscarAvanzado.aspx'
CAMPO = 'ctl00$CPH1$txtNumeroProceso'
BOTON = 'ctl00$CPH1$btnListarPliegoNumero'
SALIDA = Path('resultado_busqueda_avanzada.json')


def consultar(numero):
    salida = {
        'numero_solicitado': numero,
        'fuente': URL,
        'estado': 'NO_VERIFICADO',
        'encontrado': False,
        'registros': [],
        'error': None,
    }

    try:
        cfg = configuracion()
        cfg['max_pedidos'] = max(cfg['max_pedidos'], 6)

        sesion = SesionContratar(cfg)
        sesion.abrir()

        pagina = sesion.leer_pagina(
            URL,
            referer=cfg['base'] + '/'
        )

        if CAMPO not in pagina.campos or '__VIEWSTATE' not in pagina.campos:
            raise ErrorPortal(
                'El formulario no contiene los campos ASP.NET necesarios'
            )

        controles = [
            n for n in pagina.raiz.descendientes()
            if n.attrs.get('name') == BOTON
            or n.attrs.get('id') == BOTON.replace('$', '_')
        ]

        campos = dict(pagina.campos)
        campos[CAMPO] = numero

        submit = next(
            (
                n for n in controles
                if n.tag == 'input'
                and n.attrs.get('type', '').lower() == 'submit'
            ),
            None
        )

        if submit is not None:
            campos[BOTON] = submit.attrs.get('value', 'Buscar')
            campos['__EVENTTARGET'] = ''
            modo = 'submit_html'
        else:
            campos['__EVENTTARGET'] = BOTON
            campos['__EVENTARGUMENT'] = ''
            modo = 'postback_aspnet'

        destino = (
            urljoin(pagina.url, pagina.action)
            if pagina.action else pagina.url
        )

        respuesta = sesion.pedir(
            destino,
            datos=urlencode(campos).encode('utf-8'),
            cabeceras={
                'Content-Type':
                'application/x-www-form-urlencoded; charset=UTF-8'
            },
            referer=pagina.url
        )

        resultado, redireccion = sesion.respuesta_a_pagina(
            respuesta,
            pagina
        )

        if redireccion:
            resultado = sesion.leer_pagina(
                redireccion,
                referer=pagina.url
            )

        if resultado is None:
            raise ErrorPortal(
                'No se obtuvo una página de resultados'
            )

        salida['metodo_envio'] = modo
        salida['control_en_html'] = bool(controles)
        salida['url_resultado'] = resultado.url
        salida['pedidos_http'] = sesion.pedidos

        filas = []

        for tr in resultado.raiz.descendientes():
            if tr.tag != 'tr':
                continue

            celdas = [
                n for n in tr.descendientes()
                if n.tag in ('td', 'th')
            ]

            if not celdas:
                continue

            texto = ' | '.join(
                c.texto().strip() for c in celdas
            )

            if not re.search(
                r'(?<![\w/-])'
                + re.escape(numero)
                + r'(?![\w/-])',
                texto,
                re.I
            ):
                continue

            enlaces = []
            acciones = []

            for a in tr.descendientes():
                if a.tag != 'a':
                    continue

                href = a.attrs.get('href', '').strip()
                onclick = a.attrs.get('onclick', '').strip()

                if href and not href.lower().startswith('javascript:'):
                    enlace = urljoin(resultado.url, href)

                    if urlparse(enlace).hostname == 'contratar.gob.ar':
                        enlaces.append(enlace)

                if onclick:
                    acciones.append(onclick[:500])

                if href.lower().startswith('javascript:'):
                    acciones.append(href[:500])

            enlaces = list(dict.fromkeys(enlaces))
            acciones = list(dict.fromkeys(acciones))

            filas.append({
                'texto': texto[:1200],
                'enlaces': enlaces,
                'acciones': acciones
            })

        salida['registros'] = filas
        salida['encontrado'] = bool(filas)

        salida['estado'] = (
            'REGISTRO_EN_TABLA'
            if filas else
            'SIN_REGISTRO_VERIFICADO'
        )

        salida['aviso'] = (
            'Se encontró una fila con el número solicitado. '
            'Se registraron enlaces y acciones disponibles. '
            'Las fechas y circulares requieren verificar '
            'la ficha oficial.'
            if filas else
            'La respuesta no contiene una fila verificable '
            'con el número solicitado. Esto NO demuestra '
            'que el expediente no exista.'
        )

        salida['tablas'] = len([
            n for n in resultado.raiz.descendientes()
            if n.tag == 'table'
        ])

        salida['texto_final_respuesta'] = (
            resultado.raiz.texto()[-1200:]
        )

    except Exception as e:
        salida['estado'] = 'ERROR_CONSULTA'
        salida['error'] = '%s: %s' % (
            type(e).__name__,
            str(e)[:300]
        )

    finally:
        SALIDA.write_text(
            json.dumps(
                salida,
                ensure_ascii=False,
                indent=2
            ),
            encoding='utf-8'
        )

        print('Estado:', salida['estado'])
        print('Encontrado en tabla:', salida['encontrado'])

        if salida['error']:
            print('Error:', salida['error'])

    if salida['estado'] == 'ERROR_CONSULTA':
        raise SystemExit(1)


if __name__ == '__main__':
    p = argparse.ArgumentParser()

    p.add_argument(
        '--numero',
        required=True
    )

    n = p.parse_args().numero.strip().upper()

    if not re.fullmatch(
        r'\d+(?:/\d+)?-\d+-[A-Z]+\d+',
        n
    ):
        p.error(
            'Número inválido (ejemplo: 34-0003-LPU26)'
        )

    consultar(n)
