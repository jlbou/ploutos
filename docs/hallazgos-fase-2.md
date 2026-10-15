# Hallazgos de la fase 2

Movido de CLAUDE.md el 22/09/2026, **sin cambiar una palabra**: motor de riesgo, costes, filtros, regimen, setups, baseline, papel, jueces.
Lo que sigue vigente como regla, decision o aviso esta resumido en CLAUDE.md;
aqui queda el como y el por que, con los numeros.

---

## Fase 2 — motor de riesgo (en curso, 22/09/2026)

`risk/` esta completo y probado. **No importa nada de `ai/` ni de `execution/`**
(comprobado con AST en `tests/unit/test_architecture.py`).

| Fichero | Contenido |
|---|---|
| `risk/limits.py` | Limites VIGENTES: aplica escalones de drawdown (regla 9) y slider |
| `risk/state.py` | La foto que mira el motor. Sin I/O, sin reloj propio |
| `risk/types.py` | `Instrument`, `EntryRequest`, `RuleResult`, `Verdict` |
| `risk/rules.py` | Las 19 reglas, una funcion cada una |
| `risk/sizing.py` | Tamanyo por riesgo, redondeo SIEMPRE hacia abajo, minimos |
| `risk/equity.py` | Regla 6 y el enclavamiento de la 7 (dos lecturas) |
| `risk/engine.py` | `evaluate()`: unica puerta por la que se abre una posicion |

Tres decisiones de disenyo que conviene no deshacer:

1. **Se evaluan TODAS las reglas, sin cortocircuito.** Si una entrada viola cinco, se
   ven las cinco. El panel del PRD §10 ensenya por que se bloqueo algo y "por la primera
   que fallo" no es la respuesta completa.
2. **El tamanyo se calcula DESPUES de aprobar.** Un veredicto vetado no puede llevar
   cantidad por accidente (hay test).
3. **Una regla que revienta VETA**, no deja pasar. Ante la duda, la direccion segura.

**El slider esta recortado**: el informe §4.6 daba 7 y 8 operaciones/dia en los niveles
4 y 5; la regla 11 dice 6. `SLIDER_LEVELS` los recorta a 6.

### La prueba de mutacion encontro un agujero real

`scripts/mutation_check.py` desactiva cada regla y comprueba que algun test se pone en
rojo. Con 339 tests en verde, **la regla 9 se podia desactivar sin que nadie se entere**:
sus tests comprobaban `Limits.for_state()` pero nadie ejercitaba la regla DENTRO del
motor, que es la segunda barrera (si los limites llegan mal construidos, el motor los
rechaza). Tapado con 4 tests nuevos.

Es exactamente el fallo que el criterio ampliado buscaba: **tests en verde que no
protegen nada**. Lanzar `python scripts/mutation_check.py` antes de dar la fase por buena.

Reglas no mutables aqui, y por que: la 2 y la 5 se validan en `core.config` al arrancar,
y la 19 **no se puede comprobar desde el motor porque el motor no ve credenciales** —
que no pueda es la regla cumpliendose.

## Fase 2 — modelo de costes y filtros (22/09/2026)

`strategy/costs.py` y `strategy/filters.py`. Tres cosas que no hay que deshacer:

1. **Las comisiones se LEEN de la tabla `instruments`.** `Instrument` ya NO tiene
   valores por defecto para `maker_fee`/`taker_fee`: quien lo construya tiene que decir
   de donde salen (`Instrument.from_row()` las saca de la tabla y se planta si faltan).
   Un simbolo sin comisiones conocidas NO genera candidatos. Es la misma regla que en
   los indicadores: NaN antes que un numero inventado.
2. **La pata de salida es TAKER.** El stop vive en el exchange (regla 13) y cuando salta
   cruza el libro. Una salida urgente no puede ser maker.
3. **Los filtros NO son una capa de seguridad.** Existen para no gastar cuota de Claude
   (regla 18) en monedas que el motor iba a vetar igual. La autoridad es `risk/engine.py`.
   Un fallo en los filtros cuesta oportunidades, nunca dinero.

**El spread solo lo paga la pata que cruza, y paga la mitad** (cruzar es ir del medio a
un lado). El impacto de mercado se supone CERO, y esa suposicion la sostiene el filtro de
profundidad (>= 20x el tamanyo de la orden): si se relaja ese filtro, el modelo de costes
se queda corto. Lo que el modelo NO cuenta: la seleccion adversa de la pata maker (una
limit de compra se llena cuando el precio sigue bajando) y las entradas que no se llenan.
Las dos hacen que el coste real sea MAYOR, asi que el 3x de la regla 16 es un minimo.

### Los umbrales de ATR se DEDUCEN, no se eligen

- **Suelo**: `objetivo_minimo / (multiplo_atr x R:R)`. Por debajo, el objetivo no llega a
  pagar 3x el coste ni saliendo bien.
- **Techo**: `100 x riesgo / minimo_por_orden / multiplo_atr`. Por encima, el stop es tan
  ancho que la posicion cae por debajo del minimo del instrumento.

Por eso se calculan en cada pasada (dependen del precio y del spread del momento) y no
viven en `settings.yaml`.

### Medido contra datos reales de OKX (velas de 4 h, backup del 22/09/2026)

