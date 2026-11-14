# Módulo "Obras futuras y oportunidades privadas"

Agrega al tablero una segunda pestaña con proyectos de inversión, obras futuras y compras
privadas de energía, minería, Oil & Gas, petroquímica e industria. **No modifica nada del
agente de licitaciones públicas**: corre después, agrega su pestaña y guarda su memoria
en un archivo propio (`salida/obras.db`).

## Qué muestra de cada obra

Obra y subobras, operadora o titular, desarrolladora, ingeniería, contratista o EPC,
provincia y localidad, presupuesto, sector, y las fechas de licitación de productos,
licitación de obra, inicio de compras, inicio de obra y fin de obra. También lista los
equipos DEEP potenciales y la fuente con su fecha de verificación.

Las obras se clasifican así:

| Tipo | Qué significa |
|---|---|
| **Licitación abierta** | La fuente da una fecha límite exacta y todavía no pasó |
| **Licitación anunciada / registro de proveedores** | La empresa anunció compras o una licitación, o abrió el registro de proveedores, pero no hay fecha límite firme |
| **Adjudicado / en ejecución** | Ya hay contratista o la obra empezó |
| **Proyecto anunciado** | Inversión anunciada o aprobada (por ejemplo, RIGI), sin compras abiertas |
| **Licitación cerrada** | La fecha límite ya pasó |

## Reglas para no inventar

- Cada dato tiene que estar escrito en la fuente. Si no está, aparece **No informado**.
- Las fechas se copian tal como las escribe la nota ("segundo semestre de 2027"):
  - **confirmada**: día exacto, sin palabras de previsión;
  - **estimada**: el resto (prevé, estima, mes, semestre, año).
- Los equipos DEEP son **potenciales**: se deducen del tipo de obra y figuran rotulados así.
- Si se activa la inteligencia artificial (opcional), solo se acepta un dato si viene con una
  frase que está textualmente en la nota. Si la frase no está, el dato se descarta.

## Privacidad

- Del Excel de contactos **no se usó ninguna persona, cargo, correo ni teléfono**. Solo los
  nombres de empresa, guardados como huellas cifradas en `datos/empresas_propias.txt`: con
  ese archivo no se pueden leer los nombres. El agente reconoce una empresa de la lista
  únicamente cuando aparece escrita en una noticia.
- En el tablero, una obra donde aparece una empresa de la lista se marca con ⭐. Si el
  tablero es privado y querés ver qué empresa es, poné `mostrar_nombres_empresas_propias: true`
  en `config_obras.yaml`. Si el tablero es público en GitHub Pages, dejalo en `false`.
- Del Directorio de Empresas Energéticas solo se tomaron nombres de empresas y sus páginas
  públicas de proveedores. No se copiaron sus notas ni sus datos.

## Fuentes

- **Medios especializados:** EconoJournal, Energía Estratégica, Panorama Minero, Mining
  Press, Más Energía y la sección Energía de Diario Río Negro. Para cada uno se lee su canal
  RSS (si tiene) y además una búsqueda en Google Noticias limitada a ese sitio.
- **Búsquedas generales:** licitaciones de obra, EPC, RIGI, registros de proveedores, BESS y
  líneas de alta tensión, en cualquier medio argentino.
- **Registro manual verificado:** `datos/obras_verificadas.yaml`, que trae 10 obras reales
  con su fuente (Los Azules, VMOS, Cauchari-Olaroz, Gasoducto San Matías, Tratayén–SAO,
  Los Toldos II Este, MARA, Tres Quebradas, PSJ Cobre Mendocino y Rincón). Se pueden
  agregar más copiando un bloque. Estas obras tienen prioridad sobre lo que se lee en medios.
- **Empresas prioritarias:** `datos/empresas_prioritarias.yaml`, con las 46 del directorio
  más otras relevantes.

La lista de fuentes y si cada una respondió aparece al pie de la pestaña.

## Archivos del módulo (todos nuevos; ninguno reemplaza archivos existentes)

```
obras.py                         programa del módulo
config_obras.yaml                medios, búsquedas, tipos de obra, equipos DEEP, umbral
datos/empresas_prioritarias.yaml empresas prioritarias (datos públicos)
datos/empresas_propias.txt       lista propia cifrada
datos/obras_verificadas.yaml     obras verificadas a mano
licitaciones/obras/              código del módulo
.github/workflows/obras.yml      automatización en GitHub (corre después de "Actualizar tablero")
ejecutar_obras.bat               para correrlo en una PC con Windows
tests/test_obras.py              pruebas
tests/notas_ejemplo.json         notas inventadas para la demo
```

## Inteligencia artificial (opcional)

Sin configurar nada, el módulo usa sus propias reglas de lectura. Para que complete mejor
contratistas, ingeniería y fechas, se puede cargar en GitHub (Settings → Secrets and
variables → Actions → New repository secret) un secreto llamado `ANTHROPIC_API_KEY` con una
clave de la API de Anthropic. Tiene costo por uso; con 40 notas por día como máximo, el costo
es bajo.
