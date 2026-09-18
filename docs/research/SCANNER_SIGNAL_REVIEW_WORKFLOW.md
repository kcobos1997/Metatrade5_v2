# Revisión visual de señales del scanner

## Propósito y alcance

`tools/analyze_scanner.py` valida offline el CSV de `scanner-v1`, conserva una
fila por barra con señales aceptadas y crea una muestra reproducible para revisar
en MT5. Usa **Python 3.10 o posterior y exclusivamente su biblioteca estándar**.
No ejecuta el EA, no altera sus reglas, no crea operaciones ni calcula rentabilidad,
win rate, profit factor o resultados futuros. El Excel de Strategy Tester no es
la entrada de este analizador.

## Tres niveles de datos

1. **CSV bruto:** exportación original de MQL5/Files del terminal o del agente.
   Contiene identidad de cuenta/servidor, Magic, claves y estado. Mantenerlo fuera
   del repositorio y abrirlo únicamente para lectura. Nunca subirlo a GitHub.
2. **signals_reduced.csv:** todas las barras con al menos un canal cuyo reason sea
   exactamente `ACCEPT_DIAGNOSTIC`. Lista blanca de 28 columnas; no contiene
   identidad, claves, estado, checksum original, cuenta, servidor ni Magic.
3. **signals_review_sample.csv:** subconjunto exclusivo de la tabla anterior,
   ordenado por tiempo, con cuatro columnas para revisión manual.

`scanner_summary.json` añade conteos, distribuciones, SHA-256 del original,
fecha UTC de generación, versión Python, parámetros y resultados de validación.
Solo registra el nombre de entrada, nunca su ruta absoluta. No incluye identidad
completa ni valores de cuenta/servidor. Los IDs `SIG-000001`, etc. dependen
únicamente del orden temporal de las barras aceptadas en ese archivo: no son IDs
globales comparables automáticamente entre experimentos.

## Ejecución en PowerShell

Desde la raíz del repositorio, con Python disponible:

```powershell
python tools\analyze_scanner.py `
  --input "C:\ruta\XAUUSD_Scanner_B4C88ADF68090945.csv" `
  --output-dir "artifacts\scanner_analysis\smoke_20260610_20260814_v2" `
  --sample-size 50 `
  --seed 20260917
```

El programa nunca busca ni selecciona otro CSV. Las rutas relativas de sus
argumentos se resuelven respecto a la raíz obtenida desde el propio script, no
respecto al directorio actual. Desde otro directorio, invocar el script mediante
su ruta absoluta. El destino de CLI debe ser un hijo directo de
`artifacts/scanner_analysis/`, con nombre formado por letras, dígitos, `_` o `-`.

Salidas locales, ignoradas por Git:

```text
artifacts/scanner_analysis/smoke_20260610_20260814_v2/
  signals_reduced.csv
  signals_review_sample.csv
  scanner_summary.json
```

Código de salida: 0 = correcto; 2 = validación fallida (incluye fila y causa,
sin imprimir valores privados); 3 = fallo de archivos. argparse también usa 2
para argumentos inválidos. Las filas informadas incluyen la cabecera como fila 1;
la fila 0 indica validación global o de publicación. Consola y outputs usan UTF-8.
Se admiten entradas ASCII/UTF-8, con o sin BOM, con CRLF o LF.

### Python en este entorno

