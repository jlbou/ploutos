# Robustez de L: ¿solida o suerte? (plan fijado el 10/10/2026 ANTES de medir; resultado: SOLIDA)

Pedido por el propietario ("Fem la 1", 10/10): mirar si L se sostiene cuando cambian detalles que no deberian importar. **Solo
informacion: ninguna variante sustituye a L, salga lo que salga** (elegir la mejor seria volver a buscar hasta que algo
salga bien). El papel de L sigue tal cual (`docs/diseno-papel-l.md`).

## Las variantes (lista cerrada, 12; todo lo demas, como L)

| Grupo | Variantes | L |
|---|---|---|
| Dia de la rotacion (a las 00:00 UTC, con el cierre del dia anterior) | martes, miercoles, jueves, viernes, sabado, domingo (6) | lunes |
| Plazos de las medias | x0,8 (16/40/80/160), x0,9 (18/45/90/180), x1,1 (22/55/110/220), x1,25 (25/63/125/250) (4) | 20/50/100/200 |
| Filtro de BTC (cuantas de sus 4 medias) | al menos 1; al menos 3 (2) | al menos 2 |

En los dos periodos ya medidos: la **exploracion ampliada** (14/12/2020-20/08/2025) y el **anyo USDC** (01/09/2025-
27/09/2026, calentado en USDT). Validacion antes: L sin cambios tiene que dar EXACTO `L-ampliada.json` y `L-usdc.json`.

## Como se lee (fijado antes)

- **Exploracion:** cuantas de las 12 pasan las condiciones 1-5 de la segunda tanda (`segunda_tanda.py`), y donde
  queda el Sharpe de L entre ellas.
- **Anyo USDC:** cuantas pierden, y el rango de rendimiento y de caida.
- **L es SOLIDA si** en la exploracion pasan 1-5 al menos 9 de las 12 **y** la mediana del Sharpe de las 12 es al
  menos el 80 % del de L (1,46 -> 1,17). **Es FRAGIL si** no se cumple alguna de las dos: su resultado dependia de
  los detalles exactos.
- El anyo USDC se ensenya, no puntua: alli L ya no paso.

## Resultado (10/10, `robustez_l.py`, `robustez-l.txt`; plan en `29c6a01`, herramientas en `1706589`)

Validacion: L sin cambios da EXACTO `L-ampliada.json` y `L-usdc.json`.

**L es SOLIDA por la lectura fijada:** en la exploracion pasan las condiciones 1-5 **las 12 variantes** (hacia falta 9)
y la mediana de su Sharpe es 1,53, el 105 % del de L (1,46; hacia falta el 80 %). **L no es la mejor de su familia
elegida por suerte: queda en medio** (por encima de 4 de las 12).

| Exploracion | 50 $ -> | Caida | Sharpe | 2022 |
|---|---|---|---|---|
| L (lunes) | 421 $ | 44,5 % | 1,46 | -11,0 % |
| Otros dias (6) | 450 - 1.077 $ | 32,8 - 43,9 % | 1,50 - 2,09 | -6,1 a +0,3 % |
| Otros plazos (4) | 386 - 484 $ | 39,8 - 44,6 % | 1,39 - 1,54 | -12,3 a -6,2 % |
| Filtro de BTC (2) | 342 - 542 $ | 43,5 - 48,0 % | 1,30 - 1,65 | -16,3 a -11,1 % |

**Anyo USDC (no puntua):** de -7,0 % a +12,9 %; **pierden 6 de las 12**; caida de 17,2 a 27,7 % (BTC -22,3 %, caida
53,1 %). L (-6,9 %) queda en el extremo malo: en un anyo bajista la familia anda por el cero.

Lo que se aprende:
1. **La idea es solida:** cambie lo que cambie, en la exploracion gana y cae mucho menos que BTC. No depende de haber
   acertado los detalles.
2. **Las cifras exactas son inciertas:** solo cambiar el dia de la semana mueve el final de 421 a 1.077 $ en la
   exploracion y de -7 a +13 % en el anyo USDC. El resultado de cualquier anyo concreto tiene mucho de azar del
   calendario: hay que esperar un abanico, no un numero.
3. **Nada cambia en L:** el viernes salio mejor, pero elegirlo seria volver a buscar. El papel sigue con el lunes.
