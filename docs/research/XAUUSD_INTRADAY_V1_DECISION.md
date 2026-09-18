# Decisión de investigación: XAUUSD Intraday V1

**Fecha:** 2026-09-17. **Estado:** decisiones iniciales aprobadas; implementación diagnóstica autorizada (sección 11).
**No es una estrategia validada ni una autorización para ejecutar operaciones.**

Este documento usa las etiquetas H/V/I/D/P y el registro fechado de fuentes de
[la investigación de mercado](XAUUSD_INTRADAY_MARKET_RESEARCH.md). Las reglas
nuevas son **P: propuestas propias**, no reconstrucciones de productos comerciales.
La estrategia Range Breakout anterior permanece separada e intacta.

## 1. Recomendación principal

Comenzar con **un módulo de continuación tras pullback**, contexto direccional
H1 y ejecución M5 por vela cerrada. Una posición, SL inicial obligatorio, riesgo
fraccional pequeño, TP en R y salida temporal. Sin recuperación, promediado,
pirámide, trailing, break-even ni selector completo de regímenes en este primer
experimento. M15 se registra para estudiar después si aporta información.

**Motivo I:** el experimento permite preguntar si esperar un retroceso añade
valor a una continuación simple, manteniendo fijos riesgo y ejecución. La
literatura sobre sesiones y momentum ofrece motivación contextual, no prueba de
esta regla. No se ha encontrado evidencia directa para RSI(6)/50 en el CFD de
esta cuenta. [R1], [R2]

La meta de 1–3 oportunidades por día es descriptiva, **no un requisito mínimo**.
Se informarán días sin señal, distribución de señales por sesión, señales
bloqueadas y operaciones ejecutadas. No relajar reglas ni añadir módulos para
alcanzar una cuota.

## 2. Alternativa baseline y arquitecturas aplazadas

### Baseline B0: continuación por breakout de estructura

Mismo filtro direccional H1, costes, horarios, SL/riesgo, salidas y límites que
el candidato PB1. Para compra, el cierre M5 supera el máximo de las `p` velas
anteriores; para venta, perfora el mínimo. No exige retroceso previo. Se evalúa
una sola entrada por episodio y una posición, como PB1. Es un control nuevo de
investigación, **no una modificación del EA Range Breakout existente**.

En B0, definir `B_t = C_t > max(H_(t-p), ..., H_(t-1))` para compra
(y su simétrico para venta). Un episodio es una secuencia contigua de `B_t=true`:
solo su primera vela puede disparar. Después de cierre/rechazo y cooldown, exigir
al menos una vela cerrada con `B_t=false` antes de admitir un nuevo episodio.
Así no se multiplican entradas por máximos crecientes consecutivos. PB1 utiliza
sus episodios de retroceso definidos en 4.3; ambos comparten la política de un
intento por episodio, no una definición idéntica de setup.

El objetivo no es que PB1 opere más: debe justificar su mayor selección frente
a B0. Como ablación adicional, probar PB1 sin contexto H1, conservando exactamente
las demás reglas. Primero B0/PB1; después solo una modificación a la vez.

| Arquitectura | Decisión de esta investigación | Motivo I / condición para reconsiderar |
| --- | --- | --- |
| Pullback causal H1/M5 | Candidato PB1 | Regla corta, SL explicable, comparación incremental posible |
| Breakout estructural simple | Control B0 | Menos hipótesis de entrada, datos compartidos |
| Clasificador completo H1/M15/ADX/volatilidad | Aplazado | Interacciones, retraso y selección de módulos sin ventaja individual demostrada |
| Momentum por expansión de ATR | Experimento posterior independiente | Separar expansión útil de precio ya extendido y costes elevados |
| Reversión a la media | Módulo posterior independiente | Necesita probar lateralidad y pérdida en transiciones; no rescatar PB1 |
| Scalping de segundos/arbitraje de latencia | Fuera de V1 | Modelo de ejecución disponible insuficiente para justificar esa ventaja |
| Tick volume/delta como filtro obligatorio | Aplazado | La cuenta no aporta aquí volumen agresor centralizado verificable [T1] |
| IA/LLM o noticias web en el motor | Fuera de V1 | No hay archivo histórico causal ni política reproducible del modelo |
| Grid, martingala, DCA, recuperación | Excluidos | Contradicen el presupuesto fijo por operación y el alcance del usuario |

