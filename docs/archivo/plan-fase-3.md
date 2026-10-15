# Plan de la fase 3: el analista Claude en sombra

**Estado: decisiones de diseno TOMADAS (22/09/2026); la fase en si espera al
cierre de las fases 1 y 2 el viernes 25/09/2026.** No hay codigo de esta fase escrito.

| Decision | Eleccion del propietario |
|---|---|
| A. Modelo | Sonnet |
| B. Cuando se llama | Solo candidatos nuevos |
| C. Cartera | Propia para la IA (50 $ ficticios, igual que el baseline) |
| D. Decisiones con efecto | Solo `open` y `skip` |
| E. Facturacion | Suscripcion, a revisar antes de la fase 7 |
| F. Noticias | Fuera de la fase 3: pieza propia entre la 3 y la 6 (ver CLAUDE.md) |

Las seis coinciden con la recomendacion de la seccion 4.

## 1. Que pide la fase

| Fuente | Contenido | Criterio para avanzar |
|---|---|---|
| PRD seccion 12 | Analista Claude en sombra, presupuesto de llamadas, maquina de modos | 1 semana estable; consumo de cuota medido |
| Informe seccion 6 | Analista con esquema, presupuesto, deteccion de cuota, maquina de modos | 1 semana sin salidas invalidas no controladas; consumo medido |

"En sombra" = Claude decide, pero **en papel y en paralelo al baseline**: no hay dinero
ni ordenes reales hasta la fase 4 (demo) y la 7 (real). Lo que se mide aqui es que la
pieza funciona, que no se sale del contrato y cuanta cuota gasta.

La maquina de modos ya esta conectada al bucle (se adelanto en la fase 2, ver
`docs/archivo/cierre-fase-2.md`, seccion 5). Falta su modo propio: `CLOSE_ONLY_QUOTA`.

## 2. Lo que ya sabemos (medido el 22/09/2026, CLAUDE.md)

- `claude` v2.1.266. `--json-schema` va **en linea**, no como ruta. No existen
  `--max-turns` ni `--append-system-prompt-file`. Hay `--max-budget-usd`.
- Flags que hay que usar: `--restricted --disable-slash-commands --strict-mcp-config
  --setting-sources '' --no-session-persistence`, desde `claude_runtime/`, con
  `< /dev/null`. Sin `--restricted`, las herramientas vienen ENCENDIDAS.
- **Coste por llamada, entorno limpio: 0,0745 $ equivalentes** (cache fria, que es
  nuestro caso con velas de 4 h). 40 llamadas/dia = ~89 $/mes equivalentes de CUOTA.
- La salida parseada viene en `structured_output`.
- El esquema impide un `size_multiplier` fuera de rango, pero **NO impide un `cid`
  inventado**: eso lo tiene que hacer el parser.
- El token del `.env` vale (probado sin la sesion del portatil, con control negativo).
- **En el VPS no hay `claude`.** No hace falta Node.js: la instalacion verificada es la
  nativa (ver `docs/hallazgos-claude-cli.md`).

## 2b. Prueba en seco del analista (22/09/2026, autorizada por el propietario)

`scripts/dry_run_analyst.py`: la cadena entera con candidatos REALES de la historia
(bucle de papel -> candidatos -> prompt -> `claude -p` -> parser), entorno limpio, sin
la sesion del portatil, con el presupuesto REAL de la regla 18. **8 llamadas.**

| | |
|---|---|
| salidas validas | **6/6** con el contrato corregido (las 2 primeras, invalidas: ver abajo) |
| latencia | 12-20 s con 1 candidato, **~44 s con 4**; timeout 90 s |
| tokens de salida | 777 a 4.882 (sube con los candidatos) |
| coste equivalente | 0,097 $ la primera (cache fria); 0,02-0,09 $ las siguientes (cache caliente). **En produccion siempre fria: ~0,07-0,10 $** |
| misma eleccion que el baseline | 4/6 |
| aperturas con el tamanyo reducido | 3 (x0,7 y x0,8), con razones concretas |

**Lo que salio, por orden de importancia:**

1. **El contrato estaba mal disenyado.** Con `cid` y `position_id` opcionales, Claude
   rellenaba LOS DOS con el mismo valor en cada decision, y la respuesta entera se
   descartaba. Ahora hay un solo campo, `ref` (ver `ai/contract.py`). La decision D
   no cambia.
