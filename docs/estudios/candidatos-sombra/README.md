# Candidatos en sombra: cuantos habria (28/09/2026)

Para la decision 5 del protocolo de la fase 6 (`docs/archivo/protocolo-fase-6.md`), que se toma el 02/10. En vivo, del
25/09 12:00 al 28/09 12:00 UTC: 19 velas, 17 con la cartera llena, 4 candidatos y 3 llamadas a la IA.

**Como:** `sombra.py` pasa el recorrido del bot SIN cambios (`scripts/replay_baseline.py`). En cada vela, las monedas
que caen SOLO por tener los huecos de la regla 4 ocupados se vuelven a cribar con el tope abierto; lo que sale de
mas es la sombra ("si hubiera hueco, que abririas?"). La segunda pasada es pura: el recorrido sale IDENTICO al de
referencia (exploracion: 497 operaciones y 622 candidatos, los de `revision-estrategia/referencia.json`; anyo USDC:
161 operaciones). Las demas reglas de la criba siguen: una moneda con posicion abierta no da sombra.

| | Anyo USDC (21/08/2025-28/09/2026) | Exploracion USDT (12/2020-06/2024) |
|---|---|---|
| Dias | 385 | 1.307 |
| Velas con la cartera llena | 25 % | 39 % |
| Candidatos de verdad, al dia | **0,51** | **0,48** |
| En sombra, al dia | +0,86 | +1,51 |
| Juntos, al dia | 1,38 (x2,7) | 1,99 (x4,2) |
| **DISTINTOS al dia** (mismo simbolo y setup en velas seguidas = uno) | 0,51 -> **0,81 (x1,6)** | 0,47 -> **1,02 (x2,2)** |
| Llamadas a la IA al dia | 0,41 -> 0,92 | 0,35 -> 1,35 |
| Sombra por setup | pullback 92 %, reversion 5 %, ruptura 3 % | pullback 92 %, ruptura 6 %, reversion 2 % |

Lo que dice:
1. **Los candidatos de verdad son ~0,5 al dia** en los dos juegos de datos. En la fase 6 (3-8 semanas) serian unos
   10-28. El protocolo decia: con 2-3 al dia no hace falta la sombra; con 1 o menos, plantearsela. Estamos en el
   segundo caso.
2. **La sombra multiplica el recuento por 2,7-4,2, pero la informacion nueva por 1,6-2,2:** dos de cada tres
   candidatos en sombra son el MISMO pullback que sigue valido en la vela siguiente. Para la M1 cuentan todos, pero
   no son independientes.
3. **Cuota:** de ~0,4 a ~0,9-1,4 llamadas al dia, muy lejos de las 40 de la regla 18.
4. **Es otra medicion** (protocolo, decision 5): la pregunta cambia y no se junta con la de verdad. Y un detalle
   para el disenyo: hoy el prompt le dice a la IA cuantos huecos quedan (`slots_free`); con 0 podria saltarlo todo.

## Comprobacion en vivo (07/10/2026): por que la sombra no ha dicho nada desde el 02/10

`check_fase6.py --sombra` decia "ninguna vela decidida en sombra" y la sombra no deja rastro cuando mira y no
encuentra nada: no se distinguia "no hay" de "no mira". `comprobar_vivo.py` (en el VPS, solo lectura) vuelve a pasar
el generador con las velas de cada momento para cada moneda que la cartera de la IA descarto SOLO por estar llena.
- **Validacion:** sobre las monedas que pasaron la criba de verdad, reproduce lo apuntado en vivo: 18 de 18 (3
  candidatos, 15 sin senyal).
- **La sombra:** 66 casos en 26 velas (de 28 con la cartera llena) y **0 candidatos**. El pullback, que es el 92 % de
  la sombra en la historia, no salio en ninguno por el regimen (sin tendencia alcista); ruptura: 43 por regimen y 23
  sin ruptura; reversion: 28 por regimen y 38 sin senyal. La sombra esta enchufada y callada con razon.
- **Pendiente tras el veredicto de la fase 6** (el propietario, 07/10): que la sombra apunte en el log cuantas monedas miro y
  cuantos candidatos salieron, tambien cuando son 0 (no toca el camino de decision, pero reinicia `ploutos-paper-ai`).

Ficheros: `sombra.py` (el script), `comprobar_vivo.py` (la comprobacion del 07/10), `anyo-usdc.json` y `exploracion.json` (los resultados). Base del anyo USDC:
`docs/estudios/time-stop/historia.db` (regenerable con `time-stop/bajar_historia.py`); la de la exploracion, con
`revision-estrategia/bajar_exploracion.py`.
