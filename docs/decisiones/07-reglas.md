# Decision 7: las 19 reglas, una a una (15/10/2026)

Repaso de las reglas duras del PRD v2 (seccion 4) con las decisiones 1-6 (escalar, euros, BTC y ETH, la IA de freno).
El propietario prefirio verlas una a una (opcion b). Los numeros de las que "dependen de la estrategia" se fijan en el
disenyo del estudio, ANTES de medir.

## Regla 1 — sin apalancamiento, solo spot

**Se queda tal cual** (opcion a), con la nota de la decision 4: el apalancamiento solo se podria plantear si la
estrategia ya pasa sin el; los cortos, como variantes declaradas antes de medir.

## Regla 2 — OKX EU, via ccxt

**Se queda** (opcion a), tras comparar con otros exchanges de la UE (15/10/2026):

| | Maker / taker (nivel mas bajo) | Ida y vuelta taker | Deslizamiento BTC/EUR con 10.000 € | Volumen BTC/EUR 24 h |
|---|---|---|---|---|
| OKX EU | 0,10 % / 0,20 % | 0,40 % | 0,003 % | 9,5 M€ |
| Bitvavo | 0,15 % / 0,25 % | 0,50 % | 0,001 % | 64 M€ |
| Coinbase | 0,40 % / 0,60 % | 1,20 % | 0,011 % | 21 M€ |
| Kraken | 0,40 % / 0,80 % | 1,60 % | 0,000 % | 47 M€ |

- Libros: una foto de las API publicas de los cuatro (compra a mercado; con 100.000 €, como mucho 0,04 %).
- Comisiones: OKX, las de la cuenta (verificadas el 25/09, grupo de USDC); Kraken, su pagina oficial; Bitvavo, su
  pagina segun el buscador (no se pudo abrir); Coinbase, solo fuentes de terceros (su tabla no es publica).
- **Pendiente:** las comisiones de OKX para los pares contra euro (`account/trade-fee` con la clave). Si son mas
  caras que las configuradas, ese par no se opera (como hoy).
- El deslizamiento no decide nada: lo que pesa son las comisiones, y OKX es el mas barato; ademas, todo lo verificado
  (OCO, errores, conciliacion, 7 dias de demo) es de OKX.

## Regla 3 — la lista de pares

**Solo BTC/EUR y ETH/EUR** (opcion a), validado en los mismos 4 puntos (arranque, generador de candidatos, motor de
riesgo y justo antes de enviar la orden). La clave de OKX, limitada a BTC, ETH y EUR (la lista vive en DOS sitios:
`settings.yaml` y la clave). Anyadir otra moneda es un intento nuevo (decision 3) y se cambia en los dos sitios.

## Regla 4 — posiciones

**Maximo 1 posicion por moneda (2 en total); nunca promediar a la baja ni martingala** (opcion a). Anyadir a una
posicion que va GANANDO (piramide) solo si la estrategia lo lleva escrito antes de medir: cuenta como la misma
posicion y el riesgo total hasta el stop no pasa el limite de la regla 12. Las entradas pendientes cuentan.

## Regla 5 — capital y suelo

**Capital de referencia en euros, puesto a mano; suelo al 50 % de ese capital** (opcion a). Si se anyade dinero, el
capital de referencia (y con el el suelo) solo cambia cuando el propietario lo cambia a mano. **En el estudio, una
estrategia no pasa si su caida maxima historica se acerca al suelo** (el umbral exacto, p. ej. 35 %, se fija antes de
medir): el suelo es el freno de emergencia, no algo que salte en una caida normal; los escalones (regla 9) frenan antes.

## Regla 6 — el equity

**Igual, en euros** (opcion a): euros + Σ(cantidad × mejor bid en euros) − comisiones estimadas de salida, cada 15 s,
con datos del exchange (el saldo TOTAL, `eq`, nunca el `free`).

## Regla 7 — el freno de emergencia

**Igual** (opcion a): equity <= suelo en dos lecturas seguidas -> `CLOSE_ONLY_CAPITAL`, enclavado (solo reset manual) y
Telegram. No vende lo abierto: cada posicion sale en su stop o su objetivo, con reglas deterministas.

## Regla 8 — la preventiva

**Igual, con el colchon al 2 % del capital de referencia** (opcion a): solo se abre si, con todas las posiciones
(incluida la nueva) cerradas en su stop y con la comision de salida, el equity queda >= suelo + colchon. El salto por
debajo del stop no se suma aparte: con BTC y ETH suele ser pequenyo y lo cubre el colchon.

## Regla 9 — los escalones

**En % del capital de referencia** (opcion a): **−10 %** -> riesgo por operacion a la mitad + Telegram; **−20 %** ->
maximo 1 posicion; **−30 %** -> maximo 1 posicion y riesgo a la mitad. **El estudio los simula:** lo que se mide es la
estrategia CON los escalones (una de tendencia puede caer un 20-30 % en un anyo normal).

## Regla 10 — el limite diario

**El 6 % del capital de referencia** (opcion a), contando lo cerrado Y lo abierto desde las 00:00 UTC (como el
simulador de L) -> `CLOSE_ONLY_DAILY` hasta las 00:00 UTC. El estudio lo simula.