2. **Una de las dos discrepancias con el baseline era culpa del script**, no de la IA:
   la foto de la cartera se tomaba ANTES de procesar la vela, y el 25/08 16:00 Claude
   vio 0 huecos cuando en esa vela se habia cerrado una posicion. Corregido; esa vela
   no se ha vuelto a probar (presupuesto agotado). **Para la pieza 9: la IA tiene que
   ver el estado del momento de decidir, despues del paso 1 del bucle.**
3. **La misma entrada no da siempre la misma respuesta**: la vela del 25/08 08:00,
   enviada dos veces, eligio AVAX+DOGE y luego DOGE+XRP. Es ruido que la comparacion
   IA contra baseline de la fase 6 tendra que medir, no suponer.
4. **La latencia crece con los candidatos.** Con 6 podria acercarse al timeout de 90 s.
   Vigilarlo en la fase 3 antes de tocar el timeout.
5. Las razones citan datos de la entrada (ADX, R:R, spread, huecos, correlacion con lo
   que ya esta abierto). Con 8 llamadas no se puede decir nada de si decide MEJOR.

### Segunda tanda: el ruido de la IA (23/09/2026, 5 llamadas)

`dry_run_analyst.py --vela "25/08 16:00" --vela "25/08 08:00*4"`. 5/5 validas.

- **La vela que fallo por el script, repetida con la foto corregida:** con 1 hueco
  libre, la IA abre 1 (ETH, x0,85); el baseline abrio NEAR. Ahora es una discrepancia
  de verdad y razonada: NEAR con ADX 26,8 y el precio ya por debajo de la EMA20.
- **La misma entrada 6 veces** (25/08 08:00, 4 candidatos, 2 huecos; 2 llamadas del
  22/09 y 4 del 23/09):

  | eleccion | veces |
  |---|---|
  | DOGE + AVAX | 4 |
  | DOGE + XRP | 2 |

  **DOGE sale siempre; el segundo hueco cambia uno de cada tres.** Y con la misma
  eleccion, el tamanyo tambien baila: AVAX x1,0 unas veces y x0,8 otras, con
  confianzas entre 0,55 y 0,62. O sea: **lo claro es estable y lo marginal es ruido.**
- **Latencia con 4 candidatos: 29-52 s.** El maximo ya es el 58 % del timeout de 90 s.

**Consecuencias, para decidir en la fase 3 (no ahora):**

1. **La comparacion de la fase 6 necesitara mas operaciones de las que parece.** Si en
   las decisiones marginales la IA elige casi al azar, una diferencia pequenya contra el
   baseline puede ser ruido. Hay que medir la varianza, no suponer que es cero.
2. **El timeout.** Con 5-6 candidatos puede no bastar. Opciones: subirlo, o pasar como
   mucho los N mejores por R:R. Medirlo en la fase 3 antes de tocar nada.
3. No se propone preguntar varias veces y votar: triplicaria la cuota (regla 18).

## 3. Las piezas, en el orden en que se harian

Las marcadas **PURA** no tocan nada que este corriendo ni dependen de como acabe la
fase 2: se podrian escribir y probar en el portatil antes del viernes si el propietario lo
autoriza. Las demas, despues.

| # | Pieza | Donde | Tipo |
|---|---|---|---|
| 1 | Contrato de salida: esquema JSON y su modelo pydantic | `ai/schema.json`, `ai/contract.py` | PURA **hecha 22/09** |
| 2 | **Parser**: esquema, `cid` que existe (si no, se descarta la decision ENTERA y se apunta `llm_invalid_output`), `size_multiplier` en [0,5; 1,0], tipos permitidos | `ai/parser.py` | PURA **hecha 22/09** |
| 3 | Constructor del prompt: candidatos, cartera, limites, memoria. **Nunca claves ni entorno** (regla 19) | `ai/prompt.py` | PURA **hecha 22/09** |
| 4 | **Presupuesto de la regla 18**: 40/dia y 8 por ventana movil de 5 h, **guardado en la base** (la leccion de las reglas 10, 11 y 14: lo que vive en memoria se pierde al reiniciar) | `ai/budget.py` | PURA **hecha 22/09** |
| 5 | Clasificador de errores de cuota: `You've hit your session limit`, `weekly limit`, `Not logged in`, `Login expired`; lo desconocido = "sin IA" | `ai/quota.py` | PURA **hecha 22/09** |
| 6 | Invocacion: `subprocess` con los flags verificados, timeout de 90 s, entorno LIMPIO (solo PATH y el token), `claude_runtime/` | `ai/invoke.py` | integracion |
| 7 | `CLOSE_ONLY_QUOTA`: entra con cuota agotada o login caducado; sonda barata cada 30-60 min; sale sola cuando la sonda responde | `portfolio/loop.py` | integracion **hecha 23/09, rama `fase-3-integracion`** |
| 8 | Journal de cada llamada: prompt, salida cruda, decisiones, invalidas, tokens, coste equivalente, latencia | migracion `005` | integracion **hecha 23/09, rama `fase-3-integracion`** |
| 9 | La IA en el bucle, con su **propia cartera de papel** (ver decision C) | `portfolio/loop.py`, `scripts/run_paper.py` | integracion **hecha 24/09, rama `fase-3-integracion`**: ver `docs/archivo/diseno-pieza-9.md` |
| 10 | El juez audita tambien a la IA: nunca por encima del presupuesto, nunca un `cid` inventado aceptado, nunca un multiplicador fuera de rango, nunca abre lo que el motor veto | `portfolio/audit.py` | integracion **hecha 23/09, rama `fase-3-integracion`** |
| 11 | VPS: `claude` (nativo, sin Node.js, version fija y firma comprobada), el token en `/opt/ploutos/.env` (600), y `verify_claude_cli.py --sin-sesion` alli | `deploy/install-claude.sh` | despliegue: **script escrito 23/09, SIN ejecutar** |

