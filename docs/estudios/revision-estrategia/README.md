# Revision de la estrategia: estudio

> **Nota (15/10/2026, revision del codigo):** estos resultados se midieron con el simulador de papel ANTES de la
> suposicion 7 (`portfolio/paper.py`, rama `revision-1510-b`): en la vela que llenaba la entrada, el papel cobraba
> el objetivo aunque el maximo pudo pasar antes. Los R de los setups estan **algo inflados** (no se sabe cuanto sin
> volver a medir, y no se vuelve a medir: la estrategia de setups esta descartada y seria un intento mas). No afecta
> a la tendencia ni a L (`docs/estudios/tendencia/`), que entran a la apertura.


Metodo decidido por el propietario el 25/09/2026: `docs/archivo/propuesta-revision-estrategia.md`.

## Ficheros

| Fichero | Que es |
|---|---|
| `bajar_exploracion.py` | baja SOLO el tramo de exploracion (USDT, 01/11/2020 -> 30/06/2024) a una base nueva; PARA si llega una vela de la reserva |
| `medir.py` | lanza el recorrido del bot SIN cambios (`scripts/replay_baseline.py`) y calcula el R medio con su intervalo del 90 % por bootstrap por dias, por anyo y por setup |
| `referencia.json` | la estrategia ACTUAL en la exploracion (el numero contra el que se miden las 5 ideas) |
| `validacion-anyo-usdc.json` | `medir.py` sobre el anyo USDC ya conocido: reproduce el estudio del time-stop |
| `financiacion_reciente.py` | la financiacion de los perpetuos de OKX en los ultimos ~3 meses (lo que da la API publica), para la idea de los cortos de la segunda ronda (28/09) |
| `cortos.py` | el estudio de los cortos (28/09): `preparar` invierte los precios (1/p), `medir` pasa el recorrido del bot sin cambios con el filtro de BTC y convierte cada operacion a corto con la formula exacta y la financiacion pesimista, `resumen` aplica el criterio de la seccion 5b del plan |
| `cortos-resumen.json` | el resultado del estudio de los cortos contra el criterio (NO pasa) |
| `cortos-operaciones.json`, `largos-con-btc-operaciones.json` | cada operacion del estudio: los cortos (espejo, BTC bajista) y los largos (BTC alcista, la idea 2) |

Las bases no se suben (`*.db`): se regeneran con `bajar_exploracion.py` (~40 min).

## 1. El programa mide bien (validacion, 26/09)

Sobre el anyo USDC del estudio del time-stop, `medir.py` da exactamente lo mismo que aquel estudio:
159 operaciones, -0,379 R, -12,14 $, de 50 a 37,74 $, 43 muertas en 0-1 velas. Y anyade el intervalo:
**-0,65 a -0,08 R**: entero por debajo de cero, la perdida de ese anyo no es azar.

## 2. La referencia: la estrategia actual en 3,5 anos de exploracion (26/09)

USDT como sustituto de USDC, 02/12/2020 -> 30/06/2024 (1.307 dias, 7.842 velas de 4 h), las 19 reglas,
comisiones de `settings.yaml`, el spread medido de cada moneda para todo el periodo. **La reserva
(07/2024-08/2025) no se ha bajado.**

| | Operaciones | Aciertos | R medio | IC 90 % | Neto |
|---|---|---|---|---|---|
| **Todo** | 497 | 28 % | **+0,13** | -0,04 a +0,30 | +72,53 $ |
| 2020 (dic.) | 16 | 25 % | -0,17 | -0,83 a +0,67 | -0,87 $ |
| 2021 (alcista) | 147 | 36 % | **+0,52** | +0,19 a +0,85 | +61,25 $ |
| 2022 (bajista) | 148 | 18 % | **-0,35** | -0,58 a -0,09 | -23,00 $ |
| 2023 | 113 | 31 % | +0,37 | -0,02 a +0,76 | +37,48 $ |
| 2024 (ene.-jun.) | 73 | 25 % | +0,02 | -0,38 a +0,46 | -2,33 $ |

