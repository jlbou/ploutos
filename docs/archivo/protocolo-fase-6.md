# Protocolo de la fase 6: como se decide si la IA aporta

Estado: **DECIDIDO por el propietario el 24/09/2026**: las cinco opciones recomendadas de la seccion 10
(1a, 2a, 3a, 4a, 5a). **El juez de la seccion 9 esta HECHO** (24/09, rama `fase-3-integracion`) y
al hacerlo se afino la definicion de M1 (seccion 3, ver "Por que suma y no media"): **confirmada
por el propietario el 25/09**.

Por que se escribe AHORA, semanas antes de la fase 6: **las reglas de una comparacion se fijan
antes de ver los datos**. Si se eligen despues, siempre se encuentra una metrica en la que gana
la IA (o en la que pierde, segun lo que uno quiera ver). Es el criterio de exito 3 del proyecto:
saber *con datos* si la IA aporta ventaja sobre el baseline.

Fuentes: PRD seccion 12 (fase 6: "IA vs baseline vs hold BTC, 2-3 semanas") y seccion 7;
informe 1.9 ("al cabo de 4-8 semanas compara expectativa, drawdown y numero de operaciones";
"si el baseline rinde igual o mejor, la conclusion honesta es que la IA no aporta ventaja")
e informe 2.3.7 (metricas).

---

## 1. Que pregunta responde, y cual no

**Responde:** entre los MISMOS candidatos, ya filtrados por el codigo y aprobados por el motor
de riesgo, ¿elige mejor la IA que la regla tonta del baseline (el de mejor R:R)?

**No responde:**
- si la estrategia gana dinero (eso lo mide la comparacion con comprar y esperar, seccion 5);
- si la IA gestionaria mejor las posiciones: `close`, `hold` y `tighten_stop` se apuntan pero no
  se ejecutan (decision D de la fase 3), asi que no hay nada que comparar;
- si la IA funcionaria en un mercado distinto del que toque en esas semanas (seccion 8).

## 2. El problema: con operaciones cerradas no llega

| Dato | Valor | Fuente |
|---|---|---|
| Operaciones en el recorrido historico | **11 en 32 dias (0,35/dia)** | `hallazgos-fase-2.md` |
| Candidatos en el papel en vivo | **5 en 3 dias**, y **0 desde el 23/09 12:00** | VPS, 24/09 20:38 UTC, `paper_decisions` |
| Por que 0 | la cartera esta llena (3 de 3, regla 4) y el filtro no genera candidatos sin hueco | `strategy/pipeline.py` |

En 2-3 semanas cada cartera cerraria **unas 5-10 operaciones**. Con eso no se puede distinguir
nada: una operacion sale +2 R o -1 R, y la diferencia entre dos grupos de 7 es puro azar. El
propio informe 1.8 dice que hacen falta cientos.

**Y hay otra trampa: las dos carteras dejan de ver lo mismo.** En cuanto una abre algo que la
otra no, los huecos libres cambian, y con ellos los candidatos que ve cada una. Comparar sus
operaciones es comparar dos historias distintas, no dos decisiones sobre lo mismo.

## 3. La solucion: medir cada candidato, no cada operacion

Cada vez que la IA decide, queda guardado (journal de la pieza 8, `ai_calls` + `ai_decisions`):
los candidatos exactos que vio (entrada, stop y objetivo, en el `prompt`) y que hizo con cada uno
(`open` con su `size_multiplier`, o `skip`).

A **cada** candidato, abierto o no, se le calcula que habria pasado **si se hubiera abierto**,
contra las velas reales y con las MISMAS suposiciones que el simulador y el juez
(`portfolio/audit.expected_outcome`): entrada a su precio y nunca en la vela que la crea;
caduca a las 2 velas sin llenarse (precisado el 29/09: tras 2 velas sin llenarse aun se puede llenar en la
tercera; caduca cuando la tercera tampoco baja al limite: `ENTRY_BARS_TO_LIVE = 2`, sin cambiar el codigo); el stop gana los empates y sufre los huecos; el objetivo no.
El resultado se expresa en **R neta**: lo ganado o perdido dividido por el riesgo planificado,
descontados los costes con el mismo modelo que `strategy/costs.py` (entrada maker, salida
taker, comisiones de `settings.yaml`).

Asi, lo que decidio la IA y lo que habria decidido el baseline se comparan **sobre la misma lista
de candidatos, en la misma vela**. El baseline es una funcion pura (`strategy/baseline.py`): se
le puede preguntar despues que habria elegido de esa lista, sin haberlo ejecutado.