| par | spread % | coste ida y vuelta | equilibrio | objetivo 3x | ATR % |
|---|---|---|---|---|---|
| BTC/USDC | 0,0001 | 0,2501 % | 0,2504 % | 0,7536 % | 1,226 |
| ETH/USDC | 0,0069 | 0,2535 % | 0,2538 % | 0,7638 % | 1,579 |
| SOL/USDC | 0,0343 | 0,2671 % | 0,2675 % | 0,8050 % | 1,874 |
| XRP/USDC | 0,0131 | 0,2565 % | 0,2569 % | 0,7731 % | 2,303 |
| DOGE/USDC | 0,0409 | 0,2704 % | 0,2708 % | 0,8150 % | 3,075 |
| AVAX/USDC | 0,0459 | 0,2729 % | 0,2734 % | 0,8225 % | 4,411 |
| TRX/USDC | 0,0260 | 0,2630 % | 0,2634 % | 0,7925 % | 0,508 |
| NEAR/USDC | 0,0445 | 0,2722 % | 0,2726 % | 0,8204 % | 5,368 |

Los 8 pasan los filtros. **La profundidad confirma lo de la fase 1**: entre 41.000 $ y
1.330.000 $ hasta el 0,5 %, cuando hacen falta 300 $. Nunca ata.

**El tamanyo de posicion NO son "15 $" en todas.** Con riesgo constante, el nocional sale
de `riesgo / distancia_al_stop`, asi que depende del ATR de cada moneda:

| par | ATR% medio | ATR% del dia | stop | posicion |
|---|---|---|---|---|
| BTC/USDC | 1,059 | 1,226 | 2,33 % | **20,00 $** (tope) |
| ETH/USDC | 1,441 | 1,579 | 3,00 % | 16,66 $ |
| SOL/USDC | 1,764 | 1,874 | 3,56 % | 14,04 $ |
| XRP/USDC | 2,169 | 2,303 | 4,38 % | 11,42 $ |
| DOGE/USDC | 1,936 | 3,075 | 5,84 % | 8,56 $ |
| AVAX/USDC | 1,984 | 4,411 | 8,38 % | 5,97 $ |
| TRX/USDC | 0,505 | 0,508 | 0,97 % | **20,00 $** (tope) |
| NEAR/USDC | 3,325 | 5,368 | 10,20 % | 4,90 $ |

Los 15 $ solo salen cuando el ATR esta en su media (1,773 %, que confirma la medicion del
multiplo). **NEAR va al limite del techo** (5,37 % de ATR contra un techo de 5,85 %): con
un poco mas de volatilidad se queda fuera, y no por la moneda sino porque su minimo por
orden son 4,42 $. Vigilar en la fase 6.

### BRECHA REAL ENCONTRADA EN LA REGLA 15 (y arreglada)

Al medir los tamanyos salio que BTC y TRX llegan al tope de 20 $ por orden. Eso destapo
que **la regla 15 se podia saltar**:

- proyectaba `exposicion + target_notional_usd` (15 $) para decidir,
- pero `risk/sizing.py` podia devolver hasta `max_notional_usd` (20 $).

Reproducido: con 30 $ expuestos y una orden de 20 $, el motor **aprobaba** y la exposicion
acababa en 50 $, o sea el **100 % del equity con un tope del 90 %**.

Arreglado en tres sitios:
1. `risk/sizing.py` recorta contra el MARGEN que queda, no contra el tope entero, y
   `exposure_usd` es un argumento **obligatorio** (con un cero por defecto, olvidarse de
   pasarlo volveria a abrir la brecha en silencio);
2. `risk/rules.py` regla 15 veta solo cuando no cabe NINGUNA orden valida (margen menor
   que el minimo por orden del instrumento), que es lo unico que se puede juzgar antes de
   dimensionar;
3. `risk/engine.py` lo comprueba OTRA VEZ con el tamanyo real despues de dimensionar
   (segunda barrera del PRD §13). Si esa rama salta alguna vez, es que alguien ha roto el
   recorte del punto 1.

**Por que no lo cogio nadie:** el invariante 7 ("exposicion nunca por encima del 90 %")
estaba escrito en la cabecera de `tests/property/test_risk_invariants.py` desde el
principio **pero no tenia ningun `@invariant()` detras**. Es exactamente el fallo que
busca `scripts/mutation_check.py`: una proteccion que se da por hecha y que no comprueba
nadie. Ahora existe.

Ademas la maquina de estados **no llegaba a los estados interesantes**: con spreads de
hasta 0,3 % y R:R desde 1,2, casi la mitad de los intentos morian en la regla 16 y la
exposicion maxima alcanzada eran 35 $ de un tope de 45 $. Con los rangos ajustados llega
a 45,00 $ clavados y el invariante detecta la brecha. Leccion: **una maquina de estados
que no alcanza los estados interesantes no prueba nada**, y eso no se ve en el numero de
tests en verde.

### La regla 16 tambien estaba floja

Calculaba el coste como maker en las DOS patas mas el spread entero (0,20 % + spread).
Lo real es maker de entrada, taker de salida y medio spread (0,25 % + spread/2). Para
spreads por debajo del 0,10 % la version antigua **subestimaba el coste**, o sea dejaba
pasar operaciones que no llegan a pagar 3x lo que cuestan. Hay un test de regresion con
el caso exacto: objetivo del 0,7 % con spread del 0,01 %, que antes pasaba y ahora no.

### Invariantes de arquitectura nuevos

`strategy/` no importa `execution/`; `features/` no importa `strategy/`, `risk/` ni `ai/`
(los indicadores son calculo puro sobre velas: si miran la cartera, vuelve el look-ahead
bias por la puerta de atras).

## Fase 2 - regimen, setups y generador de candidatos (22/09/2026)

`features/regime.py`, `strategy/setups/` y `strategy/candidates.py`.

**El clasificador de regimen** usa las tres senyales del informe 1.3[3]: ADX, anchura de
Bollinger y percentil del ATR. El percentil es lo que lo hace comparable entre monedas: un
ATR del 3 % es una barbaridad en BTC y un martes normal en DOGE.

