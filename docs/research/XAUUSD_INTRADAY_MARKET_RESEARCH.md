# Investigación pública: EAs intradía para XAUUSD

**Consulta:** 2026-09-17. **Estado:** investigación documental, sin pruebas propias.
**Rama comprobada:** `research/intraday-regime-v1`, inicialmente limpia.

## 1. Resumen ejecutivo

Se investigaron **10 productos identificados por su ID oficial**, incluidos los siete nombres sugeridos. Se añadieron reversión a la media, selección de regímenes y breakout de sesión para ampliar la comparación. Esto es una muestra intencional de arquitecturas, no un censo del Market ni una clasificación de productos por rentabilidad.

**Hallazgo principal:** la descripción de la señal y la viabilidad de ejecutarla son cuestiones distintas. Las señales enlazadas de ThunderGold y TwisterPro muestran tenencias medias de 49 y 28 segundos, respectivamente, aunque sus fichas recomiendan M15. Esa diferencia hace esencial medir costes y ejecución antes de diseñar filtros adicionales. Son estadísticas de cuentas enlazadas, no una auditoría del ejecutable. [S1], [S5], [P1], [P4]

**Recomendación de investigación:** un módulo original de continuación tras pullback, con reglas de precio cerrado, contexto direccional sencillo, una posición y riesgo acotado. Compararlo con breakout de estructura sin pullback. No comenzar con un selector completo de regímenes, IA, recuperación ni volumen delta de procedencia desconocida. La clasificación de la sección 7 prioriza facilidad de refutación y ejecución; no estima retornos.

**Evidencia más débil:** rentabilidad extrapolada desde fichas comerciales, muestras recientes, parámetros ocultos y señales inaccesibles. GoldenShot ofrece una descripción relativamente detallada, pero la cuenta enlazada mostraba solo 21 operaciones y una advertencia de muestra insuficiente. Neo Delta y la señal de Lizard no devolvieron una ficha de señal disponible. [S2], [S7], [S6]

La meta de 1–3 oportunidades válidas por día **no queda demostrada** por estas fuentes. Debe medirse incluyendo días con cero señales; nunca convertirse en una cuota de operaciones.

## 2. Pregunta e hipótesis

**Pregunta:** ¿qué reglas públicas permiten diseñar un sistema intradía de XAUUSD interpretable cuya posible ventaja sobreviva a costes, cambios de sesión y diferencias de broker?

**Hipótesis falsable propuesta, aún no comprobada:** dentro de un contexto direccional definido causalmente, la reanudación tras un retroceso corto tiene una distribución de rendimientos netos favorable frente a una entrada de continuación sin retroceso, con igual riesgo y protocolo de ejecución. La formalización y los criterios de rechazo están en [la decisión V1](XAUUSD_INTRADAY_V1_DECISION.md).

## 3. Método y límites de evidencia

Etiquetas aplicadas a ambos documentos:

- **H — Hecho verificable:** contenido visible, fecha, versión, existencia de un enlace o estadística que muestra una página. No equivale a verificar el algoritmo.
- **V — Afirmación del vendedor:** funcionamiento, protecciones o rendimiento declarados; no ejecutados ni auditados aquí.
- **I — Inferencia del investigador:** consecuencia razonada, identificada como tal, no medición.
- **D — Desconocido:** no consta, no pudo consultarse o no puede atribuirse al producto.
- **P — Propuesta propia:** elección experimental o de ingeniería, pendiente de validación.

Procedimiento: buscar nombres; abrir fichas oficiales; distinguir el cuerpo del producto de las recomendaciones de otros EAs; seguir los enlaces de señales desde ese cuerpo; consultar un manual público; contrastar con documentación técnica y estudios primarios. Las reseñas, ventas, precios, premios y afirmaciones de usuarios no se usan como prueba de ventaja. No se compraron productos, descargaron ejecutables, descompilaron archivos ni intentaron reconstruir parámetros privados.

