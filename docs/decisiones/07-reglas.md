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
