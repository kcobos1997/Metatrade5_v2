# XAUUSD Intraday Signal Scanner — especificación v1

Fecha: 2026-09-17. **P: decisiones de ingeniería, sin optimización ni validación económica.**
Autoridad: [decisión aprobada](../research/XAUUSD_INTRADAY_V1_DECISION.md#11-decisiones-aprobadas-y-fase-scanner).

## 1. Alcance

EA independiente `XAUUSD_Intraday_Signal_Scanner.mq5`, símbolo `_Symbol`, contexto
H1 y observación M5. Cuatro canales: B0 BUY/SELL y PB1 BUY/SELL, independientes
para comparación. No representan una cartera simultáneamente ejecutable.
Toda aceptación significa `ACCEPT_DIAGNOSTIC`; `trade_authorized=0` siempre.
Sin órdenes, posiciones, lotaje, stops, targets, riesgo monetario, noticias,
M15, RSI, ADX, optimización ni medición de rentabilidad. El EA anterior y todos
los EX5 existentes se conservan. La advertencia de símbolo distinto de XAUUSD
no impide investigar sufijos del broker.

## 2. Inputs

| Input | Default | Restricción / significado |
| --- | --- | --- |
| EMA_H1_Period | 50 | 2–200; EMA estándar PRICE_CLOSE, calentamiento mínimo 5 periodos |
| PullbackBars | 3 | 2–20 cierres previos estrictamente ordenados |
| BreakoutLookback | 3 | 1–100 barras anteriores |
| CooldownBars | 2 | 0–100 barras M5 observadas por canal |
| MagicNumber | 1997101 | Identidad reservada; nunca utilizada para operar |
| NYStartHour / NYEndHour | 8 / 12 | 0 <= inicio < fin <= 24; intervalo semiabierto |
| BrokerUtcSchedule | vacío | Tabla de intervalos UTC y offset del servidor, descrita abajo |
| RunId | vacío | En demo se usa `demo`; obligatorio y único por ensayo en tester |
| SelfTestOnly | false | Ejecuta fixtures sin indicador, CSV de mercado ni procesamiento de ticks |

Cambiar inputs de señal, calendario o RunId genera otra identidad de experimento.
No es un método para rearmar episodios dentro de un mismo experimento.
Se rechaza optimización; la cuenta fuera del tester debe ser demo.

## 3. Tiempo, disponibilidad y datos

`decision_server` es apertura de la nueva M5 observable. `signal_open_server =
decision_server - 300`. `observed_server` es hora del tick que disparó la lectura;
`delay_seconds = observed_server - decision_server`. La clasificación de sesión
se hace con `decision_server`, no con un cierre retrospectivamente negociable.
No se impone un umbral optimizado de demora; la demora queda registrada.

Se lee exclusivamente PERIOD_M5/PERIOD_H1, nunca el timeframe visual. El watermark
persistente es `decision_server`: el mismo timestamp no se procesa de nuevo.
Al arrancar por primera vez se registra la última M5 cerrada como `BASELINE`, sin
aceptar señales. No se reproducen oportunidades anteriores a la instalación.
Reinicio con watermark vigente continúa; si faltan barras se registra `GAP_RESET`
para la última disponible, sin inventar filas/ticks intermedios.

M5: CopyRates desde posición 1, exactamente max(p, lookback)+1 elementos,
orden cronológico explícito; último final = decisión; diferencias de 300 s,
OHLC finitos positivos y coherentes. Duplicados/huecos/parciales invalidan el lote.
H1: iBarShift sobre `decision_server - 3600`; shift >= 1. Verificar por timestamp
`H1.open + 3600 <= decision_server` y edad del cierre < 3600 s. CopyRates de
5*EMA_H1_Period barras cerradas y CopyBuffer de exactamente un valor de esa H1;
BarsCalculated suficiente, EMA finita positiva distinta de EMPTY_VALUE. Se
permiten cierres H1 separados por cierres de mercado, nunca timestamps repetidos.
La EMA nativa puede cambiar si el proveedor revisa o amplía el histórico anterior:
esto requiere otro experimento; no se reescriben registros ya observados.

Un fallo de datos se registra una vez como `DATA_M5`, `DATA_H1`, `DATA_EMA` o
`DATA_TICK`; no se reintenta esa decisión ni se acepta posteriormente con más
información. Se invalidan los episodios y la siguiente barra completa es
`BASELINE`. No conocer siquiera la apertura M5 produce aviso limitado a uno por
bloque de 5 minutos y no inventa una clave. Un timestamp actual que retrocede
respecto al watermark detiene el scanner; no se confunde con un nuevo evento.

## 4. Fórmulas y episodios

`t` es última M5 cerrada, `p=PullbackBars`, `b=BreakoutLookback`.
Permiso H1: +1 si cierre H1 > EMA, -1 si <, 0 si igualdad.

- **B0 BUY:** C[t] > max(H[t-b], ..., H[t-1]). SELL: C[t] < min(L[t-b], ..., L[t-1]).
- **PB1 BUY:** C[t-p] > ... > C[t-1] y C[t] > H[t-1].
  SELL: C[t-p] < ... < C[t-1] y C[t] < L[t-1].
- Igualdad en el gatillo: `EQUALITY`; no hay epsilon ni redondeo que la convierta
  en ruptura. Igualdad entre cierres del setup rompe la secuencia (`NO_SETUP`).

**B0:** un episodio comienza con el primer raw=true tras estar rearmado. Se
consume aunque H1/sesión lo rechacen. raw=true consecutivo => `EPISODE_CONSUMED`.
Solo raw=false en una barra con índice > cooldown_until rearma; no se rearma por
cambio H1. El ID del episodio es el timestamp de su primera ruptura.

**PB1:** se sigue la secuencia maximal de cierres descendentes (BUY) o ascendentes
(SELL). El primer cierre de la secuencia identifica el episodio; prolongar la
secuencia no cambia ese comienzo. El gatillo usa exclusivamente las últimas p
barras, pero requiere episodio de longitud >= p. Un gatillo estricto consume el
episodio incluso si se rechaza. El cierre del gatillo rompe necesariamente la
secuencia previa; solo otra secuencia completa puede generar otro episodio.
Después de consumir, su nuevo comienzo debe tener índice > cooldown_until.
Esto también impide reutilizar ventanas solapadas formadas durante el cooldown.

Cada canal tiene cooldown independiente. Consumir un gatillo nuevo en índice k
fija cooldown_until=k+CooldownBars. Se bloquean k+1,...,k+c. No hay reloj de
posiciones en esta fase. Un cambio del permiso H1 invalida secuencias PB1 antes
de evaluar y la barra actual es el primer cierre del nuevo contexto; los
cooldowns se conservan. B0 conserva el episodio consumido para impedir su
reutilización bajo el nuevo permiso. Un hueco/error invalida estado y exige nueva
línea base; no se infiere qué ocurrió durante la ausencia.

Precedencia del motivo principal: error de datos / GAP_RESET / BASELINE;
NO_SETUP; EQUALITY; NO_BREAKOUT; EPISODE_CONSUMED (B0 o estado PB1 consumido);
H1_CHANGED (PB1); COOLDOWN; FRESH_SEQUENCE_REQUIRED (PB1);
H1_NEUTRAL; H1_OPPOSED; SESSION_UNKNOWN; OUTSIDE_SESSION; ACCEPT_DIAGNOSTIC.
CSV guarda además raw, permiso y sesión para estudiar rechazos concurrentes.
En BASELINE/GAP_RESET se marcan B0 raw=true como ya consumidos; PB1 empieza con
un cierre. Todos los días/barra observados se exportan, incluidos los sin señal.

## 5. Nueva York y calendario del broker

Tabla explícita, sin inferir offsets con TimeGMT ni con el reloj de Windows:
`UTC_desde|UTC_hasta|minutos;UTC_desde|UTC_hasta|minutos`.
Fechas en formato `YYYY.MM.DD HH:MM`, intervalos [desde,hasta), ordenados,
sin solapamiento UTC; offset entero entre -840 y 840. Ejemplo **sintético, no
calendario del broker**: `2026.01.01 00:00|2027.01.01 00:00|120`.
La tabla exacta forma parte de la identidad del experimento.
Para cada intervalo se prueba UTC=server-offset; exactamente una coincidencia
permite convertir. Cero coincidencias o dos durante una hora repetida del
servidor => SESSION_UNKNOWN. No elegir arbitrariamente una de las dos.

Nueva York: UTC-5 en estándar, UTC-4 desde segundo domingo de marzo 07:00 UTC
hasta primer domingo de noviembre 06:00 UTC. Implementación acotada 2007–2099,
reglas actuales versionadas; fuera del intervalo, sesión desconocida. No es una
base IANA completa ni una promesa sobre futuras reformas legales. Registrar UTC,
NY, offset del servidor y offset NY, tanto de decisión como UTC observado.
Ventana provisional ex ante [08:00,12:00); fuera se conserva raw y se rechaza
por OUTSIDE_SESSION si no existe motivo anterior. Calendario vacío permite
observar patrones con SESSION_UNKNOWN, jamás los etiqueta como dentro.

Fuentes técnicas consultadas 2026-09-17:
[CopyRates](https://www.mql5.com/en/docs/series/copyrates),
[CopyBuffer](https://www.mql5.com/en/docs/series/copybuffer),
[TimeGMT y tester](https://www.mql5.com/en/docs/dateandtime/timegmt),
[reglas DST de NIST](https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst).

## 6. CSV y persistencia

Una fila atómica lógica por decisión con los cuatro resultados; CSV ASCII con
coma, punto decimal, CRLF, header fijo. Ningún campo contiene comas o saltos.
Fechas son segundos MQL5 desde epoch: sufijos server/ny significan reloj local
representado en segundos, **no UTC**. Cero => desconocido. Valores de precios no
disponibles se acompañan siempre de código de datos inválidos.

Columnas base: identity, decision_server, signal_open_server, observed_server,
delay_seconds, decision_utc, decision_ny, observed_utc, server_offset_minutes,
ny_offset_minutes, session, data_status, h1_open_server, h1_close, h1_ema,
h1_gate, bid, ask, spread_points, m5_window, trade_authorized.
`m5_window`: barras cronológicas `time:open:high:low:close` separadas por `;`.
Por canal (b0_buy,b0_sell,pb1_buy,pb1_sell): key, raw, reason, episode_server.
Finalmente state y checksum. State serializa watermark, contador, gate, ready y
los cuatro estados (active, start_time, start_index, length, cooldown_until).
El contador mide decisiones observadas, no huecos rellenados artificialmente.

Clave evento = identidad completa + `:decision_server:modulo:direccion`.
Identidad incluye revisión de esquema/reglas, cuenta/servidor/símbolo codificados,
Magic, modo demo/tester, RunId, todos los parámetros funcionales y tabla horaria.
Nombre `XAUUSD_Scanner_<dos hashes>.csv`, pero el contenido contrasta identidad
completa para detectar colisiones. RunId acepta solo letras ASCII, dígitos, `_` y
`-`, máximo 64. Una ejecución tester nueva requiere RunId nuevo; una continuación
del mismo ensayo conserva RunId. El timeframe visual no forma parte de la clave.

Ubicación demo: terminal **MQL5/Files**; tester: **MQL5/Files del agente**. Sin
FILE_COMMON, red ni exportación externa. Apertura binaria exclusiva durante toda
la vida del EA impide dos escritores sobre la misma identidad.
Se valida header, identidad, número de campos, checksum de cada fila, orden
estrictamente creciente y snapshot. Se restaura únicamente el último estado
completo. Se añade fila+CRLF, se verifica cantidad escrita y FileFlush antes de
actualizar memoria. Truncamiento, hash incorrecto, falta de CRLF, fallo de I/O o
archivo >128 MiB => detener sin reparar/borrar/duplicar automáticamente. Conservar
archivo para auditoría; reparar con revisión o empezar experimento independiente.
Hash FNV no criptográfico: detecta corrupción accidental, no manipulación hostil.
Una caída eléctrica no garantiza durabilidad física; una cola incompleta falla
cerrada. La fila completa ya escrita es el checkpoint aunque falte avance en RAM.

## 7. Pruebas y aceptación

SelfTestOnly ejecuta fixtures del mismo motor, selección temporal, conversión,
serialización y regla watermark. No consulta precios ni escribe CSV de mercado.
También crea CSV sintéticos `ScannerSelfTest_<hora>_<contador>*.csv` en MQL5/Files
para probar persistencia/exclusión; borra únicamente esos archivos al terminar.
Debe cubrir BUY/SELL PB1/B0; igualdad; neutral; H1 abierta; secuencia extendida;
episodio consumido; cooldown; fuera de sesión; datos incompletos; restauración
sin duplicar; futuro añadido; repetición de ticks y timeframe visual. También
límites NY/DST, calendario desconocido/ambiguo, cambio H1 y corrupción de fila.

Ejecución exacta: abrir el nuevo MQ5 en MetaEditor, compilar una copia separada
si se deben preservar binarios; adjuntar ese scanner a cualquier gráfico demo
con SelfTestOnly=true y defaults. Experts debe mostrar cada PASS y
`SELFTEST: ... passed; 0 failed`. OnTick no hace nada en ese modo. No se necesitan
AutoTrading ni permisos de trading. Retirar el scanner después. Un FAIL provoca
INIT_FAILED. Esta prueba verifica lógica; no sustituye la integración real.

Integración manual posterior: con SelfTestOnly=false y RunId fijo, observar dos
M5, reiniciar en la misma M5 y cambiar timeframe M1/H4. Debe permanecer una sola
fila por decision_server, misma clave y estado restaurado; otro escritor debe
fallar al abrir el archivo. Verificar timestamps H1 cerrados, motivos de datos,
CSV fuera/dentro de ventana con calendario verificado, continuidad tras reinicio,
y ausencia total de operaciones. Copiar CSV antes de ensayar truncamiento o
corrupción en un RunId de prueba. Repetir en tester local sin optimización con
RunId nuevo, solo para comprobar registro, sin medir ni interpretar PnL.

Aceptación de fase: compilación sin errores/advertencias; fixtures sin fallos;
inspección sin llamadas de trading; integración anterior comprobada en MT5.
La entrega de código por sí sola no declara completada la aceptación en terminal.
Los criterios estadísticos de investigación permanecen intactos y pendientes.

## 8. Registro de verificación — 2026-09-17

- Compilación MetaEditor del EA: **0 errors, 0 warnings**. Fuente copiada a una
  carpeta temporal; ningún EX5 previo del proyecto fue modificado.
- Ejecución real MQL5 en terminal portátil aislado, build 6182, sin credenciales
  del usuario, con trading desactivado y proxy local sin broker. Un script temporal
  incluyó exactamente el scanner, renombró OnInit/OnTick/OnDeinit mediante macros
  y llamó RunSelfTests desde OnStart. No se ejecutó un backtest de rentabilidad.
- Resultado final: **SELFTEST: 48 passed; 0 failed**. Incluye las cuatro señales,
  igualdades, H1 neutral/abierta/antigua/cambio, pullback extendido, episodio
  consumido, cooldown/secuencia nueva, sesiones/DST/ambigüedad, datos incompletos,
  EMA fallida, huecos, prefijo frente a futuro añadido, estado restaurado,
  ticks repetidos, independencia del timeframe en el núcleo y corrupción.
- Persistencia real: creación/header, escritor exclusivo, commit, reapertura,
  fila completa escrita antes de actualizar RAM y fila truncada: **6/6 PASS**,
  incluidas en las 48 anteriores. Los CSV sintéticos se eliminaron al finalizar.
- Una ejecución inicial detectó una diferencia MQL5 entre cadena NULL y vacía.
  Se corrigió la inicialización de Frame.error y su comprobación por longitud;
  se volvió a ejecutar toda la batería con el resultado final anterior.
- Búsqueda estática: sin APIs de envío/modificación de trading, imports ni
  dependencia del timeframe visual. `git diff --check` y comprobación equivalente
  para archivos nuevos sin errores de whitespace. Sin staging, commit ni push.
- SHA256 del EA anterior, EX5 anterior, README, STRATEGY, BACKTEST_PROTOCOL y
  documento de mercado idénticos a los registrados antes de la tarea.

**Pendiente de aceptación de integración:** lectura real de CopyRates/CopyBuffer
en la cuenta demo, interpretación visual de H1/M5, calendario histórico del broker,
reenganche y cambio M1/H4 del EA completo, exportación en el agente del tester.
El fixture de timeframe demuestra independencia del núcleo; no simula los eventos
OnDeinit/OnInit del terminal. La prueba de futuro compara datos inmutables; no
certifica históricos revisados por el proveedor. Sigue pendiente toda validación
económica. La compilación y los 48 PASS no aprueban una estrategia rentable.
