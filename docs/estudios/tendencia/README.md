# Estrategia de tendencia: F y H en la exploracion (09/10/2026): NO PASA NINGUNA, las dos cerca

Criterio aprobado por el propietario el 09/10 ANTES de medir (`docs/archivo/diseno-tendencia.md`, `a47ec3d`); la condicion 5 con la
familia de tendencia (N = 6, Sharpe por suerte 0,47 al anyo; `umbral.json`, `908d6d6`). Simulador semanal propio
(`tendencia.py`), validado antes de medir: con pesos fijos da exactamente comprar y mantener (`30506d7`). Exploracion
USDT del 14/12/2020 al 30/06/2024 (1.295 dias). **La reserva, sin bajar.**

## Resultado

| | 50 $ -> | Rendimiento | Caida max. | Sharpe (anual) | 2022 | Operaciones | Comisiones | Invertido |
|---|---|---|---|---|---|---|---|---|
| **F, rotacion semanal** | **289,75 $** | **+480 %** | 49,9 % | **1,30** | -33,9 % | 158 | 23,56 $ | 83 % |
| **H, BTC + ETH con el filtro** | 130,14 $ | +160 % | **42,3 %** | 1,00 | **+1,9 %** | 22 | 2,63 $ | 57 % |
| BTC mantenido | 163,01 $ | +226 % | 76,6 % | 0,84 | -64,2 % | 1 | - | 100 % |
| BTC + ETH mantenidos | - | +353 % | 77,1 % | 0,95 | - | - | - | 100 % |

Por anyo (estrategia / BTC): F 2021 +207 % / +60 %, 2022 -34 % / -64 %, 2023 +154 % / +156 %, 2024 (ene.-jun.)
+4 % / +49 %. H 2021 +12 % / +60 %, 2022 +2 % / -64 %, 2023 +46 % / +156 %, 2024 +25 % / +49 %.

| Condicion | F | H |
|---|---|---|
| 1. Gana dinero | si | si |
| 2. Caida <= 2/3 de la de BTC (51,1 %) | si (49,9 %) | si (42,3 %) |
| 3. Sharpe >= el de BTC (0,84) | si (1,30) | si (1,00) |
| 4. En 2022 pierde <= 1/3 de lo de BTC (-21,4 %) | **no (-33,9 %)** | si (+1,9 %) |
| 5. Sharpe deflactado >= 0,95 | **no (0,942)** | **no (0,839)** |

## Lo que dice

1. **Son los mejores resultados medidos en Ploutos.** F multiplica por 5,8 los 50 $ en 3,5 anyos (BTC, por 3,3) con
   un tercio menos de caida; H no pierde en 2022 (BTC -64 %) y cae la mitad que BTC, aunque gana menos que mantener.
2. **Pero ninguna pasa el criterio que se fijo:** F falla por poco la condicion 5 (0,942 frente a 0,95) y claramente
   la 4 (en 2022 pierde un 34 %); H solo falla la 5 (0,84): su Sharpe de 1,00 no se distingue lo bastante de la suerte
   con 3,5 anyos de datos.
3. **De donde sale F:** casi todo de 2021 (+207 %, la subida de SOL, AVAX y compania); en 2022 la rotacion llega tarde
   a salir. H es mas simple y mas defensiva: sale a tiempo de los anyos malos y se pierde parte de los buenos.
4. **Por el criterio, no se retocan** (ni otros dias de rendimiento, ni otros stops, ni otras monedas).

## Las tres candidatas, con la misma vara (09/10, `comparar.py`, `comparacion.txt`)

Equity diario reescalado a 50 $ el 14/12/2020; la curva de 2 + D se rehizo con la misma medicion del 08/10
(`curva_2d.py`, `curva-2d.json`: 256 op., 115,90 $, identica). Solo describe: no decide nada.

| | 50 $ -> | Rendimiento | Caida max. | Sharpe | Operaciones | 2021 | 2022 | 2023 | 2024 (ene.-jun.) |
|---|---|---|---|---|---|---|---|---|---|
| 2 + D | 117,11 $ | +134 % | **16,6 %** | 1,28 | 256 | +94 % | 0 % | +17 % | -3 % |
| F | **289,75 $** | **+480 %** | 49,9 % | **1,30** | 158 | +207 % | -34 % | +153 % | +4 % |
| H | 130,14 $ | +160 % | 42,3 % | 1,00 | 22 | +12 % | +2 % | +46 % | +25 % |
| BTC mantenido | 163,01 $ | +226 % | 76,6 % | 0,84 | 1 | +60 % | -64 % | +156 % | +48 % |

