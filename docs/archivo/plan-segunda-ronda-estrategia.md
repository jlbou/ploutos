# Plan de la segunda ronda de la estrategia (preparado el 28/09/2026)

**Estado: PREPARADO, no empezado.** el propietario decidio el 26/09 esperar al veredicto de la fase 6 (desde el 16/10)
para decidir si hay segunda ronda y de que; el 28/09, que los cortos entran como idea candidata. Este documento
deja listo el como, para que ese dia sea decidir y no disenyar. **Nada de esto toca el bot ni la regla 1.**

El metodo es el de la primera ronda (`docs/archivo/propuesta-revision-estrategia.md`, decisiones 1a-4a del propietario): se
explora con USDT 12/2020-06/2024, la reserva (USDT 07/2024-08/2025) se mira UNA sola vez al final, el anyo USDC
es la segunda comprobacion, y el criterio se fija ANTES de medir.

## 1. De donde se parte

- La estrategia actual en la exploracion: **+0,13 R** (IC 90 %: -0,04 a +0,30); gana en 2021 y 2023 y **pierde
  en 2022, el anyo bajista (-0,35 R)**. En el anyo USDC pierde (-0,38 R).
- Ninguna de las 5 ideas de la primera ronda paso el criterio. La que mas se acerco fue la **2, el filtro de
  tendencia de BTC** (+0,28 R, IC +0,06 a +0,51; no llega a quedar entero sobre la referencia).
- Lectura: el bot pierde sobre todo cuando el mercado cae. La idea 2 lo ataca quedandose fuera; los cortos lo
  atacarian apostando a la baja.

## 2. Las ideas candidatas

**A. Cortos (el propietario, 28/09).** La hipotesis natural, que junta la idea 2 con los cortos: **largos cuando BTC esta en
tendencia alcista, cortos cuando esta en bajista, y nada en medio.** Los setups de corto serian el espejo de los
actuales (pullback a la baja en tendencia bajista, ruptura del suelo de un rango, reversion desde el techo), con el
stop por encima y el mismo tamanyo por riesgo (0,50 $). Fijar la lista exacta de setups ANTES de medir.

**A'. Cortos PROPIOS de mercado bajista (el propietario, 28/09, despues de ver que el espejo de A no pasa).** No el espejo de
los setups de largo, sino una idea pensada para caidas: por ejemplo, entrar solo cuando el precio rompe un minimo
y confirma la caida, con BTC bajista. Motivo del propietario: largos y cortos dan oportunidades en cualquier mercado. Lo que
dijo el espejo: los cortos salen a cero (-0,01 R) y pierden en los giros (principios de 2023, ~-15 R). Condiciones,
porque ya se han visto estos datos:
- los setups, el filtro y el criterio, **escritos y aprobados por el propietario ANTES de medir**, sin retocarlos despues;
- **liston mas alto** que el de la primera ronda (a fijar con el propietario; p. ej. el IC 90 % entero por encima de +0,13
  tambien en los cortos SOLOS, no solo en la combinacion), mas no perder en 2022 y aguantar la financiacion;
- una sola variante: si no pasa, no se prueban retoques;
- prioridad: despues de la idea 2 (tendencia de BTC para los largos) y de la reserva. Aunque pasara, abrir la
  regla 1 seria otra decision (6.5).

**DISENYO APROBADO por el propietario el 28/09, antes de medir: `docs/archivo/diseno-cortos-bajistas.md`** (rebote fallido con tendencia
bajista en dos niveles, stop sobre el maximo del rebote, objetivo 2 R, sin salida por regimen; IC > 0 y R >= +0,13;
simulador de cortos del estudio). **Medida el 08/10 (adelantada, el propietario): NO PASA** (166 cortos a +0,06 R, IC -0,18 a
+0,28; gana en 2022, +0,20, y pierde en los giros de 2021 y 2023; la combinacion con la idea 2, +3,8 R dentro del
ruido; `docs/estudios/segunda-ronda/README.md`).