`TRANSITION` y `UNKNOWN` son cosas DISTINTAS y mezclarlas seria caro: `UNKNOWN` es "no se
puede clasificar" (faltan velas) y ahi no opera nadie; `TRANSITION` es una lectura valida
que dice "entre estados", y **es justo donde vive una ruptura de rango**. Si fuesen la
misma etiqueta, o se prohiben las rupturas o se deja operar sobre datos insuficientes.

**Los tres setups** declaran en que regimen tienen sentido (informe 2.3[5]: no rupturas en
rango, no reversiones en tendencia). El stop es el MISMO para los tres (`multiplo_atr x
ATR`) para que el tamanyo de posicion siga siendo predecible, y **el objetivo es un nivel
real del grafico, no `entrada + 2R`**: si se fabricase multiplicando el riesgo, el R:R
seria siempre 2 por construccion y `min_reward_risk` no comprobaria nada.

### Cuatro errores que solo aparecieron al medir

1. **El percentil contaba los empates enteros.** Una moneda de volatilidad CONSTANTE daba
   percentil 100 y se clasificaba `HIGH_VOL`: la moneda mas aburrida posible salia como la
   mas movida. Con el convenio del punto medio da 50.
2. **El percentil solo no basta.** Medido en una serie con el ATR entre 1,06 % y 1,20 %:
   un rango minusculo reparte percentiles extremos por puro ruido, asi que la moneda
   acababa `HIGH_VOL` sin que hubiera pasado nada. Ahora hace falta percentil alto **Y**
   estar a mas de 1,5x de su propia mediana.
3. **El objetivo del pullback estaba conceptualmente mal.** Estaba en la maxima previa del
   swing, asi que la distancia al objetivo ERA la profundidad del retroceso y
   `R:R = profundidad / (1,9 x ATR)`: para 2:1 harian falta retrocesos de 3,8 ATR, que en
   una tendencia no son retrocesos sino rupturas. **El setup no podia producir un candidato
   valido jamas.** Es un setup de CONTINUACION: el objetivo proyecta el impulso.
4. **El techo de altura del rango mataba la ruptura.** Con `MAX_RANGE_HEIGHT_ATR = 4.0` y
   la exigencia de R:R 2:1 (que pide altura de 2 x multiplo = 3,8 ATR), la ventana util era
   de 3,8 a 4,0 ATR: el setup no habria producido nada en su vida y habria parecido que el
   mercado no daba oportunidades. Subido a 8,0; quien descarta por altura insuficiente es
   el filtro de R:R, que es donde vive esa regla.

Ademas se anyadio **no perseguir**: cada punto que el precio ya ha corrido por encima del
techo se le resta al objetivo y no al stop. Medido: entrar un 3,5 % por encima bajaba el
R:R de 2,4 a 1,6.

### Medido con un recorrido hacia delante sobre datos reales

1.928 velas-simbolo (8 monedas x ~240 velas de 4 h), pasando solo las velas cerradas hasta
cada instante (sin look-ahead):

| Regimen | % del tiempo |
|---|---|
| transition | 25,5 % |
| trend_up | 25,1 % |
| unknown | 17,0 % (calentamiento del recorrido) |
| range | 14,9 % |
| high_vol | 13,6 % |
| trend_down | 3,9 % |

| Setup | Candidatos |
|---|---|
| pullback_trend | 186 |
| range_breakout | 25 |
| **mean_reversion** | **0** |

R:R mediana **3,74** (min 2,03, max 6,94). **5,25 candidatos/dia** entre las 8 monedas, con
el PRD pidiendo 1-5 operaciones/dia y tope duro de 6: el orden de magnitud es el correcto,
y ademas candidato no es operacion (despues filtran la IA y el motor).

En 14 de 190 velas hubo 4 o 5 candidatos a la vez, mas que los 3 huecos de la regla 4. Eso
no es un problema: **elegir entre candidatos es exactamente el trabajo de la IA** (PRD 6).

### LA REVERSION A LA MEDIA NO PRODUCE NI UN CANDIDATO, y es estructural

Sobre datos reales: **285 velas en regimen `RANGE`, 7 senyales, R:R mediana 0,91 y maxima
1,06**. Ninguna llega a 2,0.

La cuenta explica por que y no depende de los datos:

- objetivo = banda central, o sea unas 2 desviaciones tipicas desde el precio;
- stop = 1,9 x ATR;
- para R:R de 2 haria falta **desviacion de 1,9 ATR o mas**, y en un rango estrecho (el
  unico sitio donde este setup se activa) no pasa nunca.

**DECISION PENDIENTE DEL PROPIETARIO.** Opciones, con lo que cuesta cada una:

1. **Dejarlo como esta.** El setup existe, esta probado y no produce nada. La fase 6 lo
   confirma con datos. Coste: codigo muerto.
2. **Stop propio para este setup** (bajo el suelo del rango en vez de 1,9xATR). El
   dimensionado lo aguanta (`risk/sizing.py` calcula el nocional desde el stop REAL y el
   riesgo sigue siendo 0,50 $) pero rompe la uniformidad del stop, que fue una
   simplificacion mia, no una exigencia del PRD. Es la opcion con mas sentido tecnico.
3. **Objetivo en la banda alta** en vez de la central. Dobla el R:R a 1,8-2,1, o sea que
   seguiria justo. Y esperar el recorrido completo del rango es optimista.

Lo que NO se hace es bajar `min_reward_risk` para que salga: eso no descubre oportunidades,
solo acepta operaciones peores.

### Los setups del slider viven en dos sitios