## 3. Evaluación crítica de la arquitectura provisional

| Componente | Evaluación I | Decisión P / prueba necesaria |
| --- | --- | --- |
| Contexto H1 y M15 | Escalas útiles para describir precio; no son dos observaciones independientes | H1 como único filtro inicial; M15 solo diagnóstico, luego ablación |
| Medias móviles + estructura | Ambos transforman precio; exigir concordancia puede ser redundante | Una EMA para dirección; extremos de precio para setup/SL, sin tercer voto |
| ADX [T11] | La línea principal no sustituye a +DI/−DI para dirección; su suavizado puede retrasar señales | Fuera del baseline; comparar después contra simple volatilidad/pendiente, no añadir ambos a la vez |
| Volatilidad | Útil para expresar distancias comparables; no prueba dirección | ATR como unidad de buffer/análisis, sin filtro optimizado inicial |
| RSI de 6 cruzando 50 | Hipótesis concreta de momentum; periodo corto puede producir cruces repetidos | Comparación posterior con el gatillo de precio y con precio+RSI; periodo 6 no seleccionado como óptimo |
| RSI + cierre rompiendo máximo previo | Ambos pueden identificar la misma recuperación con distinta demora | Medir cambio de hora/precio de entrada, muestra y retorno incremental |
| Una posición y SL | Facilitan trazabilidad y exposición acotada | Restricciones de ingeniería; no se presentan como evidencia de rentabilidad |
| Objetivo R y tiempo máximo | Reducen grados de libertad frente a muchas salidas adaptativas | Preregistrar una regla común B0/PB1; sensibilidad separada |

«Tendencia fuerte», «estructura limpia», «pullback sano», «rechazo confirmado» y
«mercado lateral» no son reglas ejecutables. Se sustituyen abajo por comparaciones
numéricas. Si se introducen swings, deben definirse con información disponible:
un pivote que necesita velas a su derecha solo puede usarse después de que esas
velas cierren. La documentación de RSI ofrece su cálculo/uso técnico, no evidencia
de ventaja económica. [T10]

## 4. Definición lógica preliminar del único módulo

### 4.1 Convenciones causales

- `t`: última vela M5 **cerrada**. `O_t,H_t,L_t,C_t`: sus precios OHLC.
- Decidir una vez al inicio observado de la siguiente vela. Nunca confirmar con
  la vela 0 ni entrar retrospectivamente al cierre ya conocido.
- `h(t)`: última vela H1 cuyo final es anterior o igual al momento de decisión.
  A las 10:05 usar como máximo la H1 terminada a las 10:00, no la H1 en formación.
- `EMA_n(h)` y `ATR_a(t)` solo incluyen barras cerradas y suficiente calentamiento.
  Los periodos están pendientes. En indicadores, verificar handles, número de
  valores copiados y orden de arrays; posición 0 de CopyBuffer es dato actual. [T8]
- Los precios de señal del CFD suelen ser Bid; entrada buy usa Ask y sell Bid.
  La salida/SL de una venta depende de Ask. No simular ambas direcciones con una
  sola serie OHLC ignorando spread. [T1]

### 4.2 Régimen: permiso direccional, no clasificador de estados

Compra permitida si `C_H1(h) > EMA_n(h)`; venta si `<`; igualdad implica neutral.
No exigir inicialmente pendiente, segunda EMA, ADX ni filtro M15. Este permiso
**no demuestra** que el mercado esté en tendencia: esa es parte de la hipótesis
a refutar. Un cambio de permiso invalida el setup, sin alterar una posición ya
abierta salvo sus salidas preregistradas.

### 4.3 Setup y gatillo

**Compra PB1:**

1. Existe permiso H1 de compra al decidir.
2. Las `p` velas M5 inmediatamente anteriores al gatillo muestran cierres
   descendentes: `C_(t-p) > C_(t-p+1) > ... > C_(t-1)`, con `p >= 2`.
3. La vela cerrada `t` reanuda al alza: `C_t > H_(t-1)`.

**Venta PB1:** invertir las desigualdades: cierres ascendentes previos,
`C_t < L_(t-1)` y permiso H1 de venta. Igualdad nunca basta. El setup es un
retroceso de cierres dentro de un permiso direccional, no una inferencia de
compras institucionales, soporte oculto o flujo de órdenes.