**B. Velas de 1 h (opcional, el propietario lo planteo el 28/09).** Volver a medir con los 3,5 anyos de USDT. En la fase 2,
con menos datos, las comisiones se comian el 66 % del bruto: no se espera sorpresa, pero son datos y no memoria.
**HECHO el 06/10 (adelantado, el propietario): NO pasa** (`docs/estudios/operaciones-cortas/README.md`): con stop de 3,3 ATR,
-0,13 R; con 1,5 ATR (operaciones de 8 h), -0,12 R y las comisiones el 165 % del bruto; los dos IC enteros bajo cero.
Sale de la segunda ronda.

**C. Time-stop (el propietario, 07/10).** Cerrar una posicion que lleva demasiado abierta para liberar el hueco. El PRD (5) lo
pide; el 25/09 el propietario decidio no ponerlo por ahora (`docs/archivo/propuesta-time-stop.md`, 1a). Se midio SOLO en el anyo USDC,
donde la estrategia pierde: no cambia nada en dinero (la mejor, 18 velas, +1,65 $ en un anyo, dentro del ruido)
porque las posiciones que corta iban GANANDO (+0,34 a +0,77 R) y el hueco lo llena otra operacion de una estrategia
que pierde. Con una estrategia que gane la cuenta puede salir distinta: por eso se vuelve a medir aqui, con los 3,5
anyos de exploracion. Propuesta, a cerrar con el propietario ANTES de medir:
- **Variantes, solo dos** (las mejores del 25/09, sin buscar otras): **18 velas (3 dias) siempre** y **18 velas sin
  avance** (solo si no ha hecho la mitad del camino al objetivo). Salida a mercado al cierre de la vela (taker).
- **Sobre que estrategia:** la actual y, si la segunda ronda se queda con la idea 2 (tendencia de BTC), tambien sobre
  esa. El time-stop no se juzga solo: se juzga lo que anyade a la estrategia que se vaya a usar.
- **Criterio:** el de la primera ronda, contra esa estrategia sin time-stop: IC 90 % (bootstrap por dias) de la
  diferencia de R por operacion entero por encima de 0, que no gane solo en un tramo, y la reserva una sola vez al
  final. Si no pasa, no se prueban otras duraciones.
- Coste: poco, el parche del 25/09 (`docs/estudios/time-stop/experimento.py`) ya existe; medio dia.
- **Mientras dure la muestra de la fase 6 no se toca el bot** (partiria la muestra en tramos).

**D. Quitar la reversion a la media (el propietario, 07/10).** Motivo: el 07/10 la cartera de la IA abrio una reversion en XRP
(stop a -1,27 %) y la cerro por el stop en la MISMA vela (-0,25 $, -1,23 R), el "cuchillo que cae" del estudio del
time-stop. **Aviso de metodo: es una idea anyadida DESPUES de ver los numeros** (la reversion pierde en los dos
juegos de datos: -0,59 R en la exploracion, IC -0,85 a -0,30, y -0,50 en el anyo USDC;
`estudios/revision-estrategia/README.md` 2, punto 3). Quitar lo que ya se sabe que pierde sube la media casi por
construccion, asi que el liston tiene que ser mas alto que el de las otras ideas. Propuesta, a cerrar con el propietario ANTES
de medir:
- **Que se mide:** el recorrido entero sin el setup `mean_reversion` (los huecos que deja los ocupan los otros dos,
  y eso se mide, no se supone). Una sola variante; tambien combinada con la idea 2 si la segunda ronda se queda con
  ella.
- **Criterio:** el R medio de la estrategia SIN reversion, con IC 90 % (bootstrap por dias) ENTERO por encima de la
  referencia (+0,13 R), con >= 100 operaciones y sin ganar solo en un tramo (no basta con que la diferencia sea
  positiva). Despues, la reserva una sola vez (R > 0 y mejor que la referencia) y el anyo USDC.
- **Si no pasa:** la reversion se queda; no se prueban retoques de su stop.
- Coste: poco, es apagar un setup en `medir.py`; un par de horas. El bot no se toca durante la muestra de la fase 6.

