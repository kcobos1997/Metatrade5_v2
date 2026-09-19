# Fase 3 — protocolo congelado de validación temporal B0+PB1

Fecha de especificación: 2026-09-19. Rama: `research/intraday-regime-v1`.
Estado: **infraestructura; ninguna ejecución del holdout autorizada todavía**.
La fase 2 es un checkpoint aceptado. No se regeneran sus artefactos ni se exploran
otros subgrupos del período de descubrimiento 2026-06-10 a 2026-08-14.

## 1. Hipótesis única y población

- Todas las aceptaciones con módulo **exactamente `B0+PB1`**, contando una vez la
  barra compartida por ambos módulos. BUY y SELL entran conjuntamente.
- Resultado primario: **retorno firmado al cierre a 60 minutos**, en puntos,
  con spread observado. Comparación confirmatoria: dirección emitida menos
  dirección invertida, pareada por señal y agrupada por **día NY de decisión**.
- No se leen muestras ni anotaciones; no se usan `context_class`,
  `signal_alignment` ni `reviewer_decision`.
- 120 minutos, MFE/MAE y cualquier desglose de dirección son secundarios. Esta
  implementación no genera desgloses BUY/SELL ni otras poblaciones. No existe
  una hipótesis confirmatoria B0+PB1 SELL. Nada secundario puede rescatar el
  fallo a 60 minutos.
- No se diseñan entradas, SL, TP, riesgo ni EA; no se ejecutan operaciones.
  En esta entrega de infraestructura no se ejecutan Strategy Tester ni backtests.
  La reproducción diagnóstica futura queda sujeta al procedimiento de la sección 7.
  Los precios de referencia son los del modelo
  analítico anterior, no una propuesta de ejecución.

## 2. Ventana inmutable y bloqueo de consulta

Selección por instante de **decisión del scanner**, cuando la vela de señal ya
cerró; `signal_open_server = decision_server - 300`.

| Límite | America/New_York | UTC |
| --- | --- | --- |
| Inicio inclusivo | 2026-08-15 00:00 EDT | 2026-08-15 04:00 |
| Final exclusivo | 2026-11-01 00:00 EDT | 2026-11-01 04:00 |

El final precede al cambio de hora NY de ese domingo a las 06:00 UTC. Se conserva
la regla DST versionada del scanner; en esta ventana NY es UTC−4. No se depende
de la zona de Windows ni de paquetes `tzdata` externos.

La CLI y la función pública `analyze` comprueban el reloj UTC **antes de leer o
hashear la entrada, importar los analizadores o crear salidas**. No existe
`--as-of`, variable de entorno ni opción para eludir el cierre. Las pruebas
sustituyen el reloj exclusivamente dentro del proceso de `unittest`.

Toda aceptación fuera de la ventana provoca rechazo del CSV completo, incluso
si pertenece a B0 o PB1 aislado. No se recorta silenciosamente un CSV de
descubrimiento. Filas sin aceptaciones pueden aportar calentamiento o precios
para completar horizontes; nunca incorporan señales externas a la población.
`--start-ny` y `--end-ny`, si se indican, deben coincidir exactamente con los
límites congelados. No hay extensión retrospectiva por falta de observaciones.

## 3. Código y parámetros congelados

SHA-256 sobre **bytes exactos**, comprobado antes de importar las dependencias y
otra vez antes de publicar. Incluso una conversión de saltos de línea invalida
el hash: no se actualizan hashes automáticamente.