Una secuencia extendida cuenta como un episodio, identificado por símbolo,
dirección y comienzo de la secuencia. Tras gatillo válido, el episodio queda
consumido aunque se rechace por costes, riesgo o ejecución. Después de consumirlo,
solo una **nueva** secuencia formada por completo después del cierre/rechazo y
cooldown puede autorizar otra entrada. No reusar la misma caída como tres señales.

### 4.4 RSI como experimento posterior

Ablaciones posibles, no acumulación inicial:

- PB1: gatillo de precio anterior.
- PB1-R: sustituir el gatillo por cruce de RSI: compra si
  `RSI_(t-1) <= 50` y `RSI_t > 50`; venta simétrica.
- PB1-PR: exigir precio y cruce en **la misma** vela cerrada.

Mantener setup, permiso, salidas y costes iguales. Empezar comparando el periodo
6 propuesto con pocos periodos vecinos preregistrados, sin buscar cada combinación
con ADX/EMA/sesión. Si el cruce ocurrió antes del gatillo, PB1-PR no debe reinterpretarlo
como simultáneo. Medir la señal que cada versión pierde, no solo su win rate.

### 4.5 Entrada

Orden de mercado en el primer tick disponible de la vela siguiente, dentro de la
sesión y antes del corte. Si hubo reinicio o hueco y esa vela ya se está formando,
no abrir una entrada de recuperación. Una solicitud por episodio; reconciliar un
resultado incierto con posiciones e historial antes de cualquier acción posterior.
Una posición simultánea propia por símbolo+Magic; sin órdenes pendientes en V1.

El límite de posiciones exige una cuenta demo dedicada o una política acordada
para posiciones manuales/otros EAs. Nunca modificar posiciones ajenas. Una solicitud
rechazada consume el episodio, no necesariamente todo el día; esta propuesta es
**distinta** de la oportunidad única diaria de Range Breakout.

### 4.6 Stop loss, objetivo y salida temporal

- Buy: `SL_raw = min(L_(t-p), ..., L_t) - b * ATR_a(t)`.
- Sell: `SL_raw = max(H_(t-p), ..., H_t) + b * ATR_a(t)`.
- Redondear al tick hacia fuera; comprobar lado, distancia mínima y volumen.
  Si no es ejecutable, rechazar; no ensancharlo arbitrariamente para forzar entrada.
- Riesgo de precio `d = abs(P_quote - SL)`; TP buy `P_quote + q*d`, sell
  `P_quote - q*d`, normalizado al tick. Misma regla en B0: extremo de su ventana
  `p` más la vela gatillo y el mismo buffer.
- SL y TP se envían inicialmente. Sin ajustes posteriores en este primer diseño.
  Un fill diferente altera R y riesgo realizados: registrar esa diferencia,
  sin prometer que el presupuesto es una pérdida máxima absoluta.
- Cerrar en el primero de SL, TP, `N_hold` velas M5 después de la entrada o fin
  de ventana operativa. El cierre temporal se intenta con el primer tick elegible;
  fallo o falta de ticks puede demorar su ejecución.

### 4.7 Sesiones y DST

Definir ventanas `[inicio, fin)` en zonas de referencia **Europe/London** o
**America/New_York**, y convertirlas por fecha a UTC y al servidor. Son identidades
de zona, no una capacidad automática garantizada de MQL5. Se necesita una tabla
histórica versionada de offsets/reglas, suministrada y verificada para el broker.
No asumir que Londres y Nueva York cambian DST el mismo día.

Primer estudio: ventanas de 2–4 horas dentro de las sesiones diurnas elegidas;
los límites exactos se acuerdan antes de examinar PnL. Es un rango experimental
por duración intradía, no una conclusión de R1. Registrar también todos los días
sin oportunidad. El cierre intradía debe preceder la pausa diaria real del símbolo,
consultada con SymbolInfoSessionTrade; esa API no proporciona por sí sola un
calendario DST histórico completo. [R1], [T9]

El día de límites diarios será el **día del servidor**, explícitamente registrado,
aunque las ventanas se definan en otra zona. No cruzar ese reinicio con una posición
abierta salvo cierre fallido: en tal caso mantener bloqueo hasta resolverla.
TimeGMT en tester no proporciona un UTC histórico independiente; no calcular el
offset pasado restando TimeCurrent y TimeGMT durante el backtest. [T4], [T5]

