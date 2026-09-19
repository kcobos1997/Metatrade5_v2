# Fase 2: robustez de las 266 señales del scanner

## Alcance y separación de fases

`tools/analyze_signal_robustness.py` usa Python 3.10+ y biblioteca estándar. Lee
el CSV bruto exacto y exige **266 aceptaciones únicas por barra**. B0+PB1 cuenta
una sola vez. No ejecuta EA, operaciones ni Strategy Tester, y no diseña entradas,
SL, TP, riesgo ni reglas de ejecución. Todos los resultados son puntos de precio,
no PnL monetario ni rentabilidad.

Reutiliza `analyze_scanner.collect`, `analyze_signal_outcomes.reconstruct_market`,
`compute_outcomes` y `horizon_result`. Conserva validaciones de checksum,
aceptación, cotización sin demora, OHLC canónicos y límites causales de
[la fase descriptiva](SCANNER_SIGNAL_OUTCOME_WORKFLOW.md). Los cuatro artefactos
aceptados de las 50 señales se leen solo para comprobar sus hashes; no se regeneran.

Las 50 anotaciones se unen y validan con el mecanismo anterior. Las otras **216**
señales no reciben `context_class`, `signal_alignment` ni `reviewer_decision`.
El análisis B0 + RANGE aparece únicamente bajo `population=REVIEWED_50`, junto a
B0 de otros contextos revisados. No se extrapola a la población completa.

## Comando exacto de reproducción

Desde la raíz de `Metatrade5_v2`, rama `research/intraday-regime-v1`:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -B tools\analyze_signal_robustness.py `
  --input "$env:APPDATA\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\MQL5\Files\XAUUSD_Scanner_B4C88ADF68090945.csv" `
  --sample "artifacts\scanner_analysis\smoke_20260610_20260814_v2\signals_review_sample.csv" `
  --annotations "$env:USERPROFILE\Downloads\signal_review_annotations_2026-09-19T02-44-08-381Z.csv" `
  --phase1-dir "artifacts\scanner_analysis\smoke_20260610_20260814_v2_outcomes" `
  --output-dir "artifacts\scanner_analysis\smoke_20260610_20260814_v2_robustness" `
  --point-size 0.01 `
  --bootstrap-reps 2000 `
  --permutations 10000 `
  --seed 20260919
```

No se buscan CSV alternativos. Rutas relativas: raíz del repositorio. El destino
debe estar directamente dentro de `artifacts/scanner_analysis/`, con nombre
alfanumérico, `_` o `-`. La CLI exige las 266 señales; la función Python permite
un conteo distinto únicamente para los fixtures de prueba.

## Convenciones fijadas antes de consultar los resultados

### Horizonte, cotización y costes

- Horizontes fijos: 15, 30, 60 y 120 minutos, con 3, 6, 12 y 24 barras M5.
- Aperturas incluidas: `[decision_server, decision_server + minutos*60)`.
  `decision_server = signal_open_server + 300`. Se excluyen la vela de señal y
  la barra que abre en el límite final.
- Una barra ausente produce INCOMPLETE y métricas vacías. No se imputa ni se
  convierte en cero. Solo se excluye esa observación de ese horizonte.
- BUY: entrada ask y salida analítica bid. SELL: entrada bid y ask futuro
  aproximado por bid futuro + spread observado de entrada constante.
- Costes: factores 1,00 / 1,25 / 1,50 / 2,00. Se fija el bid observado y
  `ask_escenario = bid + (ask_observado-bid)*factor`. Se aplica también al ask
  futuro aproximado de SELL. Nunca se cambia la trayectoria bid ni se resta el
  spread dos veces. Modelo `ENTRY_SPREAD_CONSTANT`, `point_size=0.01`.
- Dirección invertida: misma hora, barras, spread y horizonte; BUY pasa a SELL
  y viceversa. No se recalculan módulos ni aceptaciones. El grupo de dirección
  sigue siendo la dirección **originalmente emitida**.

Precios y fórmulas de excursión se calculan con Decimal de precisión 40; las
estadísticas y el remuestreo usan float de Python con sumas `math.fsum`. El CSV
presenta 12 dígitos significativos para los estadísticos; el HTML redondea solo
la presentación. No se alteran los CSV ni los precios originales.