**Advertencias de interpretación:**

1. Las fuentes son dinámicas y algunas respuestas están en caché. Los números son una instantánea de consulta, no un conjunto sincronizado de datos.
2. Una fecha de publicación del producto no es el comienzo de un historial financiero. La antigüedad de una cuenta tampoco demuestra uso continuo de la versión actual.
3. Un enlace oficial demuestra asociación declarada por el vendedor. No demuestra exclusividad del EA, ausencia de intervención manual o correspondencia de parámetros durante todo el historial.
4. Los agregados no permiten reconstruir simultaneidad, colas de pérdidas, slippage o número de episodios independientes. No se descargó un ledger completo.
5. Los resultados de futuros/ETF no se transfieren automáticamente al CFD OTC XAUUSD de este broker.
6. Hay sesgo de selección y supervivencia: se ven vendedores/productos disponibles o indexados. No conocemos todos los productos retirados ni las pruebas fallidas.
7. No se ejecutaron backtests, compilaciones ni operaciones. Nada aquí valida la ventaja propuesta.

## 4. Comparativa de diez EAs

### 4.1 Identidad y lógica declarada

Todas las características operativas de esta tabla son **V**, salvo identidad, publicación y versión, que son **H** de la ficha. **D** significa no determinado, no ausencia de la característica. Todos son productos MT5. El instrumento indicado es una recomendación comercial.

| ID / producto | Publicación; versión observada | Instrumento / timeframe | Entrada y conceptos públicos | Sesión / tipo de orden |
| --- | --- | --- | --- | --- |
| [P1 ThunderGold Scalper][P1] | 2026-07-31; 1.3 | XAUUSD/GOLD; M15 | Estructura, tendencia, momentum, vela y volumen; fórmula privada | Horas D; filtros noticias/cierre; orden D en descripción principal |
| [P2 GoldenShot][P2] | 2026-08-28; 1.25 | XAUUSD; gráfico cualquiera, marcos internos | Dos módulos: pullback y momentum; estructura y volatilidad | Market; ventanas por día y DST; detalle operativo en manual M1 |
| [P3 De Moore][P3] | 2026-08-27; 2.27 | XAUUSD/GOLD; M5 | Tendencia, price action, análisis multitemporal | Horas y orden D; advierte diferencias por filtro de noticias no aplicado en tester |
| [P4 TwisterPro Scalper][P4] | 2026-02-24; 3.20 | XAUUSD; M15 | Scalping con cinco validaciones no explicadas; dos modos | Sesión/orden D; modo 1 pocas operaciones semanales, modo 2 más activo |
| [P5 Smart Gold Hunter][P5] | 2026-03-25; 3.5 | XAUUSD; perfil prima sobre gráfico | Breakout según respuesta pública del vendedor; perfiles scalper/swing | Buy/Sell Stop declarados por vendedor en comentarios; horas exactas D |
| [P6 Lizard][P6] | Ficha ES: 2026-05-09; 1.93 | XAUUSD; H1 | Seis módulos de ruptura de swings | Stop pendientes; cobertura intradía y varios días; horas D |
| [P7 Neo Delta][P7] | 2026-09-06; 1.21 | XAUUSD; módulos M5/M20 | Momentum de delta de volumen y filtro ML; fuente/metodología delta D | Filtro noticias USD; horas y market/pending D |
| [P8 Gold Zilla AI MT5][P8] | 2026-03-26; 1.8 | XAUUSD CFD; gráfico M5, módulos M5–H1 | Cinco estrategias y selección de régimen; Grok con búsqueda web para riesgo | Horas y market/pending D |
| [P9 Pack Invest Mean Reversion EA][P9] | 2026-04-22; 1.9 | XAUUSD; tabla M5, encabezado menciona H1 | Cierre fuera de Bollinger + pin bar; filtros de tendencia/volatilidad | Sesión y tipo de orden D |
| [P10 Range Breakout EA with Range Filters][P10] | 2024-08-25; 5.20 | XAUUSD, USDJPY, BTCUSD, US30, DE40; sin marco fijo | Rango de sesión y expansión posterior; filtro interno | Transición Asia/Londres declarada; cierre intradía; orden D; servidor GMT+2/+3 según vendedor |

