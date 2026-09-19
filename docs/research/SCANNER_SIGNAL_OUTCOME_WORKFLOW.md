# Resultados posteriores de las señales revisadas

## Alcance

`tools/analyze_signal_outcomes.py` analiza offline las **50 señales revisadas**,
con Python 3.10+ y solo la biblioteca estándar. Conserva VALID, QUESTIONABLE y
REJECTED. No ejecuta MT5, operaciones ni Strategy Tester; no selecciona SL, TP,
riesgo o parámetros. **No es un backtest ni una estimación de rentabilidad.**

El flujo anterior permanece descrito en
[SCANNER_SIGNAL_REVIEW_WORKFLOW.md](SCANNER_SIGNAL_REVIEW_WORKFLOW.md). Este paso
consume la muestra y las anotaciones finales; no añade resultados futuros al
cuaderno de revisión causal ni modifica las clasificaciones humanas.

## Entradas exactas y ejecución

Desde la raíz del repositorio en PowerShell:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -B tools\analyze_signal_outcomes.py `
  --input "$env:APPDATA\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\MQL5\Files\XAUUSD_Scanner_B4C88ADF68090945.csv" `
  --sample "artifacts\scanner_analysis\smoke_20260610_20260814_v2\signals_review_sample.csv" `
  --annotations "$env:USERPROFILE\Downloads\signal_review_annotations_2026-09-19T02-44-08-381Z.csv" `
  --output-dir "artifacts\scanner_analysis\smoke_20260610_20260814_v2_outcomes" `
  --point-size 0.01
```

No se buscan otros CSV ni se elige la descarga más reciente. Las rutas relativas
se resuelven desde la raíz del repositorio, independientemente del directorio de
trabajo. El destino CLI debe ser un hijo directo de `artifacts/scanner_analysis`
con nombre alfanumérico, `_` o `-`. Solo se admite `point-size=0.01` en este
protocolo. Un error detiene la publicación; nunca sustituye una entrada.

## Validación de la unión

- Exactamente 50 filas en la muestra y 50 en las anotaciones.
- `sample_id` único y no vacío en anotaciones; corresponde a `signal_id` de la
  muestra. Ambos conjuntos de IDs deben ser idénticos. Orden de salida: muestra.
- Clasificaciones obligatorias, con valores exactos:
  - `chart_quality`: CLEAR, MIXED, POOR.
  - `signal_alignment`: ALIGNED, UNCLEAR, MISALIGNED.
  - `context_class`: TREND, RANGE, TRANSITION, UNCLEAR.
  - `reviewer_decision`: VALID, QUESTIONABLE, REJECTED.
- Nota no vacía, `status=OK` y `validation_errors` vacío. Se rechazan PENDING,
  valores desconocidos y fichas con errores o historial INCOMPLETE. Si existe
  `completed`, debe ser `true`; la descarga indicada no incluye esa columna.
- Coincidencia de fecha textual, epoch, fecha NY, dirección y módulo. Los demás
  campos compartidos tampoco pueden discrepar.
- Se reutiliza `analyze_scanner.collect` para validar **todo** el CSV bruto:
  39 columnas, una identidad, orden temporal, checksum y estado por fila,
  `trade_authorized=0`, aceptación, H1 cerrada y ventanas de señal válidas.
- Todos los campos reducidos de la muestra se contrastan con las aceptaciones
  del original, incluidos OHLC, bid, ask, spread, H1 y reason codes.
- Para este modelo la cotización debe haberse observado exactamente en
  `decision_server`, con `delay_seconds=0`. Una cotización tardía detiene el
  análisis: no se inventa un precio para el instante anterior.

Los valores `review_status`, `structure_quality`, `signal_quality` y
`review_notes` de la muestra original se conservan como procedencia. Su
`review_status=PENDING` es el estado inicial del muestreo; la clasificación final
que se valida y agrupa es **`reviewer_decision`**, proveniente de las anotaciones.
No se reemplazan ni reinterpretan las notas originales.

## Mapa canónico y límites temporales

Se recorren todas las ventanas `m5_window`, también las filas DATA_M5/DATA_H1.
Cada barra debe tener timestamp positivo alineado a 300 segundos y OHLC finitos,
positivos y coherentes, y estar cerrada al registrarse. Una ventana puede cruzar
un hueco de sesión: se incorporan sus barras válidas sin inventar las ausentes.
Una ventana vacía solo se admite en una fila DATA_M5 y queda contada.

