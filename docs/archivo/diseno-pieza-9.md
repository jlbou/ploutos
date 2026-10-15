# Diseno de la pieza 9: la IA en el bucle

**HECHA el 24/09/2026 en la rama `fase-3-integracion`, SIN desplegar.** Lo que se
construyo, al final del documento (seccion 6).

Escrito el 23/09/2026, ANTES de empezar la pieza: la pieza espera al cierre del
viernes y al OK del propietario. Aqui esta como se haria y las **tres decisiones que son de
el propietario** (seccion 5). Lo demas es mecanica y se puede cambiar sin preguntar.

Lo que ya esta decidido y no se toca: Sonnet (A), llamar solo con candidatos nuevos
(B), cartera de papel propia de 50 $ ficticios (C), solo cuentan `open` y `skip`
(D), suscripcion (E), sin noticias (F), presupuesto agotado = `CLOSE_ONLY_QUOTA`.

## 1. Lo que hay hoy y lo que falta

- `PaperLoop.step()` llama al baseline **directamente**:
  `for choice in rank(pipeline.generation())`. Hay que hacer que el que decide se
  PASE desde fuera. `portfolio/` no puede importar `ai/` (regla de arquitectura).
- `Choice` ya tiene "la misma forma que tendra la de la IA, a proposito"
  (`strategy/baseline.py`): la IA devuelve una lista de `Choice` y el resto del
  bucle (motor de riesgo, simulador, journal) no cambia.
- El servicio `ploutos-paper` lleva `ProtectHome=true` y `ProtectSystem=strict`, y
  el CLI de Claude se instala en `/home/ploutos/.local/share/claude/versions/`
  (`deploy/install-claude.sh`). **Con ese endurecimiento el CLI no se podria ni
  leer.** El servicio de la IA necesita `ProtectHome=read-only` y escribir en su
  directorio de configuracion (bajo `/opt/ploutos/var`).

## 2. Como se haria (mecanica)

**El que decide, inyectado.** `PaperLoop` recibe un `decide(contexto) -> list[Choice]`.
El baseline es `rank`, como hoy. El de la IA lo construye el script que arranca el
bucle, con `ai/`:

1. el bucle hace el paso 1 (simulador, modos) y los filtros, y le pasa al que decide
   los candidatos y el estado **del momento de decidir** (la leccion de la prueba en
   seco: la foto tiene que ser DESPUES del paso 1);
2. sin candidatos nuevos, no se llama (decision B); en `CLOSE_ONLY_QUOTA` tampoco
   (fila `skipped_quota` en el journal);
3. `CallBudget.try_acquire`: si no hay presupuesto, fila `skipped_budget` y
   `CLOSE_ONLY_QUOTA` (decision del propietario del 23/09). **El `called_ms` del journal
   tiene que ser el MISMO instante que se pasa a `try_acquire`**: el juez vuelve a
   contar la regla 18 con `called_ms`, y si fueran dos lecturas del reloj distintas
   podria ver una ventana de 5 h algo distinta de la que vio el presupuesto
   (revision del 23/09);
4. `call_analyst` (timeout 90 s). Salida invalida, timeout o error = **ninguna
   entrada en esta vela**, sin reintento (no se gasta otra llamada en la misma vela);