Durante esta entrega, `python` en el PATH era un alias de Microsoft Store sin
intérprete instalado. Se utilizó el paquete portátil oficial
[Python 3.13.12 para Windows](https://www.python.org/downloads/release/python-31312/),
verificado por SHA-256, extraído en `%TEMP%\xau-analysis-python-3.13.12`.
No se instalaron paquetes ni se modificó el PATH persistente de Windows.
Para reutilizarlo mientras exista esa carpeta:

```powershell
$env:Path = (Join-Path $env:TEMP 'xau-analysis-python-3.13.12') + ';' + $env:Path
$env:PYTHONDONTWRITEBYTECODE = '1'
python --version
```

En otro equipo basta con un Python compatible disponible; el programa no depende
de esa ubicación temporal ni descarga componentes al ejecutarse.

## Clasificación y muestra

- **B0:** aceptación del breakout estructural del scanner.
- **PB1:** aceptación de continuación tras pullback del scanner.
- **B0+PB1:** ambos módulos aceptados en la misma barra y dirección.
  Aparece una sola vez, con overlap=1.
- BUY y SELL aceptados en la misma barra invalidan el archivo.

La clasificación procede de los códigos del CSV; el analizador no recalcula
estrategias ni convierte rechazos en aceptaciones. El orden de accepted_lanes es
`b0_buy,b0_sell,pb1_buy,pb1_sell`; csv.DictWriter cita ese campo cuando contiene coma.

| Estrato exclusivo | Cuota con sample-size=50 |
| --- | ---: |
| B0 BUY | 10 |
| B0 SELL | 10 |
| PB1 BUY | 10 |
| PB1 SELL | 10 |
| B0+PB1 BUY | 5 |
| B0+PB1 SELL | 5 |

Se usa `random.Random(seed)` y selección sin reemplazo sobre barras cronológicas.
Un estrato escaso aporta como máximo su disponibilidad; **no se redistribuye** el
déficit ni se duplica una barra. El JSON informa requested/available/selected y
shortfall por estrato. La consola advierte cuando la muestra resulta menor.

Otros tamaños usan pesos 2:2:2:2:1:1, reparto por restos mayores y desempate en el
orden de la tabla; tamaño 0 permite exportar solo la tabla completa. Los dos CSV
son reproducibles con misma entrada, parámetros y versión Python. El JSON cambia
su fecha de generación deliberadamente y registra la versión del intérprete.

## Timestamps y localización en MT5

Los números server/ny representan componentes de **relojes locales serializados**,
no instantes UTC que deban convertirse según Windows. Se representan con epoch UTC
solo para conservar esos componentes. El analizador usa aritmética con datetime
UTC, nunca hora local del sistema. Cero significa desconocido y se muestra vacío.

- `signal_open_server_text`: apertura de la vela M5 que generó la señal.
- `decision_server_text`: apertura de la M5 siguiente, cuando pudo observarse;
  siempre 300 segundos después de signal_open_server.
- `decision_ny_text`: reloj NY ya calculado por el scanner. No se recalcula el DST.

Para revisar, abrir el mismo símbolo/feed en MT5, seleccionar **M5** y localizar
principalmente `signal_open_server_text` en el reloj del servidor. Comparar el OHLC
de esa vela con signal_open/high/low/close y con la última barra de m5_window.
Consultar la H1 indicada por h1_open_server: debe haber cerrado antes o al decidir.
No comparar la EMA con la H1 todavía abierta. Ante discrepancias de histórico,
marcarlas en notas; no editar el CSV bruto para hacerlas coincidir.

## Revisión manual

La muestra comienza con review_status=PENDING y las otras tres columnas vacías.
Valores sugeridos:

| Campo | Valores |
| --- | --- |
| review_status | PENDING, VALID, QUESTIONABLE, REJECTED |
| structure_quality | CLEAR, MIXED, POOR |
| signal_quality | STRONG, NORMAL, WEAK |
| review_notes | Texto breve sobre lo observado y cualquier discrepancia |

Estas etiquetas son anotaciones humanas, no filtros nuevos ni estimaciones de
ventaja. No usar velas futuras para decidir si una señal pasada era causalmente
válida. Conservar signal_id y timestamps. Evitar introducir cuenta, servidor u
otros datos personales en review_notes: la auditoría automática ocurre al generar
los outputs, no después de editarlos manualmente. Guardar una copia de la revisión
antes de repetir el comando, porque una ejecución correcta reemplaza las salidas.

## Validaciones y publicación

- Exactamente 39 columnas únicas del esquema; una sola identidad scanner-v1.
- Conversión de enteros, floats finitos, timestamps, enums, flags y los 24 enteros
  de estado; relación signal_open_server=decision_server-300 y demora coherente.
- decision_server estrictamente creciente: basta conservar el timestamp anterior
  para rechazar cualquier archivo con duplicados/retrocesos. Se detiene ante el
  primer fallo; no produce un resumen parcial de un archivo inválido.
- trade_authorized=0 en todas las filas. No se interpretan esos ceros como un
  permiso futuro para operar.
- Aceptadas: session=IN, data_status=OK, raw=1, dirección H1 compatible, una sola
  dirección, H1 cerrada, precios/cotización válidos y demora no negativa.
- m5_window en aceptadas: longitud de la configuración, pasos de 300 segundos,
  último timestamp igual a signal_open_server, OHLC finitos positivos y coherentes.
- Claves originales exactamente identity:decision:modulo:direccion; checksum FNV
  recalculado como MQL5. Esta verificación detecta corrupción, no autentica al autor.
- Muestra única, exclusiva, dentro de la disponibilidad de cada estrato.
- Lista blanca de columnas; búsqueda textual y estructurada en los tres outputs
  de identidad completa, cuenta, Magic, servidor codificado/decodificado y sus
  componentes significativos. Como toda clave original validada contiene identity,
  comprobar ausencia de identity también descarta las cuatro claves de cada fila,
  sin guardar en memoria todas las claves del CSV.
- SHA-256 antes y después de procesar para comprobar que el original no cambió.

La comprobación de tokens es conservadora: si un token corto coincide por azar
con un número legítimo o el nombre del input, se rechaza la publicación. No se
borran precios ni se relaja silenciosamente la comprobación para evitar el fallo.

csv.DictReader lee secuencialmente con límite de campo de 16 MiB. En memoria quedan
una identidad/tokens privados solo para validar, contadores y slots diarios, más
las barras aceptadas y su muestra; no todas las filas brutas.

Los tres archivos se escriben primero en un directorio temporal hermano. Solo
tras validar datos, privacidad y hash se publica el conjunto mediante cambio de
directorio. Un error de validación conserva los resultados anteriores. Si falla
el cambio de directorio durante la ejecución, se intenta restaurar la versión
anterior. Un corte de energía entre los dos renombrados puede dejar una carpeta
`.scanner-backup-*`: conservarla y revisar antes de reintentar. No se promete una
transacción resistente a fallos físicos. El destino rechaza archivos ajenos y
no puede contener el input. Ejecutar un solo analizador por destino a la vez.

## Resumen y sesiones

Se cuentan filas de todos los estados, incluidas DATA_M5/DATA_H1 y barras sin señal.
Las métricas de spread y hora NY se calculan sobre barras aceptadas únicas, sin
duplicar B0+PB1. Una aceptación por canal y una barra aceptada son unidades distintas.

Un día NY válido tiene al menos una observación IN con data_status=OK. Una sesión
completa contiene todos los timestamps de cinco minutos de [inicio,fin) según la
configuración de identity (08:00–12:00 por defecto: 48). Las etiquetas completas
no demuestran calidad de ticks ni rentabilidad. El JSON incluye el número de días
válidos, sesiones completas y tamaño esperado de cada sesión.

## Nuevos experimentos y RunId

Configurar un **RunId nuevo en el scanner** para cada ensayo independiente;
conservarlo solo al continuar el mismo experimento. Este analizador no modifica
RunId, no ejecuta backtests y no mezcla archivos de varias identidades. Copiar la
ruta exacta del nuevo CSV a --input y elegir otro nombre de carpeta de salida.
No renombrar un CSV para simular otro RunId. La prueba de integración siguiente
está ligada únicamente al archivo y conteos de esta entrega.

## Pruebas automatizadas

Fixtures sintéticos temporales, exclusivamente unittest; el CSV real nunca se
copia a tests/. Sin variable de integración, esa prueba se marca SKIPPED.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:SCANNER_CSV_PATH = "C:\ruta\XAUUSD_Scanner_B4C88ADF68090945.csv"
python -m unittest discover -s tests -p "test_*.py"
```

SCANNER_CSV_PATH debe apuntar al archivo de esta entrega. Los números esperados
están únicamente en el test de integración; el analizador siempre los calcula.
Los fixtures prueban errores de esquema, orden, identidad, trading, dirección,
OHLC, checksum, privacidad, publicación, codificación, muestreo y zona horaria.
.gitignore excluye artifacts/scanner_analysis/, data/raw/ y EX5 no rastreados;
los EX5 ya versionados siguen versionados y no son alterados por esta tarea.

## Verificación de esta entrega — 2026-09-17

Entrada: `XAUUSD_Scanner_B4C88ADF68090945.csv`, localizada inequívocamente en
MQL5/Files del agente local del tester; no se usó el reporte XLSX como sustituto.
SHA-256 original:
`ab13a313a004b862d0b65cc973fc612309489d74209958b93e7fb07fecc2e97b`.

- **42 tests OK**, incluido el test de integración real (sin skips).
- **12.848 filas**, una identidad; 2.256 barras IN; **47 sesiones completas de 48 barras**.
- Aceptaciones por canal B0 BUY/SELL: **103/97**; PB1 BUY/SELL: **47/37**.
- **284 aceptaciones**, **266 barras únicas**, **18 coincidencias B0+PB1**.
- Cero duplicados, retrocesos temporales, conflictos BUY/SELL u operaciones autorizadas.
- **50 barras** en la muestra; ninguna aceptación tiene delay distinto de cero.

| Estrato exclusivo | Barras disponibles | Seleccionadas |
| --- | ---: | ---: |
| B0 BUY | 93 | 10 |
| B0 SELL | 89 | 10 |
| PB1 BUY | 37 | 10 |
| PB1 SELL | 29 | 10 |
| B0+PB1 BUY | 10 | 5 |
| B0+PB1 SELL | 8 | 5 |

Destino local: `artifacts/scanner_analysis/smoke_20260610_20260814_v2/`.
Dos ejecuciones produjeron CSV reducidos y muestras idénticos byte a byte.
Se revisaron las primeras y últimas filas de ambos CSV. Una auditoría independiente
buscó las **51.392 claves originales**, la identidad y los tokens de cuenta/servidor
en los tres outputs: ninguna coincidencia. El hash del original permaneció igual.

Los estados completos incluyen 383 DATA_H1, 196 DATA_M5 y 12.269 OK; se conservaron
en los conteos y ninguna fila aceptada tiene error de datos. El período observado
de decisiones es 2026-06-10 01:00:00 a 2026-08-13 23:55:00 (reloj del servidor),
independientemente del nombre de la carpeta del experimento.

La codificación UTF-8 de consola se fijó tras una prueba que detectó la página de
códigos heredada de Windows; la batería completa posterior pasó. Los MQ5 y EX5
conservan sus hashes. Los resultados están ignorados, no se copió el CSV bruto al
repositorio, no se prepararon archivos para commit y no se hizo commit ni push.
No se ejecutó otro backtest ni se midió rentabilidad.