### 4.8 Spread y costes

Medir `spread_points = (Ask-Bid)/Point`, pero no fijar automáticamente 30 puntos
por herencia del otro EA. Con el Point observado de 0,01, 30 puntos son 0,30 de
precio; con otro Point, el significado cambia.

Propuesta: dos comprobaciones complementarias: techo absoluto `S_max` adaptado
a especificación/observaciones del broker y presupuesto de coste total relativo
al riesgo. Estimar `cost_R = (spread + comisión + slippage esperado, expresados
en dinero para el lote) / riesgo_inicial_dinero`. No contar dos veces el spread
si el simulador ya utiliza Bid/Ask. El umbral debe derivarse de costes observados
y del margen económico de la hipótesis, no de maximizar su backtest. Toda señal
rechazada debe quedar registrada para estudiar sesgo de selección.

### 4.9 Riesgo, límite diario y cooldown

- Riesgo monetario previsto: `balance_actual * r / 100`; no equity como base
  intercambiable sin cambiar la especificación.
- Lote con pérdida de una unidad calculada mediante OrderCalcProfit, símbolo
  activo y moneda de cuenta. Redondear hacia abajo; si queda debajo del mínimo,
  saltar la operación. Verificar margen, límites y costes además del riesgo al SL. [T7]
- Un solo lote inicial por episodio. Sin recuperar pérdidas aumentando `r`.
- Presupuesto diario `L_day`: fijarlo antes del experimento. Propuesta de unidad:
  `k_day` veces el riesgo nominal calculado sobre el balance al inicio del día.
- Contabilizar PnL diario realizado neto de comisión/swap más flotante de posiciones
  propias. Si `PnL_day <= -L_day`, bloquear entradas hasta el siguiente día e
  intentar cerrar solo las propias. No prometer respeto exacto del umbral con gaps.
- Límite `N_day` de intentos de entrada por día, persistente; una solicitud fallida
  cuenta como intento. Contar aparte setups, rechazos previos, solicitudes y fills.
  Nunca exigir mínimo diario.
- Cooldown `c` velas cerradas desde cierre o rechazo del episodio; después exigir
  una secuencia de retroceso completamente nueva. No medirlo por ticks ni
  reiniciarlo al cambiar el timeframe del gráfico.
- Restaurar límites e intentos tras reinicio mediante historia y persistencia
  aislada por estrategia/cuenta/símbolo/Magic. El tester debe aislar cada ejecución.

## 5. Evidencia, supuestos y parámetros pendientes

### 5.1 Separación de decisiones

| Tema | Respaldado por evidencia consultada | Supuesto P que necesita prueba | Todavía sin decidir |
| --- | --- | --- | --- |
| Horarios | R1/R2 muestran dependencia de sesión/mercado | Una ventana operativa mejora ejecución sin seleccionar ganadores ex post | Zona, límites, DST histórico del broker |
| Pullback | Fichas muestran su uso declarado; no causalidad ni ventaja probada | Su reanudación añade valor frente a B0 | `p`, EMA y estabilidad por dirección |
| RSI/ADX/M15 | APIs permiten calcularlos; eso no demuestra ventaja [T10] | Alguno aporta información incremental | Si se incluye alguno tras ablación |
| Datos | T1 distingue ticks y volumen real | OHLC/ticks bastan para este horizonte | Cobertura exacta y segundo broker |
| Costes | T2 permite simular demora con limitaciones | La expectativa neta sobrevive al coste observado adverso | Comisión, slippage, `S_max`, presupuesto en R |
| Riesgo | T6/T7 permiten conocer contrato y estimar pérdida | Pequeño riesgo facilita pruebas sin hacer rentable una señal mala | Capital, `r`, pérdida diaria tolerada |
| Frecuencia | Señales públicas tienen tasas distintas, algunas muy bajas | PB1 puede ofrecer varias oportunidades sin forzarlas | Tasa medida incluyendo días sin señal |
| Simplicidad | R3 explica riesgo de seleccionar entre muchas pruebas | Menos filtros mejora interpretabilidad; no garantiza ventaja | Presupuesto de experimentos y reserva OOS |