Correlacion de los rendimientos diarios: 2 + D y F +0,54; 2 + D y H +0,65; F y H +0,56.

## La combinacion J (09/10): NO PASA

Criterio fijado antes de calcularla (`docs/archivo/diseno-tendencia.md` 0, `0c88d17`); `combinacion.py`, `J.txt`. Un tercio del
capital a cada una, sin rebalancear (aproximacion: las curvas de 50 $ sumadas a un tercio).

| | 50 $ -> | Caida max. | Sharpe | 2022 | Deflactado (N = 7) |
|---|---|---|---|---|---|
| **J** | 179,00 $ (+258 %) | 29,9 % | 1,32 | -16,3 % | **0,939** |
| BTC mantenido | 163,01 $ (+226 %) | 76,6 % | 0,84 | -64,2 % | - |

Pasa las condiciones 1-4 y falla la 5. **Lo que se habia adivinado antes de calcular era optimista** (se dijo Sharpe
~1,4 y 2022 ~-11 %): F pesa mas que las otras en los vaivenes y la mezcla diversifica menos de lo esperado.

**Lo que sale de juntar todo:** las cuatro (2 + D, F, H y J) se quedan con un Sharpe deflactado de 0,84-0,94. Con 3,5
anyos de datos, un Sharpe de ~1,3 no se distingue lo bastante de la suerte: el liston de la exploracion, asi fijado,
no lo pasa ninguna estrategia realista. Lo que puede decidir es mas datos que no se hayan visto: la reserva (~14
meses) y el anyo USDC (~13 meses).

## F en la RESERVA (09/10): NO PASA. F queda descartada

Decision y criterio fijados antes de bajar nada (`docs/archivo/diseno-tendencia.md` 00, `ff1f2d1`); la reserva se bajo por
primera vez (`bajar_reserva.py`: USDT 01/05/2024-19/08/2025, 22 MB, 2.856 velas de 4 h por moneda, sin huecos) y se
midio F tal cual del lunes 01/07/2024 al 20/08/2025 (`F-reserva.json`, `veredicto-reserva.txt`).

| | 50 $ -> | Caida max. | Sharpe | Operaciones |
|---|---|---|---|---|
| **F** | 60,26 $ (**+20,5 %**) | **33,6 %** | 0,60 | 57 (40 rotaciones, 15 stops, 2 objetivos) |
| BTC mantenido | 89,54 $ (+79,1 %) | 28,1 % | 1,32 | 1 |
| BTC + ETH mantenidos | +48,6 % | - | - | - |

| Criterio de la reserva | |
|---|---|
| Gana dinero (> 0) | si (+20,5 %) |
| Caida <= 2/3 de la de BTC (18,7 %) | **no (33,6 %, mas que la de BTC)** |

Lo que dice:
1. **Fuera de los datos donde se eligio, F se viene abajo:** gana un cuarto de lo que gana mantener BTC y cae MAS que
   BTC. Su Sharpe pasa de 1,30 en la exploracion a 0,60.
2. **Es lo que el liston de "no es suerte" queria evitar:** la ventaja de F en la exploracion venia sobre todo de
   2021 (la subida de SOL, AVAX...); en 2024-2025 la rotacion entra en subidas que no siguen y paga 57 operaciones.
3. **Por el criterio, F queda descartada** y no se retoca; el anyo USDC ya no hace falta para F. **La reserva queda
   gastada:** cualquier otra estrategia medida en ella estaria contaminada por lo que ya se ha visto.

## Segunda tanda (10/10): K, L y M en la exploracion ampliada. PASAN L y M; L va al anyo USDC

Criterio aprobado por el propietario antes de medir (`docs/archivo/diseno-tendencia-2.md`, `efee279`); herramientas y validacion en
`4fe8c91`. Exploracion ampliada (exploracion + reserva gastada), 14/12/2020 - 20/08/2025, 1.710 dias.
`segunda_tanda.py`, `veredicto-segunda-tanda.txt`.

