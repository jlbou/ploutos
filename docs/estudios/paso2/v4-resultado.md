# V4: Bitstamp contra OKX en euros (15/10/2026)

**Criterio, fijado y subido antes de mirar** (`docs/plan-estudio-paso-2.md`): mediana de |diferencia| del cierre
diario UTC < 0,10 % y el 99 % de los dias < 1 %, en los dos pares.

| Par | Dias en comun | Mediana | p99 | Maxima | Criterio |
|---|---|---|---|---|---|
| BTC/EUR | 1.059 (21/11/2023-14/10/2026) | 0,034 % | 0,474 % | 4,36 % (23/03/2024) | pasa |
| ETH/EUR | 1.059 | 0,044 % | **1,026 %** | 2,33 % (15/03/2024) | **NO pasa** (por 0,026 puntos) |

## Por que no pasa (estudiado antes de decidir)

Las diferencias grandes son todas de los **primeros meses de los pares en euros de OKX** (11/2023-03/2024), con muy
poco volumen: dias de 0 a 20 ETH en OKX frente a miles en Bitstamp; el cierre de OKX era el de una operacion suelta.

| Anyo | BTC p99 | ETH p99 | Dias ETH > 1 % |
|---|---|---|---|
| 2023 (desde 21/11) | 0,96 % | 1,81 % | 7 |
| 2024 | 0,61 % | 1,03 % | 5 |
| 2025 | 0,21 % | 0,29 % | 0 |
| 2026 | 0,24 % | 0,29 % | 0 |

## Decision del propietario (15/10, opcion a), tomada DESPUES de ver los datos

**Se acepta Bitstamp** como historia en euros. Queda escrito que **V4 no paso tal como estaba escrita**, el motivo
encontrado (la falta de liquidez de OKX al principio, no un error de Bitstamp, que tiene mucho mas volumen) y que la
decision se tomo despues de mirarlo. **El criterio no se cambio:** no se rehizo la comprobacion con solo 2025-2026.

Scripts: `bajar_historia.py` (datos en `var/estudios/paso2/`, fuera de git) y `comprobar_v4.py`.
