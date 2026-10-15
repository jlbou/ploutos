# Operaciones de horas (velas de 1 h): estudio

Pedido por el propietario el 06/10/2026 (opcion B): "el que tenia jo en ment era un bot que treballes amb operacions curtes, de
hores". Es la idea B de la segunda ronda (`docs/archivo/plan-segunda-ronda-estrategia.md`), adelantada como estudio: **el bot
que corre no se toca** y la muestra de la fase 6 sigue igual. Metodo, el de la revision de la estrategia
(`docs/archivo/propuesta-revision-estrategia.md`): exploracion USDT 02/12/2020 -> 30/06/2024; **la reserva, sin bajar**.

## 1. La pregunta

Con las comisiones de la cuenta (0,10 % al entrar, 0,20 % al salir; el objetivo sale a mercado, `51094`) y 50 $,
**las operaciones de horas ganan mas por operacion que las de dias?** Y de paso: cuanto duran de verdad, cuantas salen
al dia y que parte del bruto se comen las comisiones.

## 2. Lo que se mide (fijado ANTES de medir, 06/10)

El recorrido del bot SIN cambios (`scripts/replay_baseline.py` via `revision-estrategia/medir.py`: el mismo bucle, las
19 reglas, los tres setups, el slider en 3), con UN cambio comun a todas: **el objetivo se cobra TAKER** (el papel lo
cobra maker; decision del 02/10: la correccion es de despues del veredicto en el bot, pero un estudio de operaciones
cortas no puede llevar ese sesgo, que crece cuanto mas pequenyo es el movimiento).

| Nombre | Velas | Stop (multiplo de ATR) | Por que |
|---|---|---|---|
| **R4** (referencia) | 4 h | 1,9 (el de hoy) | la estrategia actual con el mismo modelo de comisiones |
| **H1** | 1 h | 3,3 (el de `settings.yaml` para 1 h) | la idea B tal cual: posicion de ~15 $, stop ~3,3 %. Probablemente NO son operaciones de horas (el objetivo a 2 R queda a ~6,7 %) |
| **H2** | 1 h | 1,5 | lo que el propietario describe: stop de ~1,5 %, objetivo a ~3 %, operaciones de horas. La posicion topa en 20 $ (el cinturon) y el riesgo por operacion baja de 0,50 $ |

El 1,5 es el extremo bajo del rango que ya se uso en la idea 4 (1,5-2,5) y el multiplo "de libro"; se fija ahora y
no se ajusta despues. La reversion lleva su propio stop (bajo el suelo del rango) y no cambia.

**Validacion antes de medir:** el mismo programa SIN el cambio del objetivo, en 4 h, tiene que reproducir la referencia
de la primera ronda EXACTA (497 operaciones, +0,13 R, IC -0,04 a +0,30). Si no, no se mide nada.

## 3. El criterio (fijado ANTES de medir)

H1 o H2 **pasa** si cumple las tres:
1. IC 90 % del R medio (bootstrap por dias) **entero por encima del R medio de R4**;
2. al menos 100 operaciones;
3. R medio positivo en al menos 2 de los 3 anyos completos (2021, 2022, 2023).

Si no pasa pero su IC queda entero por encima de 0, se dice como "no pierde, pero no mejora a la de 4 h".
Si pasa, **no se cambia nada**: se mira la reserva una sola vez y se lleva al propietario con la segunda ronda (despues del
veredicto de la fase 6). Una ventaja solo en exploracion no basta para tocar el bot.

Ademas, sin criterio (descriptivo): duracion mediana en horas, % de operaciones cerradas en menos de 24 h,
operaciones por dia, comisiones sobre el bruto y % de posiciones que topan en 20 $.

## 4. Limites conocidos (dichos antes de medir)

Los de la primera ronda (precios contra USDT, tick y lote de hoy, spread de hoy para todo el periodo) y uno propio:
en 1 h el deslizamiento real de la salida a mercado pesa mas que en 4 h y aqui no se cobra (el stop sale al precio del
stop o al de apertura si hay hueco; el objetivo, al precio del objetivo). Va a favor de las operaciones cortas.