### Estadísticas robustas

Por cada horizonte, escenario y grupo (total, módulo, dirección, módulo ×
dirección) se calculan sobre **retorno al cierre, MFE, MAE y delta pareado**:

- N total, N completo y días NY distintos.
- Media, mediana, P25, P75 y proporción estrictamente positiva.
- Media recortada: eliminar `floor(N*0.10)` observaciones **en cada cola**.
- Media winsorizada: sustituir esas colas por el valor límite retenido de cada
  extremo. Para N<10 no se retira/sustituye ninguna observación; se informa k=0.
- Percentiles con interpolación lineal en `(N-1)*p`.
- Leave-one-out de la media: retirar cada señal y recalcular. Se registran el
  rango de medias, cambio absoluto, ranking determinista y posibles cambios de
  signo. Empates se resuelven por sample_id. N<2: no se inventa LOO.

Las métricas de MFE y MAE siguen siendo no negativas. Su proporción positiva es
una propiedad de las excursiones y no una tasa de acierto de operaciones.

### Bootstrap por día

Unidad de agrupamiento: fecha NY de `decision_ny_text`, tomada del scanner.
Para cada grupo/horizonte se remuestrean, con reemplazo, tantos días como días
observados, incluyendo **todas** sus señales completas. Estimador por réplica:
`suma de valores de los días sorteados / número de señales sorteadas`.

Se generan 2.000 réplicas y un intervalo percentil 2,5–97,5 % de la **media** de
cada métrica. No es un intervalo de la mediana. Los intervalos de ALL preservan
ponderación por señal; los de DAY_EQUAL remuestrean las medias diarias y dan
igual peso a cada día. No hay IC con menos de dos días. Para subconjuntos no
solapados se informan estadísticos descriptivos, no se inventa un IC vacío.

Cada análisis usa una subsemilla derivada por SHA-256 de semilla base, población,
grupo y horizonte. No se usa `hash()` de Python. Las mismas secuencias de días se
usan para todas las métricas y factores de spread del mismo grupo. No se mezclan
días de diferentes grupos para aumentar artificialmente el tamaño efectivo.

### Dependencia temporal

Los intervalos son semiabiertos. Dos que solo se tocan no se solapan. Se informa:

- Número de señales con algún solapamiento directo, número de pares y tamaño
  de los clusters temporales.
- Cluster: componente conexa transitiva de intervalos que se intersectan;
  extremos, ID y pertenencia por señal. No implica que todos los pares dentro
  del cluster se solapen directamente.
- `NONOVERLAP_FIRST`: recorre cronológicamente y toma la primera señal disponible;
  después solo admite señales que empiecen tras terminar la anterior.
- `NONOVERLAP_LAST`: variante simétrica desde el final. Es una comprobación de
  sensibilidad retrospectiva, no una regla de entrada ejecutable.
- Ambas selecciones dependen exclusivamente de timestamps e IDs, nunca del
  retorno, spread o clasificación. Se hacen por grupo y horizonte, antes de
  excluir INCOMPLETE, y se mantienen para los cuatro escenarios.
- `DAY`: resultados de cada día y grupo, ponderados por sus señales.
- `DAY_EQUAL`: distribución de medias diarias, dando peso igual a cada día.
  N tiene unidad **días**, indicada explícitamente. No se suma PnL.

Los contadores de solapamiento repetidos en las filas del resumen describen el
grupo completo de señales, no el subconjunto de esa fila. El CSV de clusters
permite reconstruir ambas selecciones y auditar cada intervalo.

### Control contrafactual y permutación

Delta pareado: `retorno_real − retorno_invertido`. Ambas direcciones incluyen
el mismo spread. Con este modelo simétrico el delta no depende del multiplicador
de spread, aunque ambos retornos sí empeoran al aumentar los costes.

La permutación cambia el signo del delta de **todas las señales de un día a la
vez**. Usa 10.000 sorteos y estadístico suma de deltas (equivalente a su media,
porque N es fijo). Se informan:

