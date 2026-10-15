# Las dos carteras y el techo de ATR (29/09/2026)

**Estado: DECIDIDO el 02/10 (el propietario): opcion A, dejarlo escrito sin tocar nada.** Se decidio (`docs/archivo/dossier-02-10.md`, 2.3). Ni el codigo ni el camino
de decision se tocan: la huella sigue en `f063d80147a9`.

## 1. Que paso

NEAR, 29/09 08:00 UTC: ATR 5,333 %. Sale como candidato en el baseline y **no** en la IA:

| | Equity | Techo de ATR de NEAR | Resultado |
|---|---|---|---|
| Baseline | 49,85 $ | ~5,34 % (5,323 x 49,85 / 49,68) | pasa: candidato con entrada 4,913 |
| IA | 49,68 $ | 5,323 % | "atr: demasiado alto" |

**Causa:** `strategy/filters.atr_ceiling_pct` = 100 x riesgo por operacion / minimo por orden / multiplo de ATR. El
riesgo es el 1 % del equity (regla 12), asi que un equity distinto da un techo distinto. Con 0,34 % de diferencia entre
carteras, un ATR entre los dos techos (una franja de 0,018 puntos) las separa. **No es un fallo: es la regla 12
actuando sobre dos carteras que ya no tienen el mismo equity.** Estaba previsto (la fase 6 dice que las carteras
divergen), pero no se habia medido cuanto.

## 2. En vivo (25/09 12:00 - 29/09 08:00, 24 velas)

Comparadas las 155 filas de decision de cada cartera (vela x moneda):

- **2 diferencias de criba**, las dos de NEAR y las dos por el techo de ATR: el 26/09 08:00 (IA ATR 5,384 % contra
  5,380 %; el baseline caia igual por no tener hueco, asi que no cambio nada) y el 29/09 08:00 (la de arriba).
- **1 diferencia en los candidatos:** el baseline vio 5, la IA 4. Con 5 candidatos es una muestra minuscula: no
  dice que sea el 20 %.
- El 28/09 12:00 fue al reves: el techo de la IA (5,236 %) era mas alto que el del baseline (5,217 %). Nadie gano ni
  perdio candidato porque el ATR de NEAR (5,516 %) superaba los dos.
- **NEAR esta pegada al techo estos dias:** ATR 5,0-5,9 % contra techos de 5,0-5,5 %. Es la moneda con mas
  volatilidad relativa de la whitelist, y la unica que el techo de ATR frena de forma habitual.

## 3. En la historia (`divergencia.py`)

El recorrido del bot sobre el anyo USDC (21/08/2025 - 28/09/2026: 2.310 velas, 385 dias), SIN cambios: sale
identico (161 operaciones, 198 candidatos; los de `candidatos-sombra/anyo-usdc.json`). En cada vela se vuelve a pasar
la criba con el riesgo por operacion multiplicado por un factor, y se cuentan los candidatos que se ganan o pierden:

| Diferencia de equity entre carteras | Factor del riesgo | Candidatos perdidos | Ganados |
|---|---|---|---|
| 0,17 % (la de hoy, +-) | 0,9966 / 1,0034 | **0 de 198** | 0 |
| 1 % | 0,99 / 1,01 | 0 | 0 |
| 5 % | 0,95 / 1,05 | 0 | 1 (0,5 %) |
| 10 % | 0,90 / 1,10 | 1 (0,5 %) | 3 (1,5 %) |
| **Regla 9: por debajo de 45 $, riesgo a la mitad** | 0,50 | **17 (8,6 %)** | 0 |

Lo que dice:
1. **Con la diferencia de hoy, en un anyo entero no se pierde ni un candidato.** El caso de NEAR es real pero raro:
   hace falta un ATR dentro de una franja de decimas de punto. Lo del 29/09 es mala suerte de muestra pequena, y
   con NEAR pegada al techo estos dias (seccion 2) es mas probable ahora que de media.
2. **El caso que si importa es la regla 9.** Si UNA cartera baja de 45 $ y la otra no, la de abajo arriesga la mitad,
   su techo de ATR baja a la mitad y pierde el 8,6 % de los candidatos (los mas volatiles). Hace falta un 10 %
   de drawdown (45 $ de 50 $); el baseline lleva un maximo del 3,3 %.
3. No se ha corrido la exploracion USDT (falta bajar la base con `revision-estrategia/bajar_exploracion.py`); el
   anyo USDC es el que cuenta para este dato.

## 4. Que le hace a la fase 6

La M1 (`portfolio/comparacion.py`) mide **cada candidato que vio la IA** y calcula sobre la MISMA lista lo que habria
abierto el baseline. Asi que:
- Un candidato que solo ve el baseline (NEAR, 29/09) **no entra en la M1**: es de la cartera del baseline, que es
  descriptiva. Se pierde una muestra, no se sesga la comparacion.
- Un candidato que solo ve la IA entra en la M1, y el baseline "elige" sobre esa lista como siempre.
- `check_fase6.py` no da FALLA por esto: solo compara los numeros de los candidatos que estan en las dos carteras
  (4 comparados, OK).
- **Lo que NO esta cubierto:** el protocolo excluye los tramos con una cartera PARADA, pero no dice nada de los
  tramos con una cartera por debajo de 45 $. Ahi las listas de candidatos divergen mucho mas (17 de 198 en vez
  de 0), y las dos carteras tienen tambien tamanyos distintos.

## 5. Opciones para el 02/10 (recomendada: A)

- **A. No hacer nada y dejarlo escrito (recomendada).** La M1 no se sesga y la diferencia de hoy no perdio ni un
  candidato en un anyo. Coste cero, sin tocar el camino.
- **B. Que el juez lo cuente.** `check_fase6.py` avisa (nota, no FALLA) de las velas en que una cartera tuvo un
  equity de la regla 9 y la otra no, y de los candidatos que solo vio una. Toca un juez, no el camino de decision;
  ~medio dia con tests.
- **C. Igualar el techo.** Calcular el techo con el equity inicial (50 $) en las dos carteras en vez de con el
  suyo. Las dos verian los mismos candidatos siempre, pero **cambia la regla 12 en el simulador** y parte la
  muestra (huella nueva). No se recomienda: la fase 6 mide precisamente el bot tal cual es.