| Archivo | SHA-256 |
| --- | --- |
| `XAUUSD_Intraday_Signal_Scanner.mq5` | `d7fc26b645f3f18b9b6f570f46672794fe877f95be21021fea5a9d7b985095ec` |
| `XAUUSD_Intraday_Signal_Scanner.ex5` | `ac85ea60579d767ede143d320880db49f2038fe3e2848c694170241c5241eadd` |
| `tools/analyze_scanner.py` | `b3637d1a8e03a73c7233d8fddf8cd4a2e09737847b51102b0e588120c9b20751` |
| `tools/analyze_signal_outcomes.py` | `22c22d36b33c3eb18d9881a5f0119d83c9374eab32f4898c37878e5c82afbb11` |
| `tools/analyze_signal_robustness.py` | `88d3d6ea109b3ce14ebe3e1350ef0b6d60a1dcbd627992584758d5c4f6f453cc` |

El EX5 existente se congela en la raíz del proyecto, junto al MQ5. Su hash se
verifica antes de analizar y antes de publicar, y se incluye en
`frozen_code_sha256` del manifiesto. Si falta o cambia, se bloquea la ejecución;
no se compila un sustituto ni se actualiza el hash automáticamente. Esta
comprobación conserva el ejecutable exacto; no demuestra por sí sola la
correspondencia entre binario y fuente.

Se comprueban en cada `identity`: EMA H1 **50**, PullbackBars **3**,
BreakoutLookback **3**, CooldownBars **2**, sesión NY **08:00–12:00**.
Se conserva el símbolo XAUUSD con posibles sufijos del broker. Cuenta, servidor,
Magic y RunId identifican el experimento y no seleccionan resultados; no se
publican. Se exige una sola identidad válida y se mantienen checksums,
aceptaciones, H1 cerrado y validaciones originales. No se cambia el scanner.

### Bloqueo pendiente: calendario horario del broker

Se leyó únicamente la configuración de la primera fila del CSV de descubrimiento,
sin recalcular resultados. Su calendario registrado exacto es:

```text
2026.06.01 00:00|2026.09.01 00:00|180
```

**No cubre el holdout completo.** El validador lo mantiene congelado y, después
del cierre temporal, rechaza la ejecución con `BROKER_SCHEDULE_INCOMPLETE` antes
de leer los precios. No supone que UTC+3 continúe ni inventa un calendario del
broker. Cualquier calendario distinto en el CSV también se rechaza.

Para habilitar una futura ejecución se necesita evidencia verificable del
calendario completo y una revisión explícita, registrada y aprobada de este
protocolo y de su constante `BROKER_SCHEDULE`, **antes de inspeccionar resultados**.
Esto no autoriza cambiar la hipótesis, ventana, scanner o parámetros estadísticos.
No hay una opción de CLI para aceptar un calendario alternativo. Si no puede
resolverse la integridad horaria, no se emite un veredicto estadístico.

## 4. Integridad de la colección y causalidad

Se reutiliza la reconstrucción canónica M5: deduplicación de OHLC idénticos y
rechazo de contradicciones. Cada horizonte usa exclusivamente aperturas en
`[decision_server, decision_server + horizonte)`: 12 barras a 60 minutos y 24 a
120. Quedan fuera la vela de señal y la barra del límite final. Son resultados
posteriores medidos después del cierre, nunca información disponible al emitir
la señal. Ningún selector utiliza esos resultados futuros.

Se verifican UTC, hora de servidor y hora NY contra el calendario congelado y
el offset NY de esta ventana. Una cotización de referencia tardía se rechaza.
Precios con Decimal de precisión 40; punto **0.01**; tolerancia de coherencia
entre `(ask-bid)/point` y spread registrado **0.000001 puntos**.

Para evitar aceptar como final un fichero truncado a mitad del período, se exige
cobertura de las decisiones M5 de 08:00 a 11:55 NY de lunes a viernes en **toda**
la ventana, con `data_status=OK`. Una ausencia produce `INCONCLUSIVE`, aunque
existan 20 señales. Esta comprobación es conservadora: no inventa sesiones o
precios y no es un calendario oficial de festivos del broker. Las ausencias no
se eliminan retrospectivamente para obtener PASS. Se informa el número de
slots previstos, observados válidos y ausentes.

