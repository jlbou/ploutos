# Decision: para que es la fase 7 (preparada el 09/10/2026)

**Estado: PREPARADA, pendiente del propietario.** No cambia nada del bot. El como de la fase 7 esta en `docs/archivo/guion-fase-7.md`;
esto es el **para que**, que va antes.

## 1. Donde estamos

- **Decision 4a del propietario (25/09):** sin una estrategia que no pierda en la reserva, no hay fase 7.
- **Ninguna estrategia ha pasado** (`docs/archivo/plan-segunda-ronda-estrategia.md`): ~25 variantes medidas, la mejor (2 + D)
  fallo por dos milesimas y esta guardada como candidata sin abrir la reserva. Quedan apuntadas F (rotacion semanal)
  y G (filtro de financiacion), sin medir.
- **La literatura** (`docs/estudios/recerca-trading-cripto.md`) dice lo mismo que los datos: en spot, solo largos y
  monedas grandes, seguir la tendencia sirve para caer menos, no para ganar mas que comprar y mantener. Una estrategia
  que gane con claridad con estas reglas puede no existir.
- **El PRD** define el exito como reglas que se cumplen, trazabilidad y saber si la IA aporta; "la rentabilidad es
  secundaria".
- **Calendario que manda igualmente:** el veredicto de la fase 6 (probablemente el 20/11) y 3 semanas de papel y demo
  si cambia la estrategia: dinero real, en ningun caso antes de finales de noviembre o diciembre.

## 2. Que se juega con 50 $ (las cuentas)

Con el slider 1 o 2 (PRD), el riesgo por operacion es de 0,25-0,37 $. Lo que pasaria en un anyo, con los numeros ya
medidos y ~150 operaciones al anyo (el ritmo del anyo USDC):

| Si el anyo se parece a... | R por operacion | En un anyo, aprox. |
|---|---|---|
| El anyo USDC (08/2025-09/2026) | -0,38 | **-15 a -20 $** (los escalones de la regla 9 lo frenan) |
| La exploracion (2020-2024) | +0,12 | +5 $ |
| Lo peor posible | - | **-25 $** y algo de deslizamiento: el suelo (regla 7) cierra todo y se enclava |

Es decir: **lo maximo que se puede perder es ~25-27 $**, y con la estrategia de hoy lo esperable en un anyo malo es
perder ~15-20 $.

**Lo que el dinero real ensenya y el papel y el demo no:** el deslizamiento de verdad en las salidas a mercado, las
entradas post-only rechazadas, los llenados parciales, el CSV fiscal real y la confianza en que todo funciona con
dinero. **Lo que NO ensenya:** si la IA aporta. Esa comparacion sigue en papel (la cuenta real solo copia una cartera);
con 50 $ y pocas operaciones al mes, el dinero real no anyade muestra a la fase 6.

## 3. Las opciones

**A. Mantener la 4a (fase 7 solo con una estrategia que no pierda en la reserva).**
Mientras no la haya, el bot sigue en papel y en el demo, gratis, y la fase 6 sigue midiendo la IA. Coste: 0 $. Riesgo:
que la fase 7 no llegue nunca. Es lo que hay hoy.

**B. Fase 7 para MEDIR, no para ganar.** Dinero real con la estrategia de hoy (o la que haya), aceptando que lo
esperable es perder un poco: el precio de ver la realidad (deslizamiento, rechazos, fiscalidad). Slider 1-2 y los
criterios de parada del guion (equity < 40 $ = pausa y revision). Coste esperable: ~0-20 $; maximo ~27 $.

**C. Decidir con la reserva: llevar UNA candidata y que decida.** Primero medir F (la rotacion) en la exploracion con
su criterio; despues, la mejor de 2 + D y F (una sola) va a la reserva y al anyo USDC con el criterio duro ("no
perder"). Si pasa: fase 7 con esa estrategia, tras su tramo de papel y demo. Si no pasa: elegir entre A, B y D, ya sin
dudas pendientes. Coste: ~1-2 dias de trabajo, la reserva gastada.

**D. Cerrar Ploutos como experimento.** El sistema funciona (19 reglas, trazabilidad, demo sin descuadres) y la
conclusion seria: con estas reglas no hay ventaja que justifique dinero. Se apaga ordenadamente (o se deja en papel) y
se pasa a Ebisu. Es un resultado, no un fracaso (`guion-fase-7.md`: "y eso tambien es un resultado").

## 4. Recomendacion

**C, y despues A o D segun salga; no B.**
- B es pagar por perder con una estrategia que perdio en su anyo mas reciente; lo que se aprende de la ejecucion real
  es util pero pequenyo frente a lo que ya ensenya el demo.
- C cierra la pregunta con datos y con una sola bala bien gastada: la reserva existe para esto.
- Si nada pasa, A (seguir midiendo la IA gratis hasta el veredicto) o D (cerrar y aprender para Ebisu) son honestas;
  entre las dos, decide el propietario segun cuanto le aporte seguir con Ploutos.

## 5. Lo que tiene que decidir el propietario

1. **Para que es la fase 7:** ganar dinero (A o C) o medir la realidad con dinero (B).
2. Si C: **el orden** (medir F primero y elegir una candidata, o llevar 2 + D directamente) y el **criterio del anyo
   USDC** ("no perder", R medio >= 0, propuesto el 09/10).
3. Si al final nada pasa: **A o D**.