### Las tres metricas principales

| | Que mide | Como |
|---|---|---|
| **M1. Seleccion** | ¿elige mejor que el baseline? | por vela: SUMA de multiplicador x R de lo que abrio la IA menos SUMA de R de lo que habria abierto el baseline con esa lista, cada uno hasta el cupo. Saltar todo vale 0; si eligen lo mismo con el mismo tamanyo, 0 |
| **M2. Veto** | ¿los que salta son peores que los que abre? | R media de los `skip` contra R media de los `open` |
| **M3. Tamanyo** | ¿reducir el tamanyo ayuda? | R ponderada por `size_multiplier` contra R sin ponderar, en los `open` |

**M1 es la que decide.** M2 y M3 explican por que.

**Por que suma y no media** (afinado al construir el juez, 24/09): con "R media de lo que abrio",
una vela en que la IA lo salta todo no tenia valor, y saltar es una decision: si los candidatos
eran malos, no abrir nada es acertar. Con la suma, saltar todo vale 0 R y abrir un perdedor, menos.
El multiplicador entra en M1 porque tambien es una decision de la IA; M3 lo separa.

**El cupo:** cada uno abre como mucho min(huecos libres, operaciones que quedan hoy), en su orden
(la IA, el del modelo; el baseline, de mejor a peor R:R). Es lo que hace el bucle, que prueba en
orden hasta que el motor veta por falta de hueco. Los dos datos van en la entrada guardada.

### Detalles fijados de antemano

- **Candidatos que no se resuelven:** se da un horizonte de **42 velas (7 dias)**. El que siga
  abierto se valora al cierre de la vela 42 y se cuenta aparte cuantos acabaron asi.
- **Solo se juzgan candidatos con el horizonte cumplido.** Los de la ultima semana entran en el
  siguiente recuento.
- **Limite honesto:** el contrafactual ignora que abrir uno ocupa un hueco y bloquea otros. Por eso
  las metricas de cartera de la seccion 5 se ensenyan igual, como segunda vista.

## 4. Que se excluye, y como se informa

| Caso | Que se hace | Por que |
|---|---|---|
| Tramo con la cartera de la IA parada | fuera de M1-M3 (quedan como velas atrasadas) | decision 3 de la pieza 9 |
| Tramo con la cartera del BASELINE parada | **no afecta a M1** (su eleccion se recalcula sobre la lista que vio la IA); solo a la vista de cartera | hallazgo al construir el juez |
| Velas `skipped_stale` (atrasadas tras una parada) | fuera | no se decidio con precios vivos |
| `skipped_quota`, `skipped_budget`, y llamadas que fallan por cuota agotada o login caducado | fuera de M1-M3; **contadas** en la cobertura | sin llamada util no hay decision que medir: es la infraestructura, no la IA |
| Salida invalida, timeout o error de la IA | **dentro, como `skip` de todo** | es comportamiento de la IA: en produccion haria lo mismo |
| Cambio en el camino de decision (prompt, contrato, modelo, estrategia, riesgo, comisiones) | la muestra se parte en tramos; solo se juntan tramos con el mismo codigo | se estaria midiendo otra IA |

El informe final dice siempre la **cobertura**: cuantas velas con candidatos hubo, cuantas decidio
la IA y cuantas se excluyeron y por que. Una IA que gana en el 40 % de las velas que decidio y no
decidio el 60 % no ha demostrado nada.

## 5. Metricas de cartera (solo descriptivas)

Las que pide el PRD (seccion 10, curvas comparadas) y el informe 2.3.7, para las dos carteras,
**comprar BTC y esperar** y **comprar las 8 y esperar**:

- equity y P&L neto; numero de operaciones; aciertos; expectativa en R; profit factor;
- caida maxima y tiempo en caida;
- MAE/MFE (cuanto fue en contra y a favor cada operacion).

**No deciden**, por el problema de la seccion 2. Sirven para ver que el contrafactual no cuenta
una historia muy distinta de lo que paso de verdad; si la cuenta, hay que entender por que antes
de concluir nada.

## 6. El ruido de la IA

En la prueba en seco (22/09), con la misma entrada 6 veces, la eleccion clara salia siempre y la
marginal cambiaba 1 de cada 3. **No se corrige ni se repite la llamada**: ese ruido es parte de la
IA que iria a produccion y tiene que pesar en el resultado. Se informa aparte cuantas decisiones
fueron marginales (confianza baja o dos candidatos con R:R parecido).