**Acceso irregular P6:** la ficha inglesa mostraba producto no disponible para compra; la española conservaba descripción y enlace. Registramos ambas respuestas, sin atribuir la retirada a fraude, resultados o motivo alguno. La descripción ES puede estar desactualizada. [P6], [P6EN]

### 4.2 Salidas, exposición y riesgo

**V** en toda la tabla. No se confirma el comportamiento del binario. «No grid» no prueba por sí solo ausencia de aumento de lotaje.

| Producto | SL / TP / salida | Posiciones simultáneas | Riesgo y escalado |
| --- | --- | --- | --- |
| P1 | SL corto, TP y trailing | D | Fijo o porcentual; declara no grid; desaconseja recuperar aumentando lote; otras formas ocultas D |
| P2 | SL del broker, TP, trailing/protecciones por módulo | Una global | Fijo o %; niega grid, martingala, promediado y escalado |
| P3 | Especificación de distancias/salidas D | D | Fórmula D; «riesgo controlado» no verifica ausencia de recuperación |
| P4 | SL/TP definidos; modo 2 reduce SL | D | No grid declarado; mecanismo exacto de tamaño y escalado D |
| P5 | SL/TP, trailing y break-even opcional | Entrada única declarada | Sin recuperación/grid/martingala declarados; opción de ocultar SL inicial merece revisión |
| P6 | SL/TP, trailing y break-even por módulo | Total D; seis módulos independientes | Riesgo ponderado por módulo; niega grid/martingala/promediado |
| P7 | SL fijo o Bollinger, TP y trailing | Límite agregado D | Fijo/%; recuperación opcional desactivada por defecto: agrega posición de doble lote a una perdedora |
| P8 | SL declarado; TP/salida exactos D | D | Ajuste dinámico; ausencia de grid/recuperación D; correlación baja entre módulos solo afirmada |
| P9 | SL/TP por ATR y trailing | Una | Niega grid/martingala; porcentaje orientativo declarado; detalles de escalado D |
| P10 | Cierre intradía; distancias SL/TP D en cuerpo consultado | D, admite varios mercados | Fijo/porcentaje/perfiles; niega grid/martingala; promediado D |

### 4.3 Señales enlazadas: muestra observable, frecuencia y duración

**H:** estos valores son los campos mostrados por MQL5 Signals el 2026-09-17. No los hemos recalculado. «Trades/week» no es una estimación nuestra ni tiene aquí un horizonte estadístico documentado. No se divide por cinco para prometer oportunidades diarias. La duración del gráfico y la de la posición son magnitudes distintas.

