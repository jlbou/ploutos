# Decision 3: el mercado (15/10/2026)

Tomada tras un consejo de tres miembros (Sonnet, solo lectura: datos y metodo, costes y practica, la contraria) y las
comprobaciones propias de abajo.

## Decidido (opcion a)

- **Solo BTC y ETH, contra euro (BTC/EUR y ETH/EUR) en OKX EU, spot.** La estrategia puede elegir entre BTC, ETH y
  quedarse en euros.
- **Anyadir monedas despues es un intento nuevo**: cuenta en el liston contra la suerte (N) y se decide con criterio
  escrito antes.
- **Para estudiar:** la historia larga contra USDT (BTC y ETH desde 10/2017) pasada a euros con el cambio de cada dia;
  la historia contra euro (solo desde el 20/11/2023) y los libros de ordenes en euros, **solo para los costes**.

## Lo comprobado (15/10/2026)

- **Las 8 monedas tienen par contra euro, todas `live`** (`/api/v5/public/instruments`, 272 bases contra EUR).
- **Primera vela diaria contra euro:** BTC y ETH (y SOL, DOGE, AVAX) el 20/11/2023; TRX el 21/11/2023; XRP el
  13/03/2024; NEAR el 25/02/2026 (consejo; BTC y XRP repetidos a mano).
- **Una foto del libro (15/10, 400 niveles, compra a mercado; el lado de venta sin medir):** con 10.000 €, el
  deslizamiento es 0,005 % en BTC/EUR y 0,008 % en ETH/EUR (0,002 % y 0,009 % contra USDC); SOL y XRP, ~0,02 %;
  AVAX 0,34 %, NEAR 0,27 %, TRX y DOGE ~0,11 %. Spread contra euro: AVAX 0,20 % y NEAR 0,15 % (por encima del 0,10 % de
  la regla 16). Volumen de 24 h contra euro: BTC 9,9 M€, ETH 7,8 M€, AVAX 0,05 M€, TRX 0,03 M€.
- **Lo que pesa son las comisiones** (0,40 % ida y vuelta taker), no el deslizamiento, en BTC y ETH.

## Por que

- **Menos sesgo de supervivencia:** elegir monedas por como van hoy favorece a las que sobrevivieron; BTC (la
  referencia) y ETH son las de menos sesgo y las de historia mas larga.
- **Mas anyos limpios:** con BTC y ETH hay 2018-2020 sin mirar (mercado bajista, lateral y la caida de 03/2020).
- **Menos grados de libertad:** cada moneda mas es un intento mas en el liston (ya van ~35).
- **Liquidez de sobra para escalar** (decision 2), incluso a 100.000 €.
- **Euros:** sin el riesgo del cambio euro/dolar y en la moneda en que se mide todo (decision 1); se ingresa por SEPA.

## Lo que implica

- **Regla 3:** de "solo X/USDC de 8 monedas" a "solo BTC/EUR y ETH/EUR". La clave de OKX, con BTC y ETH (y EUR).
- **Regla 17** (paridad de USDC): deja de tener sentido para operar en euros.
- **Regla 15** (correlacion): BTC y ETH se mueven muy juntos; lo que haga con ella se ve con la estrategia.
- **El papel de L sigue igual** (es un estudio con sus 8 monedas contra USDC; no opera).

## Sin comprobar

- **Si las comisiones de los pares contra euro son las mismas** que las configuradas (0,10/0,20 %): se mira con
  `account/trade-fee` (la clave) antes de estudiar costes.
- **La profundidad del lado de venta y en momentos de panico** (solo una foto): el estudio la mide en varios momentos.
- **Que la historia contra USDT pasada a euros se parezca a la de BTC/EUR** donde coinciden (desde 11/2023): el
  estudio lo comprueba antes de usarla.