## 7. La regla de decision, fijada antes

- **Unidad del muestreo: el dia.** Las velas de un mismo dia se parecen (el mercado sube o baja
  para todas), asi que el intervalo se calcula remuestreando dias enteros (*bootstrap* por
  bloques), no velas sueltas. Si no, el intervalo sale mas estrecho de lo que es.
- **Intervalo del 90 %** para M1.
- **Muestra minima: 30 velas en que la IA y el baseline DISCREPAN.** Solo esas llevan
  informacion: cuando eligen lo mismo, la diferencia es 0 por construccion.

| Resultado | Condicion |
|---|---|
| **La IA aporta** | muestra minima cumplida y el intervalo de M1 entero por encima de 0 |
| **La IA perjudica** | el intervalo de M1 entero por debajo de 0 (con cualquier muestra) |
| **No concluyente** | todo lo demas |

**Cuanto se equivoca la regla, medido con el juez** (24/09): una IA que elige AL AZAR, en 200
mercados inventados de 40 dias, sale "no concluyente" 187 veces, "aporta" 6 y "perjudica" 7. Es
lo que significa un intervalo del 90 %: ~3 % de falsas alarmas a cada lado. Una IA que conoce el
futuro sale "aporta" siempre, y una que elige lo peor, "perjudica" siempre.

**Lo mas probable, dicho claro: "no concluyente".** Con 30 discrepancias y una dispersion de
~2 R por vela, el error tipico ronda 0,35 R: solo se veria una ventaja ENORME (del orden de
+0,7 R por decision). Una IA algo mejor que el baseline no se distingue del azar en semanas.
Por eso importa la decision 4 de la seccion 10.

**Sin mirar a mitad de camino.** El juez puede correr cada dia para ver que los datos estan bien
(cobertura, candidatos resueltos), pero **no ensenya M1 hasta la fecha fijada**. Mirar el
resultado cada dia y parar cuando sale bonito es la forma mas comun de engañarse con estadistica.

## 8. El mercado de esas semanas

El bot solo va largo (regla 1): gana cuando sube y su ventaja es caer menos cuando baja. Si las
semanas de la medicion son todas alcistas (como el recorrido historico, +31,4 % de media), el
resultado vale para un mercado alcista y nada mas. El informe separa M1 por **regimen** (el que
ya calcula `features/regime.py`) y dice cuantas velas hubo de cada uno.

## 9. El juez: `scripts/check_fase6.py` (HECHO el 24/09, rama `fase-3-integracion`)

Como los demas: lee las bases en `mode=ro`, no escribe nada, sale con 0/1.

1. **Datos completos:** cada vela de decision de la IA tiene su fila en `ai_calls`; cada candidato,
   su fila en `ai_decisions`; hay velas de 4 h para resolverlos.
2. **Mismos candidatos:** en las velas en que las dos carteras tenian los mismos huecos, la lista
   del baseline y la de la IA son identicas. Si no, algo alimenta distinto a las dos y la
   comparacion no vale.
3. **Resolucion:** cada candidato resuelto con `expected_outcome` y el horizonte de 42 velas.
4. **Cobertura** y exclusiones de la seccion 4.
5. **Veredicto** (solo a partir de la fecha fijada): M1 con su intervalo, M2, M3, por regimen, y
   las metricas de cartera de la seccion 5.

Se hizo YA, antes de desplegar, porque la muestra cuenta desde el despliegue: un juez escrito
despues habria descubierto tarde que faltaba un dato. Y faltaba uno: **el journal no guardaba con
que modelo ni con que version del prompt se decidia**, asi que no habria forma de partir la
muestra en tramos. Ahora cada fila lleva la huella del camino de decision (`ai_calls.camino`:
prompt, esquema, modelo pedido, version del CLI, estrategia, riesgo, comisiones) y el modelo que
respondio (`ai_calls.modelo`, si el CLI lo dice: se comprueba en el paso 8 del despliegue).

Logica en `portfolio/comparacion.py` (pura, sin `ai/`); lectura de las bases en el script. Probado
con IAs de mentira (seccion 7) y de punta a punta con bases llenadas por el mismo camino que el bot.
Mientras no toca el veredicto, solo dice si los datos estan bien y cuanta muestra hay (salida 2).

## 10. Decisiones del propietario (24/09/2026: las cinco recomendadas)

**1. Desde cuando cuenta la muestra.**
- a) **Desde el despliegue de la fase 3** (recomendado). La cartera de la IA corre desde entonces
  y, si el camino de decision no cambia, esas semanas miden exactamente lo mismo. Fases 3+4+5+6
  pueden ser 5-8 semanas en vez de 2-3: la unica forma realista de acercarse a la muestra minima.