El informe 4.6 da los setups permitidos por nivel (1: solo pullback; 2: mas reversion;
3-5: todos) y estan en `risk/limits.py` como **texto**, no importando `strategy.setups`:
el motor de riesgo no puede depender de la capa de estrategia. La duplicacion solo es
segura porque hay un test que comprueba que los dos lados dicen lo mismo.

## Fase 2 - baseline sin IA y ejecucion en papel (22/09/2026)

`strategy/baseline.py`, `portfolio/paper.py` y `scripts/replay_baseline.py`.

**El baseline es la mitad de CONTROL del experimento** que decide si la IA aporta algo
(informe 1.9). Por eso es deliberadamente tonto: coge el candidato con mejor R:R y nunca
toca `size_multiplier` (esa palanca es solo de la IA, PRD 6). Un baseline listo no serviria:
si pierde contra la IA no sabrias si es que la IA es buena o que el baseline era malo.
Desempata por `decision_id` para que sea reproducible; sin eso, dos ejecuciones sobre los
mismos datos podrian elegir distinto y la comparacion mediria tambien el azar.

### Las seis suposiciones del simulador, todas en contra

Un simulador optimista no falla: da buenas noticias. Cada suposicion se equivoca a proposito
en nuestra contra, y cada una tiene su test.

1. **Stop y objetivo en la misma vela -> gana el STOP.** Con OHLC no se sabe cual toco
   primero. Suponer el objetivo infla los resultados brutalmente; es la trampa mas comun
   del backtesting casero.
2. **La entrada limit se llena a SU precio, nunca mejor**, aunque el mercado abra por
   debajo y en la realidad te llenaran mas barato.
3. **El stop SI sufre los huecos**: si la vela abre por debajo, se sale en la apertura.
4. **El objetivo NO se beneficia de los huecos.** Asimetrico con el 3 a proposito: el hueco
   malo cuenta y el bueno no.
5. **Una entrada puede llenarse y saltar el stop en la MISMA vela.**
6. **Comisiones por pata:** entrada limit = maker, objetivo = limit = maker, stop = cruza
   el libro = **taker**. `strategy/costs.py` supone taker en la salida SIEMPRE, asi que el
   filtro previo es mas duro que la ejecucion real: descarta de mas, nunca de menos.

Los puntos 3 y 4 son los que hacen **visible el riesgo de hueco** de los setups con stop
estrecho, que es justo lo que habia que poder medir tras darle stop propio a la reversion.

### El recorrido completo funciona de punta a punta

`scripts/replay_baseline.py` encadena candidatos -> baseline -> motor de riesgo -> papel
sobre las velas reales, pasando en cada instante **solo las velas cerradas hasta entonces**.
32 dias, 191 velas de 4 h, 8 monedas:

| | |
|---|---|
| ordenes enviadas | 13 |
| candidatos vetados | 198 (regla 4: 194, regla 15: 6, regla 14: 4) |
| operaciones cerradas | 11 (0,35/dia) |
| aciertos | 55 % (6 objetivos, 5 stops) |
| expectativa | +1,305 R |
| P&L neto | +7,83 $ |
| comisiones | 0,27 $ (3 % del bruto) |
| drawdown maximo | 4,68 % |

**La regla 4 veta 194 veces**: con 5,3 candidatos/dia y solo 3 huecos, el cuello de botella
es el capital, no la generacion de senyales. Es lo esperado con 50 $.

### PERO ESOS NUMEROS NO SON UNA VENTAJA, Y CASI ME LOS CREO

El periodo (21/08 - 22/09/2026) fue un tramo **fuertemente alcista**: subieron las 8
monedas, con una media del +31,4 % y NEAR un +130 %. La comparacion que pide el informe 1.9
(metrica 7) lo deja claro:

| | |
|---|---|
| baseline sin IA | **+19,6 %** |
| comprar BTC y esperar | +10,6 % |
| comprar las 8 y esperar | **+31,4 %** |

**El baseline gana a BTC pero pierde contra no hacer nada.** Un sistema solo largo en un
mercado asi gana dinero por definicion; lo que mide ese +19,6 % es el mercado, no la
estrategia. Y son **11 operaciones**, que estadisticamente no son nada (el propio informe
1.8 dice que hacen falta cientos por grupo para distinguir seniales de ruido).

Por eso la comparacion contra comprar-y-esperar esta ahora **dentro del script**, no en un
analisis aparte: sin esas dos lineas, un "+19,6 %, profit factor 4,36" parece una ventaja.
El script avisa solo cuando el baseline rinde menos que la cesta.

**La prueba de verdad es un tramo lateral o bajista, y estos datos no lo tienen.** Eso no
se arregla con codigo: se arregla esperando a tener mas historia, que es exactamente para
lo que sirven las fases 3 y 6.

Nota de coherencia: el criterio de avance de la fase 2 que fijo el propietario pide operaciones de
papel **coherentes**, no rentables. Era el criterio correcto.

## Fase 2 - los dos agujeros que encontro la revision (22/09/2026)

Una pasada de revision sobre lo ya construido encontro dos piezas que parecian
hechas y no lo estaban. Las dos son el mismo patron: **codigo escrito, probado
y sin enchufar**, que es peor que codigo que falta porque parece que esta.

### 1. `strategy/filters.py` no lo llamaba nadie

Solo sus propios tests. El recorrido iba directo al generador de candidatos y se
saltaba la capa entera. No era un agujero de seguridad (el motor de riesgo es la
autoridad y vuelve a comprobar lo que importa), pero si:

- el **filtro de profundidad** no corria nunca, y ese filtro es justamente lo que
  sostiene la suposicion de impacto de mercado cero de `strategy/costs.py`;