Un horizonte con cualquier barra ausente queda `INCOMPLETE`, con métricas vacías;
no se imputa cero. Se conserva su fila. Los conteos y estimadores usan solo las
señales completas de cada horizonte. Las selecciones no solapadas se fijan
**antes** de retirar horizontes incompletos.

Para emitir PASS o FAIL, **todas** las señales B0+PB1 deben estar completas a
60 minutos: `n_complete == n_total`, tanto con spread ×1 como con spread ×2.
Una sola incompleta produce `INCONCLUSIVE` con razón
`PRIMARY_60_HORIZON_INCOMPLETE`, incluso con 20 completas de 21 totales y
10 días, e independientemente del signo de los resultados disponibles.
Los conteos `n_total`, `n_complete` y `n_days` deben ser enteros no negativos,
con `n_days <= n_complete <= n_total`, e idénticos entre ambos costes. Un resumen
ausente o incoherente se rechaza como entrada inválida antes del veredicto.
Una ausencia únicamente a 120 minutos sigue siendo secundaria: no veta ni
rescata el veredicto de 60 minutos.

## 5. Precios, inversión y costes

Modelo congelado: **ENTRY_SPREAD_CONSTANT**. BUY compara el ask observado con
OHLC bid futuro. SELL compara el bid observado con OHLC ask aproximado por bid
futuro más el spread observado constante. Retorno firmado al cierre:

```text
BUY  = (close_bid_final - ask_escenario) / point
SELL = (bid_entrada - close_bid_final - spread_escenario) / point
ask_escenario = bid_entrada + (ask_observado - bid_entrada) * factor
factor = 1.00 o 2.00
```

La dirección invertida usa exactamente las mismas barras, instante y coste.
Delta = real − invertida; el spread simétrico se cancela en el delta, pero no
en los retornos. No se resta dos veces el coste ni se expresa PnL monetario.
MFE/MAE conservan las fórmulas de la fase 2, solo como descripción secundaria.

## 6. Estadística fijada y decisión primaria

Se reutilizan, sin modificarlos, `describe`, `day_bootstrap`,
`paired_permutation`, `nonoverlap` y `leave_one_out` de fase 2.

- Percentiles lineales `(N-1)*p`. Recorte y winsorización de `floor(N/10)`
  observaciones **por cola**. Sin selección de extremos después de ver resultados.
- Bootstrap percentil 95 %: **2.000** remuestras de días NY completos con
  reemplazo; razón de suma de retornos entre número de señales remuestreadas.
  Conserva ponderación por señal y dependencia intradía. No es un IC de mediana.
- Semilla **20260919**; subsemilla SHA-256 mediante la función congelada y etiqueta
  `PHASE3|60`. Mismas secuencias de días para métricas y costes. No se usa `hash()`.
- Permutación unilateral de **10.000** intercambios real/invertida conjuntos por
  día NY; estadístico suma de deltas; corrección `(1+extremos)/(10000+1)`.
  Se usa la tolerancia numérica congelada de fase 2. Solo un contraste primario:
  no Holm ni pruebas confirmatorias adicionales a 120 minutos o por dirección.
- `NONOVERLAP_FIRST` y `NONOVERLAP_LAST`: selecciones codiciosas desde ambos
  extremos, exclusivamente por timestamp/ID. Intervalos que se tocan no se solapan.
- Leave-one-out: media después de excluir cada señal; se informa mínimo, máximo
  e ID más influyente. No se elimina definitivamente ninguna señal influyente.

Con datos válidos y colección completa, se exige **todo** a 60 minutos:

1. Media, mediana, media recortada y winsorizada estrictamente positivas.
2. Límite inferior IC95 por día de la media estrictamente positivo.
3. Media del delta real−invertida y límite inferior de su IC95 positivos.
4. p unilateral primaria ≤ **0.05**.
5. Media positiva en ambas selecciones no solapadas.
6. Mínima media leave-one-out positiva.
7. Los signos de los puntos 1–3, 5 y 6 se conservan con spread ×2, incluidos
   los límites inferiores de los IC. El delta y su p no cambian por coste;
   no se introduce otra hipótesis ni se vuelve a elegir una p.