### C y D: APROBADAS por el propietario el 07/10, ANTES de medir ("fes-les totes"), con estos detalles fijados aqui

Se miden ya en la exploracion (adelantadas, como la B y los cortos); la reserva y el anyo USDC, NO: solo si alguna
pasa, al final de la segunda ronda y con el propietario.
- **Datos y recorrido:** USDT 02/12/2020-30/06/2024 (`var/estudios/exploracion.db`), `revision-estrategia/medir.py`
  (el recorrido del bot sin cambios, las 19 reglas), parcheado en memoria en `docs/estudios/segunda-ronda/`.
- **Dos contabilidades, y tiene que pasar en LAS DOS:** el objetivo cobrado maker (como la primera ronda; referencia
  +0,13 R) y taker (como lo cobra OKX de verdad; referencia +0,122 R, `operaciones-cortas/r4.json`).
- **Validacion antes de mirar ninguna idea:** sin parches, el script reproduce las dos referencias EXACTAS (497 op.;
  +0,130 y +0,122 R). Si no, no se mide nada.
- **Los anyos:** 2021, 2022, 2023 y 2024 (enero-junio); diciembre de 2020 (16 op.) no cuenta como anyo.
- **C (time-stop), cada una de las dos variantes de 18 velas:** pasa si (1) el IC 90 % de la diferencia de R medio
  por operacion (idea menos referencia), con bootstrap EMPAREJADO por dias (se remuestrean dias y en cada muestra se
  comparan las operaciones de las dos que cierran esos dias), queda entero por encima de 0; (2) >= 100 operaciones; y
  (3) la diferencia es positiva en al menos 3 de los 4 anyos. Dos variantes = dos oportunidades de acertar por
  suerte: se dira.
- **D (sin reversion):** pasa si (1) el IC 90 % del R medio (bootstrap por dias, el de `medir.py`) queda entero por
  encima de +0,13 R, en las dos contabilidades; (2) >= 100 operaciones; y (3) R medio > 0 en al menos 3 de los 4
  anyos.
- **Si no pasa, no se retoca** (ni otras duraciones del time-stop ni el stop de la reversion).

### Resultado (07/10, detalle en `docs/estudios/segunda-ronda/README.md`): NINGUNA PASA

| | Op. | R medio (maker / taker) | IC 90 % (taker) | Final (taker) | Pasa |
|---|---|---|---|---|---|
| Referencia | 497 | +0,130 / +0,122 | -0,044 a +0,292 | 119,19 $ | - |
| C, 18 velas siempre | 878 | +0,003 / -0,008 | diferencia -0,264 a +0,001 | 59,46 $ | no |
| C, 18 velas sin avance | 875 | -0,009 / -0,015 | diferencia -0,271 a -0,007 | 55,91 $ | no |
| D, sin reversion | 398 | +0,288 / +0,284 | +0,095 a +0,478 | 140,91 $ | no (el extremo bajo no llega a +0,13) |

- **C se descarta:** corta posiciones que iban ganando (+0,56 R al cortarlas) y el pullback cae de +0,39 a +0,06 R.
- **D mejora pero no llega al liston:** como la idea 2, se queda con el pullback (lo que gana) y sigue perdiendo en
  2022 (-0,31 R). La diferencia emparejada con la referencia es entera positiva (+0,09 a +0,24), pero eso es
  informativo: el criterio era el R entero sobre +0,13.
- **Siguiente pregunta natural: 2 + D** (BTC sobre su media de 200 dias Y sin reversion). Sin medir: criterio con el propietario
  antes.

### 2 + D: APROBADA por el propietario el 08/10, ANTES de medir ("mesura-ho ara sense tocar la reserva")