- el **guardian de frescura** tampoco: `data_fresh` no lo ponia nadie;
- en la fase 3, los filtros son lo que evita quemar el presupuesto de la regla 18.

Tapado con `strategy/pipeline.py`, que encadena filtros -> candidatos y criba con
lo barato antes de calcular indicadores.

**Efecto medido:** los vetos de la regla 4 en el motor bajan de **194 a 7**,
porque ahora el filtro para la moneda antes de generar nada. Los filtros
rechazaron 1.135 veces por hueco ocupado, 71 por correlacion y 11 por cooldown.

**Y no cambio ni una operacion**: las mismas 11, el mismo P&L. Es lo que tenia
que pasar. Los filtros son una optimizacion, no una autoridad; si hubieran
cambiado alguna decision, seria que se han puesto a decidir. Hay un test que lo
comprueba comparando con el camino que se los salta.

### 2. Nadie calculaba las correlaciones

La regla 15 tiene dos mitades. La de exposicion funcionaba (tras arreglar su
brecha). La de correlacion **no habia vetado nunca nada**, porque
`RiskState.correlations` llegaba siempre vacio: el motor preguntaba y la
respuesta era 0,0 para todo.

Es el mismo patron que el invariante de exposicion que estaba escrito en la
cabecera de un test sin `@invariant()` detras.

Tapado con `features/context.py`. Dos decisiones:

- **Correlacion de RENDIMIENTOS, no de precios.** Dos series que suben
  correlacionan cerca de 1 en precio aunque suban por motivos distintos: eso es
  la tendencia comun, no la relacion. Hay un test que ensenya el caso: dos
  paseos con deriva fuerte dan 0,9+ en precio y casi 0 en rendimiento.
- **Sin muestra suficiente, el par NO se registra.** No como 0,0: una
  correlacion con 10 velas no es baja, es desconocida, y guardarla como cero le
  diria al motor que dos monedas son independientes sin que nadie lo haya
  comprobado.

**Medido el 22/09/2026** (7 dias de rendimientos horarios, 168 velas):

| par | correlacion |
|---|---|
| BTC / ETH | 0,84 |
| ETH / SOL | 0,84 |
| BTC / SOL | 0,81 |

**Los tres pares del grupo BTC/ETH/SOL pasan de 0,80**, asi que tener los tres a
la vez es exactamente lo que la regla 15 existe para impedir. Media general 0,45;
TRX es casi independiente de todo (0,26).

## Que pasa cuando el mercado BAJA (aclarado con el propietario el 22/09/2026)

**El bot no gana dinero cuando el mercado cae, y no es un fallo: es la regla 1.**

`Side` solo tiene `LONG`. No es que vender en corto este prohibido, es que **no
se puede ni escribir**. Y ningun setup acepta el regimen `trend_down`. Para
ganar con las caidas harian falta margen o futuros, que la regla 1 prohibe.

Lo que el bot SI hace en un mercado bajista:

1. **No entra**: el clasificador marca `trend_down` y ningun setup se dispara
   (medido: 3,9 % de las velas de la muestra).
2. **Corta rapido** con los stops que viven en el exchange (regla 13).
3. **Se cierra solo** por las reglas 7, 9 y 10 si el capital cae.

O sea: en un tramo bajista el objetivo es **conservar capital, no ganarlo**. El
mejor resultado posible es quedarse plano menos alguna operacion parada.

Junto con lo medido en el tramo alcista (rinde menos que comprar y esperar), la
descripcion honesta de lo que es Ploutos: **un sistema solo largo con gestion de
riesgo**. Su ventaja sobre comprar y esperar no es ganar mas, es caer menos.
Eso es coherente con el PRD, donde la rentabilidad es explicitamente secundaria.

## Fase 2 - el bucle de papel en vivo (22/09/2026)

`scripts/run_paper.py` + `deploy/ploutos-paper.service`, desplegado y en marcha.

### No toca las 72 h de la fase 1, y eso esta disenyado, no es suerte

La pregunta del propietario al desplegarlo fue si afectaba al test de 72 h que estaba
corriendo. Tres cosas lo evitan:

1. **`sync.sh` no reinicia nada.** Solo copia ficheros e IMPRIME el `systemctl
   restart` como sugerencia. El proceso vivo ya tiene su codigo cargado.
2. **Base de datos separada** (`var/ploutos-paper.db`). En SQLite-WAL los
   lectores no bloquean al escritor, pero dos ESCRITORES si compiten. Con
   `busy_timeout=5000`, una transaccion del bucle podria hacer que la ingesta
   esperase 5 s, fallara una escritura y perdiera una vela: un hueco, justo en
   lo que se esta midiendo. El bucle lee la base principal y escribe en la suya.
3. **La base principal se abre en modo `ro`** (`file:...?mode=ro`). Asi un
   INSERT por error es imposible, no solo improbable.

Y la unidad usa `Wants=` y no `Requires=` sobre la ingesta, en las dos
direcciones: si la ingesta cae, el bucle no cae con ella (se queda esperando
velas, que es lo correcto); y si el bucle falla, no arrastra a la ingesta.

**Verificado despues de desplegar:** ingesta `active`, **0 reinicios**, **0
huecos sin rellenar**, 16.023 velas. Intacta.

### Sobrevive a los reinicios, y se ha probado con `kill -9`

El criterio pide 72 h de operaciones coherentes y la unidad lleva
`Restart=always`, asi que los reinicios van a pasar. Si uno perdiera las
posiciones abiertas, esas 72 h no demostrarian nada: el simulador arrancaria
vacio cada vez y nunca cerraria una operacion que durase mas que el uptime.