| Producto / señal | Enlace y atribución | Antigüedad mostrada | Trades mostrados | Trades/week; tenencia media | Limitación principal |
| --- | --- | --- | --- | --- | --- |
| P1 / ThunderGold Scalper | [S1][S1], enlazada desde P1 | 17 semanas | 142 | 11; 49 segundos | MQL5 advierte riesgo de slippage al copiar; historial anterior a publicación no certifica versión |
| P2 / GoldenShot High Risk | [S2][S2], desde P2 y M1 | 4 semanas | 21 | 5; 12 minutos | Aviso de pocos trades y cuenta reciente; perfil High Risk |
| P3 / De Moore ICM | [S3][S3], desde P3 | 13 semanas | 189 | 5; 39 minutos | Historial de cuenta no identifica versiones ni configuración histórica |
| P4 / Mode 1 | [S4][S4], desde P4 | 29 semanas | 79 | 3; 1 minuto | Muestra limitada; pocas operaciones semanales |
| P4 / Mode 2 | [S5][S5], desde P4 | 16 semanas | 70 | 5; 28 segundos | No agregar con modo 1 como si fueran una estrategia |
| P5 / Ultimate Scalper | [S6a][S6a], desde P5 | 28 semanas | 188 | 3; 51 segundos | Perfil concreto; no representa todos los perfiles |
| P6 / Normal Standard | [S6][S6], desde ficha ES | D | D | D | Página de señal no encontrada; descripción solo indica horizonte intradía/multidía |
| P7 / enlace Live Signal | [S7][S7], desde P7 | D | D | D | Señal no encontrada; no sustituirla por una cuenta de nombre parecido |
| P8 / Medium Risk | [S8][S8], desde P8 | 37 semanas | 375 | 12; 4 horas | Cuenta agregada; no separa contribución causal de IA/módulos |
| P9 | No se verificó enlace en descripción | D | D | D | Solo afirmaciones y backtests publicados por vendedor; no muestra auditada |
| P10 / Range Breakout EA Live | [S10][S10], desde P10 | 94 semanas | 1.920 totales; distribución XAUUSD 287 | 19; 7 horas, ambos agregados | Multiactivo: no asignar estas tasas a oro; Weeks y Started no son el mismo campo |

El campo Started de S10 mostraba 2026-01-01 y, a la vez, 94 semanas: no inferimos una serie continua de esa combinación de metadatos. Obtener fechas de trades y registro de alta sería necesario para reconciliarla. La antigüedad de producto, cuenta y publicación de señal se mantienen separadas. [S10]

### 4.4 Transparencia, sensibilidad y principios que sí podemos estudiar

**I**: valoraciones propias basadas en las fichas y señales anteriores; no acusaciones ni recomendaciones de compra. A = alta, M = media. La sensibilidad incluye spread, comisión, slippage, latencia y feed; no se midió experimentalmente.

| Producto | Transparencia de reglas | Sensibilidad probable y alerta | Principio público para un desarrollo independiente |
| --- | --- | --- | --- |
| P1 | Media-baja: enumera factores, no reglas | A, por tenencia corta y SL corto; pesos ocultos | Separar tendencia, señal y filtro de costes |
| P2 | Media-alta en operación, media en señal | M/A; pequeña muestra y muchas protecciones ajustadas | Pullback y momentum evaluados por separado |
| P3 | Baja | M/A; filtro de noticias distinto entre tester y ejecución | Contexto direccional + confirmación de precio |
| P4 | Baja: validaciones privadas | A, en especial segundos del modo 2 | Estudiar selectividad sin asumir que cinco filtros añaden información |
| P5 | Media en ejecución, baja en gatillo | A en Ultimate Scalper; SL inicialmente oculto opcional | Breakout con presupuesto explícito de ejecución |
| P6 | Media, con problema de acceso | M/A; concurrencia de módulos y muestras D | Swings causales sin pivotes que miren el futuro |
| P7 | Media en recuperación, baja en señal/ML | A/D; delta sin procedencia y recuperación duplicando lote | Momentum de precio; volumen solo si su dato es interpretable |
| P8 | Baja en clasificador | M/A; modelo externo, estabilidad histórica y dependencia web D | Evaluar módulos independientes antes de seleccionarlos |
| P9 | Media: regla inicial reconocible | M/A; inconsistencia M5/H1 y ajustes periódicos | Reversión condicional, con SL, sin promediar |
| P10 | Media en concepto | M; DST, parámetros internos y mezcla multiactivo | Rango por sesión y salida temporal, sin copiar presets |

Estas ideas generales no autorizan copiar código, pesos, modelos entrenados, marcas o documentación. Nuestro diseño se expresa con fórmulas propias y datos accesibles; no se intenta deducir el motor privado.

## 5. Literatura y documentación: qué respaldan y qué no