**Aviso de metodo, el mas importante de esta ronda.** Las dos piezas ya se han visto, y por separado: la idea 2 por
setup (`revision-estrategia/ideas/idea2.json`: pullback 177 op. a +0,53 R, ruptura 77 a +0,04, reversion 39 a -0,39)
deja calcular a ojo lo que daria quitarle la reversion: **unas 250 operaciones a ~+0,38 R**, antes de medir. La
exploracion ya no puede sorprender con esta pregunta: medirla confirma una cuenta, no pone a prueba la idea. **La
unica prueba limpia que queda es la reserva** (USDT 07/2024-08/2025, sin bajar), y solo se puede gastar una vez.

- **Que:** la idea 2 tal cual (`medir.py --idea 2`: sin candidatos con BTC bajo su media de 200 dias, cierres diarios
  UTC) y la D (el nivel 3 sin `mean_reversion`), a la vez. Una sola variante, sin retoques.
- **Validacion antes:** el script, con solo la idea 2, reproduce `idea2.json` EXACTA (293 op., +0,278 R, maker); las
  referencias, como el 07/10.
- **Criterio en la exploracion, en las dos contabilidades (maker y taker):** (1) IC 90 % del R medio entero por
  encima de +0,13; (2) >= 100 operaciones; (3) R medio > 0 en cada anyo con >= 20 operaciones, y al menos 3 anyos asi
  (con la idea 2, 2022 casi no opera: un anyo sin operaciones no cuenta ni a favor ni en contra).
- **Si pasa, la reserva NO se abre todavia:** se abre una sola vez, al acabar la segunda ronda (tras el veredicto de
  la fase 6), con la estrategia final ya elegida entre todo lo que haya pasado (2 + D, los cortos A' si pasan, o
  ninguna). Criterio de la reserva, el del metodo (`propuesta-revision-estrategia.md` 5): R medio > 0 y mejor que el
  baseline actual; despues, el anyo USDC: que no pierda mas que el baseline actual.