### 5.2 Rangos para explorar, no parámetros seleccionados

Todos son **P**, órdenes de magnitud para discutir y reducir antes de probar.
No vienen de un producto ni de una optimización. No hacer producto cartesiano de
esta tabla: elegir un punto de partida por interpretación temporal, registrar
unos pocos vecinos y estudiar una dimensión cada vez.

| Parámetro | Dominio provisional | Razón / qué falta |
| --- | --- | --- |
| EMA H1 `n` | 20–80 barras | Contexto de decenas de horas; no confundir horas cotizadas con días calendario; comparar estabilidad |
| Retroceso `p` | 2–4 velas M5 | Secuencia breve de 10–20 minutos; medir muestra y sensibilidad |
| ATR `a` y buffer `b` | `a` 10–20; `b` 0–0,2 ATR | Escala local y holgura pequeña; incluir buffer cero como control, respetando tick/stops |
| TP `q` | 1–2 R | Comparar distribuciones sin optimizar win rate aislado |
| Tiempo `N_hold` | 6–24 velas M5 | 30–120 minutos más corte de sesión; no derivado de señales comerciales |
| Cooldown `c` | 1–3 velas M5 | Evitar reentradas contiguas; mide pérdida de oportunidades y conserva episodio único |
| Riesgo `r` | 0,1–0,5% del balance | Presupuesto experimental conservador, no predictor de ventaja; depende de capital y lote mínimo |
| Presupuesto diario `k_day` | 2–4 riesgos nominales del inicio del día | Política de pérdida, no parámetro que deba maximizar retorno |
| Intentos máximos `N_day` | 2–4 | Techo operativo alrededor del objetivo de frecuencia; cero sigue siendo válido |
| RSI, si se investiga | 6 propuesto; vecinos 4–10, nivel 50 fijo | Sensibilidad posterior, no rejilla junto con todo lo anterior |
| `S_max` y coste máximo en R | Sin número seleccionado | Obtener distribución por sesión, contrato, comisión y deslizamiento; no inventar un umbral |
| Inicio/fin de sesión | Pendientes; duración orientativa 2–4 horas | Conocer calendario del servidor antes de elegir límites |

## 6. Especificaciones de la cuenta y riesgos MQL5

Los valores siguientes son **observaciones facilitadas por el usuario**, no
mediciones nuevas ni constantes universales. La fuente técnica de las propiedades
es MetaQuotes. [T6]

| Observado | Consulta futura obligatoria | Uso / precaución |
| --- | --- | --- |
| Digits 2; Point 0,01 | SYMBOL_DIGITS; SYMBOL_POINT | Formato y spread; no equivalen siempre al incremento de precio |
| Tick size 0,01 | SYMBOL_TRADE_TICK_SIZE | Normalizar SL/TP y precios |
| Tick value mostrado 1 | SYMBOL_TRADE_TICK_VALUE y variantes PROFIT/LOSS | No asumir moneda ni constancia; contrastar OrderCalcProfit |
| Contract size 100 | SYMBOL_TRADE_CONTRACT_SIZE y TRADE_CALC_MODE | Identificar valoración del contrato |
| Volumen 0,01–100; paso 0,01 | SYMBOL_VOLUME_MIN/MAX/STEP y LIMIT | Piso, techo y exposición permitida; no redondear arriba |
| No informado | STOPS_LEVEL, FREEZE_LEVEL, TRADE_MODE, FILLING_MODE, ORDER_MODE | Peticiones válidas y condiciones de modificación/cierre |
| No informado | Divisas de símbolo/cuenta, margen, sesiones y especificación de comisión | Conversión monetaria, pausas y costes |

Riesgos que deben resolverse antes del motor:

1. **Look-ahead multitemporal:** usar la H1/M15 incompleta al evaluar M5; probar
   mapeo por timestamp y cierre, no por índices iguales entre timeframes.
2. **Pivotes no causales:** fechar el swing en su extremo sin esperar confirmación.
3. **Datos insuficientes:** CopyRates/CopyBuffer parcial, handles inválidos,
   calentamiento, ticks ausentes y barras duplicadas deben bloquear señales.
4. **Fills irreales:** entrar al precio de cierre conocido, ignorar Bid/Ask o usar
   SL/TP de ticks sintéticos como si probaran ejecución real.