## 5. Resultados (06/10)

**Validacion:** sin el cambio del objetivo, en 4 h, reproduce la referencia de la primera ronda EXACTA (497 operaciones,
+0,13 R, IC -0,04 a +0,30, de 50 a 123,78 $; `validacion.json`). Despues se midio.

| | R4 (4 h, de hoy) | H1 (1 h, stop 3,3 ATR) | H2 (1 h, stop 1,5 ATR) |
|---|---|---|---|
| Operaciones | 497 | 925 | 1.419 |
| Aciertos | 28 % | 29 % | 22 % |
| **R medio** | **+0,12** | **-0,13** | **-0,12** |
| IC 90 % | -0,04 a +0,29 | **-0,23 a -0,02** | **-0,22 a -0,01** |
| Anyos completos con R > 0 (2021-2023) | 2 de 3 | 1 de 3 (solo 2021) | 1 de 3 (solo 2021) |
| De 50 $ a | 120,44 $ | 54,57 $ | **26,09 $** |
| Caida maxima | 25,9 % | 51,1 % | **65,6 %** |
| Duracion mediana | 40 h | 29 h | **8 h** |
| Cerradas en < 24 h | 35 % | 46 % | **75 %** |
| Operaciones al dia | 0,38 | 0,71 | **1,10** |
| Bruto / comisiones | 94,09 $ / 24,90 $ | 47,21 $ / 43,45 $ | 36,89 $ / **60,80 $** |
| **Comisiones sobre el bruto** | 26 % | **92 %** | **165 %** |
| Topadas en 20 $ | 54 % | 42 % | 29 % |
| Riesgo medio por operacion | 0,71 $ | 0,52 $ | 0,30 $ |

Por setup, en 1 h: el pullback queda en ~0 (+0,06 R en H1, +0,03 en H2; en 4 h, +0,39); la ruptura, ~0 o negativa;
la reversion pierde mucho en las tres (-0,60 / -0,80 / -0,71 R).

**Veredicto contra el criterio (seccion 3): NI H1 NI H2 PASAN.** Las dos fallan el punto 1 (su IC no solo no supera
+0,12: queda entero POR DEBAJO DE CERO) y el 3 (solo ganan en 2021). Cumplen el 2 (>= 100 operaciones). Ni siquiera
llegan a "no pierde, pero no mejora": **pierden, y no es azar.** La reserva no se mira.

Lo que dice:
1. **H2 es lo que el propietario describia** (8 h de mediana, 3 de cada 4 cerradas en el dia, ~1 operacion al dia, dentro del
   1-5 del PRD) **y es la peor**: el bruto es positivo (+36,89 $), pero las comisiones (60,80 $) se lo comen 1,65
   veces. Con 50 $ habria acabado a 1 $ del suelo de la regla 7.
2. **El mecanismo es el de la aritmetica de antes:** con stops mas cortos, la posicion topa en 20 $ y el riesgo por
   operacion baja (0,30 $ en H2), pero la comision casi no baja: 0,043 $ por operacion en H2, que son **0,14 R**,
   contra 0,050 $ y 0,07 R en R4. Y el movimiento que se captura es mas pequenyo.
3. **H1 acaba con mas dolares de los que tenia (54,57 $) aunque su R medio sea negativo:** las operaciones no son del
   mismo tamanyo en dolares y el juicio es en R (como en toda la revision). Con un 51 % de caida maxima.
4. Los limites de la seccion 4 van A FAVOR de las de horas (sin deslizamiento en la salida a mercado): en real, peor.

**Consecuencia:** las operaciones de horas, con esta estrategia, estas comisiones y este capital, no se proponen para
la segunda ronda. Lo que queda abierto es el otro motivo del propietario (que el bot opere mas a menudo), que no se resuelve
acortando las operaciones.