- **Si no pasa:** se queda la estrategia actual y la segunda ronda sigue con lo que queda (A').

**Resultado (08/10, `docs/estudios/segunda-ronda/README.md`): NO PASA, por dos milesimas.** 256 op.; maker +0,371 R
(IC +0,134 a +0,625: pasa), taker +0,363 R (IC **+0,128** a +0,616: no llega a +0,13). Los anyos, bien (2021 +0,74,
2023 +0,19, 2024 +0,06; 2022 sin operaciones). Acaba con menos dinero que la referencia (116 $ frente a 124 $) porque
opera la mitad, con menos caida (18 % frente a 25 %). La reserva, sin tocar.

**Decision del propietario (09/10): 2 + D queda GUARDADA COMO CANDIDATA**, sin llevarla todavia a la reserva. Lo que se le
planteo (por si se retoma): la reserva se gasta una sola vez; el periodo 07/2024-08/2025 fue sobre todo alcista (no
mirado, conocimiento general) y le favorece; la prueba dura seria el anyo USDC (con meses bajistas), donde se
propuso endurecer el criterio a "no perder" (R medio >= 0) en vez de "no perder mas que el baseline".

**E. Kronos como filtro (el propietario, 08/10; para despues del veredicto de la fase 6).** Kronos
(`github.com/shiyu-coder/Kronos`, MIT; articulo arXiv 2508.02739, AAAI 2026) es un modelo entrenado con ~12.000
millones de velas de 45 bolsas que predice las velas siguientes. Lo verificado el 08/10:
- el pre-entrenamiento llega **hasta junio de 2024**: ha visto la exploracion entera (no sirve para medirlo) y NO la
  reserva ni el anyo USDC;
- sus numeros absolutos son pequenyos (Kronos-small: IC 0,043, RankIC 0,025, ordenando acciones); la prueba con
  dinero es en acciones chinas diarias (coste 0,15 %); para cripto no da numeros aparte y entrena sin volumen;
- versiones abiertas: mini (4,1 M parametros), small (24,7 M), base (102,3 M); la small corre sin GPU.

Lectura (08/10): **poco probable que aporte** (mira las mismas velas que los setups, no informacion nueva; senyal
pequenya frente a ~0,3 % de coste por operacion; el problema del bot es el regimen, que ya capta la media de 200
dias de BTC), pero comprobarlo es barato. Solo podria entrar como FILTRO (no entrar si predice bajada), nunca como
senyal de compra ni como orden. **Propuesta en dos pasos, a cerrar con el propietario ANTES de medir:**
1. **Si acierta con nuestras monedas** (sin tocar la estrategia): el anyo USDC (velas de 4 h de las 8, desde el
   20/08/2025, `time-stop/historia.db`), Kronos-small sin reentrenar, 400 velas de contexto, horizonte **6 velas (24
   h)**, una prediccion cada 6 velas (sin solaparse: ~400 por moneda), media de 5 muestras con semilla fija. Mide la
   correlacion entre el rendimiento predicho y el real a 6 velas. **Pasa** si el IC 90 % (bootstrap por dias) del
   conjunto queda entero por encima de 0 y la correlacion es positiva en al menos 5 de las 8 monedas. Si no pasa, se
   cierra el tema.
2. **Solo si pasa el 1:** Kronos como filtro de las entradas, con su propio criterio fijado antes; la reserva, solo al
   final de la ronda y una vez.

**Paso 1 APROBADO por el propietario el 08/10, antes de medir, con las descargas** ("sí a les dues"). Detalles fijados aqui,
antes de lanzar nada (`docs/estudios/kronos/`):
- datos: `time-stop/historia.db`, velas de 4 h contra USDC (BTC, DOGE, ETH, SOL, TRX y XRP desde el 21/08/2025; AVAX
  desde el 09/10/2025; NEAR desde el 26/02/2026; hasta el 28/09/2026); todo posterior a junio de 2024;
- entrada al modelo: solo OHLC (como hace el articulo con la cripto), las 400 velas cerradas anteriores; prediccion
  de 6 velas; `T=1.0`, `top_p=0.9`, `sample_count=5`; semilla de torch fija;
- una prediccion cada 6 velas desde la vela 400 de cada moneda (horizontes sin solaparse);
- predicho = cierre medio de la vela +6 / ultimo cierre - 1; real = cierre de la vela +6 / ultimo cierre - 1;
- correlacion de RANGOS (Spearman), del conjunto y de cada moneda; IC 90 % del conjunto por bootstrap de dias
  (10.000, semilla fija); **pasa** si el IC queda entero por encima de 0 Y la correlacion es positiva en >= 5 de las 8.
- Descargas: el codigo (`github.com/shiyu-coder/Kronos`), `NeoQuasar/Kronos-small` (99 MB) y
  `NeoQuasar/Kronos-Tokenizer-base` (15,8 MB) de Hugging Face, PyTorch para CPU y lo que pide su `requirements.txt`;
  en `var/kronos/` (fuera de git), con su propio entorno de Python. El codigo se lee entero antes de ejecutarlo.

**Resultado del paso 1 (08/10, `docs/estudios/kronos/README.md`): NO PASA, se cierra el tema.** 2.450 predicciones;
Spearman del conjunto -0,042 (IC 90 % -0,106 a +0,021); positiva solo en 2 de 8 monedas; acierta la direccion el
46,8 %. El paso 2 no se hace.
- **Coste:** descargas con permiso del propietario en su momento (el codigo, los pesos de Hugging Face, ~100 MB a comprobar, y
  PyTorch para CPU), en un entorno aparte, solo en el portatil; unas horas de CPU (a medir con una prueba pequenya).
  Al VPS (2 GB) no va mientras no demuestre nada.

**F. Rotacion semanal de tendencia, solo largos (el propietario, 09/10; sale de `docs/estudios/recerca-trading-cripto.md`).**
Apuntada, SIN criterio ni medicion. La idea: cada semana, de las 8, se tienen las hasta 3 con el rendimiento de 4
semanas positivo y mas alto; si ninguna lo tiene, todo en USDC. Lo que la apoya: la tendencia de 1-4 semanas es lo
que mas evidencia tiene en cripto, opera poco (menos comisiones) y es de la familia de la idea 2. Lo que hay que
resolver antes de medirla:
- **No es un setup de 4 h con stop y objetivo:** sale cuando la moneda deja de estar entre las fuertes. La regla 13
  (stop y objetivo siempre en el exchange) obliga a poner igualmente una OCO (p. ej. stop a varios ATR diarios y
  objetivo lejano) y a vender a mercado en la rotacion, como ya hace el ejecutor con las salidas que no son OCO.
- **La IA** seguiria eligiendo entre candidatos (los de la semana) o reduciendo; el baseline, los de mas fuerza.
- **Medirla** pide un recorrido propio (semanal), validado como los demas, y el liston por numero de pruebas (Sharpe
  deflactado, `recerca-trading-cripto.md` 2.2).
- La literatura avisa: lo que se mantiene es la reduccion de caidas, no ganar mas que comprar y mantener.

**G. Filtro de financiacion (el propietario, 09/10; misma fuente).** Apuntada, SIN criterio ni medicion. No entrar cuando la
financiacion de los perpetuos de esa moneda esta muy alta (demasiados largos apalancados). Evidencia floja (preprints,
sin fuera de muestra claro) y la historia hay que bajarla (la API publica da ~3 meses; ver 4.1).

**I. Asegurar beneficio: el stop a +1 R cuando la operacion va a +2 R (el propietario, 09/10). Criterio APROBADO por el propietario el
09/10, ANTES de medir ("mesura-ho amb aquest criteri").** Motivo: las operaciones cerradas en papel pasaron tiempo en positivo y acabaron en el stop
(analisis del 09/10, vela a vela: de 6, solo NEAR paso de +1 R y ninguna de +2 R).
- **La regla, una sola variante:** cuando una vela de 4 h CIERRA a +2 R o mas, desde la vela siguiente el stop pasa a
  +1 R (la OCO se rehace en el exchange; el objetivo no cambia). Se mira el cierre, no el maximo, para no suponer el
  orden dentro de la vela. La salida al stop nuevo, taker y con su hueco si abre por debajo.
- **Sobre que:** 2 + D (la candidata), con el objetivo maker y taker; sobre la estrategia de hoy, solo informativo.
- **Pasa si**, en las dos contabilidades: el IC 90 % de la diferencia de R por operacion (con la regla menos sin ella),
  emparejada por dias como en la C, queda entero por encima de 0, y la diferencia es positiva en al menos 3 de los
  anyos con >= 20 operaciones. Si no pasa, no se prueban otros umbrales (+1,5 R, +3 R...). Cuenta como una prueba mas
  (N = 28 con F y H).
- **Como se mide (fijado antes):** `docs/estudios/segunda-ronda/medir_cd.py --asegurar`, sobre el recorrido del bot.
  El R de cada operacion sigue contandose contra el stop ORIGINAL (el riesgo planificado); la regla 8 (preventiva)
  sigue viendo el stop original, que es mas prudente que el movido. Comparacion contra `2+D-maker.json` y
  `2+D-taker.json` del 08/10 (los mismos datos y el mismo codigo, sin la regla).
- **Resultado (09/10): NO PASA, empeora** (2 + D taker: +0,363 -> +0,205 R por operacion, 115,90 $ -> 85,66 $;
  diferencia -0,158, IC -0,306 a -0,013). Lo que sale pronto deja hueco a operaciones nuevas que pierden.
  `docs/estudios/segunda-ronda/README.md`.
- **Lo que hay que saber:** gana en las operaciones que llegan a +2 R y se dan la vuelta (de -1 R a +1 R) y pierde en
  las que llegan a +2 R, retroceden a +1 R y despues habrian llegado al objetivo (de +3,4 R a +1 R). Cual pesa mas
  solo lo dicen los datos.

## 3. Lo que ya se sabe del corto en OKX EEA (28/09, ver `propuesta-revision-estrategia.md` 5b)

- **Existe para un particular**, por dos caminos: el **margen de spot** (prestamo con interes por hora, fuera de
  MiCA, la deuda puede quedar) y los **X-Perps** (MiFID, desde el 15/04/2026, financiacion cada cierto tiempo,
  **proteccion de saldo negativo**). Si alguna vez se abre la regla 1, el camino seria el de los X-Perps.
- **La financiacion reciente** (`docs/estudios/revision-estrategia/financiacion_reciente.py`, perpetuos USDT de
  OKX, del 22/06 al 28/09/2026, 295 cobros cada 8 h):

  | Moneda | Media cada 8 h | Al anyo | Tasas positivas | Peor cobro |
  |---|---|---|---|---|
  | BTC | +0,0051 % | +5,6 % | 91 % | -0,008 % |
  | ETH | +0,0037 % | +4,1 % | 81 % | -0,006 % |
  | SOL | +0,0029 % | +3,2 % | 70 % | -0,012 % |
  | XRP | +0,0033 % | +3,7 % | 76 % | -0,024 % |
  | DOGE | +0,0061 % | +6,7 % | 90 % | -0,007 % |
  | AVAX | +0,0038 % | +4,2 % | 74 % | -0,036 % |
  | TRX | **-0,0088 %** | **-9,6 %** | 37 % | -0,160 % |
  | NEAR | +0,0064 % | +7,0 % | 84 % | -0,029 % |

  Positiva = el corto COBRA. En estos tres meses un corto habria cobrado casi siempre (salvo TRX), **pero no es
  lo que importa**: el corto interesa en los tramos bajistas, y ahi la tasa suele bajar o volverse negativa. Hay
  que medirla en 2022, no suponerla.

## 4. Lo que falta antes de medir los cortos

1. **La financiacion de la exploracion (12/2020-06/2024).** La API publica solo da ~3 meses. Opciones:
   - a) **Los ficheros del historial de datos de OKX** (se descargan: hace falta el permiso del propietario, diciendo
     fichero, origen y tamanyo antes);
   - b) **una tasa fija pesimista para el corto** (por ejemplo, pagar 0,01 % cada 8 h siempre, que es mas de lo
     que se ve en tramos normales) como criba: si la idea no gana ni asi... o si gana solo gracias a cobrar;
   - c) las dos: la b para cribar y la a solo si la idea pasa la criba.
   **Recomendado: c.** No se baja nada si la idea no merece la pena.
