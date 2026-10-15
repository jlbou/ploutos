# Propuesta: time-stop (y lo que salio al medirlo)

Estado: **DECIDIDO por el propietario el 25/09/2026: 1a (sin time-stop por ahora) y 2a (revisar la estrategia
ANTES de la fase 7).** Decide el propietario. No se ha tocado nada del bot: todo se midio en
una copia aparte (ver "Metodo").

## 1. La pregunta

El PRD (seccion 5) y el informe (1.3[9]) piden un gestor de posiciones con **time-stop** (cerrar
una posicion que no avanza) y **trailing stop**. Hoy no hay ninguno de los dos: una posicion vive
hasta tocar el stop o el objetivo, aunque pasen semanas. Se vio en vivo: con la cartera llena (3 de
3) no se genera ningun candidato, y la fase 6 necesita candidatos para medir. ¿Mejora algo un
time-stop?

## 2. Metodo

- **Datos: un anyo de verdad.** Velas de 4 h y 1 h de las 8 monedas desde el 21/08/2025, bajadas
  de la API publica de OKX (`history-candles`): ~2.400 velas de 4 h por moneda. AVAX/USDC existe en
  OKX EEA desde el 09/10/2025 y NEAR/USDC desde el 26/02/2026: antes no se pueden operar.
- **El tramo tiene de todo:** de agosto de 2025 a marzo de 2026 el mercado cae (BTC -20 % y -25 % en
  dos trimestres seguidos) y de abril a septiembre de 2026 sube (+30 %). El recorrido que teniamos
  (21/08-22/09/2026) era solo alcista.
- **El mismo recorrido del baseline** (`scripts/replay_baseline.py`, el mismo bucle que en vivo) con
  el codigo de la rama de la fase 3 (comisiones de `settings.yaml`: maker 0,10 %, taker 0,20 %).
- **El time-stop, parcheado en memoria** en una copia aparte: si una posicion lleva N velas abierta,
  se vende al cierre de esa vela, a mercado (taker). Dos variantes: **siempre** (tras N velas pase lo
  que pase) y **sin avance** (solo si no ha hecho ni la mitad del camino al objetivo).
- Se valida el montaje repitiendo la ventana conocida (21/08-25/09/2026): sale positiva (+0,45 R,
  14 operaciones, +4,42 $), en la misma direccion que el recorrido de siempre (11 operaciones,
  +7,83 $; ahora hay 3 dias mas, otras comisiones y un anyo de calentamiento).

## 3. Resultados del time-stop

50 $ iniciales, 21/08/2025 - 25/09/2026. "x tiempo" = operaciones cerradas por el time-stop; "exp x t"
= su resultado medio.

| Variante | Op. | Aciertos | Exp. | Neto | Final | Caida max | Bajista | Alcista | x tiempo | exp x t | Candidatos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Sin time-stop (hoy)** | 159 | 19 % | **-0,38 R** | -12,14 $ | 37,74 $ | 32,0 % | -0,37 | -0,39 | - | - | 197 |
| 6 velas (1 dia), siempre | 286 | 35 % | -0,25 R | -12,78 $ | 37,22 $ | 34,0 % | -0,21 | -0,27 | 141 | +0,34 | 356 |
| 12 velas (2 dias), siempre | 239 | 29 % | -0,27 R | -11,20 $ | 38,82 $ | 33,3 % | -0,30 | -0,23 | 73 | +0,58 | 297 |
| **18 velas (3 dias), siempre** | 215 | 29 % | -0,26 R | **-10,52 $** | **39,39 $** | 30,6 % | -0,39 | -0,16 | 49 | +0,66 | 273 |
| 30 velas (5 dias), siempre | 194 | 25 % | -0,28 R | -11,84 $ | 37,98 $ | 31,8 % | -0,32 | -0,25 | 24 | +0,76 | 238 |
| 42 velas (7 dias), siempre | 183 | 23 % | -0,32 R | -11,39 $ | 38,77 $ | 31,0 % | -0,31 | -0,32 | 14 | +0,77 | 222 |
| 12 velas, sin avance | 238 | 29 % | -0,27 R | -11,26 $ | 38,76 $ | 32,5 % | -0,33 | -0,21 | 70 | +0,45 | 299 |
| 18 velas, sin avance | 214 | 29 % | -0,28 R | -11,01 $ | 38,91 $ | 31,2 % | -0,40 | -0,18 | 47 | +0,53 | 273 |
| 30 velas, sin avance | 195 | 26 % | -0,27 R | -11,51 $ | 38,31 $ | 31,2 % | -0,32 | -0,23 | 23 | +0,65 | 245 |

