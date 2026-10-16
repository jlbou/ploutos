# El motor del simulador del paso 2: que hace cada dia

Del PRD v3 (seccion 4) y del plan (secciones 8 y 11). Cada dia i (vela diaria UTC de Bitstamp):

## A la apertura del dia i (la orden de la senyal del cierre de i-1)

1. **Modos.** `CAPITAL` (regla 7): enclavado si el equity al cierre fue <= suelo dos dias seguidos; con el, solo se
   vende. `DAILY` (regla 10): desde las 00:00 UTC (la apertura), si lo cerrado + lo abierto pierde >= 6 % del capital de
   referencia frente al equity de la apertura, ese dia no se abre ni se aumenta (con ordenes solo a la apertura, solo
   puede saltar tras un stop del mismo dia, y entonces ya no hay mas ordenes ese dia).
2. **El equity de referencia** es el del cierre de i-1 (aclaracion C5), con las comisiones de salida (regla 6).
3. **Escalones** (regla 9, con ese equity frente al capital de referencia): -10 % -> topes a la mitad (22,5 % y 2,5 %);
   -20 % -> maximo 1 posicion; -30 % -> las dos cosas.
4. **Objetivo de cada moneda** = fraccion de la senyal × tope por moneda (45 %) × equity; recortado por el riesgo hasta
   el stop (5 %: nocional <= 5 % × equity / distancia al stop en %), por la exposicion total (90 %) y por la regla 8.
5. **Vuelta tras un stop** (C1): una moneda que salio por stop no vuelve a comprar hasta que su senyal se apague (0) y se
   encienda; en H3, hasta el domingo siguiente.
6. **Se ajusta** solo si la diferencia llega al minimo por orden (C6): primero las ventas, despues las compras, a la
   apertura × (1 ± deslizamiento), con la comision taker.
   **Solo se vende si la fraccion de la senyal BAJA, y solo se compra si SUBE** (revision final del 16/10): una compra
   que se reintenta nunca acaba en venta.
6b. **Una compra que una regla no deja hacer** (regla 8, maximo de posiciones, el suelo) **se reintenta cada dia**
   mientras la senyal siga encendida: no se pierde, se retrasa. Una que no pasa por menos del minimo por orden, igual.
   Los escalones solo cambian el tamanyo de las compras nuevas: no obligan a vender lo que ya hay.
7. **El stop** de una posicion nueva: entrada − 3 ATR(14) del dia i-1, fijo; si se anyade a una posicion, el stop no
   cambia. Riesgo y regla 8 se calculan con ese stop.
   **Una posicion que crece mide su riesgo con el stop que tiene** (no con 3 ATR desde hoy): si ya pasa del 5 %, no se
   anyade, y tampoco se vende por eso (revision final del 16/10). Una compra recortada por la exposicion se completa
   cuando hay sitio; la que solo recorta el efectivo (las comisiones) esta completa.

## Durante el dia i

8. **Stop** (C3): si el minimo del dia <= stop, se vende todo a min(stop, apertura) × (1 − deslizamiento), con comision.

## Al cierre del dia i

9. **Equity** = efectivo + Σ cantidad × cierre × (1 − comision taker).
10. **Suelo** (regla 7): dos cierres seguidos <= 50 % del capital de referencia -> `CAPITAL`, para siempre.
11. **Impuestos:** cada venta realiza ganancia o perdida por FIFO; al cierre del 31/12 (y del ultimo dia) se paga el
    impuesto del anyo con los tramos del ahorro y las perdidas de los 4 anyos anteriores. **El ultimo dia, lo abierto
    paga como si se vendiera** (igual que BTC mantenido, C8). El impuesto sale del efectivo aunque quede negativo: el
    equity es el correcto (en la vida real se paga en junio del anyo siguiente).

## Las metricas

La curva empieza en el **capital inicial** (el dia antes del primero), asi cuentan la entrada y sus costes (revision
final del 16/10). Lo mismo para BTC mantenido.

## Validacion (antes de medir nada)

Con fraccion 1 siempre en BTC, sin topes, sin stops y sin impuestos intermedios, el motor tiene que dar **exactamente**
BTC/EUR mantenido (comprar a la apertura del primer dia y valorar al cierre con la comision de salida).