2. **Las comisiones de los X-Perps para una cuenta EEA** (no estan en lo leido el 28/09): leerlas en la pagina de
   comisiones de OKX EEA. Si no se encuentran, usar las del spot (0,10 % / 0,20 %) y decirlo.
3. **Un simulador de cortos, SOLO para el estudio.** `portfolio/paper.py` solo sabe ir largo, y asi debe seguir
   (el bot no cambia). El estudio necesitaria su propia version en `docs/estudios/`, con: stop por encima,
   financiacion cada 8 h mientras la posicion esta abierta, y liquidacion. **Liquidacion:** con garantia aislada y
   poco apalancamiento (2x), un corto solo se liquida si el precio SUBE ~45-50 % desde la entrada, muy lejos de
   un stop del ~3 %; solo un hueco extremo la tocaria. Medir igualmente cuantas veces el precio paso de largo el stop.
4. **Las reglas duras, adaptadas en el estudio:** el riesgo por operacion (0,50 $), el maximo de posiciones, el
   suelo y la perdida diaria valen igual para un corto. Lo unico que cambia es la regla 1, y solo dentro del estudio.

## 5. El criterio (a fijar con el propietario ANTES de medir)

Propuesta, igual que la primera ronda y una condicion mas para los cortos:
- **Exploracion:** R medio por operacion con IC 90 % (bootstrap por dias) entero por encima de la referencia
  (+0,13 R), con >= 100 operaciones, y que no gane solo en un tramo.