Se deduplican OHLC idénticos por timestamp. **Cualquier diferencia numérica de
OHLC para el mismo timestamp detiene el análisis**, incluso fuera de los
horizontes de las 50 señales. No se conserva silenciosamente la primera o última
versión. La comparación usa `Decimal` sobre los textos originales, sin tolerancia
para contradicciones de OHLC.

`signal_open_server` es la apertura de la señal. La entrada analítica ocurre en
`decision_server = signal_open_server + 300`. Para un horizonte H:

```text
decision_server <= apertura M5 < decision_server + H * 60
```

| Horizonte | Barras exigidas | Última apertura respecto a la entrada |
| --- | ---: | ---: |
| 15 minutos | 3 | +10 minutos |
| 30 minutos | 6 | +25 minutos |
| 60 minutos | 12 | +55 minutos |
| 120 minutos | 24 | +115 minutos |

La primera barra siempre abre exactamente en la entrada. Se excluyen tanto la
vela de señal como la que abre en el límite final. Se usa el cierre de la última
barra incluida. No se toman velas adicionales para completar un horizonte.

Si falta alguna apertura, ese horizonte se marca `INCOMPLETE`, con cantidad de
barras disponibles y lista de timestamps/horas faltantes. MFE, MAE y retorno
quedan vacíos. La señal conserva su fila y sus otros horizontes. Los límites
`first_bar_open`, `last_bar_open` y `end_exclusive` describen el intervalo exigido,
incluso cuando alguna barra no está disponible.

Los timestamps server/NY siguen siendo componentes de relojes locales
serializados, como en el flujo anterior. No se usa el huso horario de Windows
ni se recalcula DST.

## Entrada y spread

Precios y resultados se calculan con `Decimal`, precisión de 40 dígitos. Los
CSV no redondean los resultados a un número menor de decimales. El HTML redondea
solo su presentación (2 decimales para puntos y 1 decimal para porcentajes).

- BUY entra al ask registrado; las barras futuras contienen precios bid.
- SELL entra al bid registrado; se aproxima cada precio ask futuro como
  `bid futuro + (ask de entrada - bid de entrada)`.
- El modelo se etiqueta **ENTRY_SPREAD_CONSTANT** en cada fila y en el informe.
- `entry_spread_points` conserva el valor observado del scanner.
  `entry_spread_price` usa la diferencia ask−bid observada. No se estima con barras.
- Se exige coherencia entre `(ask-bid)` y `spread_points * point_size`, con
  tolerancia de `0.000001` puntos únicamente para el ruido de serialización de
  doubles del scanner. No se corrigen cotizaciones ni se toleran OHLC distintos.

```text
BUY:
  MFE = max(0, max(high_bid) - entry_ask) / point_size
  MAE = max(0, entry_ask - min(low_bid)) / point_size
  retorno = (close_bid_final - entry_ask) / point_size

SELL:
  OHLC_ask = OHLC_bid + spread_price_at_entry
  MFE = max(0, entry_bid - min(low_ask)) / point_size
  MAE = max(0, max(high_ask) - entry_bid) / point_size
  retorno = (entry_bid - close_ask_final) / point_size
```

MFE y MAE son excursiones máximas favorable y adversa no negativas, medidas en
puntos de precio. El retorno al cierre conserva su signo. No son porcentajes ni
rendimientos monetarios. No conocemos el orden intrabar en que ocurren los extremos.

## Cuatro salidas

En `artifacts/scanner_analysis/smoke_20260610_20260814_v2_outcomes/`:

1. **signal_outcomes.csv**: 50 filas, identificadores y campos originales de
   muestra/anotaciones, entrada, spread, point y modelo. Prefijos `h15_`, `h30_`,
   `h60_`, `h120_`: status, bar_count, missing_timestamps, missing_server_text,
   límites y mfe_points, mae_points, close_return_points.
2. **outcome_summary.csv**: una fila por grupo y horizonte. `n_total`,
   `n_complete`, `n_incomplete`; media, mediana, p25 y p75 de las tres métricas;
   `positive_close_proportion` en escala 0–1. Solo los completos contribuyen.
3. **signal_outcome_report.html**: informe autónomo sin scripts ni recursos de
   red. Incluye validación, cobertura, comparación por módulo, contexto,
   decisión, dirección, alineación y cruces, advertencias y supuestos.