| Fuente primaria | Hallazgo o capacidad documentada | Límite para esta investigación |
| --- | --- | --- |
| [R1 Iwatsubo, Watkins y Xu, 2018][R1] | El resumen publicado por un autor describe diferencias intradía de microestructura entre futuros de oro/platino en Tokio y Nueva York | Se consultó el resumen, no se reprodujeron resultados. No prueba una EMA o entrada M5 rentable en CFD |
| [R2 Bouri, Ma, Xu y Zhou, working paper][R2] | Estudio de metales chinos con datos de un minuto: cambia la predictibilidad intradía tras introducir negociación nocturna | Oro comparte estudio con otros metales; mercado y mecanismo distintos. No trasladar ventanas ni coeficientes al broker |
| [R3 Bailey et al., 2015, preprint][R3] | Analiza selección de estrategias y probabilidad de sobreajuste de backtests | Fundamenta controlar número de intentos; no demuestra qué módulo tiene ventaja |
| [T1 Datos de precios MT5][T1] | Distingue tick volume de volumen de transacciones; gráficos OTC se forman con Bid | Tick volume del broker no identifica universalmente compras/ventas agresoras ni volumen centralizado |
| [T2 Tester][T2] y [T3 ticks][T3] | Documentan ticks reales/generados y simulación de demora | Son simulaciones; no auditan profundidad/liquidez ni garantizan fills reales. Verificar cobertura y modelado |
| [T4 TimeCurrent][T4] y [T5 TimeGMT][T5] | Tiempo recibido del servidor; TimeGMT en tester equivale al tiempo simulado del servidor | No recuperar DST histórico con el offset de hoy ni con la hora de Windows |

**Interpretación I:** sesiones y costes merecen controles desde el principio; el motor de señal debe justificar su valor aparte. Ninguna fuente revisada demuestra que H1+M15+ADX+RSI(6)/50 constituya una ventaja conjunta. Tampoco confirma que cada mercado lateral revierta antes de alcanzar un SL.

**Manual contrastado M1:** GoldenShot distingue unidades propias de precio y puntos del broker, permite mínimo de volumen bajo ciertas condiciones y detalla ventanas ajustadas por DST. Son decisiones del vendedor, no nuestros defaults. Para nuestro sistema se propone saltar operaciones inferiores al volumen mínimo seguro, y versionar el calendario horario en lugar de asumir un GMT fijo. [M1]

## 6. Patrones y señales de alerta

- **H/V:** se repiten tendencia, estructura, volatilidad y filtros de costes; faltan frecuentemente fórmulas de señal y registros por versión. Las tablas 4.1–4.4 documentan el alcance de cada caso.
- **I:** una posición y SL facilitan medir exposición, pero no prueban esperanza positiva ni pérdida máxima garantizada ante gaps.
- **I:** muchos filtros del mismo precio pueden reducir muestra y retrasar entrada sin añadir información independiente; exigir ablación antes de incorporarlos.
- **H/V:** P7 declara recuperación con doble lote aun distinguiéndola de una cadena de martingala. Se excluye por aumento de exposición a pérdidas, cualquiera que sea la etiqueta. [P7]
- **I:** no confundir ausencia de noticias históricas, sesiones recortadas ex post o parámetros revisados tras pérdidas con una prueba fuera de muestra intacta. P3 declara una diferencia de filtro entre tester y vivo; P9 declara reajustes periódicos. [P3], [P9]
- **I:** una promoción, alto porcentaje ganador o reseñas no sustituyen distribución completa, costes y comparación con una regla nula. No se usa ninguno como puntuación.
- **H/I:** en P8 la integración web/LLM declarada añade un problema de reproducción temporal: noticias o respuestas actuales no pueden insertarse retrospectivamente en un backtest. [P8]
- **H:** se intentó abrir Gold Reversion Gate, ID 196448: el buscador devolvió texto, pero las aperturas EN y ES fallaron. No se incluyó como undécimo producto ni se extrajeron resultados. [X1]

## 7. Familias: puntuación y clasificación