5. **Redondeos:** float, lotes mínimos y precio por dígitos en lugar de tick size.
6. **Tiempo:** offset histórico, semanas de DST desalineado, huecos de fin de
   semana, corte inclusivo/exclusivo y primera cotización posterior al cierre.
7. **Idempotencia:** muchos ticks, reinicios o timeframes no deben duplicar un
   episodio ni restablecer pérdidas/intentonas; separar día, setup y operación.
8. **Propiedad:** selección por símbolo no basta en hedging; identificar tickets
   y Magic; netting exige otra política y queda fuera hasta acordarla.
9. **Retcodes y fills parciales:** un bool favorable no confirma ejecución; no
   reenviar ciegamente ante timeout ni abrir un segundo lote para completar.
10. **Persistencia:** no compartir estado entre cuentas, variantes, símbolos o
    ejecuciones del tester. Reconciliar con posiciones/deals, no solo memoria.
11. **Noticias/datos externos:** no usar noticias revisadas, calendario actual,
    modelo actual ni etiquetas de régimen ajustadas con todo el histórico.
12. **Contabilidad:** una posición puede producir varios deals; comisiones,
    swaps y cierres parciales deben agregarse por posición sin duplicar riesgo.

## 7. Pruebas necesarias antes de escribir el motor de ejecución

En la etapa documental inicial ninguna de estas pruebas se había ejecutado.
La validación de lógica del scanner se registra en su especificación (sección 8);
las pruebas económicas de este protocolo siguen pendientes.

### A. Acuerdo y calidad de datos

- Fijar hipótesis, variables, métrica principal, calendario y número de variantes.
- Identificar histórico de ticks Bid/Ask, contrato, comisiones, cobertura y DST.
  Auditar huecos y calidad; no eliminar días malos por el resultado del sistema.
- Separar desarrollo, validación temporal y reserva final intacta por fechas,
  incluyendo episodios de mercado distintos. La duración exacta depende de
  cobertura y potencia; no elegir 2025 en adelante solo porque un vendedor lo hace.
- Estimar tamaño necesario con la variabilidad de días de entrenamiento y una
  mejora económica mínima acordada. No convertir «100 trades» en validación universal.

### B. Verificar la regla sin enviar órdenes

- Preparar ejemplos sintéticos de compra/venta, igualdad, retroceso extendido,
  cambio H1, rechazo y cooldown. Especificar a mano señales esperadas.
- Prueba de truncamiento: calcular hasta cada instante con solo datos conocidos;
  añadir futuro no debe cambiar una señal pasada.
- Comparar timestamps H1/M15/M5 y repetir con distinto timeframe del gráfico.
- Obtener un registro causal de oportunidades, también rechazadas, sin filtrar
  después por si habrían ganado. Una implementación diagnóstica futura de señales
  es una fase separada del motor de órdenes.

### C. Experimento posterior en MT5

- B0 y PB1 con ticks reales, mismos intervalos, riesgo, costes y salidas. Inspeccionar
  calidad y reglas de generación del tester. «Real ticks» no significa validación real. [T2], [T3]
- Usar comisión monetaria y Bid/Ask; evitar modo de beneficio solo en pips que
  omite componentes de coste. Comparar demora fija medida y escenarios adversos
  plausibles; no adoptar Random Delay como estimación exacta del broker. [T2]
- Reportar expectativa neta por operación y por día, exposición, drawdown,
  pérdidas extremas, MAE/MFE, retcodes, sensibilidad y distribución de frecuencia.
- Ablación secuencial de contexto H1, RSI, ADX y M15, conservando todos los intentos,
  incluso variantes perdedoras. Usar ventanas temporales y separación de operaciones
  que cruzan fronteras; ajustar transformaciones solo en entrenamiento.
- Repetir con un segundo feed/broker y parámetros vecinos preregistrados. Un
  resultado no reproducible no se corrige buscando un broker ganador después.
- Solo después, prueba forward demo prospectiva con configuración congelada y
  diario de diferencias de ejecución. No equivale a validación en cuenta real.

R3 motiva controlar selección entre pruebas; el protocolo anterior es una
propuesta propia y no afirma haber aplicado ya CSCV/PBO ni probado significancia.

## 8. Criterios objetivos para aprobar, rechazar o dejar inconclusa la hipótesis