| Setup | Operaciones | R medio | IC 90 % |
|---|---|---|---|
| pullback | 279 | **+0,39** | +0,15 a +0,64 |
| ruptura | 116 | +0,12 | -0,14 a +0,39 |
| reversion | 102 | **-0,59** | -0,85 a -0,30 |

- Equity: 50 $ -> 123,78 $ (+147,6 %), caida maxima 25,2 %. Comprar y esperar: BTC +237 %, las 8 a partes
  iguales +1.595 % (2021 multiplico por 10-100 SOL, AVAX y DOGE).
- 622 candidatos; 82 operaciones (16,5 %) muertas en 0-1 velas (en el anyo USDC, el 27 %).

### Lo que dice (y lo que no)

1. **La estrategia depende del mercado:** gana cuando sube (2021, 2023) y pierde cuando baja (2022: -0,35 R,
   y el anyo USDC: -0,38 R). En conjunto, +0,13 R, pero con un intervalo que incluye el cero. Es lo que
   ataca la idea 2 (tendencia de BTC).
2. **La reversion pierde en los dos juegos de datos** (-0,59 aqui, -0,50 en el anyo USDC). El pullback,
   en cambio, gana aqui y pierde en el anyo USDC: depende del tramo.
3. **Aviso de metodo:** "quitar solo la reversion" NO esta en la lista cerrada (la idea 3 es "solo la
   ruptura", que quita pullback y reversion). Anyadirla ahora, despues de ver estos numeros, es justo lo
   que el metodo prohibe. Si el propietario quiere probarla, que conste como idea anyadida DESPUES de mirar, con el
   listón mas alto.
4. Limites: precios contra USDT; el tick y el lote de hoy aplicados a precios de 2020-2021 (DOGE a
   0,003 $: el tick de hoy es grueso para esos precios); el spread de hoy para todo el periodo; el
   equity crece, asi que los anyos del final pesan mas en dolares (por eso se juzga en R).

## 3. Las 5 ideas en la exploracion (26/09)

Mismo recorrido, mismos datos; cada idea cambia UNA cosa (`medir.py --idea N`, resultados en `ideas/`).
El criterio, fijado antes de medir (metodo, seccion 5): IC 90 % del R medio ENTERO por encima de la
referencia (+0,13), con >= 100 operaciones, y sin ganar solo en un tramo.

| | Op. | R medio | IC 90 % | Final | Caida max. | Pasa |
|---|---|---|---|---|---|---|
| Referencia | 497 | +0,13 | -0,04 a +0,30 | 123,78 $ | 25,2 % | - |
| 1. No comprar cayendo | 378 | +0,12 | -0,05 a +0,29 | 68,61 $ | 41,9 % | no |
| **2. Tendencia de BTC** | 293 | **+0,28** | **+0,06 a +0,51** | 111,21 $ | **18,5 %** | no (por poco) |
| 3. Solo la ruptura | 259 | +0,19 | +0,01 a +0,37 | 77,46 $ | 20,8 % | no |
| 4. Pullback, stop 1,5 ATR | 553 | +0,11 | -0,06 a +0,29 | 99,80 $ | 33,4 % | no |
| 4. Pullback, stop 2,5 ATR | 410 | +0,15 | -0,01 a +0,33 | 101,83 $ | 27,2 % | no |
| 4. Ruptura, stop 1,5 ATR | 526 | +0,11 | -0,05 a +0,28 | 92,19 $ | 37,3 % | no |
| 4. Ruptura, stop 2,5 ATR | 445 | +0,14 | -0,04 a +0,33 | 105,57 $ | 35,2 % | no |
| 5. Velas de 1 dia | 89 | +0,09 | -0,27 a +0,48 | 49,22 $ | 28,0 % | no |

**Ninguna pasa el criterio tal como se fijo.** Lo que se ve:

1. **La idea 2 (no entrar con BTC bajo su media de 200 dias) es la unica que cambia algo de verdad:**
   dobla el R medio (+0,13 -> +0,28), el intervalo queda entero por encima de CERO, la caida maxima baja
   del 25 al 18 %, y en 2022 (bajista) no abre ni una operacion. Gana en todos los anyos en que opera
   (2021 +0,60, 2023 +0,15, 2024 +0,02). No pasa porque el extremo bajo (+0,06) no llega a +0,13.
2. **La idea 1 arregla lo que queria y aun asi no sirve:** las muertas en 0-1 velas bajan de 82 a 16,
   pero entrar al cierre (mas caro y con taker) se come la ventaja y la caida maxima sube al 42 %.
3. Idea 3: mejor por operacion, pero casi todo sale de 2021. Ideas 4 y 5: dentro del ruido.
4. **Sobre el propio criterio:** compara el intervalo de una idea con el numero de la referencia sin
   intervalo. Es exigente a proposito, pero no es la comparacion mas fina (la fina seria la diferencia
   emparejada vela a vela). Cambiarlo DESPUES de ver los resultados es justo lo que el metodo prohibe:
   lo decide el propietario.

## 4. La combinacion 2 + 3 y la comparacion emparejada (26/09)

Decision del propietario (opcion A): mismo criterio; se prueba la combinacion de las dos que mejoraban solas; la
comparacion emparejada, solo como informacion (`emparejada.py`). La referencia y las ideas 2 y 3 se
volvieron a medir para guardar cada operacion: salieron EXACTAS a la primera vez.

| | Op. | R medio | IC 90 % | Final | Caida max. |
|---|---|---|---|---|---|
| Referencia | 497 | +0,13 | -0,04 a +0,30 | 123,78 $ | 25,2 % |
| Idea 2 | 293 | +0,28 | +0,06 a +0,51 | 111,21 $ | 18,5 % |
| Idea 3 | 259 | +0,19 | +0,01 a +0,37 | 77,46 $ | 20,8 % |
| **2 + 3** | 180 | **+0,10** | -0,10 a +0,31 | 59,07 $ | 26,2 % |

Emparejada (R total de la idea menos el de la referencia, dia a dia, IC 90 % por bootstrap de dias):

| | R total de mas | IC 90 % |
|---|---|---|
| Idea 2 | +17,0 R | -37,9 a +70,5 |
| Idea 3 | -16,6 R | -93,3 a +58,9 |
| 2 + 3 | -45,9 R | -126,7 a +33,4 |

**Conclusion de la primera ronda:** ninguna idea demuestra que mejore la estrategia. La 2 gana mas POR
operacion y con menos caida (no pierde en 2022 porque no opera), pero hace menos operaciones y, en total,
su ventaja (+17 R) cabe de sobra en el ruido. La combinacion 2 + 3 es peor que cada una. La reserva
sigue sin bajarse. Decision del propietario del 26/09: en mercado bajista, el bot se queda fuera (en USDC), que es
lo unico que permite la regla 1 (solo largos); abrir la regla 1 para vender en corto, descartado.

## 5. Los cortos (segunda ronda adelantada, 28/09)

Decidido por el propietario ANTES de medir (`docs/archivo/plan-segunda-ronda-estrategia.md` 5b): largos solo con BTC sobre su media
de 200 dias (la idea 2) y cortos, el ESPEJO de los tres setups, solo con BTC por debajo. Criterio: IC 90 % entero
por encima de +0,13 R con >= 100 operaciones, no perder en 2022 y aguantar la financiacion pesimista (el corto
PAGA 0,01 % cada 8 h, siempre). Misma exploracion (USDT 12/2020-06/2024); **la reserva, sin bajar**.

Como se midio: los precios se invierten (C/p, con C = mediana al cuadrado de cada moneda, para que el tick y el
lote sigan teniendo sentido) y se pasa el recorrido del bot sin cambios; cada operacion se traduce a corto con la
formula exacta (mismo riesgo en dolares, comisiones de las dos patas) y se le resta la financiacion por cada cobro
de las 00, 08 y 16 UTC con la posicion abierta. `cortos.py` tiene su test (`tests/unit/test_estudio_cortos.py`).
Validacion antes de medir: sin filtro y sin invertir, reproduce la referencia EXACTA (497 op., +0,13 R,
-0,04 a +0,30). Los largos con filtro reproducen la idea 2 exacta (293 op., +0,28 R, +0,06 a +0,51).

| | Op. | Aciertos | R medio | IC 90 % |
|---|---|---|---|---|
| Largos (BTC alcista) = idea 2 | 293 | 30 % | +0,28 | +0,06 a +0,51 |
| Cortos (BTC bajista), sin financiacion | 220 | 31 % | +0,03 | -0,22 a +0,27 |
| **Cortos, con financiacion pesimista** | 220 | 31 % | **-0,01** | -0,25 a +0,24 |
| Combinacion, sin financiacion | 513 | 31 % | +0,17 | +0,01 a +0,34 |
| **Combinacion, con financiacion** | 513 | 31 % | **+0,16** | -0,00 a +0,32 |

| Anyo (combinacion, con financiacion) | Op. | R medio | IC 90 % | De ellas, cortos |
|---|---|---|---|---|
| 2020 (dic.) | 16 | -0,17 | -0,84 a +0,70 | 0 |
| 2021 | 169 | +0,42 | +0,12 a +0,74 | 55 (+0,05) |
| **2022** | 146 | **+0,08** | -0,20 a +0,37 | 146 (todas) |
| 2023 | 109 | -0,01 | -0,36 a +0,36 | 19 (**-0,79**) |
| 2024 (ene.-jun.) | 73 | +0,02 | -0,38 a +0,47 | 0 |

Cortos por setup: pullback 109 op. +0,04 R; ruptura 63 op. +0,14 R; reversion 48 op. **-0,30 R** (igual que en
largo, la reversion pierde).

**Resultado: NO pasa** (`cortos-resumen.json`). Cumple >= 100 operaciones y no perder en 2022; falla el IC entero
sobre +0,13 (el extremo bajo es +0,01, y con financiacion, 0,00) y, por eso mismo, falla con la financiacion.

Lo que dice:
1. **Los cortos no ganan ni pierden: +0,03 R sin financiacion y -0,01 R con ella**, con un intervalo que va de
   -0,25 a +0,24. En R total, los 220 cortos suman ~-1 R: la combinacion (~+80 R) es la idea 2 sola (~+81 R).
2. **En 2022 cumplen su funcion a medias:** la estrategia actual perdia -0,35 R en 148 operaciones; la idea 2 no
   operaba; los cortos dan +0,08 R en 146, que no se distingue de cero.
3. **El coste esta en los giros:** a principios de 2023 el mercado subio con BTC todavia bajo su media y los 19
   cortos de ese tramo perdieron -0,79 R de media (~-15 R), lo que se come lo ganado en 2022 (~+12 R).
4. La financiacion pesimista resta ~0,03 R por corto: no es lo que los hunde.

Aproximaciones (dichas antes de medir): los indicadores sobre 1/precio no son el espejo exacto (RSI y medias,
casi); largos y cortos se miden por separado sin compartir los huecos de la regla 4 (solapan poco: los tramos de
BTC alcista y bajista no coinciden); la financiacion es una tasa fija pesimista, no la real de 2022; la
liquidacion no se modela (con 2x haria falta una subida del ~45-50 %: 29 cortos peores que -1,2 R por huecos,
el peor -1,51 R, ninguno cerca). Las cifras en dolares de `cortos-resumen.json` NO restan la financiacion; el
juicio es en R.

Consecuencia (plan 5b): **no se mira la reserva, y la tercera cartera de cortos en sombra no se construye.** La
regla 1 no cambia.