**Juicio de diseño I/P, no evidencia de rentabilidad.** Todos los criterios usan 1–5, mayor es mejor. 1 = muy desfavorable/incierto; 3 = viable con limitaciones; 5 = favorable para un experimento simple. Igual ponderación; total máximo 50. Diferencias pequeñas no son estadísticamente significativas. Cambiar un punto por criterio puede alterar el orden: no convertir la suma en certeza.

- C: claridad/programabilidad. F: compatibilidad potencial con varias oportunidades sin exigirlas.
- R: robustez conceptual. E: tolerancia a ejecución/costes. B: independencia del broker.
- O: bajo riesgo de sobreoptimización. D: disponibilidad de datos realistas.
- S: facilidad de SL definido. U: compatibilidad con una posición. X: explicación falsable de la ventaja.

| Puesto / familia | C | F | R | E | B | O | D | S | U | X | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1. Tendencia tras pullback | 5 | 4 | 4 | 4 | 4 | 4 | 5 | 5 | 5 | 4 | 44 |
| 2. Breakout de sesión/estructura | 5 | 3 | 4 | 3 | 4 | 4 | 5 | 5 | 5 | 4 | 42 |
| 3. Expansión de momentum/volatilidad | 5 | 4 | 4 | 3 | 3 | 3 | 5 | 5 | 5 | 4 | 41 |
| 4. Reversión en lateral | 4 | 4 | 3 | 3 | 3 | 3 | 5 | 5 | 5 | 3 | 38 |
| 5. Múltiples regímenes | 2 | 4 | 3 | 3 | 3 | 1 | 4 | 5 | 5 | 3 | 33 |
| 6. Volumen/tick volume | 3 | 3 | 3 | 2 | 1 | 3 | 2 | 5 | 5 | 3 | 30 |
| 7. Scalping de segundos | 4 | 2 | 2 | 1 | 1 | 2 | 2 | 4 | 5 | 2 | 25 |

### Justificación de cada puntuación

1. **Pullback:** C5: cierres y extremos programables; F4: admite varios episodios, tasa desconocida; R4: continuidad es hipótesis razonable, no probada aquí; E4: evita exigir segundos, sin inmunidad a costes; B4: usa precios comunes pero diferentes feeds cambian velas; O4: pocos parámetros si omitimos filtros; D5: OHLC y ticks disponibles en MT5; S5: extremo del retroceso; U5: serializable; X4: compara reanudación con no-pullback. Apoyo contextual R1/R2; formulación propia, no resultado de esos estudios.
2. **Breakout:** C5: máximo/mínimo pasado inequívoco; F3: rango de sesión ofrece pocas ventanas, estructura permite más; R4: hipótesis de expansión comprobable; E3: gaps y entrada tras expansión encarecen; B4: OHLC común con horarios distintos; O4: pocos grados de libertad; D5: datos estándar; S5: nivel o distancia explícita; U5: sencillo serializar; X4: medir continuación frente a ruptura fallida. P10 ilustra el concepto, no demuestra su ventaja.
3. **Momentum:** C5: retorno/ATR cuantificables; F4: varios episodios posibles, sin tasa asegurada; R4: existe literatura contextual de predictibilidad; E3: señal suele coincidir con expansión del coste; B3: cola de ticks más sensible al feed; O3: umbrales y ventanas añaden búsqueda; D5: OHLC/ticks; S5: ATR/extremo definido; U5: una entrada por episodio; X4: persistencia frente a agotamiento. R2 no valida nuestros horizontes.
4. **Reversión:** C4: desvío claro, lateralidad menos clara; F4: puede haber varios excesos, sin promesa; R3: una tendencia rompe el supuesto local; E3: objetivos cercanos pesan más en costes; B3: cotizaciones extremas difieren; O3: bandas/régimen/salida crean grados de libertad; D5: precios disponibles; S5: SL obligatorio aunque sea tocado; U5: no necesita promediar; X3: necesita explicar por qué el exceso es transitorio. P9 aporta reglas, no prueba causal.
5. **Multirrégimen:** C2: clasificación y arbitraje de módulos complican; F4: amplía cobertura potencial; R3: depende de estabilidad del clasificador; E3 y B3: hereda módulos/feeds; O1: gran espacio de selección; D4: OHLC basta para versión sencilla, no para toda señal externa; S5: puede imponer SL; U5: un árbitro puede serializar; X3: hay que probar ventaja incremental de clasificar. P8 ejemplifica complejidad declarada; R3 justifica cautela metodológica.
6. **Volumen:** C3: contador simple, interpretación compleja; F3: por medir; R3: actividad podría informar, no identifica necesariamente flujo; E2: depende de recepción de ticks; B1: proveedor específico; O3: normalización/lookbacks añaden búsqueda; D2: no existe delta centralizado garantizado del CFD; S5 y U5: compatibles por diseño; X3: distinguir actividad de agresión. T1 sostiene la distinción; P7 no resuelve procedencia de su delta.
7. **Segundos:** C4: reglas simples posibles; F2: frecuencia alta potencial no equivale a oportunidades económicas; R2: margen pequeño ante fricciones; E1 y B1: ejecución/feed dominantes; O2: optimización puede explotar el simulador; D2: ticks no incluyen todo el proceso de llenado; S4: SL definido, ejecución difícil de acotar; U5: serializable; X2: ventaja exige explicar microestructura. S1/S5 muestran horizontes; T2 limita lo inferible del tester.