**Propuesta de protocolo para acordar antes de ver resultados, no resultados actuales.**
Aprobar significa pasar al siguiente ensayo demo, nunca prometer rentabilidad.

1. **Integridad obligatoria:** cero señales cambiadas por añadir datos futuros,
   cero duplicados por reinicio, cero operaciones ajenas afectadas; todos los
   costes, rechazos y huecos identificados. Un fallo invalida el experimento.
2. **Métrica primaria:** media de PnL neto diario en R nominal de inicio de día,
   incluyendo ceros; comparación emparejada PB1 menos B0 en los mismos días.
   No seleccionar ganador por profit factor o win rate después de ver resultados.
3. **Evidencia positiva:** en reserva final, límite inferior de intervalo del 95%
   de la media neta PB1 > 0 y de la diferencia PB1–B0 > 0. Estimar incertidumbre
   por bloques temporales, con longitud seleccionada en desarrollo; corregir
   comparaciones si se incluyen múltiples variantes. Un único holdout consultado
   repetidamente deja de ser reserva intacta. [R3]
4. **Refutación/inconclusión:** si el límite superior de esperanza neta es <= 0,
   rechazar la ventaja positiva bajo ese diseño; si el intervalo abarca cero,
   clasificar como inconcluso. Si PB1 no supera B0, no atribuir ventaja al pullback;
   B0 puede investigarse por separado si cumple sus propias pruebas.
5. **Robustez económica:** esperanza neta puntual positiva en cada feed y escenario
   de coste adverso preregistrado y en los vecinos de parámetros acordados. Si el
   resultado depende de un único punto óptimo, no aprobar. No añadir escenarios
   favorables ni quitar desfavorables después.
6. **Riesgo:** drawdown observado y pérdida diaria compatible con el presupuesto
   que el usuario acepte antes de pruebas; ausencia de apalancamiento acumulativo.
   El valor máximo tolerado aún debe acordarse, por lo que esta puerta no puede
   evaluarse hoy. Mostrar también pérdidas que excedan el SL previsto por gaps.
7. **Estabilidad temporal:** reportar resultados por ventanas preregistradas y
   sensibilidad al retirar bloques rentables. No aprobar una ventaja sostenida
   únicamente por el bloque elegido retrospectivamente; límites de concentración
   se fijan antes de abrir la reserva.
8. **Frecuencia:** medir tasa total, por sesión y proporción de días vacíos. Estar
   por debajo de 1–3 no refuta rentabilidad, pero sí puede incumplir una preferencia
   operativa. Decidir entonces si se acepta menor frecuencia; no forzar entradas.
9. **Paso a demo:** se requiere concordancia causal y una envolvente de costes
   acordada antes de observar fills futuros. Si la ejecución sale de esa envolvente,
   detener la promoción y revisar la hipótesis, sin reoptimizar sobre la reserva.

## 9. Preguntas originales (resoluciones en sección 11)

1. ¿La prioridad es sencillez/robustez o aproximarse a 1–3 oportunidades? ¿Se acepta
   una tasa menor si la evidencia es mejor?
2. ¿Broker, servidor, tipo de cuenta, moneda, balance demo y comisión exactos?
   ¿Hay documentación del offset y de sus cambios DST históricos?
3. ¿Se investigará primero Londres o Nueva York? ¿Cuáles serán apertura, cierre
   y pausa diaria en la zona elegida y en el servidor?
4. ¿Aceptamos H1 como único permiso inicial, M15 solo diagnóstico y RSI/ADX
   aplazados hasta una prueba de aportación incremental?
5. ¿Qué riesgo por operación, presupuesto diario, drawdown máximo e intentos
   diarios toleramos? ¿La cuenta será exclusiva para este EA?
6. ¿Qué periodos/feeds están disponibles y cuál queda reservado sin consultar?
   ¿Qué presupuesto máximo de variantes y criterio de potencia usamos?
7. ¿Aceptamos TP fijado con la cotización previa, con diferencias por slippage,
   para evitar modificaciones posteriores? ¿Cómo se tratará un fill sin SL confirmado?
8. ¿Noticias se incluyen inicialmente con costes realistas o se acuerda una
   exclusión causal fija? Si se excluyen, ¿qué archivo histórico se usará?

## 10. Estado y trazabilidad