5. cada `open` valido pasa a ser un `Choice`, **en el orden en que los dio el modelo**
   (la confianza se registra pero NO ordena: `ai/parser.py`; este documento decia "en
   el orden de confianza" y era un error), y el motor de riesgo lo aprueba o lo veta
   **igual que al baseline**;
6. el multiplicador se aplica a la cantidad que da el motor, redondeando HACIA ABAJO
   al lote. Si queda por debajo del minimo del par, no se abre (y se apunta).
   Aplicarlo despues del motor garantiza que solo reduce: el motor ya ha visto el
   tamanyo maximo;
7. la llamada y sus decisiones se guardan en la MISMA transaccion que la vela
   (`save_step(..., ai_calls=...)`, ya existe).

**El juez ya esta** (pieza 10): `check_paper.py --decider ai --paper-db <la de la IA>`.

**El test de la excepcion se cambia, no se borra:** hoy dice "ningun servicio usa
`ai/`". Pasa a decir "la ingesta y el bucle del BASELINE no importan `ai/`". El
grupo de control no puede depender del codigo de la IA ni para arrancar: un error de
import en `ai/` tumbaria el baseline, y con el la comparacion.

## 3. La memoria

Medido en el portatil (2 llamadas reales): el CLI llega a **~400 MB residentes y
hasta 500 MB de memoria privada**, 32-34 s por llamada. El VPS tiene 1.967 MB, sin
swap; con la medicion del spread terminada quedan ~1.280 MB libres. Un bucle de
papel mas (~170 MB) y una llamada (~500 MB) dejan **~600 MB de margen**. Cabe, pero
sin colchon, y cuando falta memoria sin swap el kernel mata un proceso: puede ser la
ingesta, que es la base de todo.

Tres protecciones, baratas y reversibles:
- **Un fichero de swap de 1 GB** (hay 53 GB libres en disco). No es para usarlo: es
  para que un pico no mate nada.
- **`OOMScoreAdjust=-900` en `ploutos-ingest`**: si el kernel tiene que matar algo,
  que no sea la ingesta.
- **`MemoryMax=900M` en el servicio de la IA**: si el CLI se dispara, systemd mata
  ESE servicio (y `Restart=always` lo levanta), no otro.

## 4. Las velas atrasadas

Si el servicio de la IA ha estado caido y se pone al dia con varias velas cerradas,
llamar a Claude por velas de hace horas gasta presupuesto en decisiones que ya no
sirven (los precios han cambiado). El baseline si las procesa todas (no le cuesta
nada).

## 5. Las decisiones del propietario

**DECIDIDAS el 23/09/2026: las tres recomendadas** (servicio aparte, las tres
protecciones de memoria, solo la ultima vela tras una parada). Ver CLAUDE.md.

**1. Un servicio aparte para la IA, o el mismo proceso para las dos carteras.**
- **Recomendado: servicio aparte** (`ploutos-paper-ai`, `scripts/run_paper_ai.py`,
  base `var/ploutos-paper-ai.db`). Una llamada de 50 s o un cuelgue no retrasan ni
  tumban el baseline; un escritor por base (la regla de SQLite); el juez ya audita
  una cartera por base; y el limite de memoria se le pone solo a el.
- Contra: ~170 MB mas de memoria (otro Python).
- El mismo proceso ahorra esa memoria, pero ata las dos carteras: si la IA falla,
  falla el grupo de control, y la comparacion de la fase 6 deja de ser limpia.

**2. Las tres protecciones de memoria de la seccion 3** (swap de 1 GB,
`OOMScoreAdjust` en la ingesta, `MemoryMax` en la IA).
- **Recomendado: las tres**, despues del viernes y ANTES de arrancar la IA. Tocan la
  configuracion del VPS (el swap) y los servicios (las otras dos).
- Alternativa: un VPS con mas memoria. Cuesta dinero cada mes y no hace falta si la
  medida en el VPS confirma los ~500 MB.

**3. Que hace la IA con las velas atrasadas tras una caida.**
- **Recomendado: solo llama por la ULTIMA vela cerrada.** Las anteriores se apuntan
  en el journal como no llamadas por atrasadas (un motivo nuevo, que el juez tiene que
  conocer), y no se entra.
- Consecuencia: tras una caida, la IA pierde entradas que el baseline si hace. En la
  fase 6, la comparacion tiene que excluir los tramos en que cualquiera de los dos
  estuvo caido (lo que habria que hacer igualmente).
- Alternativa: llamar por todas. Gasta presupuesto en decisiones sobre precios que ya
  no existen.

## 6. Lo que se construyo (24/09/2026)

| Pieza | Donde |
|---|---|
| El que decide, pasado desde fuera (`Decider`, `DecisionContext`) | `portfolio/loop.py` |
| El multiplicador, aplicado DESPUES del motor y hacia abajo al lote; fuera de [0,5; 1] o por debajo del minimo, no se abre | `portfolio/loop.py` |
| Un candidato que no es de esta vela, no entra (el bucle no se fia del parser) | `portfolio/loop.py` |
| El analista como decisor: velas atrasadas, modos, presupuesto, llamada, journal, sondas | `ai/decider.py` |
| El servicio: base propia, token obligatorio (salida 2), QUOTA guardado con la vela, sonda guardada al momento | `scripts/run_paper_ai.py` |
| Tres puntos de extension neutros en el runner del baseline (no importa `ai/`) | `scripts/run_paper.py` |
| `skipped_stale`: nuevo motivo de "no se llamo" (juez y journal) | `ai/journal.py`, `portfolio/audit.py` |
| Servicio systemd con `MemoryMax=900M`, `ProtectHome=read-only` y SIN `MemoryDenyWriteExecute` (el CLI tiene JIT) | `deploy/ploutos-paper-ai.service` |
| `OOMScoreAdjust=-900` en la ingesta; swap de 1 GB | `deploy/ploutos-ingest.service`, `deploy/swap.sh` |
| El test de arquitectura pasa a "la ingesta y el baseline no importan `ai/`" | `tests/unit/test_architecture.py` |

**Comprobado:**
- 893 tests; el recorrido del baseline sale identico (11 op., +7,829 $): el camino de
  la fase 2 no cambia.
- **De punta a punta sobre la historia real** (240 velas, `run_paper_ai` con un Claude
  simulado que abre con multiplicador, se salta candidatos, devuelve un `cid` inventado
  y choca una vez con la cuota): 20 ordenes, 18 cerradas, entrada y salida de QUOTA por
  sonda, y **el juez con las 21 comprobaciones en verde** (`--decider ai`).
- **Con Claude de verdad, una vela** (25/08 08:00, 4 candidatos, `entrada_de` sacada del
  contexto del bucle): salida valida en 37 s, 3 `open` (uno con multiplicador 0,7) y 1
  `skip`; el journal y las 3 ordenes, guardados.

**Queda para desplegarla** (despues del cierre del viernes y con el OK de la fase 3):
`deploy/swap.sh`, `deploy/install-claude.sh`, el token en `.env`, reinstalar los
servicios (`install.sh`), la base de papel del baseline de cero (comisiones) y arrancar
los DOS bucles a la vez para que las dos carteras empiecen en la misma vela.
