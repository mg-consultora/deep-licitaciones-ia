# Agente de licitaciones: UPS, baterías estacionarias y energía crítica

Revisa todos los días las licitaciones publicadas en Argentina, se queda con las que tienen que
ver con UPS industriales, rectificadores, cargadores, bancos de baterías, sistemas de corriente
continua (48, 110, 125 y 220 Vcc), inversores y energía crítica, y arma un **tablero con
semáforo**:

- 🟢 **Verde**: en plazo, con la apertura más adelante.
- 🟡 **Amarillo**: vence pronto (menos de 7 días; se cambia en `config.yaml`).
- 🔴 **Rojo**: vencida o ya adjudicada (no hace falta analizarla).
- ⚪ **Gris**: el aviso no trae fecha (por ejemplo, "se informará por circular"). Hay que verificarla.

De cada licitación muestra el número de proceso, la obra, el organismo, la provincia, el sector,
el tipo de contratación, el estado y las fechas (publicación, límite de consultas, presentación
y **apertura de sobres**), con el link al aviso oficial.

**Avisos:** solo avisa (por correo o Telegram, y arriba de todo en el tablero) cuando sale una
**circular nueva** o **cambia una fecha** de una licitación que ya se sigue, siempre con el link.

## De dónde saca los datos

| Fuente | Qué cubre | Estado |
|---|---|---|
| Boletín Oficial, Tercera Sección | Todas las licitaciones públicas nacionales: las de **COMPR.AR**, las de **CONTRAT.AR** y las de empresas del Estado (Energía Argentina, Nucleoeléctrica, CNEA, Yacyretá, Trenes, universidades…) | Funciona |
| Páginas públicas (lista en `config.yaml`) | Portales provinciales y sitios de empresas que publican aparte | Funciona; conviene ajustar las direcciones |
| Correo de invitaciones | Invitaciones de **SAP Ariba** (YPF, TGS, Pluspetrol, MetroGAS…) y de otros portales | Listo; falta cargar la casilla |
| Portales con usuario | Ariba, CAMMESA, Transener, Edenor, Edesur, Genneia, Central Puerto, mineras | Preparados; se activan con usuario y clave |

**¿Por qué el Boletín Oficial y no COMPR.AR directo?** COMPR.AR está armado con formularios que
cambian en cada visita, y por eso los conectores genéricos tiran error. Las licitaciones públicas
de COMPR.AR y CONTRAT.AR tienen que publicarse igual en el Boletín Oficial. El Boletín publica cada
día el PDF de la Tercera Sección con su huella digital (SHA-256), así que el agente lo baja,
comprueba que no esté alterado y lo lee. Este camino es mucho más estable.

**Lo que no cubre el Boletín:** las licitaciones privadas y las contrataciones directas que solo
aparecen dentro de COMPR.AR, y las compras de las empresas privadas. Para las privadas está el
canal de correo, y los portales cuando se tenga el alta.

## Instalación (una sola vez)

1. Instalar Python 3.10 o superior desde python.org. En Windows, tildar "Add Python to PATH".
2. Abrir una terminal en esta carpeta y ejecutar:
   ```
   pip install -r requirements.txt
   ```
3. Probar con datos de ejemplo (no necesita internet):
   ```
   python agente.py --demo --abrir
   ```
4. Correrlo de verdad:
   ```
   python agente.py --abrir
   ```
   La primera vez revisa 30 días hacia atrás y tarda unos minutos. El tablero queda en
   `salida/tablero.html`. En Windows también se puede hacer doble clic en `ejecutar_agente.bat`.

> **Importante:** tiene que correr en una computadora o servidor **en Argentina**. El sitio del
> Boletín Oficial rechaza muchas conexiones desde el exterior.

## Que corra solo todos los días

- **Windows:** Programador de tareas → Crear tarea básica → Diaria, 8:00 → Iniciar un programa →
  `python` con argumentos `agente.py --dias 5` y "Iniciar en" = esta carpeta.
- **Mac/Linux:** `crontab -e` y agregar
  `0 8 * * 1-5 cd /ruta/a/agente_licitaciones && python3 agente.py --dias 5`

## Activar el canal privado

1. Copiar `.env.ejemplo` como `.env` y completar lo que se tenga.
2. **Correo de invitaciones:** es lo primero que conviene activar. Las empresas que usan Ariba
   mandan por mail la invitación a cada licitación, las circulares y las prórrogas. Con los datos
   de la casilla (en Gmail, con una "contraseña de aplicación"), el agente lee esos correos y los
   suma al tablero con su fecha de cierre y su link. Los remitentes se configuran en `config.yaml`.
3. **Portales con usuario:** al cargar usuario y clave de un portal, el tablero lo marca como
   "credenciales cargadas, falta programar la lectura". Ese paso se completa en
   `licitaciones/fuentes/privadas.py` (método `leer_portal`), mirando la pantalla real de cada portal.
   Antes de automatizar un ingreso, conviene leer los términos de uso del portal: algunos no
   permiten accesos automáticos, y en ese caso el correo de invitaciones es el camino correcto.

## Ajustar qué entra al tablero

Todo está en `config.yaml`:

- **`rubros.terminos`**: cada palabra suma puntos (rectificador = 3, UPS = 2, baterías = 1…).
  Entra lo que llega a `puntaje_minimo` (2). Para ver solo lo industrial, subirlo a 3.
- **`rubros.excluir`**: descarta baterías de autos, neumáticos, pilas, etc.
- **`sectores`** y **`sectores_prioritarios`**: los prioritarios (energía, minería, oil & gas,
  industria) suman puntos extra.
- **`paginas_publicas`**: agregar portales provinciales (Neuquén, Mendoza, San Juan, Salta,
  Catamarca…) o la sección de licitaciones de cada empresa.

## Archivos

```
agente.py                    programa principal
config.yaml                  rubros, sectores, páginas y umbrales
.env.ejemplo                 plantilla de usuarios y claves
licitaciones/
  fuentes/boletin_oficial.py descarga y lectura del Boletín Oficial
  fuentes/paginas_web.py     páginas públicas
  fuentes/privadas.py        correo de invitaciones y portales con usuario
  filtros.py                 puntaje por rubro y semáforo
  db.py                      memoria local: detecta circulares y cambios de fecha
  tablero.py                 genera el tablero HTML
  notificar.py               avisos por correo y Telegram
tests/                       pruebas (python -m pytest tests)
salida/                      tablero, base de datos y PDFs descargados
```