- **Condicion nueva:** que **no pierda en 2022** (el anyo bajista), porque ese es el motivo de probar cortos, y que
  el resultado no dependa de COBRAR financiacion (con la tasa pesimista de 4.1 b tiene que seguir por encima).
- **Reserva (una vez) y anyo USDC:** como en la primera ronda.

## 5b. DECIDIDO por el propietario el 28/09, ANTES de medir nada

el propietario adelanta el estudio de los cortos (no espera al 16/10) y pide preparar a la vez una tercera cartera de papel
solo de cortos, en sombra, que NO se despliega hasta que el estudio pase. Fijado antes de ver ningun numero:
- **Setups:** el ESPEJO de los tres actuales (rebote en tendencia bajista, ruptura a la baja de un rango, vuelta
  desde el techo), solo con **BTC bajo su media de 200 dias**; los largos, solo con BTC por encima (la idea 2).
- **Criterio:** el de la seccion 5 tal cual: IC 90 % entero por encima de +0,13 R con >= 100 operaciones, no
  perder en 2022 y aguantar con financiacion pesimista (el corto PAGA 0,01 % cada 8 h, siempre); despues, una
  sola mirada a la reserva (R > 0 y mejor que la referencia) y el anyo USDC.
- **Como se mide (sin tocar el bot):** los precios se INVIERTEN (cada vela pasa a 1/precio: el maximo pasa a ser
  el minimo) y se pasa el recorrido del bot sin cambios, con sus 19 reglas. Un largo sobre los precios invertidos
  es exactamente un corto sobre los reales: el stop y el objetivo saltan en las mismas velas. El resultado se
  corrige operacion a operacion con la formula exacta, R_corto = R_invertido x p_salida / p_stop, y se le resta
  la financiacion pesimista por cada 8 h abierta. Aproximaciones que se diran en el resultado: los indicadores
  sobre 1/precio no son el espejo exacto (la RSI y las medias casi), y largos y cortos se suman sin compartir los
  huecos de la regla 4 (solapan poco: los tramos de BTC alcista y bajista no coinciden en el tiempo).

