#!/usr/bin/env python3
"""Prueba no destructiva de conectividad de fuentes públicas. Solo stdlib."""
import http.client
import json
import socket
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path

HOSTS = [
    ('COMPR.AR', 'comprar.gob.ar', '/'),
    ('Argentina.gob.ar', 'www.argentina.gob.ar', '/'),
    ('Datos abiertos', 'datos.gob.ar', '/'),
    ('CAMMESA', 'cammesaweb.cammesa.com', '/'),
]
TIMEOUT = 10

def check(label, host, path):
    row = {'fuente': label, 'host': host, 'dns': 'NO PROBADO', 'tcp': 'NO PROBADO', 'tls': 'NO PROBADO', 'http': 'NO PROBADO', 'detalle': ''}
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys((i[0], i[4][0]) for i in infos))
        row['dns'] = 'OK'
    except Exception as exc:
        row['dns'] = 'FALLA'
        row['detalle'] = str(exc)
        return row
    selected = None
    for family, ip in addresses:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(TIMEOUT)
                sock.connect((ip, 443))
            selected = ip
            break
        except (OSError, TimeoutError) as exc:
            row['detalle'] = f'{ip}: {type(exc).__name__}: {exc}'
    if selected is None:
        row['tcp'] = 'FALLA'
        return row
    row['tcp'] = 'OK'
    try:
        with socket.create_connection((selected, 443), timeout=TIMEOUT) as sock:
            with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
                row['tls'] = f'OK ({tls.version()})'
    except Exception as exc:
        row['tls'] = 'FALLA'
        row['detalle'] = f'{type(exc).__name__}: {exc}'
        return row
    conn = None
    try:
        conn = http.client.HTTPSConnection(host, timeout=TIMEOUT)
        conn.request('GET', path, headers={'User-Agent': 'DEEP-Licitaciones/diagnostico-contacto', 'Accept': 'text/html,application/json,*/*'})
        response = conn.getresponse()
        response.read(1024)
        row['http'] = str(response.status)
        row['detalle'] = f'Location: {response.getheader("Location", "")[:160]}' if response.status in (301, 302, 303, 307, 308) else ''
    except Exception as exc:
        row['http'] = 'FALLA'
        row['detalle'] = f'{type(exc).__name__}: {exc}'
    finally:
        if conn is not None:
            conn.close()
    return row

def main():
    rows = []
    for label, host, path in HOSTS:
        print(f'Probando {label} ({host})...', flush=True)
        row = check(label, host, path)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        time.sleep(1)
    lines = ['# Diagnóstico de fuentes DEEP', '', f'Ejecutado: {datetime.now(timezone.utc).isoformat()}', '', '| Fuente | DNS | TCP | TLS | HTTP | Detalle |', '|---|---|---|---|---|---|']
    for r in rows:
        vals = [r['fuente'], r['dns'], r['tcp'], r['tls'], r['http'], r['detalle']]
        lines.append('| ' + ' | '.join(str(x).replace('|', '/') for x in vals) + ' |')
    lines += ['', '**Nota:** HTTP 200 solo confirma acceso, no que existan licitaciones vigentes o una API utilizable.']
    summary = '\n'.join(lines) + '\n'
    print('\n' + summary)
    import os
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(summary)
    Path('diagnostico_fuentes_resultado.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