8. Al menos **20 señales completas y 10 días NY** completos a 60 minutos.

**PASS:** todos los criterios. **FAIL:** tamaño suficiente y algún criterio
primario falla. **INCONCLUSIVE:** tamaño insuficiente, colección incompleta o
cualquier horizonte primario de 60 minutos incompleto; tiene prioridad sobre
PASS/FAIL. Cero no es positivo. Ausencias no equivalen a
ceros. Los resultados de 120 minutos no intervienen en ninguna decisión.

`WINDOW_OPEN`, hashes/parámetros incompatibles, fechas externas y calendario
insuficiente son **bloqueos/entradas inválidas**, no FAIL ni INCONCLUSIVE por
evidencia estadística. No generan resultados ni manifiesto de resultados.
La prioridad es **entrada inválida/bloqueo > INCONCLUSIVE > PASS/FAIL**.
`BROKER_SCHEDULE_INCOMPLETE` permanece exactamente como bloqueo, sin inferir
que el offset UTC+3 continúe ni resolver ahora el calendario.

## 7. Salidas y reproducción futura

### Procedimiento futuro de colección diagnóstica

La prohibición actual de Strategy Tester corresponde a **esta entrega de
infraestructura**. La futura reproducción diagnóstica queda autorizada únicamente
después de cumplir las tres condiciones: cierre temporal, calendario completo
resuelto y registrado conforme a este protocolo, y **aprobación explícita**.
Este documento no sustituye esa aprobación ni autoriza ejecutar ahora.

1. Registrar antes de ejecutar la configuración aprobada y los hashes exactos
   del MQ5 y EX5 congelados. Usar el scanner diagnóstico sin llamadas de trading;
   no añadir lógica de operaciones ni recompilar para alterar el experimento.
2. Realizar **una sola ejecución** en Strategy Tester con **Every tick based on
   real ticks**, XAUUSD y el broker originales. Mantener los mismos parámetros
   e identidad registrados para el experimento aprobado: servidor, cuenta,
   símbolo, Magic, modo tester y RunId. No variar la identidad entre colección
   y validación ni ensayar configuraciones alternativas.
3. Usar la ventana congelada: inicio inclusivo 2026-08-15 00:00 y final exclusivo
   2026-11-01 00:00 America/New_York. La correspondencia con el reloj del servidor
   se documentará usando el calendario verificado; no se supone UTC+3. No cambiar
   los límites por escasez de señales. El calentamiento y las barras posteriores
   necesarias para medir horizontes no amplían la población de señales admitidas.
4. Preparar un destino de colección aislado y vacío para evitar que el journal
   del scanner se añada a un CSV preexistente. No combinar CSV, reutilizar el CSV
   de descubrimiento, recortar aceptaciones externas ni repetir ejecuciones
   buscando un resultado favorable. Una incidencia se documenta sin autorizar
   automáticamente otra ejecución.
5. Conservar el **CSV original exacto**, sin edición, reducción ni concatenación.
   Registrar su SHA-256 junto con los SHA-256 del MQ5 y EX5, configuración,
   identidad y evidencia de cobertura temporal. Mantener los identificadores
   sensibles en el registro local; el manifiesto público no los divulga.
6. Ejecutar el validador sobre ese único CSV cuando esté autorizado. Una entrada
   inválida o un bloqueo se informa antes de interpretar resultados. No se
   sustituyen ni se eliminan señales incompletas para conseguir PASS.

### Comando y artefactos futuros

Solo tras cierre, resolución del calendario y autorización para analizar:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -B tools\validate_b0_pb1_holdout.py `
  --input "C:\ruta\CSV_ORIGINAL_HOLDOUT_COMPLETO.csv" `
  --output-dir "artifacts\scanner_analysis\phase3_b0_pb1_20260815_20261101"