- p unilateral: real superior a invertida.
- p bilateral: diferencia en cualquier dirección.
- Corrección Monte Carlo: `(1 + réplicas extremas)/(1 + B)`.
- p unilateral ajustada por Holm entre 48 pruebas: 12 grupos de población ×
  4 horizontes. Las 12 pruebas de las 50 revisadas forman una familia separada.
  Los factores de spread no añaden pruebas porque el delta pareado es invariante.

La prueba supone intercambiabilidad de las etiquetas real/invertida, o simetría
de los deltas agregados por día bajo la hipótesis nula. No demuestra una
asignación aleatoria real ni resuelve dependencia entre días. Los IC del
bootstrap y los ocho contrastes H1 son **individuales**, no simultáneos.

## Hipótesis y criterio de candidata

- **H1:** se compara B0+PB1 con B0 y con PB1 para cada horizonte. Los contrastes
  de medias remuestrean conjuntamente los mismos días de la unión de ambos
  módulos, manteniendo su dependencia. Réplicas sin observaciones de un módulo
  no permiten ese contraste; se informa el número de réplicas válidas. Un
  contraste medio positivo no demuestra estabilidad: se revisan mediana,
  recorte, LOO, solapamiento y costes de cada módulo.
- **H2:** se examinan delta pareado, IC por día y p de permutación ajustada.
- **H3:** se exige que los signos sobrevivan a extremos, selección no solapada,
  ponderación por día, eliminación individual y aumento de spread.
- **B0 + RANGE:** comparación exploratoria dentro de REVIEWED_50. No se usa
  para etiquetar las 266 ni para definir un nuevo clasificador después de ver
  los resultados.

Una configuración grupo/horizonte solo recibe
`CANDIDATE_FOR_INDEPENDENT_VALIDATION` si cumple **todo**:

1. Media, mediana, media recortada y winsorizada positivas en ALL,
   NONOVERLAP_FIRST, NONOVERLAP_LAST y DAY_EQUAL, con spread ×1 y ×2.
2. Todas las medias leave-one-out positivas con spread ×1 y ×2.
3. Límite inferior IC95 positivo para la media original y el delta pareado.
4. p unilateral pareada ajustada por Holm ≤0,05.
5. Al menos 20 señales completas y 10 días. Es un requisito de cautela fijado
   antes del análisis, no un parámetro optimizado para escoger un módulo.
6. Población ALL_266. Las comparaciones manuales permanecen exploratorias.

Se registran todas las razones de fallo en `candidate_failures`. Este criterio
es deliberadamente más exigente que una media positiva. Una candidata **no es
edge**: requiere validación temporal independiente y un protocolo fijado antes
de observar esos datos nuevos. No se diseñan aquí reglas de ejecución.

## Cinco resultados

Directorio nuevo: `artifacts/scanner_analysis/smoke_20260610_20260814_v2_robustness/`.

- `robustness_summary.csv`: formato largo. Población, grupo, horizonte, coste,
  subconjunto, día y métrica identifican cada fila. Subconjuntos: ALL,
  NONOVERLAP_FIRST, NONOVERLAP_LAST, DAY_EQUAL, DAY y CONTRAST (H1).
- `signal_influence.csv`: una fila por señal, grupo, horizonte, coste y métrica;
  valor real/invertido, cotización, intervalo, integridad, LOO y ranking. Una
  señal aparece en sus distintos grupos; **no sumar estas filas como señales
  independientes**. Para la tabla canónica usar ALL_266 + TOTAL + ALL implícito,
  un horizonte, un factor y una métrica. Conserva las 266 señales, incluso si
  alguna métrica queda vacía por horizonte incompleto.
- `overlap_clusters.csv`: pertenencias y límites por señal/grupo/horizonte,
  solapamientos directos y marcas de ambas selecciones no solapadas.
- `robustness_report.html`: informe autónomo, sin red ni servidor, que compara
  grupos, controles, costes, dependencias y las hipótesis.
- `robustness_manifest.json`: hashes de las tres entradas, hashes protegidos de
  fase 1, código, parámetros, conteos, cobertura, hipótesis y nombres/hashes de
  los cuatro resultados anteriores. No contiene reloj de generación ni su
  propio hash circular.