**Lectura:**
- **En dinero, el time-stop no cambia nada.** La mejor variante (18 velas) acaba 1,65 $ por encima en
  un anyo, y las demas entre -0,6 y +1,1 $: dentro del ruido.
- **Por que:** las posiciones que corta el time-stop estaban GANANDO (+0,34 a +0,77 R de media al
  cortarlas). Libera el hueco, si, pero para abrir otra operacion de una estrategia que de media
  pierde (-0,38 R). Mas operaciones de algo que pierde no arreglan nada.
- **Lo que si hace: mas candidatos.** Con 18 velas, 273 en vez de 197 (+39 %). Eso es muestra para la
  fase 6, pero cambiar la estrategia para tener mas muestra es medir otra estrategia.

## 4. Lo importante: el baseline PIERDE en un anyo

Esto es mas grave que la pregunta del time-stop, y es la razon de medir con un anyo:

- **159 operaciones, 19 % de aciertos, -0,38 R de media, de 50 $ a 37,74 $ (-24,5 %).** Con 159
  operaciones ya no es ruido: la media esta claramente por debajo de cero.
- Pierde **en los dos tramos**: -0,37 R en el bajista y -0,39 R en el alcista (abril-julio de 2026
  fueron malos; agosto y septiembre, buenos). Los 32 dias que teniamos eran una ventana
  excepcionalmente buena.
- **Comprar y esperar:** BTC -25,0 %; las 8 a partes iguales +2,6 %. El baseline (-24,5 %) no pierde
  mas que BTC, pero pierde.
- **Las reglas duras hicieron su trabajo:** 13 meses con una estrategia que pierde y el equity nunca
  se acerco al suelo de 25 $; los escalones (regla 9) reducen el riesgo al bajar de 45 $.

**Donde se pierde** (recorrido sin time-stop):

| | |
|---|---|
| Stops | 129, a **-1,27 R** de media (no -1,00: huecos y comision de salida) |
| Objetivos | 30, a +3,43 R |
| Para no perder haria falta acertar | el 27 % (acierta el 19 %) |
| **Muertas en 0-1 velas** | **43 (27 %), a -1,31 R**: la compra limit se llena PORQUE el precio cae, y sigue cayendo ("coger un cuchillo que cae") |
| Duran 4-7 dias | 21, a +0,50 R: las largas no son el problema |
| Por setup | pullback -0,47 R (73), reversion -0,50 R (43), ruptura -0,10 R (43) |

## 5. Lo que este estudio NO dice

- Usa el spread de hoy para todo el anyo (no hay historia del libro) y supone USDC en paridad.
- El simulador es pesimista a proposito (el stop gana los empates y sufre los huecos).
- Es UN anyo y UN baseline: cualquier arreglo que se pruebe sobre estos mismos datos corre el riesgo
  de ajustarse a ellos (sobreajuste). Hace falta separar una parte para comprobar.

## 6. Decisiones para el propietario

**1. El time-stop.**
- a) **No, por ahora** (recomendado): no mejora el dinero y cambiaria la estrategia justo cuando
  empieza a contar la muestra de la fase 6 (decision 1 del protocolo: desde el despliegue).
- b) Si, 18 velas (3 dias), siempre: +39 % de candidatos. Habria que construirlo de verdad (simulador,
  bucle, juez que lo audite, configuracion) y no estaria para hoy.

**2. Que hacer con que el baseline pierda.** No bloquea nada de hoy: la fase 3 y la 6 son papel, y
comparar la IA con un baseline que pierde sigue siendo valido (incluso interesante: puede verse si la
IA evita los "cuchillos"). Pero **con esta estrategia, la fase 7 (dinero real) perderia dinero.**
- a) **Abrir una revision de la estrategia antes de la fase 7** (recomendado), medida con este anyo y
  con una parte reservada para comprobar. Ideas a medir: no comprar en caida (esperar a que la vela
  cierre por encima en vez de una orden limit que se llena cayendo), filtro de tendencia general
  (no ir largo con BTC en tendencia bajista), stops y objetivos por setup. Seria un trabajo propio,
  con sus decisiones.
- b) Esperar a la fase 6 y decidir con los datos de la IA.

## Metodo, reproducible

Los dos scripts del estudio (bajar la historia y el experimento) estan en
`docs/estudios/time-stop/`. La base con el anyo no se sube (son ~90.000 velas): se regenera con el
primero en un par de minutos.
