# Preparacion de la fase 4: stop y objetivo en el exchange

Escrito el 23/09/2026, **antes** de la fase 4 y sin claves: solo el codigo de `ccxt`
instalado (4.5.82), la documentacion publica de OKX (`www.okx.com/docs-v5/en/`,
leida entera ese dia) y peticiones **construidas en local sin enviarlas**
(`ccxt.okx().create_order_request(...)` con los mercados publicos).

Es la parte mas delicada de la fase 4: la regla 13 ("stop-loss y take-profit
SIEMPRE en el exchange, creados al abrir") es la que protege el capital cuando el
bot no esta. Lo que aqui pone "verificado" lo esta en el codigo o en la
documentacion; lo que pone "PROBAR EN DEMO" no se puede saber sin ejecutarlo.

## 1. `ccxt` convierte una OCO de spot en una orden de MARGEN (regla 1)

`ccxt/okx.py`, `create_order_request`, lineas 3336-3339:

> si una orden condicional u OCO lleva `tdMode = 'cash'`, la cambia por
> `marginMode`, que por defecto es `'cross'`. El comentario dice que OKX les
> devolvia `51000 Parameter tdMode error` con `cash`.

Peticiones construidas en local para `BTC/USDC` (sin enviar):

| Como se pide | `ordType` | `tdMode` |
|---|---|---|
| `stopLossPrice` + `takeProfitPrice` (la forma "unificada" de ccxt) | `oco` | **`cross`** |
| Solo `stopLossPrice` | `conditional` | **`cross`** |
| Lo mismo con `params={"tdMode": "cash"}` | `oco` | `cash` |
| Con `options={"defaultMarginMode": "cash"}` al crear el exchange | `oco` | `cash` |
| Entrada `limit` con `stopLoss`/`takeProfit` adjuntos | `limit` | `cash` |

La documentacion de OKX dice que en **modo spot** el unico `tdMode` para SPOT es
`cash`; `cross` en SPOT es "Cross SPOT" de los modos de margen. Es decir: segun el
modo de la cuenta, la orden por defecto de ccxt **falla** (cuenta solo spot) o
**es una orden de margen** (cuenta con margen activado). Lo segundo es exactamente
lo que prohibe la regla 1.

**Propuesta para la fase 4** (no hecho, es codigo de la fase 4):
- `options={"defaultMarginMode": "cash"}` al crear el exchange **y** `tdMode: "cash"`
  explicito en cada orden: dos sitios, como pide la convencion de las reglas duras.
- Una comprobacion en `execution/` justo antes de enviar: cualquier peticion con
  `tdMode` distinto de `cash` se rechaza. Es el mismo punto donde la regla 3 revisa
  la whitelist.
- Un test que construya en local TODAS las peticiones que el bot hace (entrada, OCO,
  cancelacion) y compruebe `tdMode == "cash"`. No necesita claves.
- **PROBAR EN DEMO:** que OKX acepta la OCO con `cash` en una cuenta solo spot (el
  comentario de ccxt dice que no; la documentacion dice que si).

## 2. El `decision_id` no vale como `clOrdId`

OKX: el `clOrdId` y el `algoClOrdId` son "una combinacion de alfanumericos
(mayusculas y minusculas), solo numeros o solo letras, **de hasta 32 caracteres**".
El `decision_id` lleva guiones (`d-20260922T0000-near-pb`, 23 caracteres).

- Hace falta una traduccion **determinista** (p. ej. quitar los guiones:
  `d20260922T0000nearpb`, 20 caracteres) y otra distinta para la OCO de esa misma
  decision (un sufijo), para que la cadena decision -> orden -> OCO siga siendo
  trazable a mano.
- Sin `clOrdId` propio, ccxt pone el suyo con su identificador de broker
  (`6b9ad766b55dBCDE`) y ademas un `tag`. Hay que pasar siempre el nuestro.

## 3. El `clOrdId` NO sirve de idempotencia por si solo

OKX: el `clOrdId` "tiene que ser unico entre las ordenes PENDIENTES; cuando una
orden llega a un estado final (llenada, cancelada) **se puede reutilizar**".

Consecuencia: si el bot envia una orden, se corta la conexion y la orden se llena
antes de que el bot reintente, **reenviarla con el mismo `clOrdId` crea una orden
NUEVA**, no un error de duplicado. La idempotencia de la fase 4 tiene que
**consultar primero** (`GET /api/v5/trade/order?clOrdId=...`) y solo enviar si no
existe. Consultar antes de reenviar, nunca reenviar a ciegas.

## 4. Dos formas de poner el stop, y el hueco de los llenados parciales

**a) TP/SL adjuntos a la entrada** (`attachAlgoOrds`): se envian con la orden limit
de entrada y OKX crea la orden algoritmica al llenarse. Documentacion:
- "se generan solo cuando esta orden se llena; si la madre se cancela antes de
  cualquier llenado, no se genera ninguna";