```powershell
Start-Process -FilePath (Resolve-Path "artifacts\scanner_analysis\smoke_20260610_20260814_v2_robustness\robustness_report.html").Path
```

No se publican identidad, cuenta, servidor ni Magic del scanner. Las entradas y
la fase aceptada se vuelven a verificar por SHA-256 antes de publicar. Se escribe
primero en un directorio temporal y se publica el conjunto con el protocolo de
reemplazo existente. Un destino que contenga archivos ajenos, una entrada o la
fase anterior se rechaza. Una ejecución fallida conserva la salida anterior.

Determinismo: mismos bytes, parámetros, código y versión Python producen los
cinco archivos idénticos. Semillas explícitas, orden fijo, agrupaciones ordenadas,
percentiles definidos y serialización sin fechas de ejecución. Cambiar el código
cambia su hash en el manifiesto, aunque no cambien los resultados numéricos.

## Pruebas reproducibles

```powershell
$env:SCANNER_CSV_PATH = "$env:APPDATA\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\MQL5\Files\XAUUSD_Scanner_B4C88ADF68090945.csv"
$env:SCANNER_SAMPLE_PATH = (Resolve-Path "artifacts\scanner_analysis\smoke_20260610_20260814_v2\signals_review_sample.csv").Path
$env:SCANNER_ANNOTATIONS_PATH = "$env:USERPROFILE\Downloads\signal_review_annotations_2026-09-19T02-44-08-381Z.csv"
$env:REVIEW_BROWSER_EXE = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
$env:ROBUSTNESS_REAL_TEST = '1'
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -B -m unittest discover -s tests -p "test_*.py" -v
```

La prueba real de robustez usa 100 réplicas/permutaciones para comprobar la
integración; los resultados entregados usan las 2.000/10.000 del comando principal.
Los fixtures verifican cifras conocidas, causalidad, spread, inversión pareada,
bootstrap por día, permutación, Holm, LOO, clusters, incompletos, no imputación de
etiquetas, protección de fase 1 y reproducibilidad byte a byte. Sin las variables
explícitas se omite la integración correspondiente.

## Limitaciones

Los grupos y horizontes se inspeccionan retrospectivamente tras haber visto las
50 señales; esta población es una ampliación dentro del mismo período, no una
validación fuera de muestra. Los grupos se solapan y algunas configuraciones
son pequeñas. Agrupar por día trata la dependencia intradía, pero no garantiza
independencia entre días ni estacionariedad. Los extremos OHLC no indican su
orden intrabar. No se modelan ejecución, spread futuro real, slippage, comisiones,
swaps o liquidez. Ningún signo positivo aislado ni p sin ajuste prueba edge.

## Resultados de la ejecución de fase 2

### Integridad y cobertura

- **114 pruebas aprobadas, sin omisiones**, incluidas 20 de robustez y todas las
  integraciones reales. La integración de robustez utiliza 100 réplicas; la
  entrega final utiliza 2.000 bootstrap y 10.000 permutaciones, semilla 20260919.
- **266 señales**: B0 182, PB1 66 y B0+PB1 18. Se cubren **47 días NY**.
- 50 señales revisadas; ninguna etiqueta manual inventada para las otras 216.
- Cobertura: **266/266** a 15, 30 y 60 minutos; **265/266** a 120 minutos.
- SIG-000050, B0 SELL, decisión 2026-06-19 18:45:00 del servidor: faltan nueve
  barras de 20:00 a 20:40 inclusive. Solo su horizonte de 120 minutos queda
  INCOMPLETE en cada escenario; su fila y los otros horizontes se conservan.
- Dos ejecuciones completas produjeron los **cinco archivos idénticos byte a
  byte**. Se verificaron hashes de entradas, los cuatro artefactos de fase 1 y
  los cuatro MQ5/EX5: permanecieron iguales.
- Auditoría independiente de **4.256 escenarios** (266 × 4 horizontes × 4 costes):
  límites temporales, identidad de spread real/invertido y LOO correctos. Cuatro
  filas incompletas corresponden al único horizonte ausente en cuatro costes.