## 8. Implicaciones para nuestro EA

1. Conservar Range Breakout como experimento separado; no copiar ni sobrescribir sus reglas/documentos.
2. Diseñar un baseline mínimo y registrar señales rechazadas, exposición y costes en unidades de riesgo.
3. M15 puede registrarse como contexto para análisis, sin exigir inicialmente concordancia H1+M15.
4. RSI(6)/50, ADX y tick volume son candidatos de ablación, no confirmaciones obligatorias por defecto.
5. Primero comprobar causalidad, datos y tamaño mínimo de operación; después estudiar sensibilidad.
6. La decisión de avanzar se basa en rendimiento neto fuera de muestra, estabilidad y ejecución, nunca en semejanza con un producto.

## 9. Registro de fuentes

**Todas consultadas o intentadas el 2026-09-17.** P = ficha; S = señal; M = manual; R = estudio; T = documentación. Enlaces directos en cada fila. Las páginas primarias se resumen, sin citas extensas.

| ID | Fuente / acceso | Consulta |
| --- | --- | --- |
| P1 | [ThunderGold Scalper, 188424][P1], ficha accesible | 2026-09-17 |
| P2 | [GoldenShot, 185207][P2], ficha accesible | 2026-09-17 |
| P3 | [De Moore, 189042][P3], ficha accesible | 2026-09-17 |
| P4 | [TwisterPro Scalper, 166740][P4], ficha accesible | 2026-09-17 |
| P5 | [Smart Gold Hunter, 170050][P5], ficha y respuesta indexada del vendedor | 2026-09-17 |
| P6/P6EN | [Lizard ES][P6] accesible; [EN][P6EN] mostraba indisponibilidad | 2026-09-17 |
| P7 | [Neo Delta, 191042][P7], ficha accesible | 2026-09-17 |
| P8 | [Gold Zilla AI MT5, 155855][P8], ficha accesible | 2026-09-17 |
| P9 | [Pack Invest Mean Reversion EA, 174110][P9], ficha accesible | 2026-09-17 |
| P10 | [Range Breakout EA with Range Filters, 122237][P10], ficha accesible | 2026-09-17 |
| M1 | [GoldenShot, manual v1.25 de Adam Hrncir][M1], público y enlazado por P2 | 2026-09-17 |
| S1 | [ThunderGold, 2384469][S1], accesible | 2026-09-17 |
| S2 | [GoldenShot High Risk, 2387381][S2], accesible | 2026-09-17 |
| S3 | [De Moore ICM, 2382941][S3], accesible | 2026-09-17 |
| S4/S5 | [Twister modo 1][S4] / [modo 2][S5], accesibles | 2026-09-17 |
| S6a | [Smart Gold Hunter Ultimate Scalper, 2365400][S6a], accesible | 2026-09-17 |
| S6/S7 | [Lizard, 2372821][S6] / [Neo Delta, 2389995][S7], no encontradas | 2026-09-17 |
| S8 | [GoldZILLA Medium Risk, 2362448][S8], accesible | 2026-09-17 |
| S10 | [Range Breakout EA Live, 2271995][S10], accesible | 2026-09-17 |
| R1 | [Iwatsubo, Watkins, Xu (2018), resumen del autor][R1] | 2026-09-17 |
| R2 | [Bouri, Ma, Xu, Zhou, Night trading momentum…][R2], PDF académico, versión de trabajo; año no confirmado en portada | 2026-09-17 |
| R3 | [Bailey, Borwein, López de Prado, Zhu (2015), Probability of Backtest Overfitting][R3], preprint del autor | 2026-09-17 |
| T1 | [MetaTrader 5: datos de precios][T1] | 2026-09-17 |
| T2/T3 | [Strategy Testing][T2] / [Real and Generated Ticks][T3] | 2026-09-17 |
| T4/T5 | [TimeCurrent][T4] / [TimeGMT][T5] | 2026-09-17 |
| T6/T7 | [Propiedades del símbolo][T6] / [OrderCalcProfit][T7] | 2026-09-17 |
| T8/T9/T10 | [CopyBuffer][T8] / [SymbolInfoSessionTrade][T9] / [iRSI][T10] | 2026-09-17 |
| T11 | [iADX][T11], buffers principal y direccionales | 2026-09-17 |
| X1 | [Gold Reversion Gate][X1], texto indexado; apertura fallida; excluido de muestra | 2026-09-17 |