## Regla 11 — operaciones al dia

**Igual: maximo 6 al dia** (opcion a), cerradas mas vivas. Es un freno contra un bot desbocado, no parte de la
estrategia.

## Regla 12 — el riesgo por operacion

**Lo fija el estudio antes de medir, con un techo duro: 5 % del equity hasta el stop por posicion y 10 % entre las
dos** (opcion a). El deslizador del panel solo puede reducirlo, nunca subirlo. Con un 1 % y stops de tendencia (3 ATR,
~12-18 %), una posicion seria el 6-8 % del capital: casi imposible ganar a BTC (decision 1).

## Regla 13 — la proteccion en el exchange

**El stop, siempre en el exchange desde que se llena la entrada, y nunca un momento sin el** (opcion a). El objetivo,
en el exchange si la estrategia lo tiene (sale a mercado, taker: `51094`). Las salidas por senyal: cancelar la
proteccion y vender a mercado (verificado en el demo). Si la estrategia mueve el stop: primero el nuevo, despues quitar
el viejo. **Sin comprobar:** si OKX spot deja tener dos stops de venta a la vez sobre la misma cantidad (pueden bloquear
el saldo dos veces); si no, se usa la modificacion de la orden algoritmica (`amend-algos`), comprobada antes en el demo.

## Regla 14 — cooldown y pausa tras perdidas

**Fuera** (opcion c; el propietario: innecesaria). Ya frenan los escalones (regla 9), el limite diario (regla 10) y el
suelo. Si una estrategia quiere esperar antes de volver a entrar, lo lleva en su propia definicion, escrita antes de
medir.

## Regla 15 — exposicion y correlacion

**Se queda la exposicion maxima del 90 % del equity; sale la parte de la correlacion** (opcion a): BTC y ETH siempre
estan muy correlacionadas y, con 2 posiciones como mucho, el limite nunca frenaria; ese riesgo junto ya lo limita el
techo del 10 % de la regla 12.

## Regla 16 — spread y coste

**Se queda el limite de spread: no se entra con un spread > 0,10 %** (opcion a; en BTC/EUR y ETH/EUR suele ser
0,00-0,02 %, asi que solo salta en un momento raro del mercado). **El "objetivo >= 3 veces el coste de ida y vuelta"
solo se aplica si la estrategia tiene un objetivo fijo;** si sale por senyal, lo cubre que el estudio la mide neta de
costes.

## Regla 17 — la paridad de USDC

**Fuera** (opcion a): operando contra euro, el dinero son euros en OKX, no un token que pueda perder la paridad.

## Regla 18 — el presupuesto de la IA

**Igual** (opcion a): como mucho 40 llamadas al dia y 8 por ventana de 5 h, todas las del bot juntas (configurable).
Agotado -> `CLOSE_ONLY_QUOTA`.

## Regla 19 — las claves

**Igual** (opcion a): solo lectura y trading, nunca retirada, lista de IP del VPS, fuera del repositorio; la IA nunca
ve claves ni variables de entorno. La clave real, limitada a BTC, ETH y EUR. En el repositorio (publico), un test
comprueba que nada tenga forma de clave.

## Resumen

| # | Queda asi |
|---|---|
| 1 | Spot, sin apalancamiento ni cortos (condiciones de la decision 4) |
| 2 | OKX EU via ccxt |
| 3 | Solo BTC/EUR y ETH/EUR, validado en 4 puntos; la clave, con BTC, ETH y EUR |
| 4 | 1 posicion por moneda (2 en total), pendientes cuentan; nunca promediar a la baja ni martingala; piramide solo si la estrategia la lleva escrita |
| 5 | Capital de referencia en euros a mano; suelo al 50 %; en el estudio, ninguna estrategia que se acerque al suelo en su peor caida |
| 6 | Equity en euros cada 15 s con datos del exchange |
| 7 | Suelo dos lecturas -> `CLOSE_ONLY_CAPITAL` enclavado |
| 8 | Preventiva con stops y comision de salida; colchon del 2 % |
| 9 | Escalones −10 / −20 / −30 % (riesgo a la mitad; max. 1 posicion; las dos cosas), simulados en el estudio |
| 10 | Limite diario del 6 %, cerrado y abierto |
| 11 | Max. 6 operaciones al dia |
| 12 | Riesgo hasta el stop: lo fija el estudio, techo 5 % por posicion y 10 % en total; el deslizador solo reduce |
| 13 | El stop siempre en el exchange; objetivo si la estrategia lo tiene; salidas por senyal cancelando y vendiendo |
| 14 | **Fuera** |
| 15 | Exposicion max. 90 %; **fuera** la correlacion |
| 16 | Spread max. 0,10 %; el 3x el coste solo con objetivo fijo |
| 17 | **Fuera** |
| 18 | Presupuesto de la IA: 40 al dia, 8 por 5 h |
| 19 | Claves sin retirada, IP del VPS, fuera del repo |

Quedan **17 reglas**. Cuando se construya (paso 3): tests primero en `risk/` y la prueba de mutacion, con las reglas
nuevas.