En la etapa documental original, los documentos se redactaron sin modificar `.mq5`, `.ex5`, README ni la estrategia
previa. No se compilaron archivos, ejecutaron backtests, abrieron operaciones o
modificó el historial Git. La implementación requiere resolver las preguntas y
registrar el experimento; esta investigación no selecciona parámetros finales.

**Fuentes directas, todas consultadas 2026-09-17:** registro completo y evidencia
por producto en el documento de mercado. A continuación, referencias técnicas y
académicas usadas en esta decisión.

[R1]: https://www.clintonwatkins.com/publications/2018-jcm-Intraday-seasonality-microstructure-platinum-gold/index.html
[R2]: https://acfr.aut.ac.nz/__data/assets/pdf_file/0008/686816/4a-Z-Ivy-Zhou.pdf
[R3]: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
[T1]: https://www.metatrader5.com/en/terminal/help/trading_advanced/price_data
[T2]: https://www.metatrader5.com/en/terminal/help/algotrading/testing
[T3]: https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation
[T4]: https://www.mql5.com/en/docs/dateandtime/timecurrent
[T5]: https://www.mql5.com/en/docs/dateandtime/timegmt
[T6]: https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants
[T7]: https://www.mql5.com/en/docs/trading/ordercalcprofit
[T8]: https://www.mql5.com/en/docs/series/copybuffer
[T9]: https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade
[T10]: https://www.mql5.com/en/docs/indicators/irsi
[T11]: https://www.mql5.com/en/docs/indicators/iadx

## 11. Decisiones aprobadas y fase scanner

**Registro 2026-09-17 — P aprobadas por el usuario, no evidencia de rentabilidad.**
Esta sección prevalece sobre los pendientes y rangos exploratorios anteriores;
se conservan como trazabilidad de la propuesta inicial y del futuro motor.

- Sencillez, trazabilidad y robustez tienen prioridad. Se acepta menos de 1–3
  operaciones diarias; nunca se fuerza frecuencia.
- Candidato PB1, control B0, contexto H1, detección M5 cerrada. M15 queda para
  diagnóstico posterior; RSI y ADX, para pruebas de aportación incremental.
- Nueva York es la sesión inicial; [08:00,12:00) America/New_York es una ventana
  **provisional elegida antes de observar PnL**, no una conclusión empírica.
  Se registrarán oportunidades fuera de ventana, marcadas no operables.
- Sin filtro inicial de noticias. Conservar tiempos servidor/UTC/NY y hora de
  observación para análisis posterior causal; falta confirmar calendario del broker.
- Cuando exista ejecución: cuenta demo exclusiva, una posición propia por
  símbolo+Magic, riesgo propuesto 0.25% del balance actual; presupuesto diario
  0.75% del balance inicial del día (tres riesgos nominales), máximo tres intentos.
- Gestión futura: SL inicial, TP fijo en R y salida temporal. Sin trailing,
  break-even, grid, martingala, DCA, recuperación, piramidación ni IA.
- Se mantiene íntegro el criterio estadístico de sección 8. Una muestra insuficiente
  puede producir **inconcluso** y no autoriza reducir el criterio después de ver datos.
- La primera implementación es exclusivamente un **Signal Scanner sin trading**,
  separado del EA anterior y de Range Breakout. No implementa riesgo ni ejecución.
- Defaults de ingeniería, no optimizados ni validados: EMA H1 50, PullbackBars 3,
  BreakoutLookback 3, CooldownBars 2; rupturas estrictas, igualdad rechazada;
  B0/PB1 simultáneos solo para observación comparativa.

Las reglas de estado, datos, sesión, persistencia y aceptación se fijan antes del
código en [la especificación del scanner](../specs/XAUUSD_INTRADAY_SIGNAL_SCANNER_SPEC.md).
Las preguntas 1, 3 (zona/ventana), 4, 5 (riesgo propuesto/exclusividad) y 8 quedan
resueltas arriba. Siguen pendientes calendario histórico del broker, costes,
cobertura/feeds, reserva temporal, potencia, presupuesto de variantes, drawdown
máximo y detalles de SL/TP/salida del futuro motor. Ninguno autoriza operaciones
ni optimización durante esta fase. Las pruebas de lógica del scanner no son las
pruebas económicas todavía pendientes de las secciones 7–8.
