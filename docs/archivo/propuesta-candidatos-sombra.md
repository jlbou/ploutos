# Propuesta: candidatos en sombra (decision 5 del protocolo de la fase 6), para el 02/10/2026

Preparada el 28/09/2026 a peticion del propietario. **Estado: DECIDIDA el 02/10: opcion B, con los cuatro detalles de la seccion 3 tal cual**. Antes: con el recuento de la primera
semana de `check_fase3.py`. Es una funcionalidad FUERA del PRD: por eso la decide el propietario y no se hace sin su OK.

## 1. El problema, con numeros

La fase 6 decide con la M1: por cada candidato, que habria pasado si se hubiera abierto, y si la IA elige mejor que el
baseline (`protocolo-fase-6.md`). Pero con la cartera llena (3 posiciones, regla 4) el filtro "hueco libre" corta y
no sale ningun candidato: la IA no ve nada.

| | En vivo (25-28/09) | Historia: anyo USDC | Historia: exploracion |
|---|---|---|---|
| Velas con la cartera llena | 17 de 20 (85 %) | 25 % | 39 % |
| Candidatos al dia | 1,2 (4 en 3,3 dias) | 0,51 | 0,48 |
| Con la sombra, al dia | - | 1,38 | 1,99 |
| **DISTINTOS al dia** (el mismo en velas seguidas cuenta uno) | - | 0,51 -> **0,81** | 0,47 -> **1,02** |

Fuente de la historia: `docs/estudios/candidatos-sombra/README.md` (el recorrido del bot sin cambios; sale identico).
El protocolo decia: con 2-3 candidatos al dia no hace falta; con 1 o menos, plantearsela. **Estamos en el segundo caso.**
Sin sombra, en la fase 6 (3-8 semanas) saldrian ~10-28 candidatos: casi seguro "no concluyente".

## 2. Que seria

En cada vela, si alguna moneda cae SOLO por no haber hueco, se vuelve a cribar como si hubiera hueco. Lo que sale son
los candidatos en sombra:
- **La IA** los ve en una llamada APARTE, despues de la de verdad, y dice `open` o `skip` como siempre.
- **El baseline** "elige" el de mejor R:R, como siempre (codigo, sin llamada).
- **No se abre NADA.** Ni en papel ni en el demo. Se apuntan y el juez calcula su resultado contrafactual con la misma
  funcion que la M1.
- **Es otra medicion** (lo dice el protocolo): se juzga APARTE ("M1 en sombra") y no se junta con la de verdad. Si
  las dos apuntan al mismo sitio, la conclusion es mucho mas solida; si no, se dice.

## 3. Los cuatro detalles que hay que resolver (y la propuesta)

1. **Que le decimos a la IA de los huecos.** Hoy el prompt le pasa `slots_free`; con 0 podria saltarlo todo por
   logica ("no hay sitio"), y entonces la sombra mediria eso y no su criterio. **Propuesta:** la misma entrada que una
   llamada normal, con `slots_free: 1` y las posiciones de verdad como contexto. La IA no sabe que es sombra: decide
   igual que si hubiera un hueco, que es exactamente la pregunta.
2. **El presupuesto de la regla 18** (40 al dia, 8 por 5 h) lo gastan tambien las llamadas en sombra. Una sombra NUNCA
   puede dejar sin llamada a una vela de verdad. **Propuesta:** la sombra solo llama si, despues, quedarian al menos
   4 llamadas en la ventana de 5 h y 20 en el dia; si no, se apunta "sombra sin presupuesto" y no cuenta. Con ~1
   llamada mas al dia, en la practica no pasara nunca.
3. **No partir la muestra de la fase 6.** La huella del camino (`ai.journal.camino`) cubre el prompt, el contrato,
   el modelo y la configuracion: la sombra no cambia ninguno (misma instruccion, mismo esquema), asi que las decisiones
   de verdad siguen en el tramo `f063d80147a9`. Se comprueba al desplegar con `check_fase6.py`.
4. **Que la sombra no abra nunca nada.** Un test de que el bucle no ejecuta ninguna decision marcada como sombra, y
   una comprobacion en el juez de papel: ninguna orden de papel con un candidato de sombra.

Coste: ~0,5-1 llamada mas al dia (0,09 $ equivalentes cada una: ~0,5 $/semana de cuota), memoria igual (las llamadas
van una detras de otra) y hasta ~90 s mas por vela.

## 4. Las opciones para el 02/10

- **A. No hacer sombra.** La fase 6 sigue con ~0,5 candidatos al dia; lo probable es llegar al tope de 8 semanas
  (20/11) y que salga "no concluyente" (la decision 4 del protocolo dice que entonces la fase 7 va con la IA y se sigue
  midiendo).
- **B. Sombra en vivo, en el servicio de la IA (recomendado si el recuento del 02/10 confirma <= 1 al dia).** Lo de la
  seccion 3. Trabajo: ~1 dia con tests y el juez; se despliega tras el cierre de la fase 3 y antes de la fase 4.
- **C. Sombra diferida.** Un proceso aparte, una vez al dia, reconstruye las velas con la cartera llena y le pregunta
  a la IA con los datos de entonces. No toca el servicio de la IA, pero reconstruir la entrada exacta de cada momento
  (posiciones, correlaciones, modo) es mas trabajo y mas facil de equivocar; y la IA decidiria horas despues.

## 5. Lo que se decide el 02/10

1. A, B o C, con el recuento de la semana delante.
2. Si B: los cuatro detalles de la seccion 3 tal como estan, o cambiar alguno.
3. Si B o C: el juez de la M1 en sombra se escribe ANTES de ver ningun dato de sombra (como el de la M1).