El estado vive en la base de papel y un **cursor** dice hasta que vela se
proceso, para que al arrancar continue donde estaba en vez de empezar de cero
o reprocesar.

**Probado en el servidor:** `systemctl kill -s KILL` -> systemd reinicia (1
reinicio) -> la entrada pendiente de TRX y el cursor siguen ahi.

### Un solo bucle, compartido por el historico y el vivo

`portfolio/loop.py` tiene la secuencia una sola vez y la usan tanto
`scripts/replay_baseline.py` como `scripts/run_paper.py`. Si cada uno tuviera
su copia, se separarian con el tiempo y **las 72 h en vivo estarian midiendo
algo distinto de lo que se midio en el historico**, sin que nadie se entere.

Verificado: tras refactorizar el historico para usar el bucle compartido, los
numeros salen IDENTICOS (13 ordenes, 11 operaciones, +7,830 $).

### AVISO sobre lo que las 72 h pueden demostrar

Con velas de 4 h, 72 h son **18 velas**. A los 0,35 operaciones/dia medidos,
eso es **una operacion, quiza dos**. Las 72 h sirven para ver que el bucle
corre, que sobrevive a reinicios y que lo que decide tiene sentido. **No sirven
para sacar conclusiones estadisticas**, y el criterio que fijo el propietario pedia
"coherentes", no "rentables", que era lo correcto.

## El juez de las 72 h de papel (22/09/2026)

`scripts/check_paper.py` (logica en `portfolio/audit.py`). Igual que `check_gaps.py`:
exit 0 cumplido, 1 incoherente, 2 aun sin evidencia (menos de 72 h o cero ordenes).
**Es lo que hay que lanzar el viernes 25/09** para cerrar el criterio ampliado
(el procedimiento entero, con los cuatro criterios, en `docs/archivo/cierre-fase-2.md`):

    ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_paper.py'

La primera vela procesada es la de las 16:00 del 22/09, asi que las 18 velas
(72 h) se completan hacia las **16:00 UTC del 25/09**.

**No reutiliza el codigo que juzga**: re-simula cada orden contra las velas
reales y recalcula equity, comisiones y limites por su cuenta. Si llamara al
simulador o al motor, cualquier fallo de estos le daria la razon a su propio
error. Cada comprobacion tiene su prueba de mutacion en `tests/unit/test_audit.py`
(24 de 24 detectadas).

**Desde el 22/09/2026 22:05 UTC el bucle guarda CON QUE decidio** cada vela
(`002_context.sql`): el spread y la profundidad de cada moneda y las correlaciones
de 7 dias. Con eso el juez audita tambien la regla 16 y la mitad de correlacion de
la 15, cada una con su formula escrita aparte. Las ordenes anteriores (la de TRX de
las 16:00) salen como **SIN DATOS**: ni fallo ni cumplida. Solo queda fuera la
regla 17 (no hay serie del precio del USDC).

### Una correlacion SIN MEDIR cuenta como correlacionada (decidido, ver abajo)

Antes el motor hacia `correlations.get(pareja, 0.0)`: lo que no conocia lo trataba
como independiente, justo lo que `features/context.py` queria evitar al no
registrar las parejas sin muestra. El propietario eligio la opcion 2 el 22/09/2026 (ver
"Decisiones del propietario").

### Escribirlo destapo CINCO fallos, con la suite en verde

Ninguno lo cogio un test. Salieron de leer el bucle y la base del VPS con la
pregunta "que tendria que ser cierto aqui":

1. **Las reglas 10, 11 y 14 se olvidaban de todo al reiniciar.** El bucle llevaba
   en memoria las operaciones cerradas hoy y las recientes. Con `Restart=always`,
   un reinicio a media tarde ponia a cero la perdida del dia, el contador de
   operaciones, los cooldowns y la pausa. Ahora se sacan en cada vela de
   `broker.trades`, que es lo que se guarda: una sola fuente de verdad.
2. **Una pasada que fallaba a medias podia aplicar la misma vela dos veces.** El
   cursor no avanzaba pero el simulador en memoria si. Ahora se recarga de la base.
3. **Journal y estado iban en dos transacciones**: un corte entre las dos
   duplicaba decisiones al reintentar. Ahora `store.save_step`, una sola.
4. **Cada guardado reescribia la historia de la curva** con los contadores del
   momento (`INSERT OR REPLACE` sobre todas las filas).
5. **El equity de papel no restaba la comision de entrada** de las posiciones
   abiertas: ~0,015 $ por posicion, pero a favor nuestro. Y el test que lo cubria
   tenia el numero malo escrito como esperado.

Ademas, **el redondeo al lote perdia un lote entero por la coma flotante**
(0,58 TRX salia 0,57): ver `risk/types.py`. Y hypothesis encontro que el
tamanyo final salia con cantidades sucias (2,2779000000000003) que no son
multiplo del lote.

**PARA LA FASE 4:** `Instrument.round_price_down` no lo llama nadie. Los precios
de entrada **no se redondean al tick**, y el exchange rechaza un limite que no lo
sea. Hay que hacerlo en `execution/` justo antes de mandar la orden.

### El juez de la FASE 1 tambien estaba ciego (arreglado el 22/09/2026)

`check_gaps.py` buscaba huecos solo ENTRE dos velas guardadas y contaba las
esperadas de la primera a la ultima presente. Reproducido con el script real:
**con las ultimas 12 h sin ninguna vela decia "CRITERIO CUMPLIDO", cobertura
100 %**. O sea, no veia justo lo que las 72 h existen para detectar: que la
ingesta se muera. No tenia ni un test. Ahora las esperadas salen del reloj
(`data/coverage.py`) y `tests/unit/test_check_gaps.py` lanza el script de verdad
con cada tipo de hueco. Contra la base del VPS dice lo mismo que decia: 0 huecos.