4. **outcome_manifest.json**: hashes SHA-256 de las tres entradas, parámetros,
   conteos, cobertura, versión Python y nombres/hashes de los tres resultados
   anteriores. No incluye su propio hash, porque sería una referencia circular;
   puede comprobarse externamente con `Get-FileHash`.

Agrupaciones predefinidas: total; módulo; dirección; reviewer_decision;
signal_alignment; context_class; módulo × contexto; decisión × contexto. Se
incluyen también grupos vacíos con `n_total=0` y estadísticas vacías, nunca ceros
inventados. `group_value` y `group_value_2` identifican cada dimensión del grupo.

Percentiles: interpolación lineal sobre los valores ordenados en posición
`(n-1)*p`, con p=0.25, 0.5 y 0.75. Para n=1 los tres coinciden con el único valor.
La proporción positiva usa exclusivamente retornos **estrictamente mayores que
cero**, con denominador n_complete. Estos conteos son por señales, no por canales.

Abrir el informe con doble clic o:

```powershell
Start-Process -FilePath (Resolve-Path "artifacts\scanner_analysis\smoke_20260610_20260814_v2_outcomes\signal_outcome_report.html").Path
```

## Integridad, determinismo y limitaciones

Se verifican los hashes de las tres entradas antes y después. Los resultados se
escriben en un directorio temporal hermano y se publican juntos mediante el
protocolo existente de reemplazo con restauración ante error. Se rechazan destinos
con archivos ajenos o que contengan alguna entrada. Los cuatro resultados pueden
reemplazarse al repetir el mismo comando; conservar aparte cualquier edición
manual. Ejecutar un solo analizador por destino.

Con los mismos bytes de entrada, parámetros, código y versión Python, los cuatro
archivos son idénticos byte a byte. No hay reloj de generación, aleatoriedad ni
rutas absolutas en el manifiesto. Cambiar la versión Python cambia su campo de
versión deliberadamente. Se audita ausencia de identidad, cuenta, servidor y
Magic del CSV bruto; se conservan únicamente los campos públicos del muestreo.

La muestra está estratificada y no reproduce necesariamente las frecuencias de
la población. Sus señales y horizontes pueden solaparse. Los grupos pequeños se
marcan si tienen menos de 10 horizontes completos, como advertencia descriptiva,
no como selección de parámetros. No se prueba independencia, significación ni
capacidad predictiva. No se modelan spread futuro real, slippage, comisiones,
swaps, liquidez ni ejecución. Los resultados dependen del feed y del supuesto de
spread constante. No se usan para proponer SL, TP, tamaño de posición o riesgo.

Salida CLI: 0 = resultados publicados (se admite cobertura incompleta explícita);
2 = validación fallida; 3 = error de archivos. Los fallos conservan los resultados
anteriores y no publican métricas parciales.

## Pruebas

```powershell
$env:SCANNER_CSV_PATH = "$env:APPDATA\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\MQL5\Files\XAUUSD_Scanner_B4C88ADF68090945.csv"
$env:SCANNER_SAMPLE_PATH = (Resolve-Path "artifacts\scanner_analysis\smoke_20260610_20260814_v2\signals_review_sample.csv").Path
$env:SCANNER_ANNOTATIONS_PATH = "$env:USERPROFILE\Downloads\signal_review_annotations_2026-09-19T02-44-08-381Z.csv"
$env:REVIEW_BROWSER_EXE = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -B -m unittest discover -s tests -p "test_*.py" -v
```

Los fixtures no requieren archivos reales ni paquetes externos. Las integraciones
reales solo se activan con las rutas explícitas anteriores; no buscan CSV. Se
prueban unión exacta, rechazo de datos incompletos/duplicados, BUY/SELL conocidos,
spread, signos, límites, huecos, OHLC contradictorios, resúmenes con vacíos,
determinismo, publicación e integridad de entradas. La batería existente del
cuaderno incluye pruebas headless en Edge con un perfil temporal.

## Verificación de esta entrega

- **94 pruebas aprobadas, sin omisiones**: 42 del analizador de muestreo,
  26 del cuaderno HTML y 26 del analizador de resultados posteriores.
- Unión exacta de **50 señales**, 50 IDs únicos y cero errores de anotación.
- CSV original: **12.848 filas**, **12.851 barras canónicas**, **38.541
  repeticiones idénticas**, cero contradicciones OHLC. Se validaron los 12.848
  checksums y la coincidencia de las 50 señales con sus aceptaciones originales.
