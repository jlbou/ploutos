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