### LA REGLA 17 NO PODIA SALTAR NUNCA (arreglado el 22/09/2026)

`RiskState.usdc_deviation_pct` valia **0,0 por defecto** ("medida y en paridad") y
nadie la calculaba. La regla y el filtro existian, con sus tests, y no podian vetar
nada ni en papel ni en real. Otra vez el patron "escrito, probado y sin enchufar".

Ahora el valor por defecto es `None` = **desconocida, y desconocida veta**: si algun
dia alguien se olvida de calcularla, el bot deja de abrir y se nota, en vez de
operar a ciegas. `TradingLoop.step` la pide como argumento obligatorio.

- `features/usdc.py`: el calculo (puro). `data/usdc.py`: los cuatro libros.
- El bucle de papel la lee de OKX en cada vela y la guarda en `paper_usdc`
  (`003_usdc.sql`); el juez la audita. Verificado desde el VPS: -0,014 %.
- **Es la paridad de AHORA, no la de la vela**: si el bucle se pone al dia de
  varias velas tras una caida, todas usan la misma lectura. No hay historia de USDC.
- **El recorrido historico SUPONE la paridad** (lo imprime en la cabecera): sin
  historia del precio, con `None` vetaria todo el recorrido.
- **Para la fase 4:** esto deberia salir de la ingesta, que es la capa de datos. No
  se hizo ahi porque obligaba a reiniciar la ingesta en mitad de las 72 h.

### EL BUCLE DE PAPEL VIVIA SIEMPRE EN NORMAL (arreglado el 22/09/2026)

`core/modes.py` (la maquina de modos del PRD seccion 5) existia y estaba probada,
pero el bucle no la usaba: el modo era una constante. Consecuencias: la regla 7 no
ENCLAVABA (con el equity rebotando a 26 $ se volvia a abrir) y al llegar a la
perdida diaria no se entraba en CLOSE_ONLY_DAILY ni se cancelaban las pendientes.
Dinero no se perdia (el motor ya vetaba por las reglas 7, 8 y 10), pero la fase 4
se iba a construir sobre un bucle que no habia cambiado de modo ni una vez.

Ahora, en cada vela y ANTES de decidir (`TradingLoop._update_modes`):
- **CLOSE_ONLY_CAPITAL**: dos lecturas de equity seguidas en o bajo 25 $. Enclavado:
  se guarda en `paper_mode_changes` (`004_modes.sql`) y sobrevive a los reinicios.
  Solo sale a mano:
  `sudo -u ploutos .venv/bin/python scripts/run_paper.py --reset-capital "motivo"`
  y despues `systemctl restart ploutos-paper`. En papel hay una lectura por vela
  (dos lecturas = 8 h); en real seran cada 15 s.
- **CLOSE_ONLY_DAILY**: perdida realizada del dia >= 3 $. Sale sola a las 00:00 UTC.
- **Al pasar de NORMAL a cualquier solo cierre se cancelan las pendientes.**
- QUOTA (Claude, fase 3), DEGRADED (conexion con el exchange, fase 4) y HALTED no
  aplican a este bucle todavia.

El juez deduce los modos por su cuenta (equity y operaciones; del journal solo lee
los resets manuales, que no se pueden deducir) y comprueba que no se entro en solo
cierre y que las pendientes se cancelaron. Mutaciones: quitar la cancelacion, el
enclavamiento o la reconstruccion al arrancar ponen tests en rojo.

### Simulacro de restauracion (22/09/2026)

Nunca se habia restaurado una copia de verdad; solo se comprobaba que abria. Se
hizo: copia en el VPS a mano (`systemctl start ploutos-backup`, el mismo servicio
del temporizador), `fetch-backup.sh` al portatil, restaurada en un directorio
temporal, y sobre ella los dos jueces y `run_paper.py --status`. **Dicen lo mismo
que el VPS**, y el bucle arrancado sobre la copia recupera su estado exacto (la
orden de TRX, el cursor, el modo). Para repetirlo:

    bash deploy/fetch-backup.sh ploutos
    # descomprimir las dos copias mas recientes y:
    .venv/Scripts/python.exe scripts/check_gaps.py --db <copia> --until <AAAA-MM-DDTHH:MM de la copia>
    .venv/Scripts/python.exe scripts/check_paper.py --main-db <copia> --paper-db <copia de papel>
    .venv/Scripts/python.exe scripts/run_paper.py --status --main-db <copia> --paper-db <copia de papel>

`--until` hace falta: una copia de hace horas, juzgada ahora, tiene "huecos" al
final que no son de la ingesta, sino la edad de la copia.

**El simulacro encontro que `fetch-backup.sh` habria fallado cada semana** desde la
primera copia de la base de papel: la marcaba como "no restaurable" (buscaba la
tabla `candles`) y luego reventaba en Windows por no cerrar la conexion. La
comprobacion vive ahora en `scripts/verify_backups.py`, con tests.

**OJO:** el servicio de copias ejecuta `/usr/local/bin/ploutos-backup`, que es una
COPIA de `deploy/backup.sh` hecha por `install.sh`. Si se cambia `deploy/backup.sh`
hay que volver a pasar `install.sh`, o el VPS seguira con la version vieja. A
22/09/2026 son identicos.

### Que se guarda y donde (pregunta del propietario)