- Salidas: 27.592 filas de resumen, 72.576 de influencia y 4.536 de clusters.
  Estos conteos incluyen grupos y métricas repetidos; no son señales adicionales.

### Resultado global, spread observado

Retorno firmado al cierre, en puntos:

| Min | N completo | Media | Mediana | Recortada 10 % | Winsorizada 10 % | IC95 media por día |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 15 | 266 | 8,51 | −53,00 | −28,98 | −2,10 | [−104,80; 125,74] |
| 30 | 266 | −21,88 | −114,00 | −48,12 | −30,80 | [−180,99; 128,70] |
| 60 | 266 | 28,94 | −179,00 | −53,06 | −24,31 | [−206,61; 256,06] |
| 120 | 265 | 160,42 | 43,00 | 53,99 | 124,24 | [−181,33; 495,24] |

### Dependencia, costes e influencia

| Min | Señales solapadas | Pares | Clusters | Mayor cluster | Media sin solape, primeras | Media sin solape, últimas | Media total spread ×2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 15 | 44 | 22 | 244 | 2 | 17,41 | −72,58 | 0,57 |
| 30 | 143 | 86 | 182 | 5 | 19,27 | −180,65 | −29,82 |
| 60 | 237 | 240 | 89 | 10 | 70,42 | −238,68 | 21,00 |
| 120 | 266 | 496 | 47 | 10 | 255,04 | −257,04 | 152,48 |

La elección entre primeras y últimas señales no solapadas cambia el signo de
la media global en los cuatro horizontes. No se elige retrospectivamente la
variante favorable. Con ponderación igual por día, a 120 minutos la media es
64,83, la mediana −48,86 y la media recortada −22,22 puntos.

| Min | Señal más influyente | Valor de la señal | Media completa | Media al retirarla |
| --- | --- | ---: | ---: | ---: |
| 15 | SIG-000101 | 6.965,00 | 8,51 | −17,74 |
| 30 | SIG-000145 | −6.129,00 | −21,88 | 1,16 |
| 60 | SIG-000064 | 6.338,00 | 28,94 | 5,14 |
| 120 | SIG-000097 | 7.527,00 | 160,42 | 132,51 |

### Evaluación explícita de las hipótesis

**H1 — ventaja más estable de B0+PB1: no establecida.** B0+PB1 tiene medias
positivas en los cuatro horizontes (182,39 / 406,94 / 808,33 / 883,44 puntos),
pero son solo 18 señales en 15 días. De los ocho contrastes de medias contra
B0/PB1, tres tienen IC95 individual completamente positivo: contra B0 y PB1 a
60 minutos, y contra B0 a 120. Los otros cinco incluyen cero. Estos intervalos
no son simultáneos y no bastan para establecer una ventaja general estable.

**H2 — dirección emitida superior a invertida: no confirmada para el total.**
Deltas medios real−invertida: 32,90 / −27,89 / 73,77 / 336,71 puntos a
15/30/60/120 minutos. Todos sus IC95 contienen cero. Las p unilaterales son
0,3931 / 0,5643 / 0,3775 / 0,1660; las p Holm son 1 en los cuatro casos.
Los desgloses por módulo y dirección se conservan completos, sin escoger solo
los resultados favorables.

**H3 — supervivencia a extremos, solapamiento y costes: no hay candidata que
pase todos los controles.** Las medias positivas globales no son coherentes
con las medianas, los recortes, ambas selecciones no solapadas y el control por
días. A 15 minutos, una sola señal revierte el signo. A 120 minutos el spread ×2
conserva la media positiva, pero el subconjunto no solapado desde el final y la
mediana diaria son negativos y el IC95 global cruza cero. **Candidatas: cero.**

**B0 + RANGE, únicamente revisión manual:** 7 señales en 7 días. Sus medias
son −399,14 / −441,71 / −1.087,43 / −363,71 puntos para los cuatro horizontes.
Son datos exploratorios de las 50 revisadas, no una clasificación del contexto
de las 266. No se propone convertir estas observaciones en una regla de filtro.

No se ejecutaron operaciones, Strategy Tester, backtests, staging, commit ni push.
No se cambió ningún artefacto aceptado, CSV de entrada, MQ5 o EX5.