| | 50 $ -> | Caida max. | Sharpe | 2022 | Tramo reserva | Op. | Deflactado | 1-5 |
|---|---|---|---|---|---|---|---|---|
| H | 118,62 $ (+137 %) | 49,4 % | 0,72 | +1,9 % | -8,9 % | 37 | 0,628 | no (3 y 5) |
| 2 + D | 115,16 $ (+130 %) | **24,8 %** | 0,98 | 0,0 % | -1,7 % | 389 | 0,813 | no (5) |
| K | 161,68 $ (+223 %) | 37,7 % | 1,05 | -23,9 % | +37,4 % | 213 | 0,852 | no (4) |
| **L** | **421,36 $ (+743 %)** | 44,5 % | **1,46** | -11,0 % | +30,5 % | 130 | **0,978** | **si** |
| **M** | 138,42 $ (+177 %) | **23,0 %** | 1,10 | -11,8 % | +17,9 % | 602 | 0,876 | **si** |
| BTC mantenido | 293,09 $ (+486 %) | 76,6 % | 0,93 | -64,2 % | +79 % | 1 | - | - |

**Va al anyo USDC: L** (la de mayor deflactado; con 0,978 pasaria incluso el liston eliminatorio de 0,95).

Lo que hay que saber de L (mirado DESPUES del veredicto, solo informa; no cambia nada):
1. **Gran parte viene del principio de 2021:** de 50 a 170,86 $ entre el 14/12/2020 y el 01/06/2021 (BTC x1,91),
   cuando las medias de 100 y 200 dias aun no se podian calcular y contaban como cumplidas. Desde el 01/06/2021, L
   multiplica por 2,47 y BTC por 3,07: gana menos que mantener, con mucha menos caida.
2. Reparte la ganancia entre seis monedas (SOL +99 $, NEAR +85, TRX +70, ETH +68, BTC +64, DOGE +59; XRP -63 y
   AVAX -22): no depende de una sola. 130 operaciones (87 rotaciones, 24 stops, 19 objetivos), invertida el 56 % del
   tiempo, 31,71 $ de comisiones; nunca mas de 3 posiciones.
3. Su peor caida (44,5 %) va del 13/03/2024 al 25/10/2024.
4. **El tramo de la reserva no es limpio para L:** L se disenyo despues de ver que F fallaba ahi (con la literatura,
   no con esas curvas, pero se sabia). La prueba limpia es el anyo USDC.

## El anyo USDC (10/10): NO PASA NINGUNA de las dos que cuentan

Criterio y orden fijados por el propietario antes de mirar ese anyo (`docs/archivo/diseno-tendencia-2.md` 00, `27cda17`); herramientas
en `0cf8a8c`. Del lunes 01/09/2025 al 27/09/2026 (392 dias), USDC, con los indicadores calentados en USDT.
`anyo_usdc.py`, `veredicto-anyo-usdc.txt`. Pasa si no pierde (>= 0) y cae <= 2/3 de lo que cae BTC (35,4 %).

| | 50 $ -> | Caida max. | Sharpe | Op. | Veredicto |
|---|---|---|---|---|---|
| **L (cuenta)** | 46,54 $ (-6,9 %) | 20,5 % | -0,41 | 13 | **NO** (pierde) |
| **M (cuenta)** | 49,99 $ (-0,02 %) | 13,0 % | 0,06 | 61 | **NO** (pierde 1 centimo) |
| H (informacion) | 45,77 $ (-8,5 %) | 20,2 % | -0,46 | 3 | no |
| 2 + D (informacion) | 51,54 $ (+3,1 %) | 15,5 % | 0,27 | 43 | si |
| K (informacion) | 48,45 $ (-3,1 %) | 15,3 % | -0,15 | 18 | no |
| BTC mantenido | 38,86 $ (-22,3 %) | 53,1 % | -0,31 | 1 | - |

Lo que dice:
1. **Por el criterio, ni L ni M pasan; no se retoca nada.** M se queda a un centimo: el criterio era ">= 0" y no se
   redondea a su favor.
2. **La proteccion funciona:** en un anyo en que BTC cae un 53 % desde su maximo y acaba en -22 %, las cinco caen
   entre un 13 y un 20 %. Lo que no consiguen es no perder.
3. **L pierde casi todo al principio:** entra el 15/09 y el 06/10/2025 y los stops la sacan (6 stops, -9,1 $ en
   septiembre y octubre de 2025); luego pasa el 74 % del tiempo en USDC y recupera con NEAR (+100 %) en 09/2026.
4. **2 + D pasa, pero solo como informacion:** elegirla AHORA seria elegir despues de ver la prueba, lo que la prueba
   queria evitar (la trampa de F).

## Ficheros

`tendencia.py` (simulador, validacion, medicion y juez), `dsr_umbral.py` y `umbral.json` (el Sharpe por suerte),
`F.json` y `H.json` (cada operacion y la curva diaria), `veredicto.txt` (la salida del juez tal cual).