Nada se borra: ni la ingesta ni el bucle tienen ningun `DELETE` sobre historia
(los dos `DELETE` de `portfolio/store.py` reescriben el estado VIVO, ordenes y
posiciones, dentro de la misma transaccion). `backup.sh` copia las DOS bases cada
noche a las 03:15 UTC con 14 dias de rotacion en el servidor, y la tarea semanal de
Windows las baja al portatil. Disco del VPS el 22/09: 3,4 GB usados de 58 GB.

## Dos errores de despliegue que costaron una vuelta (22/09/2026)

1. **CRLF otra vez, y van dos.** Escribi `install.sh` con `Path.write_text()`
   desde Windows, que traduce los saltos de linea por defecto. En Linux fallo
   con un error de sintaxis que no se parece en nada a la causa.
   **`.gitattributes` NO protege aqui**: `sync.sh` copia el arbol de trabajo
   con tar, no un checkout de git, asi que lo que esta en el disco de Windows
   es lo que llega al servidor. Ahora hay un test que rechaza CRLF en
   `deploy/*.sh`, `*.service` y `*.timer`.

2. **`load_settings()` dependia del directorio desde el que arrancabas.** La
   ruta por defecto era relativa. Con systemd no se notaba porque la unidad
   fija `WorkingDirectory`, pero lanzar un script a mano desde otro sitio
   fallaba con un `PermissionError` sobre una ruta relativa. Ahora la ruta por
   defecto es absoluta, sacada de donde vive el modulo.

## La invariante que me habia inventado mal (22/09/2026)

Anyadi "portfolio no importa strategy" sin comprobarlo contra el informe, y el
propio test de arquitectura la atrapo al intentar meter el orquestador en
`portfolio/`. **Contradice el informe seccion 1.7**, que pone el coste de
oportunidad en `portfolio/` y lo calcula comparando `EV_nuevo(candidato)`
contra las posiciones abiertas: sin ver candidatos no se puede hacer.

Retirada y sustituida por una a nivel de FICHERO, que es lo que de verdad se
queria decir: **el ejecutor (`portfolio/paper.py`) no importa `strategy`,
`features` ni `ai`**. Recibe veredictos ya aprobados y los simula. El
orquestador (`portfolio/loop.py`) si puede: es su trabajo encadenar capas.


## El multiplo de ATR, MEDIDO (22/09/2026)

`CLAUDE.md` prometia fijarlo "midiendo el ATR real, no a ojo". Hecho, sobre ~300 velas
de las 8 monedas descargadas de OKX:

| tf | ATR% medio | stop con 1,5xATR | posicion resultante | multiplo para 15 $ |
|---|---|---|---|---|
| 5m | 0,381 % | 0,57 % | **87 $** | 8,7x |
| 15m | 0,675 % | 1,01 % | **49 $** | 4,9x |
| 1h | 1,009 % | 1,51 % | **33 $** | 3,3x |
| **4h** | **1,779 %** | **2,67 %** | **18,7 $** | **1,9x** |

Confirma la decision de dimensionado con numeros reales: **en 4 h, 1,9xATR da un stop
del 3,33 % y una posicion de ~15 $**. En `config/settings.yaml`, `strategy.atr_multiple`.

**Los timeframes cortos quedan descartados por aritmetica, no por gusto:** en 5 m
harian falta stops de 8,7xATR para no pasarse del tamanyo, y un stop tan ancho en
relacion al movimiento normal ya no es un stop tecnico, es un numero arbitrario.

**Duda sobre 1 h: MEDIDA el 22/09/2026, y apunta a que no compensa.**

El razonamiento previo era aritmetico: 1 h necesita 3,3xATR, asi que para un R:R de
2:1 el objetivo tendria que estar a 6,7 %, que en velas de 1 h es un movimiento
grande. En 4 h ese mismo 6,7 % son ~3,8 ATR, mucho mas alcanzable.

Comparado con el recorrido del baseline sobre **la MISMA ventana** (14-22/09,
8 dias, las mismas 8 monedas; con `--since` para que la comparacion sea justa, que
sin eso eran 32 dias contra 8):

| | 4 h | 1 h |
|---|---|---|
| operaciones | 7 | 9 |
| aciertos | 57 % | 44 % |
| expectativa | **+1,421 R** | +0,331 R |
| P&L neto | +5,10 $ | +0,75 $ |
| **comisiones** | **4 % del bruto** | **28 % del bruto** |
| profit factor | 5,00 | 1,40 |
| MFE medio | +11,09 % | +3,10 % |

**4 h gana en todas las metricas.** Y se ve el mecanismo: el MFE medio de 1 h es
+3,10 % contra +11,09 %, o sea que captura movimientos mucho mas pequenyos, asi
que la MISMA comision se come siete veces mas del beneficio. Es exactamente lo que
avisa el informe seccion 2.2 ("objetivo de 1-5 operaciones al dia, no 10-20").

**Repetido el 22/09/2026 con la historia de 1 h completa y la regla nueva de
correlaciones**: 4 h, identico (7 op., +1,421 R, +5,10 $). 1 h, algo PEOR que antes:
10 op., 40 % de aciertos, +0,266 R, +0,18 $, comisiones el **66 % del bruto** y profit
factor 1,08. La conclusion se refuerza.

**NO es concluyente**: son 7 y 10 operaciones en un solo tramo alcista. Pero ahora
la comparacion es justa y coincide con la aritmetica. La decision sigue siendo de
la fase 6; lo que cambia es que ya no hay que tomarla a ciegas.

**El ATR depende del regimen de mercado**, asi que estos multiplos valen para lo medido
y habra que revisarlos. `risk/sizing.py` es robusto igualmente: calcula el nocional a
partir del stop REAL, sea cual sea, y el riesgo nunca pasa del permitido.
