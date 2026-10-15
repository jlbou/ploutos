# Que puede ver la fase 6 (01/10/2026, para la decision de la sombra del 02/10)

**Pregunta:** con el ritmo de candidatos que hay, y con la sombra, que diferencia entre la IA y el baseline puede
declarar el juez de la fase 6, y con que probabilidad. **Estado: estudio; no cambia nada.** Las reglas del juez se
fijaron antes de ver datos (protocolo de la fase 6, 24/09) y no se tocan aqui.

**Como:** `potencia.py` simula fases 6 enteras con las MISMAS piezas que el juez (`portfolio/comparacion.py`): la
M1 por vela, el intervalo del 90 % remuestreando dias enteros y el veredicto (APORTA solo con 30 discrepancias o
mas). 400 fases por casilla, 1.000 remuestreos. Entradas medidas: 0,52 velas con candidatos al dia en vivo (la
sombra anyade 0,51-1,00, segun `candidatos-sombra`); 1 de cada 3 velas discrepa (en vivo y en la prueba en seco;
se prueba tambien 1 de cada 2); 1,97 R de desviacion por operacion (se prueba tambien 2,8, si en la vela que
discrepa cada una abre una distinta). **delta** = lo que gana (o pierde) la IA en cada vela en que discrepa, en R.
Referencia: el baseline pierde -0,38 R por operacion; una IA que solo supiera saltarse las malas ganaria del
orden de +0,4 R en cada salto. Resultado completo en `resultado.json`.

## Lo que sale (sigma 1,97 R, 1 de cada 3 velas discrepa; las otras casillas, en el JSON, dicen lo mismo)

| A las 8 semanas | Discrepancias | Con 30 o mas | APORTA si delta +0,5 / +1,0 | PERJUDICA si delta -0,5 / -1,0 |
|---|---|---|---|---|
| Sin sombra (lo de ahora) | 9,5 | 0 % | 0 % / 0 % | 23 % / 49 % |
| Sombra sola, ritmo alto (se juzga aparte) | 18 | 1 % | 0 % / 1 % | 31 % / 73 % |
| Las dos juntas (no es lo que dice el protocolo) | 28 | 39 % | 17 % / 38 % | 42 % / 88 % |

Con 1 de cada 2 velas discrepando, "las dos juntas" llegan a 43 discrepancias y APORTA sale el 49 % (+0,5) y el
93 % (+1,0). A las 3 semanas (el minimo) no se ensenya nada: no hay 30 discrepancias en ninguna casilla.

**Falsa alarma:** con una IA que ni gana ni pierde (delta 0), el juez dice PERJUDICA el **7 %** de las veces (de
media; hasta el 11 %), algo mas que el 5 % nominal: con pocas discrepancias, el intervalo por dias se queda
estrecho. APORTA en falso: 0 % sin sombra, hasta el 6 % con todo junto.

## Lo que quiere decir

1. **Sin sombra, la fase 6 NO puede decir "APORTA"**: el minimo de 30 discrepancias no se alcanza en 8 semanas
   (unas 10). Solo puede decir PERJUDICA (si la IA es claramente mala) o NO CONCLUYENTE. El protocolo ya preve
   ese caso (decision 4: no concluyente -> fase 7 con la IA y se sigue midiendo); ahora se sabe que es casi seguro.
2. **La sombra, juzgada aparte, tampoco lo cambia**: dobla la muestra en el mejor caso y sigue sin llegar a 30.
   Lo que si gana: ver antes una IA claramente mala (de 49 % a 73 % con delta -1,0).
3. **Juntas** (real + sombra en una sola M1) seria la unica forma de que APORTA fuera posible en 8 semanas, y solo
   si la IA es MUY buena (+1 R por decision distinta: mas del doble de lo que pierde el baseline). Pero juntar las
   dos cambia el protocolo (decision 5: "otra medicion, se juzga aparte"): si se quisiera, tiene que decidirlo el propietario
   ANTES de ver un solo dato de sombra, y con un argumento en contra: las decisiones en sombra no son identicas a
   las de verdad (la IA decide con un hueco que no existe).
4. **Para una ventaja realista** (+0,25 a +0,5 R por decision distinta), verla 8 de cada 10 veces pide unas
   (2,49 x 1,97 / delta)^2 discrepancias: ~96 con +0,5 R y ~385 con +0,25 R. A ~0,5 discrepancias al dia (real
   y sombra juntas), de medio anyo a dos anyos. Eso es la fase 8 (medir en vivo, mucho tiempo), no la 6.

**Para la decision del 02/10:** la sombra no hace que la fase 6 sea concluyente. Su valor es otro: el doble de
datos para lo que se siga midiendo despues (fases 7 y 8) y ver antes una IA mala. Si eso compensa ~1 dia de
trabajo y ~0,5 llamadas mas al dia, es la pregunta real.

Limites del calculo: las velas que discrepan se tratan como independientes entre dias y con una desviacion fija;
en la realidad, un mismo pullback puede seguir varias velas (`candidatos-sombra`: dos de cada tres en sombra son el
mismo), lo que hace la muestra efectiva aun MAS pequenya. Los numeros de arriba son, por eso, optimistas.