```

Este es un comando futuro con ruta pendiente; **no se ejecutó en esta entrega**.
La salida debe ser un directorio nuevo `artifacts/scanner_analysis/phase3_*`.
Se rechazan directorios existentes, enlaces y destinos que contengan la entrada;
no se sobrescriben fases aceptadas. Publicación por renombrado desde un temporal
hermano; los hashes de entrada/código/protocolo se vuelven a comprobar.

- `holdout_summary.csv`: 60/120 × spread 1/2 × ALL/FIRST/LAST × métricas;
  no estratos direccionales. La p solo aparece para el delta primario a coste ×1.
- `holdout_signals.csv`: una fila por señal/horizonte/coste, con dirección original,
  intervalos, cobertura, retornos real/invertido y selección no solapada.
- `holdout_manifest.json`: PASS/FAIL/INCONCLUSIVE, razones y criterios, parámetros,
  cobertura, hash de entrada, scanner MQ5 y EX5, analizadores, protocolo, validador y salidas.
  No incluye identidades sensibles, rutas locales ni reloj de generación.

Mismos bytes de entrada, código, parámetros y versión Python producen salidas
idénticas byte a byte en directorios distintos. El manifiesto excluye su propio
hash. No se instalan paquetes ni se necesita red. El reloj del equipo es una
barrera operativa, no una protección contra manipulación deliberada del sistema.
Los hashes comprueban versiones; no autentican al broker ni demuestran que no
se omitieron datos. La comprobación de slots detecta truncamientos, no falsificación.

## 8. Pruebas sin resultados reales

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -B -m unittest discover -s tests -p "test_validate_b0_pb1_holdout.py" -v
```

Los fixtures se crean en directorios temporales, con precios artificiales y un
calendario **sintético** completo. No se leen CSV del holdout ni artefactos
aceptados. Se prueban bloqueo antes de lectura, límites UTC/NY, hashes, parámetros,
exclusión de descubrimiento, causalidad, costes, inferencia por día, decisiones,
ausencias, tamaños mínimos, neutralidad de secundarios, conservación de entrada
y reproducción byte a byte. Las integraciones reales de fases anteriores deben
permanecer desactivadas durante esta fase de infraestructura.

Verificación inicial de Fase 3: **27 pruebas nuevas aprobadas**. La regresión
descubrió 141 pruebas: **137 aprobadas y 4 integraciones reales omitidas
deliberadamente**. Tres pruebas antiguas de Edge fallaron inicialmente al no
poder iniciar el proceso gráfico en el sandbox; las tres pasaron al repetirlas
fuera de esa restricción, con páginas sintéticas y perfiles temporales.
Se comprobó reproducción byte a byte de las tres salidas con fixtures, bloqueo
previo a lectura y conservación de las entradas sintéticas. No se ejecutó el
análisis real ni se abrió ningún resultado parcial del holdout.

Verificación del endurecimiento: **33 pruebas específicas aprobadas** (seis
adicionales). Regresión completa: **147 descubiertas, 143 aprobadas y cuatro
integraciones reales omitidas deliberadamente**. También pasaron `py_compile`
del validador y sus pruebas, y `git diff --check`. Se comprobó la prioridad de
entrada inválida/bloqueo, el caso 20 completas de 21 a 60 minutos, la neutralidad
de ausencias solo a 120 minutos y la alteración de una copia temporal del EX5.
El EX5 original permanece intacto. No se leyó ningún CSV real ni se ejecutó
Strategy Tester o el holdout durante este endurecimiento.

PASS sería superar este protocolo, no demostrar edge, rentabilidad ejecutable
ni independencia entre días. El contraste presupone simetría/intercambiabilidad
de deltas diarios. Persisten las limitaciones de spread futuro aproximado,
comisiones, deslizamiento y ausencia de ejecución.
