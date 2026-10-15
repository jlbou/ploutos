# Time-stop: ¿cerrar por tiempo mejora el resultado? (y el baseline en un año)

Estudio del 25/09/2026. Todo se midió en una copia aparte: el bot no se tocó.

## La pregunta

Una posición vive hasta tocar su stop o su objetivo, aunque pasen semanas. ¿Mejora algo un **time-stop** (vender
una posición que lleva N velas abierta)?

## Método

- **Un año de datos reales:** velas de 4 h y 1 h de las 8 monedas desde el 21/08/2025, bajadas de la API pública de
  OKX (`bajar_historia.py`). El tramo tiene de todo: de agosto de 2025 a marzo de 2026 el mercado cae (BTC −20 % y
  −25 % en dos trimestres seguidos) y de abril a septiembre de 2026 sube (+30 %).
- **El mismo recorrido del baseline** que en vivo (`scripts/replay_baseline.py`), con comisiones maker 0,10 % y
  taker 0,20 %.
- **El time-stop, parcheado en memoria** (`experimento.py`): vender al cierre de la vela N, a mercado. Dos
  variantes: **siempre** y **sin avance** (solo si no ha hecho ni la mitad del camino al objetivo).

## Resultados

50 $ iniciales, 21/08/2025 - 25/09/2026 (`resultados.jsonl`). "x tiempo": operaciones cerradas por el time-stop.

| Variante | Op. | Aciertos | R medio | Neto | Final | Caída máx. | x tiempo | R de esas |
|---|---|---|---|---|---|---|---|---|
| **Sin time-stop** | 159 | 19 % | **−0,38** | −12,14 $ | 37,74 $ | 32,0 % | - | - |
| 6 velas (1 día) | 286 | 35 % | −0,25 | −12,78 $ | 37,22 $ | 34,0 % | 141 | +0,34 |
| 12 velas (2 días) | 239 | 29 % | −0,27 | −11,20 $ | 38,82 $ | 33,3 % | 73 | +0,58 |
| 18 velas (3 días) | 215 | 29 % | −0,26 | −10,52 $ | 39,39 $ | 30,6 % | 49 | +0,66 |
| 30 velas (5 días) | 194 | 25 % | −0,28 | −11,84 $ | 37,98 $ | 31,8 % | 24 | +0,76 |
| 42 velas (7 días) | 183 | 23 % | −0,32 | −11,39 $ | 38,77 $ | 31,0 % | 14 | +0,77 |
| 18 velas, sin avance | 214 | 29 % | −0,28 | −11,01 $ | 38,91 $ | 31,2 % | 47 | +0,53 |

**Lo que dice:**
- **En dinero, el time-stop no cambia nada:** la mejor variante acaba 1,65 $ por encima en un año, dentro del ruido.
- **Por qué:** las posiciones que corta estaban GANANDO (+0,34 a +0,77 R al cortarlas). Libera el hueco para abrir
  otra operación de una estrategia que, de media, pierde. Más operaciones de algo que pierde no arreglan nada.
- **Lo que sí hace: más candidatos** (273 en vez de 197 con 18 velas), pero cambiar la estrategia para tener más
  muestra es medir otra estrategia.

## Lo importante: el baseline pierde en un año

- **159 operaciones, 19 % de aciertos, −0,38 R de media, de 50 $ a 37,74 $ (−24,5 %).** Pierde en los dos tramos:
  −0,37 R en el bajista y −0,39 R en el alcista.
- Comprar y esperar: BTC −25,0 %; las 8 a partes iguales +2,6 %.
- **Las reglas duras hicieron su trabajo:** trece meses con una estrategia que pierde y el equity nunca se acercó al
  suelo de 25 $.

| Dónde se pierde | |
|---|---|
| Stops | 129, a **−1,27 R** de media (no −1,00: huecos y comisión de salida) |
| Objetivos | 30, a +3,43 R |
| Para no perder haría falta acertar | el 27 % (acierta el 19 %) |
| **Muertas en 0-1 velas** | **43 (27 %), a −1,31 R**: la compra limitada se llena PORQUE el precio cae, y sigue cayendo |
| Por setup | pullback −0,47 R (73), reversión −0,50 R (43), ruptura −0,10 R (43) |

## Lo que este estudio NO dice

- Usa el spread de hoy para todo el año y supone USDC en paridad.
- El simulador es pesimista a propósito (el stop gana los empates y sufre los huecos).
- Es UN año y UN baseline: un arreglo probado sobre estos mismos datos corre el riesgo de ajustarse a ellos. Por eso
  la revisión de la estrategia ([`../revision-estrategia/`](../revision-estrategia/)) explora con otros años y guarda
  una parte sin mirar.

**Decisión:** sin time-stop por ahora, y revisar la estrategia antes de usar dinero real.