- **50/50 horizontes completos** a 15, 30, 60 y 120 minutos: **200/200** en total.
- Dos ejecuciones reales produjeron los cuatro archivos idénticos byte a byte.
- Una comprobación independiente recalculó los 200 horizontes usando deltas de
  precio firmados y confirmó las tres métricas, sus intervalos y la exclusión
  de todas las velas de señal.
- Hashes de las tres entradas conservados, al igual que los MQ5 y EX5.

### Revisión de casos contra los precios originales

Resultados a 15 minutos, en puntos; redondeo solo en esta tabla:

| ID | Dirección | Módulo | Decisión | MFE | MAE | Cierre |
| --- | --- | --- | --- | ---: | ---: | ---: |
| SIG-000016 | BUY | PB1 | REJECTED | 596,00 | 358,00 | 543,00 |
| SIG-000005 | SELL | PB1 | VALID | 103,00 | 4.275,00 | −4.275,00 |
| SIG-000017 | BUY | B0 | QUESTIONABLE | 409,00 | 556,00 | −366,00 |
| SIG-000011 | SELL | B0+PB1 | VALID | 774,00 | 687,00 | 398,00 |
| SIG-000013 | SELL | B0+PB1 | QUESTIONABLE | 76,00 | 880,00 | −239,00 |

Ejemplo BUY SIG-000016: entrada 2026-06-12 16:05 servidor, ask 4197,19.
Barras futuras de 16:05, 16:10 y 16:15; límite excluido 16:20. High máximo
4203,15, low mínimo 4193,61 y cierre 4202,62: MFE 596, MAE 358, cierre +543.
La vela de señal de 16:00 queda excluida.

Ejemplo SELL SIG-000005: entrada 2026-06-10 16:35 servidor, bid 4143,09,
spread de entrada 0,10 de precio. Barras futuras de 16:35, 16:40 y 16:45;
límite excluido 16:50. High bid máximo 4185,74, low bid mínimo 4141,96,
cierre bid 4185,74. Tras sumar el spread: MFE 103, MAE 4275 y cierre −4275.
La vela de señal de 16:30 queda excluida. Los CSV conservan toda la precisión
serializada; las cifras anteriores se expresan con precisión de cotización.

### Resumen descriptivo

Retorno firmado **medio al cierre**, en puntos, conservando todas las señales:

| Grupo | N | 15 min | 30 min | 60 min | 120 min |
| --- | ---: | ---: | ---: | ---: | ---: |
| Total | 50 | 103,98 | 141,44 | 80,84 | 280,44 |
| B0 | 20 | 18,05 | 170,35 | −175,95 | 120,00 |
| PB1 | 20 | 117,45 | −8,85 | 1,70 | 215,35 |
| B0+PB1 | 10 | 248,90 | 384,20 | 752,70 | 731,50 |
| TREND | 20 | −36,60 | 211,50 | −67,25 | 116,25 |
| RANGE | 12 | 382,42 | 334,83 | −175,92 | 514,75 |
| TRANSITION | 18 | 74,56 | −65,33 | 416,56 | 306,67 |
| VALID | 20 | 29,00 | 116,35 | −130,15 | 3,85 |
| QUESTIONABLE | 23 | 201,87 | 149,48 | 167,22 | 368,39 |
| REJECTED | 7 | −3,43 | 186,71 | 399,86 | 781,71 |

No hay señales con contexto UNCLEAR; sus filas de resumen tienen N=0 y métricas
vacías. El grupo REJECTED tiene solo siete casos. Las medias varían por horizonte
y no establecen por sí solas una relación predictiva entre las etiquetas y los
resultados. Las distribuciones MFE/MAE y los percentiles completos están en
`outcome_summary.csv`; no se escogió ningún parámetro a partir de estas cifras.

Hashes SHA-256 de entrada:

- Scanner: `ab13a313a004b862d0b65cc973fc612309489d74209958b93e7fb07fecc2e97b`.
- Muestra: `5de53a7e06980a551b7357225816b7a9b9b4c302eb7e43a03e14b03b063d9cd1`.
- Anotaciones: `b49e2b9ef3be66681b4138620ce3bb5634e87bc52365acb1d68ba2033a066e3c`.

No se ejecutaron operaciones, Strategy Tester, backtests, staging, commit ni push.
Los cambios pendientes del cuaderno HTML anterior no fueron modificados durante
esta entrega.