- el `attachAlgoClOrdId` "pasa a la orden algoritmica **cuando la orden se llena
  completamente**".

**No dice que pasa con una entrada llenada A MEDIAS que luego se cancela**, y el
bot cancela las entradas que caducan (`ENTRY_BARS_TO_LIVE`). Si en ese caso no hay
stop para la parte llenada, es una posicion sin proteccion: la regla 13 rota.

**b) OCO independiente despues del llenado** (`POST /api/v5/trade/order-algo`,
`ordType=oco`): el bot la crea al ver el llenado. Hay un rato sin stop (lo que
tarda en verlo) pero la cantidad es la que de verdad se lleno.

**Propuesta:** la que ya pide el PRD en la seccion 5 ("verificar/crear la OCO de
cada posicion"): hacer (a) si el demo demuestra que funciona, y la reconciliacion
(al arrancar y cada 5 min) comprueba en todo caso que **cada posicion tiene una OCO
que cubre su cantidad**, y si no, la crea (b). **PROBAR EN DEMO:** entrada llenada a
medias y cancelada, con TP/SL adjuntos: se crea algo para la parte llenada?
**Resultado (02/10, seccion 11):** si, pero al CANCELAR el resto; mientras esta a medias, todo indica que no.

## 5. La comision se cobra en la moneda que RECIBES

Cuenta con `feeType = 0` (el valor por defecto): "la comision se cobra en la
moneda que recibes". Comprar 0,15 ETH con un 0,10 % de comision deja **0,14985
ETH**. Una OCO de venta de 0,15 ETH pide mas de lo que hay.

- Opcion 1: la OCO vende lo que de verdad hay (llenado menos comision, redondeado
  hacia abajo al lote). Deja polvo de la moneda en la cuenta.
- Opcion 2: `feeType = 1` ("la comision siempre en la moneda de cotizacion; solo
  spot"), con `POST /api/v5/account/set-fee-type`. La cantidad comprada es exacta y
  la contabilidad coincide con la del simulador de papel, que ya cobra la comision
  en dolares. **Es un ajuste de la cuenta: lo decide el propietario.**

Ademas, las ordenes TP/SL "**no congelan saldo**" al ponerse: el saldo de la moneda
sigue apareciendo libre. Si algo lo gastara, la OCO fallaria al saltar. El bot no
opera nada mas en esa moneda (maximo 1 posicion por simbolo), asi que no deberia
pasar, pero la reconciliacion tiene que comparar saldo y cantidad de la OCO.

## 6. El objetivo: `maker` en el modelo, `taker` si no se pide bien

El modelo de costes y el simulador cobran el objetivo como **maker** (sale en una
orden limit). En la OCO de OKX el objetivo puede ser de dos tipos (`tpOrdKind`):
- `condition` (el valor por defecto): al tocar el precio de disparo lanza una
  orden; con `tpOrdPx = -1` es **a mercado (taker)**, que es lo que hace ccxt por
  defecto.
- `limit`: el objetivo se queda en el libro como orden limit (maker) y el stop
  queda "enlazado" (la documentacion lo llama `linkedAlgoOrd`).

En el recorrido del baseline de 4 h, el 55 % de las salidas son objetivos. Si en
real salen como taker, el coste de cada una sube 0,10 puntos (0,20 % contra 0,10 %
desde el 25/09) y el modelo seria optimista. **PROBAR EN DEMO** que la OCO de spot
admite `tpOrdKind = limit`. Si no, corregir el modelo de costes antes de la fase 6.
**Resultado (02/10, seccion 11): NO lo admite (`51094`).** Precision: el filtro de costes (regla 16) ya suponia la
salida taker; los que suponen maker en el objetivo son el simulador de papel y la M1 de la fase 6.

## 7. Otros datos verificados

- **Disparo del stop:** para SPOT solo existe el ultimo precio (`last`), segun la
  seccion de ordenes trigger; `index` y `mark` son de derivados. ccxt usa `last` por defecto. Consecuencia: una mecha en
  OKX dispara el stop aunque el resto del mercado no la tenga.
- **`slOrdPx = -1`** = el stop sale a mercado (taker), que es lo que supone el
  modelo. Un stop limit podria no llenarse en una caida rapida: la propuesta es a
  mercado.
- **Tope:** 100 ordenes TP/SL pendientes por instrumento. El bot tiene como mucho
  una por simbolo: no aplica.
- **Limite de peticiones:** 20 ordenes algoritmicas cada 2 s por instrumento.

## 8. Lista para el demo (fase 4)

Todo con los 5 pares que el demo tiene contra USDC (BTC, ETH, SOL, DOGE, NEAR) y
con importes minimos.

1. OCO de spot con `tdMode = cash` en la cuenta de demo: se acepta? (seccion 1)
2. La misma sin `tdMode`: confirmar que ccxt manda `cross` y ver que contesta OKX.
3. Entrada limit con TP/SL adjuntos, llenada entera: se crea la OCO? con que ids?
4. Entrada limit con TP/SL adjuntos, llenada a medias y cancelada: que pasa con la
   parte llenada? (seccion 4: el caso peligroso)
5. `clOrdId` reutilizado despues de llenarse: crea una orden nueva? (seccion 3)
6. Cantidad recibida al comprar con `feeType = 0`, y OCO por la cantidad de la
   orden: que hace OKX al saltar? (seccion 5)
7. OCO con `tpOrdKind = limit`: sale como maker el objetivo? (seccion 6)
8. Cancelar la OCO y volver a crearla (lo que hara la reconciliacion).
9. **Con que se paga en el libro unificado** (anyadida el 01/10, seccion 9): entrada limit en `X-USDC` SIN
   `tradeQuoteCcy` y otra CON `tradeQuoteCcy: "USDC"`; y la OCO de cada una igual. Comprobar en el saldo y en el
   llenado que se paga y se cobra en USDC (no en USD, USDG ni RLUSD), y que la cantidad y la comision cuadran
   (con `feeType = 1`). Si la OCO no acepta `tradeQuoteCcy`, apuntar que contesta OKX.

## 9. El libro unificado en dolares y `tradeQuoteCcy` (01/10/2026)

Desde el 30/09 OKX junta en el libro `X-USDC` a quien paga con USD, USDC, USDG o RLUSD, como si valieran lo mismo
(`hallazgos-fase-3-4.md` 5d; `tradeQuoteCcyList` de los 8 de la whitelist: `USDG`, `USD`, `USDC`, `RLUSD`). Con que
moneda se paga lo dice el parametro `tradeQuoteCcy` de la orden. Changelog de la API (2026-09-30): "por defecto, la
moneda de cotizacion del `instId`", es decir, USDC en `X-USDC`. No dice nada de las ordenes algoritmicas (OCO).

**Propuesta (decide el propietario el 02/10, con el OK a la fase 4):**
- `execution/peticiones.py` manda `tradeQuoteCcy: "USDC"` EXPLICITO en la entrada y en la OCO, igual que `tdMode`.
- `execution/guardia.py` rechaza una peticion sin ese valor, o con otro: si OKX cambiara el valor por defecto, el bot
  pagaria con otra moneda sin decirlo, y la cuenta de la regla 6 (equity en USDC) dejaria de cuadrar.
- La prueba 9 del demo decide si la OCO lo acepta; si no lo acepta, se quita de la OCO y se apunta por que.

## 10. Primera pasada de las pruebas del demo (02/10/2026, 14:14 UTC)

Script: `scripts/pruebas_demo.py` (rama `fase-4-piezas-puras`), ejecutado en el VPS desde `/tmp`, sin tocar
`/opt/ploutos`. Resultado completo en el JSON de esa pasada.

- **Ninguna compra salio: `50123` ("This API Key does not have trading permission for the Crypto")** en NEAR y en
  ETH; una sonda despues (compra post-only al 50 % del precio, que no se llena) da lo mismo en las CINCO monedas del
  demo. La clave autentica, lee y no tiene retirada (`comprobar_cuenta_demo.py`), pero no deja operar ninguna.
  Sospecha: entre las monedas permitidas de la clave (el 23/09 se eligieron 6) no esta USDC, la de cotizacion.
  No hay API para leer esa lista: lo mira el propietario en la web del demo.
- **Prueba 2 (sin enviar, a proposito):** ccxt sin `tdMode` construye la OCO en `cross`, con `tag` y con su
  `clOrdId` de broker; la guardia la rechaza por los cuatro motivos. La cuenta demo esta en `acctLv = 1` (modo spot:
  OKX la rechazaria). Hecha.
- El saldo del demo quedo exactamente igual y sin ordenes pendientes.
- Las pruebas 1, 3-9 quedan por hacer cuando la clave deje operar.

- **Resuelto el mismo dia:** el propietario cambio las monedas permitidas de la clave en la web del demo; a las 20:35 UTC la
  misma sonda deja operar las cinco (orden aceptada y cancelada). Resultados en la seccion 11.

## 11. Segunda pasada: las 9 pruebas, HECHAS (02/10/2026, 20:35 UTC)

Mismo script (rama `fase-4-piezas-puras`, commit 298762b), en el VPS desde `/tmp`, NEAR/USDC salvo la prueba 4 (BTC).
Respuestas de OKX tal cual en `docs/archivo/pruebas-demo/resultado-02-10.json` (y la repeticion de la 4 en
`resultado-02-10-prueba4b.json`). Coste para el demo: -0,49 USDC y 0,00000001 BTC de polvo (el redondeo al lote al
vender). Al acabar, 0 ordenes y 0 OCO pendientes (comprobado aparte).

| # | Pregunta | Respuesta de OKX | Que decide |
|---|---|---|---|
| 1 | OCO de spot con `tdMode = cash` | **Aceptada** (`sCode 0`), `live`, `tradeQuoteCcy USDC` sin pedirlo | La OCO de `peticiones.proteccion` vale tal cual |
| 2 | La misma sin `tdMode` | No se envia: ccxt pone `cross` + `tag` + su `clOrdId`; la guardia la rechaza por 4 motivos; cuenta en `acctLv 1` (spot) | Hecha en la primera pasada (seccion 10) |
| 3 | Entrada con TP/SL adjuntos, llenada entera | **OKX crea la OCO** al llenarse (mismo milisegundo), `ordType oco`, con NUESTRO `algoClOrdId`, por la cantidad entera, `tpOrdKind condition` | La forma (a) de la seccion 4 funciona |
| 4 | Lo mismo llenada A MEDIAS y cancelada | Al cancelar el resto, **OKX crea la OCO por la parte llenada** (0,00012135 de 0,00018202 BTC) con nuestro `algoClOrdId` y un `algoId` NUEVO. Su `cTime` es el de la cancelacion + 1 ms | Ver "el hueco del parcial", abajo |
| 5 | `clOrdId` reutilizado tras llenarse | **Crea una orden NUEVA** (otro `ordId`), y se llena; la consulta por `clOrdId` devuelve ya la nueva | Confirmado: consultar ANTES de reenviar (seccion 3) |
| 6 | `feeType = 1`: cantidad exacta | **Exacta**: pedidas 2,139 NEAR, recibidas 2,139; la comision, en USDC (`feeCcy USDC`) | Decision 2 de la fase 4, confirmada |
| 7 | Objetivo como limit (`tpOrdKind = limit`) | **NO SE PUEDE**: `51094` "You can't place TP limit orders in spot, margin, or options trading". Sin `tpTriggerPx`: `51000` | El objetivo sale a MERCADO (taker). Ver abajo |
| 8 | Cancelar la OCO y recrearla con el mismo id | Cancelar por `algoClOrdId` **funciona**; recrearla con el mismo `algoClOrdId` tambien (otro `algoId`) | La conciliacion puede cancelar y recrear por nuestro id |
| 9 | `tradeQuoteCcy` en el libro unificado | Aceptado en la entrada (9a) y en la OCO (9b). Con y sin el, se paga en USDC: el saldo de USD (5.000) no se movio | Mandarlo explicito y que la guardia lo exija (decision del 02/10) |

**Lo que cambia algo:**

1. **El objetivo es taker (prueba 7).** El filtro de la regla 16 (`strategy/costs.py`, `risk/types.py`) YA supone la
   salida taker: no deja entrar nada que no cubra eso. Pero el **simulador de papel** (`portfolio/paper.py`, salida
   por objetivo = maker) y la **M1 de la fase 6** (`portfolio/comparacion.py`, igual) cobran el objetivo como maker:
   son optimistas en 0,10 puntos de comision (y la mitad del spread) en cada salida por objetivo. Con un stop del
   ~3,3 %, unos **0,03 R por objetivo**; las dos carteras y los dos lados de la M1 llevan el mismo sesgo. Decide el propietario
   cuando se corrige (la muestra de la fase 6 esta en marcha).
2. **NEAR paga el doble en el DEMO.** `GET /api/v5/account/trade-fee` par por par: BTC, ETH, SOL y DOGE (grupo 12)
   0,10 % / 0,20 %; **NEAR-USDC (grupo 13) 0,20 % / 0,35 %**, y asi se cobro (0,035 USDC en 10 $). En la cuenta REAL
   (`groupId` publico de `eea.okx.com`) las 298 parejas contra USDC, NEAR incluida, son del grupo 12: es cosa del
   demo. `comprobar_cuenta_demo.py` miraba solo BTC; ahora mira los cinco y da "NO se opera" por NEAR (decision del
   23/09). Decide el propietario que hace el demo con NEAR.
3. **El hueco del parcial (prueba 4).** La documentacion dice que la OCO adjunta pasa a existir "cuando la orden se
   llena completamente"; en la prueba 3 y en la repeticion (4b, que se lleno entera en 0,7 s) nacio al llenarse, y en
   la 4 nacio al CANCELAR. Todo indica que **mientras la entrada esta a medias, lo llenado no tiene stop**; no se pudo
   ver directamente (en la repeticion el libro del demo se repuso y se lleno entera). Con entradas que viven hasta 3
   velas (12 h), un parcial podria pasar horas sin proteccion: la regla 13 rota. Decide el propietario como se cierra el hueco
   (pieza b).

Detalles para las piezas:
- La OCO creada desde la entrada guarda NUESTRO `algoClOrdId` (no el `attachAlgoId` de la orden): la conciliacion
  la encuentra por nuestro id.
- El demo llena siempre al mismo precio y en los mismos trozos (tres compras seguidas: `avgPx` 4,6734988 y ultimo
  trozo 1,067): su libro no se parece al real. **El deslizamiento del demo no sirve para medir nada.**
- `51400` al cancelar una orden ya llenada: no es un error del bot (consultar el estado y seguir).

**Decidido por el propietario el 02/10 (las tres recomendadas):** (1) el objetivo taker en el papel y la M1, despues del veredicto
de la fase 6; (2) NEAR solo en papel en el demo, comision comparada par por par; (3) entrada a medias -> cancelar el
resto en el momento. Detalle en `diseno-fase-4.md`.

## 12. El demo no es el mercado real (02/10/2026, datos publicos)

Medido al empezar el ejecutor (pieza c), porque las ordenes de papel salen de precios del mercado REAL y se envian al
DEMO:

| Par | Bid demo contra real (3 lecturas) | Spread del demo | Tick real -> demo | Minimo real -> demo |
|---|---|---|---|---|
| BTC-USDC | 0,000 % | 0,02 % | 0,1 -> **1** | 0,0001 -> 0,00001 |
| ETH-USDC | -0,03 a -0,05 % | 0,08-0,11 % | 0,01 -> **1** | igual |
| SOL-USDC | -0,02 a -0,06 % | 0,085 % | 0,01 -> **0,1** | igual |
| DOGE-USDC | 0 a -0,10 % | 0,11-0,22 % | 0,00001 -> **0,0001** | igual |
| NEAR-USDC | -0,22 a -0,28 % | 0,47-0,56 % | igual | igual (lote 0,001) |

- El demo SIGUE al mercado real de cerca (salvo NEAR, que ademas va solo en papel), pero con un libro artificial: ticks
  10 veces mas gruesos y spreads mas anchos.
- **El ejecutor ajusta cada orden a los ticks y lotes del DEMO** (`execution.precios.al_tick` con el instrumento del
  demo: entrada hacia abajo, stop y objetivo hacia arriba). En ETH, hasta 1 $ (0,04 %); en DOGE, hasta un 0,11 %.
- **El spread de la regla 16, de la ingesta (mercado real)**, como decidio el propietario ("el mercado, de la ingesta"): con el del
  demo, ETH y DOGE quedarian vetados casi siempre (> 0,10 %) por un libro que no es el de verdad.
- Consecuencia para la fase 4: el demo prueba la CADENA (ordenes, OCO, conciliacion, reglas con datos del exchange),
  no los costes ni los llenados. Lo que el demo gane o pierda contra el papel no mide nada de la estrategia.

## 13. Prueba 10: una OCO que SALTA (03/10/2026, 09:40-10:13 UTC)

Con `ploutos-exec` parado (la semana acababa de empezar: se vuelve a arrancar con una foto nueva). Respuestas tal
cual en `docs/archivo/pruebas-demo/resultado-03-10-prueba10*.json`. Cuatro intentos:

1. **OCO con el objetivo a 2 $ del ultimo precio, y despues con el stop a 2 $: ninguna salto en 24 min.** En el demo el
   `last` (el precio con el que saltan los stops en spot) **casi no se mueve**: de 84.590 a 84.578 en 24 min. En el demo
   una OCO puede tardar mucho en saltar aunque el libro se mueva; en el mercado real, no.
2. **Objetivo en el mejor ask: OKX rechaza la OCO, `51279` "TP trigger price cannot be lower than the last price".**
   Nuestra propia compra habia subido el `last` por encima del ask.
3. Stop en el mejor bid y una venta minima a ese precio: la venta se lleno 1 $ por encima del stop; no salto.
4. **Stop un tick por encima del mejor bid: SALTO** (`effective`, `actualSide: "sl"`).

**Lo que da OKX de una OCO que salta:** `state: effective`, `actualSide` (sl | tp), `actualSz`, `triggerTime`, y el
`ordId` / `ordIdList` de la orden que lanza; **`actualPx` llega VACIO**. La orden lanzada: venta `market`, `tdMode cash`,
`tradeQuoteCcy USDC`, `avgPx` 84.574, comision en USDC, **NUESTRO `algoClOrdId`** y un **`clOrdId` de OKX
(`O3976871216119152640`)**, no el nuestro.

**Lo que cambia en el ejecutor:**
- El precio y la comision de salida, de la orden lanzada (por su `ordId`): ya era asi; `actualPx` no se usa.
- **Arreglado:** una orden con nuestro `algoClOrdId` es parte de su OCO. Si la conciliacion la pillaba viva, su `clOrdId`
  "O..." habria salido como orden AJENA (descuadre). Test nuevo; el simulador la reproduce tal cual.
- **Decidido por el propietario el 03/10 (opcion A):** si al CREAR o rehacer una OCO el precio ya paso el objetivo (o el stop),
  OKX la rechaza (`51279`); el ejecutor mira el ULTIMO precio y, si ya toco el objetivo o el stop, vende a mercado con
  el id de salida. El juez lo acepta solo si el llenado esta mas alla del stop o del objetivo de la orden de papel.
  Solo puede pasar en el camino de respaldo (la OCO adjunta la crea OKX al llenarse, al precio de entrada).