`risk/` sigue sin importar nada de `ai/` (test de AST). La IA propone, el motor dispone.

**OJO para la pieza 10:** el juez de papel DEDUCE los modos (equity y operaciones),
pero `CLOSE_ONLY_QUOTA` no se puede deducir: depende de como respondio Claude. Cuando
la IA tenga su cartera, el juez tiene que leer esas transiciones de
`paper_mode_changes`, como ya hace con los resets manuales. Si no, marcaria como
"cancelada sin motivo" una entrada que se cancelo bien al entrar en QUOTA.
**Hecho (23/09):** `Audit._cuota_por_vela`. Un cambio con la marca de una vela se hizo
al procesarla (cuenta al TERMINARLA); uno entre velas (la sonda) cuenta desde la
primera vela procesada despues (`ts + timeframe`).

**Lo que audita la pieza 10** (`scripts/check_paper.py --decider ai`), sin importar `ai/`:
- `propone_y_dispone` (las dos carteras): ninguna orden de algo vetado; cada operacion
  es de esa cartera; **el baseline sin ni una llamada a Claude** (es el grupo de
  control); en la de la IA, cada orden es un `open` del analista en esa vela y con el
  multiplicador aplicado (riesgo <= riesgo por operacion x multiplicador).
- `analista_presupuesto`: la regla 18 contada aparte (40/dia UTC, 8 en 5 h moviles,
  las sondas y los fallos tambien cuentan); ninguna decision en QUOTA; "presupuesto
  agotado" siempre deja QUOTA puesto; "no llamo por cuota" solo estando en QUOTA.
- `analista_referencias`: cada decision sobre algo que se le ofrecio (leido del prompt
  GUARDADO), todos los candidatos con fila, salida invalida sin decisiones.
- `analista_multiplicador`: todo `open` con multiplicador en [0,5; 1,0].

**Condicion que deja para la pieza 9:** el juez audita UNA cartera por base, y la
tabla `paper_orders` no dice de quien es. La IA necesita **su propia base de papel**
(p. ej. `var/ploutos-paper-ai.db`), que ademas es lo natural con un escritor por base.
Si la pieza 9 las juntara en una, habria que cambiar esto.

**OJO para la pieza 9:** `portfolio/` tampoco puede importar `ai/` (regla de
arquitectura: "el gestor de posiciones trabaja sin IA"). La IA no entra en el bucle
con un import: se le PASA desde fuera, como el que decide, desde el script que
arranca el bucle. Es lo mismo que ya pasa con el baseline, y mantiene el bucle
identico para las dos carteras.

**Piezas 1-5 autorizadas por el propietario el 22/09/2026** antes del cierre de la fase 2,
porque no influyen en lo que se mide (ver CLAUDE.md, "Decisiones del propietario").

## 4. Decisiones que son del propietario

**A. Modelo.** Sonnet es lo medido (0,0745 $/llamada). Haiku gastaria menos cuota y
Opus mas. Recomiendo **Sonnet**: es lo que ya esta verificado, y el informe seccion
1.9 dice que la arquitectura pesa mas que el modelo.