### Resultado (28/09, detalle en `docs/estudios/revision-estrategia/README.md` seccion 5): NO PASA

| | Op. | R medio | IC 90 % |
|---|---|---|---|
| Largos (BTC alcista) = idea 2 | 293 | +0,28 | +0,06 a +0,51 |
| Cortos, con financiacion pesimista | 220 | -0,01 | -0,25 a +0,24 |
| Combinacion, con financiacion | 513 | +0,16 | -0,00 a +0,32 |

Cumple >= 100 operaciones y no perder en 2022 (+0,08 R); falla el IC entero sobre +0,13 (y con financiacion). Los
cortos no aportan: ~-1 R en total; lo que ganan en 2022 (~+12 R) lo pierden en el giro de principios de 2023
(~-15 R, BTC aun bajo su media). **No se mira la reserva y la cartera de cortos en sombra no se construye.**

## 6. Decisiones para el propietario, al empezar la segunda ronda

1. **Si hay segunda ronda** y con que ideas (A', C y D; la B ya se midio y no pasa).
2. **De donde sale la financiacion historica** (4.1: recomendado c).
3. **Los setups de corto**, cerrados antes de medir (2.A).
4. **El criterio** (seccion 5), antes de ver ningun numero.
5. **Aunque los cortos pasaran**, abrir la regla 1 seria otra decision, con los riesgos medidos, despues.
6. **El time-stop (2.C):** las dos variantes y el criterio, antes de medir.
7. **Quitar la reversion (2.D):** el criterio con el liston mas alto, antes de medir.
8. **Kronos (2.E):** el criterio del paso 1 y el permiso para las descargas.
9. **Rotacion semanal (2.F) y filtro de financiacion (2.G):** si se miden, y con que criterio (Sharpe deflactado).

## 7. Cuanto trabajo es (aproximado)

El simulador de cortos del estudio y su validacion: un dia. Bajar y preparar la financiacion historica: medio dia.
Medir y documentar: medio dia. Todo en el portatil, sin tocar el VPS.