También falló la apertura editorial del artículo de 2025 «The night effect…» ([DOI 10.1016/j.gfj.2025.101084](https://doi.org/10.1016/j.gfj.2025.101084), HTTP 403; intento 2026-09-17). No se afirma haber leído ese artículo completo ni se identifica automáticamente con el working paper R2. No se usaron copias comerciales no autorizadas ni sitios de reventa.

[P1]: https://www.mql5.com/en/market/product/188424
[P2]: https://www.mql5.com/en/market/product/185207
[P3]: https://www.mql5.com/en/market/product/189042
[P4]: https://www.mql5.com/en/market/product/166740
[P5]: https://www.mql5.com/en/market/product/170050
[P6]: https://www.mql5.com/es/market/product/172541
[P6EN]: https://www.mql5.com/en/market/product/172541
[P7]: https://www.mql5.com/en/market/product/191042
[P8]: https://www.mql5.com/en/market/product/155855
[P9]: https://www.mql5.com/en/market/product/174110
[P10]: https://www.mql5.com/en/market/product/122237
[M1]: https://www.mql5.com/en/blogs/post/774929
[S1]: https://www.mql5.com/en/signals/2384469
[S2]: https://www.mql5.com/en/signals/2387381
[S3]: https://www.mql5.com/en/signals/2382941
[S4]: https://www.mql5.com/pt/signals/2360946
[S5]: https://www.mql5.com/pt/signals/2377152
[S6a]: https://www.mql5.com/en/signals/2365400
[S6]: https://www.mql5.com/en/signals/2372821
[S7]: https://www.mql5.com/en/signals/2389995
[S8]: https://www.mql5.com/en/signals/2362448
[S10]: https://www.mql5.com/en/signals/2271995
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
[X1]: https://www.mql5.com/en/market/product/196448
[T11]: https://www.mql5.com/en/docs/indicators/iadx
