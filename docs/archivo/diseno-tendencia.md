# Estrategia de tendencia: variantes F y H (propuesta de criterio, para aprobar ANTES de medir)

Preparada el 09/10/2026 a peticion del propietario. **Estado: criterio APROBADO por el propietario el 09/10, tal como esta, ANTES de
medir** ("confirmo el criteri tal com està"). La regla 12 nueva se usa en la medicion; aplicarla al bot sigue
pendiente del propietario (`docs/archivo/propuesta-prd-v3.md`).

**Resultado (09/10, `docs/estudios/tendencia/README.md`): NO PASA NINGUNA, las dos cerca.** F: 50 -> 290 $ (+480 %),
caida 50 %, Sharpe 1,30; falla la 4 (2022 -34 %) y la 5 por poco (0,942). H: 50 -> 130 $ (+160 %), caida 42 %,
Sharpe 1,00, 2022 +2 %; falla solo la 5 (0,84). BTC mantenido: +226 %, caida 77 %, Sharpe 0,84. La reserva, sin tocar.

**De donde sale.** el propietario fija el objetivo del bot: ganar dinero (`docs/archivo/decision-fase-7.md`). Los datos y la literatura
(`docs/estudios/recerca-trading-cripto.md`) coinciden: en spot y solo largos, el dinero de estos anyos no ha salido de
entrar y salir cada pocos dias, sino de **tener cripto cuando sube y estar en USDC cuando baja**. El cambio de enfoque
va con la propuesta de PRD v3 (`docs/archivo/propuesta-prd-v3.md`).

**De donde sale la ganancia, dicho claro:** de la subida de la cripto a largo plazo, esquivando lo peor de las caidas;
no de ser mas listo que el mercado. Si la cripto no sube a largo plazo, ninguna estrategia solo de largos gana.

## 00. DECISION del propietario (09/10): F va a la reserva (la unica vez), y despues al anyo USDC

Con las cuatro candidatas cerca (2 + D, F, H, J; ninguna pasa la condicion 5), el propietario elige F para la reserva ("Fem-ho!").
Detalles fijados AQUI, antes de bajar nada:
- **Reserva:** USDT del lunes 01/07/2024 a las 00:00 al 20/08/2025 00:00 UTC (lo que nunca se bajo), las 8 monedas,
  4 h y 1 h; para calentar los indicadores (28 dias de rendimiento, ATR de 42 dias, 7 dias de correlacion) se bajan
  tambien las velas desde el 01/05/2024, que ya son de la exploracion. `docs/estudios/tendencia/bajar_reserva.py`.
  Instrumentos y spread, los de la exploracion.
- **Pasa la reserva si:** rendimiento neto > 0 Y caida maxima <= 2/3 de la de BTC mantenido en el mismo periodo.
- **Despues, el anyo USDC** (`time-stop/historia.db`, contra USDC): del lunes 06/10/2025 (el primero con el ATR
  calentado; los datos empiezan el 21/08/2025) al 28/09/2026. **Pasa si:** no pierde (rendimiento >= 0) Y caida
  maxima <= 2/3 de la de BTC mantenido.
- **F tal cual** (`tendencia.py`, sin tocar nada). Si falla una de las dos, F queda descartada y no se retoca.
- Lo que se apunta despues: el anyo USDC tambien esta sin ver para 2 + D, como segunda opcion mas floja.
- **Resultado (09/10): F NO PASA la reserva** (+20,5 % frente a +79,1 % de BTC; caida 33,6 %, mas que la de BTC,
  28,1 %). F queda descartada; la reserva, gastada. `docs/estudios/tendencia/README.md`.

## 0. La combinacion J de las tres candidatas (el propietario, 09/10): criterio fijado ANTES de calcularla

el propietario pide probar si combinar 2 + D, F y H es "la combinacion buena". **Aviso, dicho antes de calcular:** con las tres
curvas ya vistas se puede adivinar a ojo que la combinacion probablemente pasara; por eso pasar aqui demuestra poco y
lo que mandaria es la reserva y el anyo USDC.
- **Que es J:** el capital en tres partes iguales (16,67 $ cada una), cada parte con su estrategia y sus reglas, sin
  rebalancear entre ellas; el equity de J es la suma. **Una sola configuracion** (ni otros pesos ni pares de dos).
- **Como se calcula:** con las curvas diarias ya medidas (`F.json`, `H.json`, `curva-2d.json`), cada una a un tercio.
  **Aproximacion que se dice:** cada parte se midio con 50 $, y las reglas que no escalan (suelo de 25 $, perdida
  diaria de 3 $, escalones, minimos por orden) y el limite de 3 posiciones en total no se aplican a la combinacion.
  En el bot real, J necesitaria cambiar la regla 4 (hasta 8 posiciones) o repartir los huecos.
- **Criterio:** las mismas 5 condiciones de la seccion 3, contra BTC mantenido; en la 5, **N = 7** (la familia y J),
  con la misma V que la decision del 09/10 (`umbral.json`).
- Si no pasa, no se prueban otras mezclas.

## 1. Las dos variantes (una sola configuracion cada una; no se retocan)

**F. Rotacion semanal.** Cada lunes a las 00:00 UTC, con el cierre diario del domingo: de las 8 monedas, las que
tienen el rendimiento de 28 dias positivo, de mayor a menor; se toman hasta 3 respetando la regla 15. Las que ya se
tienen y siguen elegidas se mantienen (sin comisiones); las demas se venden. Si ninguna tiene rendimiento positivo,
todo en USDC.

**H. BTC y ETH con el filtro de BTC.** Cada lunes, igual: si BTC cierra el domingo por encima de su media de 200
dias, se tienen BTC y ETH a partes iguales; si no, todo en USDC. Es la version mas simple de la idea 2.