**B. Cuando se llama** (PRD seccion 6: candidatos nuevos, revision periodica de cartera
y revision diaria de aprendizaje). Con velas de 4 h hay como mucho 6 momentos de
decision al dia. Recomiendo **solo candidatos nuevos** en esta fase: la revision de
cartera trae `close` y `tighten_stop` (ver D) y la de aprendizaje es de la fase 8.
Calculo: 1-6 llamadas/dia, muy por debajo de las 40 de la regla 18.

**C. La IA con su propia cartera de papel.** Para comparar IA contra baseline (fase 6)
cada uno tiene que llevar su cartera: mismos candidatos, mismo motor de riesgo,
decisiones distintas. Si compartieran cartera, las decisiones de uno cambiarian los
huecos del otro y la comparacion no mediria nada. La tabla `paper_trades` ya tiene la
columna `decider` para esto. Recomiendo **carteras separadas**.

**D. Que tipos de decision cuentan.** El contrato (informe seccion 1.5) tiene `open`,
`skip`, `close`, `hold` y `tighten_stop`. Recomiendo que en esta fase **solo cuenten
`open` y `skip`**, y que `close`, `hold` y `tighten_stop` se registren sin
ejecutarse: la gestion de posiciones sigue siendo determinista (stop y objetivo en el
exchange, regla 13) hasta que haya datos de que la IA la mejora.

**E. Suscripcion o API de pago.** El informe seccion 3.1 avisa de la zona gris de los
terminos (uso continuo 24/7 frente a "uso ordinario e individual") y de que la cuota
es la misma que usas tu. La API de pago lo separa pero cuesta dinero de verdad: con
facturacion por uso, a 0,0745 $/llamada y 1-6 llamadas/dia, serian **2-13 $/mes
frente a 50 $ de capital**. Recomiendo seguir con la **suscripcion** en esta fase
(es papel, pocas llamadas) y decidirlo con el consumo medido antes de la fase 7.

**F. Noticias.** El PRD las permite solo como filtro de riesgo, y son texto no
confiable (inyeccion de prompt). Recomiendo **dejarlas fuera de la fase 3**: sin ellas
no hay superficie de inyeccion, y anyadirlas despues es una pieza aislada.

## 5. Criterio de avance propuesto

Juntando PRD e informe, y con la leccion de esta fase (un criterio sin juez no es un
criterio):

1. **Una semana** con el analista en sombra y el servicio estable.
2. **Cero salidas invalidas no controladas**: toda salida invalida acaba en "no hacer
   nada" y apuntada, nunca en una excepcion ni en una orden. Con juez automatico.
3. **Consumo medido**: llamadas/dia, tokens, coste equivalente y latencia de cada
   llamada, y cuanto de la cuota semanal se comio (esto lo mira el propietario en
   *Settings > Usage*: no hay API para leerlo).
4. El juez de papel sigue en verde para las DOS carteras.

**Empieza a contar el 25/09/2026** (despliegue ~17:49 UTC; las dos carteras desde la vela de las
12:00 UTC). La semana se cumple el **02/10/2026**. Ese dia: `check_paper.py` de las dos carteras,
`check_fase6.py` (los datos), el consumo de la IA del journal (`ai_calls`) y la cuota semanal que
mira el propietario en *Settings > Usage*.

**Juez (26/09): `scripts/check_fase3.py`** mide los cuatro puntos de las bases (exit 0 cumplido, 1 FALLA,
2 aun no). Estable = las dos carteras cubren 7 dias, van al dia (15 min de margen tras el cierre) y ninguna
vela `skipped_stale`. Sin controlar = una vela con candidatos de la IA y sin fila en `ai_calls` (una
excepcion del analista no deja fila); las invalidas controladas (timeout, error, fuera de contrato) se
cuentan pero no son FALLA. Ensenya tambien los candidatos por dia y las velas con la cartera llena, para
la decision 5 de la fase 6. Corre cada noche con los jueces diarios (`--sin-papel`).

## 6. Riesgos conocidos

- **Cuota compartida.** Si el bot se come la cuota semanal, el propietario se queda sin Claude.
  El presupuesto de la regla 18 es la defensa; el consumo medido dira si basta.
- **Caducidad del token**: ~22/09/2027. Aviso 14 dias antes (PRD seccion 9, fase 5).
- **Terminos de uso**: ver decision E.
- **Nada de esto dice si la IA aporta.** Eso es la fase 6, con semanas de datos y un
  mercado que no sea solo alcista. En la fase 3 solo se comprueba que la pieza es fiable.