- b) Solo desde el inicio de la fase 6. Mas limpio, pero casi seguro "no concluyente".

**2. Cuando se para.**
- a) **Minimo 3 semanas (PRD), y despues hasta tener 30 discrepancias, con un tope de 8 semanas
  en total (informe 1.9)** (recomendado). Fecha y reglas fijadas antes.
- b) 3 semanas fijas, pase lo que pase.

**3. Que metrica decide.**
- a) **M1, contrafactual por candidato** (recomendado): es la unica con muestra suficiente y
  compara decisiones sobre lo mismo.
- b) El equity final de las dos carteras. Mas intuitivo, pero con 5-10 operaciones es azar.

**4. Que se hace con cada resultado.** Es la mas importante y la de mas consecuencias.
- **La IA perjudica** → la fase 7 opera con el baseline. Recomendado sin dudas.
- **La IA aporta** → la fase 7 opera con la IA (lo previsto en la decision 1 de la fase 4).
- **No concluyente** (lo probable):
  - a) **Fase 7 con la IA y se sigue midiendo**, con el baseline en papel al lado (recomendado).
    El riesgo de una IA que no aporta esta acotado: no puede saltarse ninguna regla dura ni
    aumentar el tamanyo, solo elegir entre candidatos ya aprobados o reducirlo. Lo que se pierde
    en el peor caso es la diferencia entre dos elecciones buenas, con 50 $.
  - b) Fase 7 con el baseline: si no se ha demostrado que la IA aporte, no se usa. Coherente con
    el informe 1.9, pero la fase 7 dejaria de medir la IA con dinero real.
  - c) Alargar la fase 6 hasta que sea concluyente. Puede no acabar nunca.

**5. Candidatos "en sombra" cuando la cartera esta llena.** Hoy, con 3 posiciones abiertas no se
genera ningun candidato, y por eso la muestra crece tan despacio. Se podria seguir generandolos
y preguntar a la IA igualmente, solo para medir (sin abrir nada). Multiplicaria la muestra, pero:
es una funcionalidad nueva, fuera del PRD; gasta cuota (hasta 6 llamadas mas al dia, dentro de
las 40 de la regla 18); y la pregunta cambia ("si hubiera hueco, ¿que abririas?"), asi que
seria otra medicion que no se puede juntar con la de verdad.
- a) **Decidirlo tras la primera semana de la fase 3, con el recuento real** de cuantos candidatos
  ve la IA (recomendado). Si salen 2-3 al dia, no hace falta; si sale 1 o menos, habra que
  plantearselo.
- b) No hacerlo nunca.
- c) Hacerlo ya.

**Decidido el 02/10/2026 (el propietario): candidatos en sombra, opcion B** (en vivo, en el servicio de la IA;
`docs/archivo/propuesta-candidatos-sombra.md`), con el recuento de la primera semana: 0,7 candidatos al dia en el baseline y
0,6 en la IA. Como se hizo:
- **El juez, antes que los datos:** `check_fase6.py --sombra`, escrito el 02/10 sin que existiera ninguna llamada en
  sombra. Las MISMAS reglas que la M1 (resolucion, M1 por vela, intervalo por dias, 30 discrepancias, calendario
  desde su primera vela) y se juzga APARTE: nunca se junta con la de verdad. El baseline "elige" sobre la misma
  lista por codigo (`comparacion.seleccion_baseline`), con `cupo` = min(1 hueco, operaciones que quedan hoy).
- **En el journal:** `kind = 'sombra'`. Todos los jueces y el panel de la M1 de verdad filtran `kind = 'decision'`.
- **La pregunta:** con la cartera llena, las monedas que caen SOLO por no haber hueco se vuelven a cribar con el tope
  abierto; la IA ve la misma entrada que siempre con `slots_free: 1` y las posiciones de verdad.
- **Nunca abre nada:** el bucle no hace caso de lo que devuelva la sombra, y el juez de papel falla si alguna orden
  sale de un candidato en sombra.
- **No parte la muestra:** la huella del camino sigue en `f063d80147a9` (comprobado antes y despues).
- Lo que se sabe de antemano (`docs/estudios/potencia-fase-6/README.md`): juzgada aparte, tampoco llegara a 30
  discrepancias en 8 semanas. Su valor es el doble de datos para lo que se siga midiendo y ver antes una IA mala.
