#!/usr/bin/env python3
"""Auditoría única: salida, tablero y consulta EN VIVO de CONTRAT.AR. No modifica archivos."""
import json, re, sys, urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from html.parser import HTMLParser

class Filas(HTMLParser):
    def __init__(self):
        super().__init__(); self.tabla=False; self.fila=False; self.celda=False; self.buf=[]; self.cols=[]; self.rows=[]; self.link=''; self.links={}
    def handle_starttag(self,t,a):
        a=dict(a)
        if t=='table' and a.get('id')=='ctl00_CPH1_GridListaPliegos': self.tabla=True
        elif self.tabla and t=='tr': self.fila=True; self.cols=[]; self.link=''
        elif self.fila and t=='td': self.celda=True; self.buf=[]
        elif self.celda and t=='a' and not self.link: self.link=a.get('href','')
    def handle_data(self,d):
        if self.celda: self.buf.append(d)
    def handle_endtag(self,t):
        if t=='td' and self.celda: self.cols.append(' '.join(' '.join(self.buf).split())); self.celda=False
        elif t=='tr' and self.fila:
            if len(self.cols)==6: self.rows.append(self.cols); self.links[self.cols[0]]=self.link
            self.fila=False
        elif t=='table' and self.tabla: self.tabla=False

errors=[]; warnings=[]; checks=[]
def ok(s): checks.append(s); print('OK:',s)
def fail(s): errors.append(s); print('ERROR:',s)
def warn(s): warnings.append(s); print('AVISO:',s)

root=Path('.'); script=root/'buscar_licitaciones.py'; dashboard=root/'index.html'; output=root/'licitaciones.json'
if not output.exists(): fail('No existe licitaciones.json'); data={}
else:
    try: data=json.loads(output.read_text(encoding='utf8'))
    except Exception as e: fail(f'JSON inválido: {e}'); data={}
items=data.get('licitaciones',[])
if not isinstance(items,list): fail('licitaciones no es lista'); items=[]
now=datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).replace(tzinfo=None)
seen=set()
for i,r in enumerate(items):
    n=str(r.get('numero') or f'fila-{i}')
    if r.get('fuente')!='CONTRAT.AR': fail(f'{n}: fuente distinta de CONTRAT.AR')
    if n in seen: fail(f'{n}: duplicado')
    seen.add(n)
    if 'contratar.gob.ar' not in str(r.get('enlace','')): warn(f'{n}: enlace sin dominio oficial')
    dates={}
    for key in ('publicacion','consultas','cierreOfertas','documentacionFisica','apertura'):
        v=r.get(key)
        if v:
            try: dates[key]=datetime.fromisoformat(v).replace(tzinfo=None)
            except Exception: fail(f'{n}: fecha inválida {key}={v}')
    if any(dates.get(k) and dates[k]<now for k in ('cierreOfertas','apertura')): fail(f'{n}: vencido en salida')
    if not dates.get('cierreOfertas'): warn(f'{n}: cierre sin publicar; estado debe ser pendiente')
    if not r.get('detalleVerificado'): warn(f'{n}: ficha no verificada')
if items: ok(f'{len(items)} registros auditados (duplicados, fuentes, fechas y vencimientos)')
else: warn('El JSON no contiene licitaciones; esto NO prueba que el portal esté vacío')
if script.exists():
    code=script.read_text(encoding='utf8')
    try: compile(code,str(script),'exec'); ok('Sintaxis del agente')
    except SyntaxError as e: fail(f'Sintaxis agente: {e}')
    if re.search(r'PUBLICAR_CAMMESA\s*=\s*False',code): ok('CAMMESA en pausa en código')
    else: fail('CAMMESA no aparece explícitamente en pausa')
    if 'ListarAperturaProxima.aspx' in code: ok('Agente apunta al listado de próximas aperturas')
    else: warn('No se reconoce la URL del listado')
    if 'javascript:' in code and 'return None' in code: warn('Revisar enlaces __doPostBack: el agente podría descartarlos')
else: fail('Falta buscar_licitaciones.py')
if dashboard.exists():
    page=dashboard.read_text(encoding='utf8')
    if 'cierreOfertas' in page: ok('Tablero contempla cierreOfertas')
    else: fail('Tablero no contempla cierreOfertas')
    if 'No publicada' in page: ok('Tablero contempla No publicada')
    else: warn('Tablero no muestra literalmente No publicada')
else: fail('Falta index.html')

# Consulta real independiente: compara el listado actual con la salida del agente.
url='https://contratar.gob.ar/ListarAperturaProxima.aspx'
try:
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept-Language':'es-AR,es;q=0.9'})
    with urllib.request.urlopen(req,timeout=25) as response:
        raw=response.read(5_000_000); html=raw.decode('utf-8','replace')
    parser=Filas(); parser.feed(html)
    if not parser.rows: fail('Portal accesible, pero no se pudo leer la tabla: posible cambio de estructura')
    else:
        ok(f'Consulta EN VIVO: {len(parser.rows)} filas en la tabla visible de próximas aperturas')
        nums={r[0] for r in parser.rows}; matches=nums & seen
        ok(f'{len(matches)} procesos publicados en JSON también figuran en la tabla visible actual')
        missing=seen-nums
        if missing: warn(f'{len(missing)} procesos JSON no figuran en la tabla visible (podrían estar en otra página o haber cambiado)')
        postbacks=[n for n,h in parser.links.items() if h.lower().startswith('javascript:')]
        if postbacks: warn(f'{len(postbacks)} enlaces del listado son javascript/postback; comprobar navegación al detalle')
        # La tabla puede estar paginada; sin navegar todas las páginas NO existe cobertura completa.
        if re.search(r'__doPostBack|GridListaPliegos.*Page',html,re.I|re.S): warn('Posible paginación ASP.NET: solo se auditó la página visible; cobertura total NO certificada')
        else: warn('Solo se auditó la página visible; no se certifica cobertura completa del portal')
except Exception as e:
    warn(f'Consulta EN VIVO no verificada: {type(e).__name__}: {e}')
    warn('Resultado local no certifica cobertura; ejecutar en GitHub Actions con conectividad')

report={'fecha':datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).isoformat(),'registros':len(items),'comprobaciones':checks,'errores':errors,'advertencias':warnings,'cobertura_total_certificada':False}
Path('auditoria_contratar_resultado.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(f'RESUMEN: {len(errors)} errores, {len(warnings)} advertencias. Cobertura total: NO CERTIFICADA')
sys.exit(1 if errors else 0)