## 2. Comun a las dos (fijado aqui)

- **Datos:** la exploracion, USDT del 02/12/2020 al 30/06/2024 (`var/estudios/exploracion.db`); cierre diario = el de
  la vela de 4 h de las 20:00 UTC; correlaciones con 7 dias de velas de 1 h. **La reserva, sin bajar.**
- **Capital:** 50 $. **Comisiones:** taker (0,20 %) en cada compra y cada venta (pesimista: rebalanceo a mercado).
- **Tamanyo:** como mucho el 30 % del equity por posicion en F (3 x 30 % = el 90 % de la regla 15) y el 45 % en H (2
  x 45 %), y ademas la regla 12 propuesta: el riesgo hasta el stop de cada posicion, como mucho el 5 % del equity.
- **Stop (regla 13):** 3 ATR diarios (14) bajo la entrada, en el exchange; si una vela de 4 h lo toca, se vende al
  stop (o a la apertura si abre por debajo), taker. Esa moneda no vuelve hasta el rebalanceo siguiente. **Objetivo:**
  +100 % (la regla 13 lo exige; casi nunca salta).
- **Las reglas que se simulan:** 4 (3 posiciones), 7 (suelo de 25 $), 8 (preventiva: con todos los stops, >= 26 $), 9
  (escalones: < 45 $ el tamanyo a la mitad, < 40 $ 2 posiciones, < 35 $ 1), 10 (perdida del dia >= 3 $: ese dia no se
  compra; la compra pasa al dia siguiente), 15 (exposicion 90 %; una moneda no entra si correlaciona > 0,8 con 2 o
  mas de las que ya hay, como hace el bot), 16 (spread, con la medida de hoy, como los estudios anteriores).
- **Validacion antes de mirar F o H:** con el filtro siempre encendido, sin stop y sin rebalanceo, el simulador tiene
  que dar exactamente comprar y mantener (BTC y BTC+ETH) menos las comisiones de entrada.
- **Comparacion:** BTC comprado y mantenido; BTC y ETH a partes iguales mantenidos; USDC.

## 3. El criterio en la exploracion (cada variante, todo a la vez)

1. **Gana dinero:** rendimiento neto total > 0.
2. **Cae mucho menos:** caida maxima <= 2/3 de la de BTC mantenido en el mismo periodo.
3. **Mejor por riesgo:** Sharpe anualizado (rendimientos diarios) >= el de BTC mantenido.
4. **Aguanta el anyo bajista:** en 2022 pierde como mucho 1/3 de lo que pierde BTC mantenido.
5. **No es suerte (Sharpe deflactado). CAMBIADO por el propietario el 09/10, ANTES de medir (opcion b):** con N = 27 el Sharpe
   por suerte salia 1,73 al anyo (F o H habrian necesitado ~2,6, el triple que BTC mantenido); se cuenta solo la
   FAMILIA de tendencia (idea 2, 2 + 3, 2 + D, A' con la idea 2, F y H): **N = 6, Sharpe por suerte 0,47 al anyo**
   (`docs/estudios/tendencia/umbral.json`). Lo de abajo es lo que se aprobo antes y queda descartado.
   ~~N = todas las variantes de estrategia medidas en Ploutos mas estas 2.~~ Contadas
   el 09/10: primera ronda 8 (ideas 1, 2, 3, 4 x 4 y 5), 2 + 3, el espejo de cortos, H1 y H2, las 8 del time-stop del
   25/09, C x 2, D, 2 + D y A' = 25; con F y H, **N = 27**. Se pide que la probabilidad de que el Sharpe de verdad
   supere al que saldria por suerte con 27 pruebas sea >= 0,95 (Bailey y Lopez de Prado). El "Sharpe por suerte" se
   calcula con la dispersion de los Sharpes de las variantes ya medidas (curvas diarias rehechas con sus operaciones)
   y **se sube al repositorio ANTES de medir F y H**, con la lista exacta.

**Si pasan las dos:** la de mayor Sharpe deflactado. **Si no pasa ninguna:** no se retocan (ni otros dias de
rendimiento, ni otros stops, ni otras monedas).

## 4. Despues (solo con la que pase)

- **Reserva (una sola vez):** rendimiento neto > 0 y caida maxima <= 2/3 de la de BTC mantenido.
- **Anyo USDC (08/2025-09/2026, con sus meses bajistas):** no perder (rendimiento >= 0) y caida <= 2/3 de BTC.
- Si pasa todo: papel y demo unas semanas (con el bot adaptado) y despues los 50 $ reales. No mas capital hasta que
  haya aguantado meses de verdad, idealmente con una bajada por medio.

## 5. Lo que hay que saber antes de aprobarlo

- **Gana poco en los anyos alcistas frente a mantener:** el filtro llega tarde (BTC estuvo bajo su media mas de 9
  meses en 2025-2026) y el criterio no le pide ganar mas que BTC, sino ganar y caer mucho menos.
- **La reserva (07/2024-08/2025) fue sobre todo alcista** (conocimiento general, no mirado): por eso la prueba dura es
  el anyo USDC.
- **Necesita cambiar la regla 12** (riesgo por operacion de 0,5-1,5 %): con un stop amplio, una posicion del 30 % del
  equity arriesga un 4-5 %. Es una regla dura: la decide el propietario (`docs/archivo/propuesta-prd-v3.md`).
- **La regla 15 limita la cartera:** las monedas fuertes suelen correlacionar > 0,8 entre ellas; a menudo solo
  cabran 2.
- **Coste:** el simulador semanal y su validacion, ~1 dia; medir y documentar, medio dia. Sin tocar el bot.
