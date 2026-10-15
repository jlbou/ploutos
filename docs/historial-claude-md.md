# Historial: el CLAUDE.md completo hasta el 06/10/2026

Copia INTEGRA del CLAUDE.md antes de resumirlo (06/10/2026, a peticion del propietario, para gastar menos contexto). El vigente es `CLAUDE.md`; aqui esta el detalle de cada decision y cada hallazgo, tal como estaba. No se actualiza.

---

# Ploutos — memoria del proyecto

Bot de trading **spot** de cripto, 100 % autónomo, 50 $ de capital, decisiones asistidas
por Claude vía `claude -p`, dentro de reglas deterministas que la IA **no puede modificar**.

Éxito = (1) las reglas duras se cumplen siempre, (2) trazabilidad total de cada decisión,
(3) saber con datos si la IA aporta ventaja sobre un baseline sin IA. **La rentabilidad es secundaria.**

## Jerarquía de documentos

1. `docs/prd-ploutos-v2.md` — **fuente de verdad**.
2. `docs/informe-ploutos.md` — el *cómo* (arquitectura, contrato IA, APIs, UI). Solo manda donde el PRD calla.
3. Si ninguno lo cubre y afecta a riesgo, dinero o reglas duras → **preguntar al propietario**, no decidir.

Contradicciones ya resueltas a favor del PRD (no re-litigar):
- Quote: **solo `X/USDC`**. El informe §4.1 admitía `X/BTC`; el PRD no. El equity no lleva término en BTC.
- Slider: el informe §4.6 da 7–8 op./día en niveles 4–5; el tope duro del PRD son **6**. Se recorta a 6.
- Fase de papel: **2–3 semanas** (PRD §12), no 2–4.

## Las 19 reglas duras (PRD §4) — ni la IA ni el bucle de aprendizaje las tocan

1. Sin apalancamiento. Solo spot. Nunca margin, futuros ni préstamos.
2. Exchange: OKX EU, vía `ccxt`.
3. Solo `X/USDC` de una whitelist explícita de **8 monedas**. Validado en 4 puntos: arranque,
   generador de candidatos, motor de riesgo y justo antes de enviar la orden.
4. Máx. **3 posiciones simultáneas**; las órdenes de entrada pendientes **cuentan**. Máx. 1 por símbolo.
   Prohibido promediar a la baja y la martingala.
5. `initial_capital = 50`, `floor = 25`, en configuración. Solo se cambian a mano.
6. `equity` = USDC libre + Σ(cantidad × mejor bid) − comisiones estimadas de salida. Cada 15 s,
   con datos del **exchange**, no de la BD local.
7. Equity ≤ 25 $ en **dos lecturas consecutivas** → `CLOSE_ONLY_CAPITAL`, **enclavado**
   (solo reset manual) + Telegram.
8. Preventiva: se abre solo si, con **todas** las posiciones (incluida la nueva) cerradas en su stop,
   el equity queda ≥ 25 $ + 1 $ de colchón.
9. Escalones: < 45 $ → riesgo/op. a la mitad + Telegram; < 40 $ → máx. 2 posiciones; < 35 $ → máx. 1.
10. Pérdida del día ≥ 3 $ → `CLOSE_ONLY_DAILY` hasta las 00:00 UTC.
11. Máx. **6 operaciones al día** (tope duro; el slider nunca lo sube).
12. Riesgo por operación: 1 % del equity por defecto, modulado por el slider en **[0,5 %; 1,5 %]**.
13. Stop-loss y take-profit **siempre en el exchange** (OCO / orden algorítmica), creados al abrir.
14. Cooldown 2 h en un símbolo tras stop-loss; pausa 4 h tras 3 pérdidas seguidas.
15. Exposición máx. 90 % del equity. Máx. 2 posiciones con correlación entre sí > 0,8 (7 d).
16. No entrar con spread > **0,10 %** ni con objetivo esperado < **3×** el coste de ida y vuelta.
17. USDC desviado > 1,5 % de la paridad → sin entradas nuevas.
18. Presupuesto de Claude: máx. **40 llamadas/día** y **8 por ventana de 5 h** (configurable).
19. Claves API: solo lectura y trading, **nunca retirada**, IP whitelist del VPS, fuera del repo.
    La IA nunca ve claves ni variables de entorno.

**Modos** (PRD §5): `NORMAL`, `CLOSE_ONLY_QUOTA`, `CLOSE_ONLY_DEGRADED`, `CLOSE_ONLY_DAILY`,
`CLOSE_ONLY_CAPITAL`, `HALTED`. El modo efectivo es **el más restrictivo** de los activos.
`CLOSE_ONLY_CAPITAL` es enclavado. Al entrar en cualquier `CLOSE_ONLY_*`: cancelar entradas pendientes,
verificar/crear la OCO de cada posición, gestionar con reglas deterministas, notificar.

**Papel de la IA** (PRD §6): analista, no operador. Elige entre candidatos ya filtrados por código,
puntúa y justifica. No emite órdenes, no crea pares, no toca límites. Solo puede **reducir** el tamaño
(`size_multiplier` ∈ [0,5; 1,0]). Salida inválida o timeout = **no hacer nada**.
Las noticias son solo filtro de riesgo, nunca señal de compra, y son texto no confiable.

## Estructura (informe §6)

```
config/   settings.yaml (limites duros, whitelist, slider); .env NO en git
core/     modos, eventos, reloj, logging, secretos
data/     ingesta WS/REST, store (+ migraciones de papel), validacion, cobertura, usdc
features/ indicadores, regimen, correlaciones, paridad de USDC
strategy/ costes, filtros, setups, candidatos, pipeline, baseline sin IA
ai/       contrato, parser, prompt, presupuesto, cuota, invocacion, decisor   [fase 3; solo en ploutos-paper-ai]
risk/     motor de riesgo: 19 reglas, sizing, limites, equity
execution/ ordenes, OCO, idempotencia, reconciliacion                         [fase 4]
portfolio/ simulador de papel, bucle compartido, persistencia, juez de papel
notify/   avisos de Telegram, comandos, latidos a Healthchecks
api/ ui/  el panel (fase 5, en marcha)   learning/  vacio (fase 8)
scripts/  servicios, jueces, verificaciones, recorridos
deploy/   instalacion, servicios systemd, copias, sync
tests/    unit, property-based
claude_runtime/  directorio VACIO desde el que se ejecuta claude -p
```

## Invariantes de arquitectura (hay tests que las comprueban con AST)

- **`risk/` no importa NADA de `ai/`.** Un fallo de la IA no puede tumbar el motor de riesgo.
- `core`, `data`, `features`, `strategy` y `portfolio` tampoco importan `ai/`. **La IA entrara en el
  bucle pasada desde fuera** (como el baseline), no con un import.
- `features/` no importa `strategy/`, `risk/` ni `ai/`; `strategy/` no importa `execution/`.
- **El simulador (`portfolio/paper.py`) no importa `strategy`, `features` ni `ai`**: ejecuta
  veredictos ya aprobados. El bucle (`portfolio/loop.py`) si puede encadenar capas.
- **La ingesta y el bucle del BASELINE no importan `ai/`** (`test_la_ingesta_y_el_baseline_no_dependen_de_la_ia`):
  el grupo de control no puede depender de la IA ni para arrancar. La IA tiene su servicio
  (`scripts/run_paper_ai.py`) y se le pasa al bucle desde fuera (`test_la_cartera_de_la_ia_si_usa_ai`).
- El CLI de Claude se lanza con **`DISABLE_UPDATES=1`** y version fija (`ai.invoke.VERIFIED_VERSION`): la
  instalacion nativa se actualiza sola y eso invalidaria lo verificado.
- El estado verdadero es el del **exchange**, no la BD local (reconciliacion al arrancar y cada 5 min).
- Cada regla dura se comprueba en **al menos dos sitios**. Indicadores **solo sobre velas cerradas**.
- `deploy/*.sh`, `*.service` y `*.timer` **sin CRLF** (hay test: ya rompio el servidor dos veces).

## Convenciones de trabajo

- **Por fases** (PRD §12). Solo la fase acordada. Al terminarla: parar, ensenyar que hay, como se prueba
  y si se cumple el criterio de avance. No empezar la siguiente sin OK del propietario (excepcion en
  "Decisiones del propietario"). **Leccion:** la fase 1 se construyo sin cerrar la 0; comprobar que la
  anterior esta cerrada DE VERDAD, preguntando en vez de suponer.
- **Stack:** Python 3.12, `ccxt` (con WebSocket), `asyncio`, `pydantic`, `pandas`, SQLite en WAL,
  `pytest` + `hypothesis`. Fase 5: FastAPI + WebSocket + SPA. Dependencia nueva = justificarla antes.
- **Python del proyecto: `.venv/Scripts/python.exe`** (en el VPS, `.venv/bin/python`). Con `py -3.12`
  falla al importar `pydantic` y parece otro problema.
- **Configuracion:** limites duros en `config/settings.yaml`, validados con pydantic al arrancar.
  Configuracion invalida → **el bot no arranca**.
- **Secretos:** solo en `.env` (en `.gitignore`), con `.env.example` sin valores. Nunca en los logs.
  el propietario los pone el mismo: **nunca se le pide que pegue un token en el chat** y ningun script los
  imprime (Telegram lleva el token en la URL: todo error pasa por `core.secrets.scrub_url`).
  **Nunca `source .env`**: bash lo ejecuta como shell y un valor con espacios acaba en la terminal
  (paso el 22/09/2026 con el token de Claude). Leerlos con `core.secrets.Secrets`.
- **Revisor de codigo: `ruff` (0.16.9, solo en el portatil)**, solo errores probables (E9, F, B; sin
  formato), como un test mas (`tests/unit/test_ruff.py`; en el VPS se salta). Decision del propietario del 25/09.
- **Tests primero en `risk/`:** cada regla dura con test unitario + propiedades. Antes de dar por
  bueno un cambio en `risk/`: `scripts/mutation_check.py` (romper cada regla y ver su test en rojo).
- **Formato de commit (fijo, todos iguales).** Pedido por el propietario el 22/09/2026. Las secciones
  opcionales se omiten ENTERAS si no aplican; no se dejan vacias ni se rellenan con "ninguno".

  ```
  <ambito>: <que se ha hecho, en minuscula, max 72 caracteres>

  QUE CAMBIA
  - una linea por pieza tocada, en orden de importancia

  POR QUE
  Parrafo corto. Si corrige algo, primero el sintoma y luego la causa.

  HALLAZGOS                  (opcional: solo si se descubrio algo)
  1. ...

  MEDIDO                     (opcional: solo si hay numeros)
  ...los numeros, diciendo el tamanyo de la muestra...

  TESTS: N en verde | mutacion: 16/16

  Co-Authored-By: <el modelo que hace el commit> <noreply@anthropic.com>
  ```

  Ambitos en uso: `fase N`, `deploy`, `docs`, `fix`, `tests`.
  La linea TESTS lleva la mutacion solo cuando se ha tocado `risk/`.

- **Trazabilidad:** todo con timestamp UTC y un `decision_id` (= el `cid` que ve la IA) que encadena
  candidato → IA → veredicto → orden → fill → cierre.
- **Nada de dinero real ni de claves privadas hasta la fase 4**, y aun asi solo en el demo de OKX.
  Fases 1-3: solo datos publicos de mercado.
- **No anyadir funcionalidades** fuera del PRD. Si algo falta o esta mal planteado, decirselo al propietario
  con argumentos en vez de arreglarlo por cuenta propia.
- **Verificar, no suponer** todo lo que dependa del comportamiento real de una API.
- **El patron que mas ha costado:** codigo escrito, probado y SIN ENCHUFAR (filtros, correlaciones,
  regla 17, modos). Al terminar una pieza, comprobar que alguien la llama de verdad en el camino
  que corre, no solo en sus tests. Y un criterio sin juez automatico no es un criterio.

## Verificado (no re-suponer). Detalle en `docs/hallazgos-*.md`

**OKX**
- Los 8 de la whitelist tienen par `X/USDC` `live` (296 bases `/USDC`). En la UE la interfaz dice
  `X/USD` pero el formulario cotiza por defecto en USDC (`tradeQuoteCcyList`). Regla 3 sin cambios.
- **Cuentas EU: `hostname: eea.okx.com`** (en `settings.yaml`). `www.okx.com`, el de ccxt por
  defecto, da **50119** con cualquier clave. Los datos PUBLICOS son identicos en todos los hosts.
- **`50119` ("API key doesn't exist") tiene tres causas y no dice cual:** host equivocado, IP fuera
  de la lista blanca, clave mal copiada. **`50101`** = clave de un entorno pedida contra el otro.
- **403 al User-Agent por defecto de Python**: fijar uno (ccxt lo hace).
- **Minimo por orden = `minSz` x precio; OKX no publica minimo nocional.** BTC: ~8,6 $. Por eso el
  disenyo **no lleva salidas parciales** (el 50 % de 15 $ quedaria por debajo en BTC).
- **Comisiones: las de ccxt (maker 0,10 %, taker 0,15 %) NO son las de la cuenta**: son genericas y
  la tabla `instruments` las copia. Anuncio oficial de OKX EEA (leido el 23/09): cuenta solo spot,
  nivel Regular, **0,20 % / 0,35 % hasta el 25/09 08:00 UTC y 0,10 % / 0,20 % desde entonces**. El
  taker del modelo se queda corto 0,05 puntos. En 4 h casi no cambia nada (11 op., +7,80 $ en vez
  de +7,83 $). De donde salen: decision del propietario del 23/09 (ver "Decisiones del propietario").
- **El demo solo tiene 5 de los 8 contra USDC** (BTC, ETH, SOL, DOGE, NEAR). No usar los pares USDT
  del demo. `tests/risk_fixtures.INSTRUMENTS` = copia exacta de los 8 reales (comprobado).
- **La whitelist vive en DOS sitios:** `settings.yaml` y la clave de API de OKX (limitada por moneda
  base; quinto punto de la regla 3). Si cambia una, hay que cambiar la otra.
- **OCO con ccxt (23/09, sin claves, ver `docs/preparacion-fase-4.md`):** por defecto ccxt manda la OCO
  de spot con **`tdMode: cross` (margen, regla 1)**; con `tdMode: cash` explicito sale bien. El
  `clOrdId` de OKX es alfanumerico <= 32 (el `decision_id` lleva guiones) y solo es unico entre
  ordenes PENDIENTES (reenviar tras un llenado crea otra). Comision en la moneda recibida por
  defecto. TP/SL adjuntos a una entrada llenada A MEDIAS: sin documentar, probar en demo.
- **Las 9 pruebas del demo, HECHAS el 02/10** (`preparacion-fase-4.md` 11, JSON en `docs/archivo/pruebas-demo/`): OCO `cash`
  aceptada; la adjunta a la entrada nace al llenarse ENTERA, con nuestro `algoClOrdId`; a medias, solo al cancelar el
  resto (hueco de la regla 13 mientras tanto); `clOrdId` reutilizado = orden nueva; `feeType 1` = cantidad exacta;
  cancelar/recrear por `algoClOrdId` vale; `tradeQuoteCcy` aceptado en entrada y OCO. **El objetivo NO puede ser limit
  en spot (`51094`): sale a mercado, taker.** El simulador de papel y la M1 lo cobran como maker (~0,03 R optimista
  por objetivo); el filtro de la regla 16 ya era taker. **Comision por GRUPO de instrumento** (`groupId`): en el demo
  NEAR (grupo 13) paga 0,20 % / 0,35 %; en la real las 298 contra USDC son grupo 12. El deslizamiento del demo no
  sirve (llena siempre igual).
- Anuncios oficiales: API publica `/api/v5/support/announcements` (por `eea.okx.com`), con tipos
  `announcements-delistings` y `announcements-deposit-withdrawal-suspension-resumption`.
- Sin `USDC/USD`. La paridad se deduce (ver decision de la regla 17). **OKX RETIRO `BTC/USD` el 30/09/2026**
  (entre las 08:00 y las 12:00 UTC; en eea y www): contra USD solo queda `USDT/USD`. El libro de un par que no existe
  responde `50013` ("Systems are busy"), no `51001`: parece una caida y no lo es. **Causa: el "Unified USD
  Orderbook"** (`hallazgos-fase-3-4.md` 5d): `X-USD` se junto con `X-USDC`, que acepta USD, USDC, USDG y RLUSD 1:1
  (`tradeQuoteCcyList`); "X/USD" en pantalla = `instId` `X-USDC`. `tradeQuoteCcy` por defecto = la del `instId`
  (USDC). No salio en los anuncios de la API. Propuesta para la fase 4: `tradeQuoteCcy: USDC` explicito y prueba 9.
- `watch_ohlcv` devuelve SOLO la vela en curso: el cierre lo decide el secuenciador por la secuencia
  del exchange, nunca por el reloj (`data/ingest/sequencer.py`).

**`claude -p` (v2.1.266)** — detalle en `docs/hallazgos-claude-cli.md`
- `--json-schema` recibe el esquema **EN LINEA**, no una ruta. No existen `--max-turns` ni
  `--append-system-prompt-file` (usar `--append-system-prompt "$(cat ...)"`). Hay `--max-budget-usd`.
- **Las herramientas vienen ENCENDIDAS** por defecto. Flags: `--restricted --disable-slash-commands
  --strict-mcp-config --setting-sources '' --no-session-persistence`, desde `claude_runtime/`, con
  `< /dev/null`. `--bare` NO sirve con la suscripcion (solo lee `ANTHROPIC_API_KEY`).
- **Coste: 0,0745 $ equivalentes por llamada** (entorno limpio, cache fria, Sonnet), ~9 s. Es CUOTA,
  no dinero. Una sesion lanzada desde la app de escritorio hereda variables del host y mide el doble.
- La salida parseada viene en `structured_output`. **El esquema NO impide un `cid` inventado**: lo
  para `ai/parser.py`.
- **Prueba en seco (22/09, 8 llamadas, `scripts/dry_run_analyst.py`):** 6/6 validas tras corregir el
  contrato (un solo campo `ref`: con `cid`+`position_id` Claude rellenaba los dos). Latencia 12-44 s
  segun candidatos (hasta 52 s con 4, timeout 90 s). **La misma entrada 6 veces: la eleccion clara
  sale siempre, la marginal cambia 1 de cada 3** (y el tamanyo tambien). Detalle en `docs/archivo/plan-fase-3.md`.
- El token del `.env` vale: probado SIN la sesion del portatil y con un control sin token que fallo
  (`verify_claude_cli.py --sin-sesion`, repetible en el VPS).
- **Memoria de una llamada: 382-409 MB residentes, hasta 500 MB privada** (portatil, 2 llamadas). El
  VPS tiene 2 GB sin swap: de ahi las protecciones de memoria (decision de la pieza 9).
- **En el VPS (25/09, despliegue): 230 MB de pico** en una llamada real (9,6 s). El modelo que decide es
  `claude-sonnet-5` (el alias `sonnet` apunta ahi), y el CLI usa ademas `claude-haiku-4-5` para algo
  interno: el journal guarda los dos (`modelUsage`).
- **El instalador con `DISABLE_UPDATES=1` no instala NADA** y dice "Installation complete": esa variable,
  solo en la llamada del bot (arreglado el 25/09 en `deploy/install-claude.sh`, con test).

**Mercado y estrategia** — detalle en `docs/hallazgos-fase-2.md`
- **4 h gana a 1 h en todas las metricas** (en 1 h las comisiones se comen el 66 % del bruto).
  Multiplo de ATR en 4 h: 1,9x (stop ~3,3 %, posicion ~15 $). Timeframes cortos, descartados.
- El baseline **rinde menos que comprar y esperar** en un tramo alcista (+19,6 % contra +31,4 %).
- **En UN ANYO (21/08/2025-25/09/2026, con tramo bajista y alcista) el baseline PIERDE**: 159 operaciones,
  19 % de aciertos, **-0,38 R**, de 50 $ a 37,74 $ (-24,5 %; BTC -25 %, las 8 +2,6 %). Pierde en los dos
  tramos; los 32 dias de agosto-septiembre eran una ventana excepcional. 27 % de las operaciones mueren
  en 0-1 velas (la compra limit se llena porque cae). El time-stop no lo arregla. Detalle y decisiones en
  `docs/archivo/propuesta-time-stop.md` (25/09). Las reglas duras aguantaron: nunca cerca del suelo.
  **El bot no gana cuando el mercado cae** (regla 1, solo largos): su ventaja es caer menos.
- **Historia disponible (25/09):** contra USDC solo desde el 20/08/2025 (AVAX 09/10/2025, NEAR 25/02/2026);
  contra USDT, de 2017-2020 en adelante (5-8 anyos, 4 h y 1 h incluidas). Los cierres se parecen un 0,05-0,36 %
  de media: sirven para explorar la estrategia, no para la comprobacion final (`hallazgos-fase-3-4.md` 5b).
- La profundidad nunca ata con ordenes de 15 $; **el spread si**.
- **Spread en 24 h (22-23/09, un dia laborable):** BTC 0,004 %, ETH 0,011 %, TRX 0,026 %, XRP 0,034 %,
  SOL 0,037 % (pasa holgada), AVAX 0,045 %, **NEAR 0,0501 % y DOGE 0,054 %** (por encima del 0,05 %
  de la seleccion; DOGE en las cuatro franjas). En dinero es poco (0,0003 $ por operacion); lo que
  cambia es el tiempo que la regla 16 bloquea: 3,6 % DOGE, 2,7 % NEAR, 0 % BTC/ETH/SOL/TRX.
  **X/USD contra X/USDC: cerrado, no compensa** (mejor en 4, peor en 4, y "USD" sin aclarar).
  **Segunda ventana (23/09 06:40 -> 24/09 11:17): al reves, DOGE 0,046 % pasa y NEAR 0,0525 % falla.**
  Las dos estan en el borde y el veredicto depende de las horas medidas: decidir con semanas.

## Decisiones del propietario

- **22/09/2026 — Whitelist de 8 monedas confirmada:** `BTC, ETH, SOL, XRP, DOGE, AVAX, TRX, NEAR`
  (todas contra USDC). ADA y LINK quedan fuera por spread medio > 0,05 %. TRX y NEAR entran como
  sustitutos medidos. SOL entra aunque va justo (0,048 %): vigilar en la medición larga.
- **22/09/2026 — Criterio de avance de la fase 2 ampliado** (el del PRD, "tests de propiedades en
  verde", se queda corto): añadir (a) baseline sin IA generando operaciones de papel coherentes
  durante ≥ 72 h, y (b) prueba de mutación manual: romper a propósito cada regla dura una por una y
  verificar que su test se pone en rojo. Un test que sigue verde con la regla rota no protege nada.
- **22/09/2026 — Dimensionado y horizonte.** Se mantiene el riesgo de 1 % (0,50 $) por operación y
  las posiciones salen de **~15 $** (≈30 % del equity). Eso implica stops del orden del 3,3 % y, por
  tanto, setups en velas de **4 h** (1 h como secundario con múltiplo de ATR mayor), no en 5/15 min.
  Coherencia de los números del PRD: 3 × 15 $ = 45 $ = el 90 % de exposición máxima (regla 15), y
  6 op. × 0,50 $ = 3 $ = el límite diario (regla 10). Cinturón adicional: ningún nocional > 20 $.
  Todo son parámetros de `settings.yaml`, reversibles sin tocar código. El múltiplo de ATR por
  timeframe se fija en la fase 2 midiendo el ATR real, no a ojo.

- **22/09/2026 — La reversion a la media lleva stop propio (opcion 2).** Con el stop
  uniforme de 1,9xATR el setup no producia NI UN candidato en 285 velas reales en rango
  (R:R mediano 0,91, maximo 1,06). Ahora el stop va bajo el suelo del rango, que es donde
  la idea se invalida de verdad: una reversion se rompe cuando el precio SALE del rango,
  no cuando recorre una distancia fija en ATR.
  **Medido despues:** 3 candidatos con R:R mediano 2,45 y stop del 1,61 % (frente al
  3,7-4,1 % de los otros setups). **Contrapartida honesta:** un stop tan estrecho lleva la
  posicion al tope de 20 $, asi que ante un hueco a la baja del 5 % se pierde ~1,00 $ en
  vez de los ~0,67 $ de un setup con stop ancho. El riesgo *planificado* sigue siendo
  0,50 $; el riesgo de HUECO no. Vigilarlo en la fase 6.
  Sigue siendo el setup marginal: 3 candidatos de 214 (1,4 %).

- **22/09/2026 — Una correlacion sin medir cuenta como correlacionada (opcion 2).**
  `RiskState.correlated_with` (regla 15) cuenta como correlacionada toda pareja sin
  correlacion medida (menos de 84 velas de 1 h en 7 dias). Sin historia, como mucho
  2 posiciones a la vez: no para el bot, pero no apila apuestas cuya relacion nadie
  ha comprobado. Descartadas: dejarlo como independiente (lo que habia) y no abrir
  nada sin correlaciones (demasiado estricto). El juez de papel audita igual.
  **En vivo no cambia nada** (167 velas de 1 h en 7 dias en el VPS).
  En el recorrido historico al principio SI cambiaba (+6,70 $ en vez de +7,83 $),
  pero era un efecto de los datos: la base local tenia 1 h solo desde el 09/09 y
  187 de 240 velas no tenian correlaciones. **Con la historia de 1 h completada
  (desde el 24/07, 1.451 velas seguidas por moneda) el recorrido de 4 h sale
  IDENTICO al original**: 11 operaciones, +7,829 $, +19,6 %. Solo cambia el filtro
  de correlacion (71 -> 218 descartes), que ahora mide de verdad y descarta
  candidatos que tampoco habrian entrado por falta de huecos.

- **22/09/2026 — De donde sale la paridad de USDC (regla 17): "A con control C".**
  OKX no tiene `USDC/USD`. Principal A = `USDC/USDT x USDT/USD` (si el que se despega
  es USDT, los dos factores se compensan); control C = `BTC/USD / BTC/USDC`
  (independiente de USDT). Si discrepan mas del 0,5 %, o falta un precio, la paridad
  es DESCONOCIDA y **no se entra**. Descartadas: solo A (ciega si el "USD" de OKX
  estuviera atado a USDC) y solo `USDC/USDT` (mide contra USDT, no contra el dolar).
  Medido: A 0,99986, C 0,99985-1,00005; coinciden dentro del 0,02 % con un umbral
  del 1,5 %. `USDC/EUR` solo no sirve: el euro se mueve medio punto al dia contra
  el dolar y se confundiria con un despegue.
  **SUSTITUIDA el 01/10/2026: solo A** (ver la decision de esa fecha).

- **22/09/2026 — Las seis decisiones de diseno de la fase 3** (ver `docs/archivo/plan-fase-3.md`).
  Tomadas ANTES de empezar la fase; la fase en si sigue sin OK hasta cerrar la 2.
  - A. Modelo: **Sonnet** (el verificado: 0,0745 $ equivalentes por llamada).
  - B. Se llama a Claude **solo con candidatos nuevos** (1-6 llamadas/dia con 4 h).
  - C. **Cartera de papel propia para la IA**, separada de la del baseline. Las dos
    son de 50 $ FICTICIOS: papel, sin dinero ni ordenes reales (el propietario lo confirmo).
  - D. Solo cuentan **`open` y `skip`**. `close`, `hold` y `tighten_stop` se
    registran pero no se ejecutan: la gestion de posiciones sigue determinista.
  - E. **Suscripcion** por ahora; se revisa con el consumo medido antes de la fase 7.
  - F. **Sin noticias** en la fase 3: sin texto no confiable, sin superficie de inyeccion.

- **22/09/2026 — Noticias: pieza propia entre la fase 3 y la 6, en un servicio aparte.**
  "Fuera de la fase 3" NO es "fuera del bot": el PRD las pide (seccion 6: filtro de
  riesgo, nunca senyal de compra; seccion 5: salida ante hackeo o deslistado), pero su
  tabla de fases no les asigna ninguna. El propietario decidio:
  - **Cuando:** despues de la fase 3 y ANTES de la 6. En la 3 meterian texto no
    confiable justo cuando se esta probando si el analista es fiable; a mitad de la 6
    partirian en dos la comparacion IA contra baseline.
  - **Donde (opcion B):** servicio propio `ploutos-news` con base de datos propia.
    Descartadas: dentro de la ingesta (una fuente externa que falla arrastraria al
    servicio critico) y dentro del bucle (miraria cada 4 h, tarde para salir de un
    hackeo). Codigo: `data/news/` (fuentes), `features/news.py` (clasificacion pura,
    flags por moneda con caducidad) y un filtro en `strategy/filters.py`, que va antes
    del baseline y de la IA: **los dos reciben las mismas flags**.
  - **Primero lo determinista:** anuncios de OKX + reglas por palabras clave. Claude
    clasificando titulares, solo si los datos dicen que aporta.
  - **Si la fuente cae:** se avisa pero NO se bloquea (es un filtro, no una regla dura
    como la 17). Excepcion: una flag de deslistado o hackeo ya vista se mantiene hasta
    que caduque.
  - **Verificado el 22/09/2026:** OKX publica sus anuncios en una API publica
    (`/api/v5/support/announcements`, funciona por `eea.okx.com`), ya clasificados por
    tipo, entre ellos `announcements-delistings` y
    `announcements-deposit-withdrawal-suspension-resumption`.
  - De paso salio el anuncio "Upcoming Spot Fee Adjustment EEA": revisado el 23/09 (ver
    las comisiones en "Verificado").

- **22/09/2026 — EXCEPCION a "no empezar una fase sin cerrar la anterior".** Se
  escriben YA las cinco piezas PURAS de la fase 3 (esquema, parser, prompt,
  presupuesto de la regla 18, clasificador de errores de cuota), **porque no influyen
  en lo que se esta midiendo**: solo en el portatil, sin desplegar, sin que las
  importe ningun servicio. La integracion (piezas 6-11 del plan) y el VPS esperan al
  cierre del viernes 25/09. La condicion no depende de acordarse: la comprueba
  `test_los_servicios_en_marcha_no_usan_ai_todavia` en `tests/unit/test_architecture.py`.

- **23/09/2026 — La excepcion se amplia a las piezas 7 y 8 de la fase 3** (`CLOSE_ONLY_QUOTA` y el
  journal de las llamadas a Claude), a peticion del propietario. Tocan el bucle y la base de papel, asi que
  van en la rama **`fase-3-integracion`**, no en `main`: `main` sigue siendo exactamente lo
  desplegable, y si el viernes hay que arreglar la fase 2, no se cuela nada de la 3. Nada de esto
  se despliega hasta el cierre del viernes.
  **Ampliada el 23-24/09**, siempre a peticion del propietario y en la misma rama: pieza 10 (el juez audita a
  la IA), pieza 11 (instalador del CLI), pieza 9 (la IA en el bucle), las comisiones y los avisos de
  Telegram.

- **24/09/2026 — La excepcion llega a DOS piezas PURAS de la fase 4**, a peticion del propietario:
  `execution/ids.py` (`decision_id` -> `clOrdId`/`algoClOrdId` y vuelta) y `execution/guardia.py`
  (la comprobacion justo antes de enviar: spot puro, whitelist, lado, tipo, ids propios). Sin claves,
  sin red, sin enchufar a nada: rama `fase-4-piezas-puras`. El resto de la fase 4 espera a la 3.

- **26/09/2026 — La excepcion llega a la parte de LECTURA del panel (fase 5) y a `execution/peticiones.py`
  (fase 4)**, a peticion del propietario: en el portatil, sin desplegar, sin enchufar. El panel en `main` (`api/`, que
  nadie arranca en el VPS; FastAPI solo en el portatil); lo de la fase 4, en su rama. El mismo dia, tambien
  el nucleo PURO del juez de la fase 4 (`execution/juez.py`, pieza 8), a peticion del propietario.

- **25/09/2026 — La excepcion llega al clasificador de noticias** (pieza 1 de `docs/diseno-noticias.md`),
  a peticion del propietario: pura (titulo -> avisos), sin red ni base, sin enchufar. Rama `noticias`. El resto
  de la pieza (servicio, filtro, salida a mercado) espera: va entre la fase 3 y la 6.

- **23/09/2026 — Presupuesto propio agotado = `CLOSE_ONLY_QUOTA`.** Cuando se agota el presupuesto
  de la regla 18 (40/dia, 8 por 5 h), el bot entra en `CLOSE_ONLY_QUOTA` igual que con la cuota de
  Claude agotada o el login caducado, y sale cuando una sonda responde. El PRD seccion 5 no lo
  lista entre las causas: lo decidio el propietario (sin presupuesto la IA no puede decidir; se trata igual
  que si no hubiera IA). Descartado: no cambiar de modo y solo dejar de llamar.

- **23/09/2026 — Las comisiones salen de `settings.yaml`, no de ccxt.** Las de ccxt son genericas,
  no las de la cuenta (ver `hallazgos-fase-0-1`). Se fijan en configuracion, validadas al arrancar,
  con las de una cuenta solo spot, nivel Regular, desde el 25/09: **maker 0,10 %, taker 0,20 %**.
  Las de la tabla `instruments` dejan de usarse para costes. **Hecho en la rama `fase-3-integracion`**
  (`exchange.fees` y `FeesConfig.apply()`, el unico paso hacia motor, costes y juez); llega a `main` con
  el despliegue. **OJO:** el juez recalcula las comisiones de lo guardado, y con la base de papel de las
  72 h (hecha con taker 0,15 %) daria FALLA en el equity: el viernes se juzga con el codigo DESPLEGADO
  y despues la base de papel empieza de cero (la de las 72 h se archiva). **En la fase 4**, con clave: se comparan con
  las reales de la cuenta (`GET /api/v5/account/trade-fee?instType=SPOT`) y si las reales son MAS
  CARAS que las configuradas, no se opera. Dos detalles de esa API, leidos en su documentacion:
  el signo va al reves (negativo = comision que pagas, positivo = rebaja) y para los pares contra
  USDC hay que leer `takerUSDC`/`makerUSDC` (o `feeGroup` con el `groupId` del instrumento), no
  `taker`/`maker`, que son los de los pares contra USDT.

- **23/09/2026 — Las tres decisiones de la pieza 9** (detalle en `docs/archivo/diseno-pieza-9.md`, rama
  `fase-3-integracion`). La pieza se hizo el 24/09 en esa rama; se despliega tras el cierre y el OK.
  1. **La IA en un servicio APARTE** (`ploutos-paper-ai`, base propia). Si la IA falla o se cuelga,
     el grupo de control sigue; con un solo proceso, un fallo de la IA pararia tambien el baseline y
     la comparacion de la fase 6 dejaria de ser limpia. Coste: ~170 MB mas.
  2. **Las tres protecciones de memoria del VPS**, despues del viernes y ANTES de arrancar la IA:
     swap de 1 GB, `OOMScoreAdjust` para que la ingesta sea la ultima en caer, y `MemoryMax` en el
     servicio de la IA. Motivo: 2 GB sin swap, y una llamada a Claude ocupa 400-500 MB (medido).
     Descartado: un VPS mas grande (cuesta cada mes y con lo medido no hace falta).
  3. **Tras una parada, la IA solo decide sobre la ULTIMA vela cerrada.** Las anteriores se
     apuntan como no decididas por atrasadas: sus precios ya no existen y el presupuesto (40/dia)
     no se gasta en ellas. Consecuencia: la fase 6 compara excluyendo los tramos en que cualquiera
     de las dos carteras estuvo parada.

- **23/09/2026 — DOGE y NEAR se quedan en la whitelist por ahora; se decide ANTES de la fase 7.**
  En la medicion de 24 h, DOGE (0,054 %) y NEAR (0,0501 %) pasan del 0,05 % con que se eligio la
  whitelist. No se cambia nada ahora: hasta la fase 7 todo es papel o demo, y el bucle de papel ya
  guarda el spread de cada moneda en cada vela (`paper_market`), asi que 2-3 semanas de fase 3 daran
  datos de laborables y fines de semana mucho mas solidos que un dia. Contrapartida asumida: si se
  mantiene DOGE porque "en dinero no importa", el mismo argumento habria dejado entrar ADA y LINK;
  es reconocer que la linea del 0,05 % es orientativa. Si al final cambia la whitelist, cambiar
  tambien la clave de OKX (quinto punto de la regla 3).

- **23/09/2026 — Los mensajes de Telegram, en castellano** (como el codigo y los logs), con formato
  HTML, iconos y cifras alineadas (el propietario, al verlos en el movil). Los pide el PRD seccion 9 y las reglas
  7 y 9 ("+ Telegram"). En `main` el bucle solo los escribe en el log; en la rama, enchufados (ver "Ramas").

- **24/09/2026 — Las cinco decisiones de la fase 4** (`docs/archivo/diseno-fase-4.md`). Tomadas antes de
  empezarla; **REPASADAS con el propietario el 26/09: se mantienen**, con la 1 precisada (el demo es un ESPEJO de la
  cartera de la IA en papel: mismas ordenes, sin llamadas nuevas; la de papel sigue midiendo la fase 6) y una
  sexta: **DEGRADED con 3 errores seguidos, 2 s de reloj (el de la ingesta) y 10 min sano para salir**.
  1. **El demo ejecuta la cartera de la IA** (la que ira a dinero real en la fase 7): se prueba la
     cadena entera antes de que cueste nada. Solo los 5 pares del demo; XRP, AVAX y TRX, en papel.
  2. **Comision siempre en USDC (`feeType = 1`)**, en el demo y despues en la real: cantidades
     exactas, la OCO vende lo que hay y la contabilidad cuadra con el papel. Ajuste de la cuenta:
     lo hace el propietario (o yo con su permiso expreso).
  3. **Entradas post-only**: coinciden con el modelo de costes (maker). Se mide en el demo cuantas
     rechaza OKX por haber cruzado ya el precio.
  4. **`HALTED` NO cierra las posiciones**: las OCO siguen en el exchange. "Cerrar todo" es otro
     boton, con doble confirmacion.
  5. **Descuadre** = una diferencia entre exchange y local que la conciliacion no explica en la
     misma pasada, o una posicion sin OCO durante mas de una pasada (5 min). Los segundos de
     retraso normales no cuentan. Lo mide `check_exec.py` (pieza 8).

- **24/09/2026 — El vigilante externo, YA para la fase 3, con Healthchecks.io y avisos por
  Telegram** (`docs/propuesta-vigilante.md`). Motivo: si el VPS cae entero o un servicio se cuelga
  sin morir, nadie avisa (un bot caido no avisa de que se ha caido), y en la fase 3 el bot va solo
  una semana. Plan gratuito: 20 comprobaciones, se usan 4 (ingesta, papel baseline, papel IA, copia
  de la noche), cada una con un latido cada 5 min (limite: 5 por minuto). El propietario crea la cuenta y las
  comprobaciones y pone las URL en `.env` (`HEALTHCHECK_*`). **Latido hecho el 24/09 en la rama
  `fase-3-integracion`**: `notify/latido.py` (nunca lanza, timeout 5 s, uno cada 2 min como mucho);
  cada parte late SOLO cuando va bien de verdad (papel: vuelta sin error; ingesta: velas de 1 m de
  las 8 frescas; copia: bien, o `/fail` para avisar ya). Ningun test late de verdad (conftest).
  **Las 4 URL ya estan en el `.env` del VPS (24/09, verificado por recuento y huella, sin verlas)**;
  en el del portatil NO (si el bot corriera ahi, lateria en nombre del VPS y taparia una caida).
  Hasta el despliegue nadie las lee: el codigo de `main` las ignora.
  Descartados: una tarea del portatil (de noche no vigila), un servidor propio (coste) y esperar a
  la fase 5.

- **25/09/2026 — Actualizaciones del VPS y noticias** (el propietario, con los botones):
  - **Reinicio automatico solo cuando un parche lo pide, a las 07:15 UTC** (`docs/propuesta-actualizaciones.md`,
    opcion 2). Hecho en la rama (`deploy/52ploutos-reboot.conf`); llega con el despliegue.
  - **M1 como SUMA por vela** (saltar todo vale 0), confirmado.
  - Noticias (`docs/diseno-noticias.md`): **solo anuncios de OKX** al principio (medios despues y en
    sombra); flag critica con posicion = **vender a mercado**; duraciones 72 h / 7 d / 24 h. Deslistado:
    **vende primero (si hay posicion), avisa por Telegram y el propietario decide despues** (quitar la moneda o
    levantar la flag); no caduca solo. Confirmado por el propietario.

- **25/09/2026 — Sin time-stop por ahora, y la estrategia se revisa ANTES de la fase 7** (`docs/archivo/propuesta-time-stop.md`).
  El time-stop no mejora el dinero en un anyo y cambiaria la estrategia justo cuando empieza a contar la
  muestra de la fase 6. El baseline pierde en ese anyo (-0,38 R en 159 operaciones): con esta estrategia
  la fase 7 perderia dinero. La revision sera un trabajo propio, medido con el anyo de datos y una parte
  reservada para comprobar (sin sobreajustar), con sus propias decisiones. No toca la fase 3 ni la 6.

- **25/09/2026 — El panel (fase 5) se usara por Tailscale** (PRD 10: "solo via Tailscale o Cloudflare
  Tunnel"). El panel escucha SOLO en la red de Tailscale; el cortafuegos del VPS sigue dejando entrar
  solo SSH y desde Internet el panel no existe. Descartado Cloudflare Tunnel + Access: hace falta un
  dominio propio y deja el panel detras de un login en Internet. En la fase 5, el propietario crea la cuenta de
  Tailscale y pone la app en el movil y el portatil; unir el VPS a su red es un paso del despliegue.

- **25/09/2026 — Imagen:** en todo lo que ve el propietario (panel, Telegram, web) **no se nombra a Claude**: se
  dice "la IA" o "el analista" (unica excepcion: la orden literal `claude setup-token`). Hay un test
  que lo comprueba en los avisos. **Logo:** la Π con dos velas colgando (concepto B), azul petroleo;
  ficheros y usos en `assets/logo/README.md`.

- **25/09/2026 — Como se revisa la estrategia antes de la fase 7** (`docs/archivo/propuesta-revision-estrategia.md`):
  explorar con USDT 12/2020-06/2024; **reservar USDT 07/2024-08/2025 sin mirar** (una sola vez, al final);
  el anyo USDC (ya visto) como segunda comprobacion. **Lista cerrada de 5 ideas** (no comprar cayendo,
  tendencia de BTC, solo ruptura, stop por setup, velas de 1 dia), combinaciones de dos solo si mejoran
  solas. Una estrategia nueva se aplica **despues del veredicto de la fase 6**. **Sin una estrategia que no
  pierda en la reserva, no hay fase 7 con dinero real.**

- **25/09/2026 — El bucle de aprendizaje (fase 8)** (`docs/archivo/diseno-aprendizaje.md`, el propietario con los botones):
  la unidad es el CANDIDATO con su resultado contrafactual; **dos etapas**: criba con la historia (con una
  parte reservada que se mira una sola vez por hipotesis) y confirmacion en sombra en vivo. Lo aprendido
  se aplica **solo a la cartera de la IA; el baseline queda congelado** como control. El codigo valida y
  **el propietario aprueba cada aplicacion**. Como mucho **3 hipotesis en prueba y 5 reglas en la memoria** del prompt.
  Motivo: 1,97 R de desviacion por operacion (medido): solo en vivo, de 2 a 5 anyos por hipotesis. La
  herramienta de la criba es la misma que hace falta para revisar la estrategia antes de la fase 7.

- **25/09/2026 — La API del panel (fase 5)** (`docs/diseno-api-panel.md`, el propietario con los botones): servicio
  aparte `ploutos-panel` de SOLO LECTURA (bases en `mode=ro`, sin `ai/`, sin exchange), solo en la IP de
  Tailscale. **Foto entera del estado por WebSocket** cuando cambia (no deltas); **pagina propia en HTML y
  JavaScript sin compilar** (no React), con Lightweight Charts guardado en el repo; el estado de cada
  servicio se DEDUCE de lo fresco de su base. Controles: pausar, quitar la pausa, parar, levantar la
  parada y cerrar todo (doble confirmacion), **sin PIN** (Tailscale es la unica barrera); el suelo, solo
  en el VPS; entran en `control_comandos` con origen `panel`. **Slider bloqueado en el nivel 3** hasta
  cerrar la fase 6 y revisar la estrategia. Dependencia: FastAPI + uvicorn (el PRD los nombra).

- **25/09/2026 — Comandos de Telegram** (`docs/diseno-comandos-telegram.md`, el propietario con los botones):
  `/status`, `/pause` (solo cierre manual, modo nuevo `CLOSE_ONLY_MANUAL`; `/closeonly` es sinonimo),
  `/kill` (`HALTED`: cancela las entradas pendientes y las OCO siguen) y `/resume`. **Desde el movil solo
  se levanta la pausa**, con confirmacion (`/si` en 60 s); `HALTED` y el suelo, solo en el VPS o el panel.
  Siempre las DOS carteras a la vez (la fase 6 las compara). Cerrar todo NO va por Telegram. Servicio
  propio (`ploutos-telegram`, `getUpdates`) con base propia que las carteras leen en `mode=ro`. **Se
  despliega con la pieza de noticias**: el bucle cambia una sola vez durante la muestra de la fase 6.

- **28/09/2026 — La regla 4 se queda en 3 posiciones.** el propietario planteo subirla a 4 hasta el veredicto de la fase 6
  (la cartera llena en 17 de 19 velas: la IA solo ve 4 candidatos en 3 dias). Al ver que 4 x 15 $ = 60 $ no cuadra
  con el 90 % de exposicion (la comprobacion de `core/config.py` no deja arrancar) y que partiria la muestra, lo
  dejo en 3. Lo que hace crecer la muestra de la M1 sin tocar reglas son los candidatos en sombra (decision 5 del
  protocolo, el 02/10).

- **28/09/2026 — Copia diaria, CSV fiscal, diagrama de nodos y cortos A'** (el propietario, las cuatro recomendadas): copia DIARIA
  al portatil (PRD 11); el CSV del panel lleva los EUROS con el cambio USDC/EUR de OKX, pedido SOLO al bajarlo:
  **excepcion acotada a "el panel no habla con el exchange"** (dato publico, sin claves; un test comprueba que es lo
  unico del panel que sale a la red); el diagrama de flujo por nodos ("Flujo de la ultima vela", vista de sistema y
  por moneda); y el disenyo de los cortos A', aprobado antes de medir (`docs/archivo/diseno-cortos-bajistas.md`).

- **01/10/2026 — Regla 17: la paridad de USDC, SOLO con A** (`USDC/USDT x USDT/USD`, mismo umbral del 1,5 %), y un
  **aviso de Telegram** cuando la regla 17 empieza o deja de bloquear (solo al cambiar). Motivo: OKX retiro `BTC/USD`
  el 30/09, el control C dejo de existir y la paridad quedo DESCONOCIDA: **las dos carteras sin entradas durante 5
  velas (30/09 08:00 - 01/10 00:00), 20 h, sin que nadie lo supiera** (ningun juez da FALLA: el bot cumplia la regla).
  En OKX ya no queda ningun control independiente de USDT. Lo que A no ve: USDC y USDT cayendo a la vez y en la misma
  medida. Descartadas: un control externo (Kraken o Coinbase: otra dependencia que, al caer, bloquearia igual) y
  esperar al 02/10. Desplegado el 01/10 ~07:30 UTC; la fuente de la paridad no entra en la huella (`f063d80147a9`).

- **02/10/2026 — Cierre de la fase 3, sombra y fase 4** (el propietario, las recomendadas): **fase 3 CERRADA**; **candidatos en
  sombra, opcion B** (en vivo, en el servicio de la IA; los cuatro detalles de `docs/archivo/propuesta-candidatos-sombra.md` 3
  tal cual: `slots_free: 1` sin decirle que es sombra, presupuesto con margen de 4 en 5 h y 20 al dia, sin cambiar la
  huella, nunca abre nada; se juzga APARTE y su juez se escribe ANTES de ver datos de sombra). Sabiendo
  (`estudios/potencia-fase-6`) que no hara concluyente la fase 6: el motivo es el doble de datos y ver antes una IA
  mala. **OK a la fase 4** con `tradeQuoteCcy: "USDC"` explicito; empieza despues de la sombra. **Techo de ATR entre
  las dos carteras (`estudios/divergencia-atr`): opcion A, dejarlo escrito sin tocar nada.**

- **02/10/2026 — El saldo del demo: SALDO VIRTUAL de 50 $ (opcion A del propietario).** La cuenta demo tiene los fondos por
  defecto de OKX (5.000 USDC, 1 BTC, 1 ETH, 50.000 XRP, USD y EUR; `comprobar_cuenta_demo.py`), no 50 $: con la regla 6
  tal cual el equity saldria > 100.000 $ y las reglas 7, 8, 9 y 15 no significarian nada, y XRP no tiene par contra USDC
  en el demo. El ejecutor hace una FOTO del saldo al arrancar y cuenta como suyo 50 USDC + lo que cambie desde entonces
  por sus ordenes: equity = 50 + delta USDC + sum(delta cantidad x mejor bid) - comisiones de salida; la conciliacion
  compara tambien deltas. Sirve igual en la fase 7 si la cuenta real tiene otros fondos. Un movimiento a mano en el
  demo sale como descuadre. Descartadas: dejar el demo en ~50 USDC (sin verificar que OKX lo permita) y dejar el
  riesgo en el papel (la fase 4 no probaria la regla 6 con datos del exchange).

- **02/10/2026 — Lo que dijeron las 9 pruebas del demo (el propietario, las tres recomendadas;** `preparacion-fase-4.md` 11):
  1. **Objetivo taker:** el simulador de papel y la M1 lo cobran como maker (~0,03 R optimista por objetivo). **No se
     tocan durante la muestra de la fase 6** (regla fijada antes; las dos carteras llevan el mismo sesgo). Se corrigen
     despues del veredicto, ANTES de la segunda ronda de estrategia y de la fase 7.
  2. **NEAR, solo en papel en el demo:** la regla del 23/09 ("mas caras que las configuradas, no se opera") se aplica
     PAR POR PAR; el demo opera BTC, ETH, SOL y DOGE (NEAR paga 0,20 % / 0,35 % ahi). El mismo codigo protege la fase 7.
  3. **Entrada llenada a medias: cancelar el resto EN EL MOMENTO.** OKX crea entonces la OCO por lo llenado (prueba 4);
     la posicion sale mas pequenya que la planificada, nunca sin stop. Descartado: OCO propia dejando viva la entrada
     (dos OCO y cantidades que cambian). Pieza b; la conciliacion lo comprueba igual.

- **02/10/2026 — Como espeja el demo la cartera de la IA (pieza c, el propietario, las cuatro recomendadas;** `diseno-fase-4.md`):
  1. **La MISMA cantidad** que la orden de papel (precio, stop y objetivo iguales): espejo de verdad.
  2. **El motor de riesgo ENTERO otra vez** antes de enviar cada entrada copiada, con el estado del DEMO (equity,
     posiciones, perdida del dia, operaciones; el mercado, de la ingesta). Si veta, no se copia y se apunta por que.
  3. **Caducidad con reloj propio:** la misma regla que el papel (3 velas desde que se crea), contada por el ejecutor.
  4. **Salidas que no son stop ni objetivo** (noticia critica, "cerrar todo"): el demo cancela la OCO y vende a
     mercado, con un id propio (un tercer tipo de peticion en la guardia).

- **03/10/2026 — OCO rechazada con el precio ya pasado: VENDER A MERCADO (el propietario, opcion A).** Si al crear o rehacer una
  OCO OKX la rechaza (`51279`, "TP trigger price cannot be lower than the last price") y el ULTIMO precio ya toco el
  objetivo o el stop, el ejecutor cancela lo que quede y vende a mercado con el id de salida: es lo que habria hecho la
  OCO. Se mira el precio, no el codigo (el del stop no se ha visto). El juez lo acepta solo si el precio del llenado
  esta mas alla del stop o del objetivo de la orden de papel. Descartada: solo avisar (la posicion sin proteccion).

- **03/10/2026 — La semana del demo solo vale con actividad (el propietario, opcion A).** La cartera de la IA tenia las 3 plazas
  llenas (AVAX, SOL y ETH, abiertas antes de la foto) y el ejecutor solo copia decisiones NUEVAS: la semana podia
  pasar sin una sola orden en el demo. El criterio pasa a ser **7 dias sin descuadres Y al menos una operacion
  completa** (compra, OCO y cierre); si no la hay, se alarga hasta que la haya. Lo mira el juez (`execution/juez.py`,
  `MIN_COMPLETAS`). **Opcion B tambien, el mismo dia** (con cuatro condiciones: solo ETH y SOL, se cuentan aparte como 'adoptadas', cuentan para la operacion completa, ninguna a menos de un 1 % del stop o del objetivo): `scripts/adoptar_posiciones_demo.py` compro a las 14:28 UTC SOL 0,09084 a 119,57 y ETH 0,006178 a 2.683,28 con su stop y objetivo de papel adjuntos; el ejecutor las adopto a las 14:33 y la pasada de las 14:38 cuadra.

- **03/10/2026 — Fase 5 CERRADA (el propietario).** Todo lo del PRD 9 y 10 con datos reales menos el panel de hipotesis, que pasa a
  la fase 8. Antes de cerrarla se arreglaron los dos huecos del demo (aviso de cierre con R y duracion; error de clave
  de OKX dicho como tal). Detalle en `docs/archivo/cierre-fase-5.md`.

- **24/09/2026 — Las cinco decisiones del protocolo de la fase 6** (`docs/archivo/protocolo-fase-6.md`), fijadas
  ANTES de ver datos de la IA: 1) la muestra cuenta **desde el despliegue de la fase 3**, partida en
  tramos si cambia el camino de decision; 2) **minimo 3 semanas, hasta 30 velas en que IA y baseline
  discrepan, tope 8 semanas**, y el juez no ensenya el veredicto antes; 3) decide **M1, el
  contrafactual por candidato** (la cartera es solo descriptiva); 4) IA perjudica -> fase 7 con el
  baseline; aporta -> con la IA; **no concluyente (lo probable) -> con la IA y se sigue midiendo**;
  5) candidatos en sombra con la cartera llena: **se decide tras la primera semana de la fase 3**.

## Fase 0 — estado

| Elemento | Estado |
|---|---|
| Cuenta en OKX EU (KYC) | **hecho** (22/09/2026) |
| Clave de API | **demo `ploutos-demo` hecha y verificada** (22/09): `eea.okx.com`, sin retirada, solo la IPv4 del VPS. **Monedas permitidas: 6** (el propietario, 23/09): las 6 de las 8 que el entorno demo ofrecia para elegir. **No es un limite por clave**, es lo que habia en el demo. Para la fase 4 basta con las 5 operables en demo contra USDC (BTC, ETH, SOL, DOGE, NEAR). La real, en la fase 7, con las 8: comprobar al crearla que las deja anyadir todas. **02/10: la clave del demo NO deja operar NINGUNA de las 5** (BTC, ETH, SOL, DOGE, NEAR): OKX contesta `50123` ("This API Key does not have trading permission for the Crypto") a una compra post-only al 50 % del precio. El propietario cambio las monedas permitidas en la web del demo y a las 20:35 deja operar las cinco. **Leccion: `50123` = moneda no permitida en la clave** (al crear la real, comprobar tambien la de cotizacion) |
| VPS | **operativo**: VPS nano, Ubuntu 24.04.5, Python 3.12.3,. IP fija: la de `Host ploutos` en `~/.ssh/config` (no se escribe aqui) |
| Bot de Telegram | **hecho**: `chat_id` en `.env`, mensaje de prueba recibido |
| Token de Claude | **regenerado y VERIFICADO** (22/09) con una llamada real sin sesion. Caduca ~22/09/2027: avisar 14 dias antes (PRD §6). `claude.token_expires_on: 2027-09-22` en `settings.yaml` (APROXIMADO): el aviso sale en el resumen de la IA; al regenerar el token, cambiar la fecha |
| Reloj | **hecho**: en Windows el W32Time estaba parado (-10 s); en el VPS, `chrony` |

## Estado ahora (actualizar al cambiar) — 02/10/2026

| Fase | Estado |
|---|---|
| 1. Ingesta | **CERRADA** (25/09 17:28 UTC): 72 h, 44.440 velas, 0 huecos. Ver `docs/archivo/cierre-fase-2.md` |
| 2. Riesgo, estrategia, baseline en papel | **CERRADA** (25/09): los 4 criterios cumplen (810 tests, papel 17/17 en 72 h, mutacion 16/16). Ver `docs/archivo/cierre-fase-2.md` |
| 3. Analista en sombra | **CERRADA** (02/10, OK del propietario): 7,0 dias, ninguna vela perdida, 3/3 respuestas validas, consumo medido por el journal (0,27 $ equivalentes en la semana; la cuota de Settings se reinicio el 01/10 antes de mirarla), juez de papel CUMPLIDO en las dos (168 h). Resultados en `docs/archivo/cierre-fase-3.md` 6. Las carteras siguen: la muestra de la fase 6 cuenta desde el 25/09 (tramo `f063d80147a9`) |
| 4. Ejecucion en el demo | **DESPLEGADA el 03/10** (`ploutos-exec`): espeja la cartera de la IA en el demo (BTC, ETH, SOL y DOGE; NEAR, XRP, AVAX y TRX en papel). **La semana cuenta desde la foto del 03/10 10:16:28 UTC** (50 $ virtuales; la primera arrancada, 09:33, se paro para la prueba 10 y su base esta en `/var/backups/ploutos/ploutos-exec-arranque-0933.db`). Prueba 10 hecha (una OCO que salta, `preparacion-fase-4.md` 13). En el panel desde el 03/10 ('Demo de OKX'). Falta: tests de caos y **1 semana sin descuadres con al menos una operacion completa** (decision del 03/10; juez cada noche). Guion: `docs/archivo/guion-fase-4.md`; cierre preparado en `docs/archivo/cierre-fase-4.md` (06/10: 3,0 dias, 839 pasadas, todas cuadran, 0 completas) |
| 5. Panel, Telegram, vigilante | **CERRADA** (03/10, el propietario): panel desde el 26/09 (cuatro paginas, y desde el 03/10 el demo con el estado de la OCO de cada posicion y la pantalla de carga), comandos y Healthchecks desde el 25/09 (8 comprobaciones). Repaso punto por punto en `docs/archivo/cierre-fase-5.md`. **El panel de hipotesis y aprendido pasa a la fase 8** (sin datos hasta entonces); el slider, bloqueado en el 3 hasta el veredicto de la fase 6 |
| 6. IA contra baseline | **MIDIENDO** desde el 25/09 (tramo `f063d80147a9`); veredicto desde el 16/10. Desde el 02/10, ademas, la **M1 EN SOMBRA** (opcion B): con la cartera llena la IA decide sobre lo que saldria con hueco (`kind = 'sombra'`, `slots_free: 1`), no se abre nada y se juzga aparte con `check_fase6.py --sombra` |
| Estrategia, segunda ronda | **Cortos: estudiados el 28/09 y NO PASAN** (`docs/estudios/revision-estrategia/README.md` 5): 220 cortos a -0,01 R con financiacion (IC -0,25 a +0,24); la combinacion con los largos con BTC alcista (+0,16 R, IC -0,00 a +0,32) no supera +0,13 entero. Reserva sin mirar; la cartera de cortos en sombra (`docs/archivo/diseno-cartera-cortos.md`) no se construye. **Velas de 1 h (operaciones de horas): estudiadas el 06/10 y NO PASAN** (`docs/estudios/operaciones-cortas/README.md`: -0,13 y -0,12 R, IC entero bajo cero). El resto de la segunda ronda, tras el veredicto de la fase 6 |
| Noticias y comandos de Telegram | **EN MARCHA desde el 25/09 ~18:20 UTC** (`ploutos-news`, `ploutos-telegram`; rama `comandos` fusionada en `main`). Con latido a Healthchecks desde el 25/09 22:28 UTC (5a y 6a comprobacion). `/status` probado desde el movil. Criterio: 7 dias de `check_news.py` y `check_control.py`: **CUMPLIDOS el 02/10** (7,1 dias, `cierre-fase-3.md` 6) |

**En el VPS corren (desde el 25/09):** `ploutos-ingest`, `ploutos-paper` (baseline), `ploutos-paper-ai`
(la IA, `MemoryMax`), `ploutos-news` y `ploutos-telegram` (desde las ~18:20), y desde el 26/09 `ploutos-panel`
(el panel, CON CONTROLES; desde el 29/09 en CUATRO paginas: Resumen, IA, Operaciones y Sistema, con la barra abajo en el movil; desde el 01/10, al tocar una posicion abierta sale su grafico de velas de 4 h con entrada, stop y objetivo (`/api/velas`); desde el 27/09 con el aspecto de la maqueta: barra azul petroleo del logo, dos columnas, letras de la maqueta guardadas en `ui/vendor/fonts` y `Cache-Control: no-cache`; solo en la IP de Tailscale: `http://ploutos.example.ts.net:8765`; el cortafuegos
abre el 8765 solo en `tailscale0`; desde Internet no responde; comprobado), con swap de 1 GB, nucleo 6.8.0-142 y reinicio automatico a las 07:15 UTC si un
parche lo pide. Latidos a Healthchecks de los cinco y de la copia: 6 comprobaciones del VPS, y desde el 01/10 una 7a del PORTATIL (la copia diaria) (el aviso por Telegram, PROBADO
el 25/09 parando la IA 19 min); desde el 03/10, la del ejecutor (`HEALTHCHECK_EJECUTOR`, 5 min + 15 min): 7 del VPS y 1 del portatil. El `.env` del VPS tiene 14 claves.
**Desde el 03/10 (foto a las 10:16 UTC) corre tambien `ploutos-exec`** (el ejecutor del demo, fase 4; el UNICO con las claves de OKX; base
`var/ploutos-exec.db`, sexta en las copias). Avisos de Telegram enchufados.
La base de papel de las 72 h, archivada: `var/ploutos-paper-fase2.db` y
`/var/backups/ploutos/ploutos-paper-cierre-fase2.db` (y en el portatil, `var/backups/`).
Copias cada noche a las 03:15 UTC, de las CINCO bases; la tarea DIARIA de Windows (desde el 28/09; antes semanal) baja al portatil cada dia
a las 12:00 SOLO las nuevas y guarda 8 semanas (la mas reciente de cada base, siempre; el propietario, 28/09). **Desde el 01/10
(el propietario):** el 30/09 la copia se CORTO a medias (Windows la mato, 0xC000013A) sin avisar. Ahora se lanza a las 12:00, cada
hora hasta medianoche, al iniciar sesion y al desbloquear, con `-SoloSiFalta` (nada si la de hoy ya salio bien); una
marca (`var/backup-en-curso.txt`) delata la cortada en la siguiente; un fallo se avisa UNA vez al dia; y late a una
SEPTIMA comprobacion de Healthchecks (`HEALTHCHECK_COPIA_PORTATIL`, solo en el `.env` del portatil; la crea el propietario).
Descartado: que el VPS empuje la copia al portatil (el VPS tendria acceso de escritura a las copias que lo protegen).

**Durante la fase 3 y la muestra de la fase 6:** nada que cambie el camino de decision sin decirlo (parte
la muestra en tramos, decision 1 del protocolo). Los arreglos del bucle del 28/09 (esperar a las ocho monedas)
no cambian la huella: no parten la muestra. **Temporal hasta el 09/10:** `ploutos-spread-extra` (mide ADA y LINK).

## Ramas

| Rama | Que es |
|---|---|
| `main` | lo desplegado en el VPS: desde el 25/09 lleva la fase 3 entera (fusionada `fase-3-integracion`). El directorio de trabajo se deja SIEMPRE aqui: `sync.sh` copia lo que haya en disco |
| (borradas el 26/09) | `noticias`, `fase-3-integracion`, `noticias-servicio`, `comandos`, `comisiones-settings` y `telegram-avisos`: todo su contenido esta en `main` (comprobado antes de borrar) |
| `fase-4-piezas-puras` | **Juntada en `main` el 03/10** (`b4e7b65`): toda la fase 4 (piezas puras del 24-26/09, las 9 pruebas, el ejecutor, el servicio, el juez y la ingesta con `core/salud.py`). Se puede borrar tras la semana |

**Avisos de Telegram (desplegados el 25/09):** se escriben en `paper_avisos` (006) en la MISMA transaccion que la
vela y otro paso los manda en cada vuelta (max 5, timeout 10 s, uno por segundo, para en el primer
fallo, nunca lanza); los de mas de 12 h se descartan. Resumen de ayer desde las 00:10 UTC. **Ningun
test ve las credenciales de Telegram** (`tests/conftest.py`): sin eso, pasar los tests mandaria
mensajes de verdad. El vigilante (Healthchecks) y los comandos, desplegados el 25/09; los avisos de las NOTICIAS
(flag nueva, pendientes de decidir, fuente caida) los manda el servicio de noticias desde su propia base.

**Pendiente con fecha:**
- **Revision semanal de actualizaciones, domingos 07:30 UTC** (`ploutos-actualizaciones.timer`, el propietario 26/09):
  Tailscale se instala solo (sin reiniciar el bot); librerias, el programa de la IA y Ubuntu no de seguridad,
  solo aviso por Telegram. **Tailscale no se actualiza con las automaticas de Ubuntu.**
  **Primer aviso (27/09), decidido con el propietario:** el programa de la IA (2.1.266 -> 2.1.274) NO se toca hasta el
  veredicto de la fase 6 (partiria la muestra); ccxt (4.5.82 -> 4.5.84), justo ANTES de empezar la fase 4, con
  los tests; los 6 de Ubuntu que no son de seguridad (apparmor, libaudit, dmidecode, firmware AMD), en una
  parada de mantenimiento elegida (p. ej. antes de desplegar la fase 4): `needrestart` reiniciaria los servicios.
  **HECHA el 02/10 (13:56-14:03 UTC): ccxt 4.5.84 (fijada en `pyproject.toml`) y los 6 paquetes; huella intacta; resultado
  en `docs/archivo/parada-mantenimiento-fase-4.md` 9.** El nucleo 6.8.0-146 (solo en noble-updates), sin instalar. Guion: ccxt 4.5.84 probado en el portatil: los tests de
  `main` y de la rama en verde y las 48 peticiones a OKX identicas; ccxt no entra en la huella (no parte la muestra).
- **La caducidad de la clave de Tailscale del VPS: DESACTIVADA por el propietario el 26/09** (antes caducaba el 25/03/2027).
- **Los jueces, solos cada dia a las 00:30 UTC** (`ploutos-jueces.timer`, desde el 26/09): los nueve (desde el 03/10 `check_exec.py`, la fase 4; con `check_fase3.py`, el criterio de la fase 3,
  desde el 02/10 `check_fase6.py --sombra`, la M1 en sombra, aparte, y desde el 01/10 `check_bloqueos.py`: FALLA si en las ultimas 24 h una cartera lleva 3+ velas sin poder entrar por un motivo de
  SISTEMA, no de mercado; `portfolio/bloqueos.py`);
  Telegram SOLO si alguno da FALLA o no corre. A mano: `scripts/jueces_diarios.py --seco`.
- **Entradas de papel (precisado 29/09):** se pueden llenar en cualquiera de las 3 velas siguientes a la que las crea y caducan
  si la tercera no baja al limite (`ENTRY_BARS_TO_LIVE = 2` son las velas SIN llenarse); no cambia el codigo.
- **Fase 3:** `check_paper.py` (las dos carteras) y `check_fase6.py` sin FALLA. A la semana
  (~02/10, guion en `docs/archivo/cierre-fase-3.md`): criterio de la fase 3 con `scripts/check_fase3.py` (exit 0 = cumplido; la cuota semanal la mira
  el propietario en Settings > Usage) y decidir los candidatos en sombra con su recuento. **Ensayo general el 28/09: sin FALLA**
  (`cierre-fase-3.md` 5b); la propuesta de la sombra, en `docs/archivo/propuesta-candidatos-sombra.md`.
- **Comision del demo en USDC: HECHO el 28/09** (`feeType` 0 -> 1, releido) con `scripts/fijar_comision_usdc.py
  --aplicar`, por decision del propietario y como EXCEPCION acotada a "nada de claves hasta la fase 4" (solo el demo,
  reversible, sin ordenes; de paso, la clave del demo sigue viva). **El dia que empiece la fase 4, relanzarlo SIN
  --aplicar** por si OKX reinicia el demo. Antes de empezar la fase 4: las decisiones, repasadas el 26/09. La ingesta desplegada sale de DEGRADED al momento, sin
  la espera de 10 min: se corrige al enchufar `core/salud.py`.
- **Fase 4 (equity, regla 6):** leer el USDC TOTAL de OKX (`eq`, en ccxt `total`), nunca el `free`:
  lo congelado por una entrada pendiente sigue siendo nuestro. Hecho en `execution/equity.py`.
  (`risk.equity.compute_equity` ya exige la comision taker, sin valor por defecto.)
- **Fase 4:** una pausa de Telegram tiene que cancelar las entradas pendientes EN EL MOMENTO (en papel
  cuenta al cierre de la vela; ver `docs/diseno-comandos-telegram.md`).
- **Fase 4:** enchufar `execution/precios.al_tick` (hecho el 24/09 en `fase-4-piezas-puras`: entrada al tick
  hacia abajo, stop y objetivo hacia arriba; **ccxt redondea el precio AL MAS CERCANO**, por eso va antes);
  la paridad de USDC deberia salir de la ingesta.
- **Tras el veredicto de la fase 6, antes de la segunda ronda:** el objetivo como TAKER en `portfolio/paper.py` y en
  `portfolio/comparacion.py` (decision del 02/10; hoy maker, ~0,03 R optimista por objetivo).
- **Antes de la fase 7:** la estrategia. PRIMERA RONDA HECHA (26/09): ninguna de las 5 ideas demuestra que
  mejore (`docs/estudios/revision-estrategia/README.md`); la reserva, intacta. El propietario: se decide la segunda ronda
  tras el veredicto de la fase 6 (desde el 16/10). **el propietario, 28/09: los CORTOS se ADELANTAN**: estudio con la
  historia ya (largos con BTC alcista, cortos espejo con BTC bajista; criterio fijado antes, plan 5b) y la
  tercera cartera de cortos en sombra, disenyada y sin construir hasta que el estudio pase. **Resultado (28/09): NO
  pasa** (los cortos, -0,01 R con financiacion; README del estudio, seccion 5): la cartera no se construye. OKX EEA si ofrece
  cortos a un particular (margen de spot y X-Perps). La regla 1 NO cambia. Y decidir DOGE y NEAR (y AVAX) con `scripts/estudio_spread.py`
  (lee `book_metrics`, una muestra cada ~10 s desde el 22/09; `paper_market` solo tiene una por vela). Con
  5,1 dias (27/09): **AVAX 0,0503 % de media** (0,055 % en fin de semana; en la primera medicion era 0,045 %),
  DOGE 0,046 % (0,052 % en la franja de America), NEAR 0,046 %. La regla 16 bloqueo 1 de 30 cierres de vela
  en DOGE y en NEAR, 0 en AVAX. Decidir con 14 dias o mas (el script lo avisa); mejor lanzarlo en el portatil
  sobre la copia (en el VPS tarda 10 s con 5 dias y crece con la base).
  **el propietario (27/09): se decide el 09/10** (dos semanas, dos fines de semana; guion en `docs/archivo/decision-whitelist-0910.md`:
  la regla 3 exige 8 exactas y el cambio se aplicaria tras el veredicto de la fase 6, porque parte la muestra).
  **ADA y LINK, midiendose hasta el 09/10** (el propietario, 28/09) con AVAX, DOGE y NEAR: servicio TEMPORAL
  `ploutos-spread-extra` (no lo instala `install.sh`); el 09/10, pararlo y quitarlo. Recomendacion dada: si AVAX sigue
  ~0,05 %, mantenerla y decir que el 0,05 % pasa a ser aviso y la regla 16 la norma; pero entonces revisar
  ADA (0,067 %) y LINK (0,065 %) con el mismo criterio. El spread es coste, no rentabilidad: que AVAX fuera la
  unica posicion en beneficio (27/09, +4,8 %) no entra en la decision.
- **Tras el veredicto de la fase 6: proponer los MEDIOS de comunicacion como fuente de noticias EN SOMBRA**
  (el propietario, 28/09; su decision del 25/09 era "medios despues y en sombra"). Hoy solo se leen los anuncios de OKX
  (80 hasta el 28/09, ninguna flag: ninguno toca las 8) y la IA no lee noticias (decision F).
- **Las cuatro propuestas pendientes, decididas por el propietario el 28/09 (las recomendadas):** (1) copia DIARIA fuera del VPS: **HECHO el 28/09** (tarea diaria al portatil);
  (2) el CSV fiscal en euros: **HECHO el 28/09** (el CSV del panel, con el cambio USDC/EUR de OKX, `api/cambio.py`);
  (3) el diagrama de nodos del panel: **HECHO el 28/09** ("Flujo de la ultima vela"); (4) el disenyo de la idea A' (cortos propios de mercado bajista): **APROBADO el 28/09**
  (`docs/archivo/diseno-cortos-bajistas.md`), se mide en la segunda ronda.
- **Hacer publico el repositorio: EN ESPERA (el propietario, 25/09).** Revision hecha el 25/09 sobre los 187 commits:
  ningun valor real del `.env`, ni la IP del VPS, ni datos del nombre real; lo que si sale es el correo
  personal como autor de TODOS los commits, "el propietario" (~600 veces, 94 mensajes de commit), y detalles que
  lo situan (Espanya en el informe, KYC de OKX, el proveedor del VPS y precio). Lo que el propietario quiere publicar:
  **solo codigo y tests**, "el propietario" -> "el propietario", sin esos detalles. Recomendado: repo NUEVO con un
  solo commit (el privado queda intacto); reescribir el historial del privado obligaria a sacar CLAUDE.md
  y los docs de todo el historial. Nada se publica sin su OK final, ensenyando antes el contenido exacto. Si cambia la whitelist, cambiar tambien la clave de OKX.

## Trampas y avisos vigentes

- **Si el SSH por la IP publica da timeout** (28/09, desde una red del propietario; el VPS aceptaba otras conexiones), entrar
  por Tailscale: `ssh -o HostKeyAlias=<IP publica> -i ~/.ssh/ploutos_ed25519 root@ploutos.example.ts.net`.
  `sync.sh ploutos` falla igual: copiar con `scp` por Tailscale. **Desde el 02/10 hay un alias `ploutos-ts`** en el
  `~/.ssh/config` del portatil (Tailscale, misma clave y huella): `ssh ploutos-ts`, `sync.sh ploutos-ts`. La copia diaria
  lo usa sola si `ploutos` no conecta (`daily-backup.ps1 -TargetAlternativo`; el 02/10 fallo por esto y avisó).
- **Windows tiene DOS clientes SSH**: el `ssh` de Git Bash no ve el agente de Windows ("Permission
  denied (publickey)"). `deploy/_ssh.sh` elige el bueno; forzar otro con `PLOUTOS_SSH=/ruta/ssh`.
- **`sync.sh` NO reinicia nada** (solo copia, con `tar` si no hay rsync) y **no copia `.env`**.
- **`/usr/local/bin/ploutos-backup` es una COPIA de `deploy/backup.sh`** hecha por `install.sh`: si
  se cambia uno, reinstalar.
- **Ficheros escritos desde Windows salen con CRLF**: en Linux fallan con errores que no se parecen
  a la causa. Escribir con `\n` explicito.
- **El VPS salia por IPv6** y OKX lo veia como IP no autorizada. Arreglado en `/etc/gai.conf` por
  `install.sh`. Trampa: una sola linea `precedence` descarta la tabla ENTERA. Comprobar:
  `curl -s https://api64.ipify.org` tiene que dar la IPv4.
- **SQLite en WAL: un escritor por base.** Por eso el papel tiene su base (`var/ploutos-paper.db`) y
  lee la principal en `mode=ro`. Copiar una base en uso con `cp` da copias corruptas: `VACUUM INTO`.
- **Lo que vive en memoria se pierde al reiniciar** y los servicios llevan `Restart=always`: todo
  estado que importe a una regla (operaciones del dia, cooldowns, modos, presupuesto de Claude) se
  deriva de lo guardado.
- **Las actualizaciones automaticas de Ubuntu REINICIAN los servicios.** El 23/09 a las 06:40 UTC,
  `unattended-upgrade` actualizo `sudo` y `needrestart` reinicio `ploutos-ingest` y `ploutos-spread`
  (el papel no). La ingesta se recupero sola (backfill de 301 velas por timeframe) y el juez no ve
  huecos. **`NRestarts` NO cuenta estos reinicios:** para saber si un servicio se ha reiniciado,
  mirar `systemctl show <servicio> -p ActiveEnterTimestamp`. La medicion del spread volvio a contar
  sus 24 h desde las 06:40 (el CSV se abre en modo anyadir: no se perdio nada).
- **Una vela solo esta lista cuando estan cerradas las OCHO monedas** (`run_paper._closed_bars_after`, 28/09):
  antes bastaba una y el 27/09 04:00 el bucle proceso sin DOGE (ver `hallazgos-fase-3-4.md` 5c). La fila de
  equity de esa vela se corrigio a mano con copia previa (decision del propietario).
- **Un par que OKX retira puede bloquear una regla EN SILENCIO** (01/10, BTC/USD y la regla 17): el bot hace lo correcto
  (sin dato, no entra) y ningun juez lo ve como fallo. Si una cartera lleva varias velas sin candidatos, mirar
  `paper_decisions` (`detail`) antes de achacarlo al mercado.
- **`CLOSE_ONLY_CAPITAL` solo sale a mano:** `sudo -u ploutos .venv/bin/python scripts/run_paper.py
  --reset-capital "motivo"` y despues `systemctl restart ploutos-paper`.

## Operacion

```bash
bash deploy/sync.sh ploutos                                   # copia; NO reinicia
ssh ploutos 'systemctl restart ploutos-paper'                 # SOLO el papel; la ingesta no se toca
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_gaps.py'     # juez fase 1
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_paper.py'    # juez fase 2
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/run_paper.py --status'
bash deploy/fetch-backup.sh ploutos                           # bajar y verificar copias
.venv/Scripts/python.exe scripts/verify_claude_cli.py --sin-sesion   # 1 llamada real, sin la sesion
```

Simulacro de restauracion (probado el 22/09 y, con las CINCO bases, el 27/09: 23 copias restaurables,
los siete jueces sin FALLA y las dos carteras arrancan con su estado): descomprimir las copias de una
misma hora (`ploutos`, `ploutos-paper`, `ploutos-paper-ai`, `ploutos-news`, `ploutos-control`) y lanzar
sobre ellas `check_gaps.py --db <copia> --until <hora>`; `check_paper.py` (y con `--decider ai`) con
`--main-db/--paper-db/--news-db/--control-db`; `check_fase3.py --sin-papel` y `check_fase6.py` con
`--ahora-ms <hora de la copia>`; `check_news.py` y `check_control.py` con `--paper-db` de las dos; y
`run_paper.py --status` / `run_paper_ai.py --status` con las mismas bases.

## Documentos

| Documento | Que hay |
|---|---|
| `docs/prd-ploutos-v2.md` | **fuente de verdad** |
| `docs/informe-ploutos.md` | el como; manda solo donde el PRD calla |
| `docs/archivo/cierre-fase-2.md` | criterios de la fase 2, comandos y plantilla de resultados |
| `docs/archivo/cierre-fase-4.md` | el cierre de la fase 4 preparado (06/10): cuando se cierra, de donde puede salir la operacion completa, criterios y jueces, caos, hallazgos (el `429` al arrancar) y plantilla de resultados |
| `docs/archivo/cierre-fase-5.md` | el repaso de la fase 5 punto por punto (PRD 9 y 10), los dos huecos del demo arreglados y el cierre (03/10) |
| `docs/archivo/cierre-fase-3.md` | el guion del 02/10, criterios y jueces de la fase 3, lo encontrado (memoria y disco, 27/09) y plantilla de resultados |
| `docs/archivo/plan-fase-3.md` | piezas, decisiones y criterio de la fase 3 |
| `docs/archivo/diseno-pieza-9.md` | la IA en el bucle: como, la memoria del VPS, lo construido |
| `docs/archivo/despliegue-fase-3.md` | el guion paso a paso con que se desplego la fase 3 (25/09) |
| `docs/hallazgos-fase-0-1.md` | ingesta, despliegue, OKX: hosts, demo, quote, IPv6, claves |
| `docs/hallazgos-fase-2.md` | motor de riesgo, costes, setups, papel, jueces, los fallos encontrados |
| `docs/hallazgos-claude-cli.md` | `claude -p`: flags, token, coste, esquema |
| `docs/hallazgos-fase-3-4.md` | 23-25/09: ccxt y OKX para la ejecucion, anuncios de OKX, la IA y su journal, la fase 6, el VPS |
| `docs/archivo/propuesta-revision-estrategia.md` | como revisar la estrategia antes de la fase 7: datos (USDT con reserva), 5 ideas cerradas, criterio y 4 decisiones del propietario (25/09) |
| `docs/archivo/plan-segunda-ronda-estrategia.md` | la segunda ronda preparada (28/09): cortos y velas de 1 h como candidatas, la financiacion reciente, lo que falta y las decisiones del propietario |
| `docs/archivo/diseno-cartera-cortos.md` | la tercera cartera de papel, solo de cortos, en sombra (28/09): dos caminos, piezas y decisiones; sin construir |
| `docs/archivo/diseno-cortos-bajistas.md` | la idea A' (cortos propios de mercado bajista), APROBADA por el propietario el 28/09 antes de medir: setup, criterio y como se mide |
| `docs/archivo/decision-whitelist-0910.md` | la decision de la whitelist del 09/10 preparada: guion, datos, que la condiciona (8 exactas, parte la muestra) y opciones |
| `docs/estudios/operaciones-cortas/README.md` | operaciones de horas (velas de 1 h, 06/10, el propietario): criterio fijado antes; H1 y H2 NO pasan (-0,13 y -0,12 R, IC entero bajo cero; en H2, 8 h de mediana, las comisiones son el 165 % del bruto) |
| `docs/estudios/viabilidad-otros-activos.md` | un bot aparte con acciones, divisas, oro, futuros o CFD (06/10): con 50 EUR no es viable sin apalancamiento; la CNMV prohibe la publicidad de CFD a minoristas desde 2023 |
| `docs/archivo/propuesta-time-stop.md` | el time-stop medido con un anyo, y que el baseline pierde en ese anyo (decidido) |
| `docs/archivo/caos-fase-4.md` | los tests de caos del demo (03/10): cuando, quien, como (la red se corta SOLO al ejecutor con `IPAddressDeny`), que tiene que pasar y los resultados |
| `docs/archivo/guion-fase-4.md` | del OK del 02/10 a "1 semana sin descuadres": construir (parada, cuenta demo, 9 pruebas, piezas que faltan, rama) y desplegar y medir (servicio, copias, vigilante, caos, la semana) |
| `docs/archivo/parada-mantenimiento-fase-4.md` | el guion de la parada antes de la fase 4: ccxt 4.5.84 (probado) y los paquetes de Ubuntu, orden de reinicio, comprobaciones y vuelta atras |
| `docs/preparacion-fase-4.md` | OCO de OKX con ccxt: trampas verificadas y lista para el demo |
| `docs/archivo/diseno-fase-4.md` | la ejecucion en el demo: servicio, piezas, flujo, caos, juez y 5 decisiones del propietario |
| `docs/archivo/propuesta-candidatos-sombra.md` | la decision 5 de la fase 6 preparada para el 02/10: numeros, que seria, los 4 detalles (huecos, presupuesto, huella, no abrir nada) y opciones A/B/C |
| `docs/archivo/dossier-02-10.md` | las decisiones del 02/10 en una pagina (cierre de la fase 3, sombra, techo de ATR, OK a la fase 4 con `tradeQuoteCcy`) y lo pasado el 30/09-01/10, con los numeros del 01/10 |
| `docs/estudios/divergencia-atr/README.md` | hallazgo del 29/09: el techo de ATR depende del equity y las dos carteras pueden ver candidatos distintos (0 de 198 en un anyo; la regla 9 pierde el 8,6 %) |
| `docs/estudios/potencia-fase-6/README.md` | que puede ver la fase 6 (01/10): sin sombra ~10 discrepancias en 8 semanas, APORTA imposible (pide 30); la sombra no lo cambia; falsa alarma de PERJUDICA ~7 % |
| `docs/archivo/protocolo-fase-6.md` | como se decidira si la IA aporta: metrica por candidato, exclusiones, regla fijada antes y 5 decisiones del propietario |
| `docs/propuesta-actualizaciones.md` | las actualizaciones automaticas del VPS: como estan, riesgos y opciones (DECIDIDO: opcion 2) |
| `docs/diseno-noticias.md` | la pieza de noticias: historial real de OKX medido, flags, piezas, tests y decisiones del propietario |
| `docs/archivo/esbozo-panel-fase-5.html` | maqueta del panel de la fase 5 (PRD 10), con datos de EJEMPLO; publicada como artifact privado del propietario |
| `docs/archivo/diseno-aprendizaje.md` | el bucle de aprendizaje (fase 8): los numeros medidos (1,97 R de desviacion), dos etapas, catalogo de campos y 4 decisiones del propietario (25/09) |
| `docs/diseno-api-panel.md` | la API del panel (fase 5): que expone, como se actualiza, controles, slider y 4 decisiones del propietario (25/09) |
| `docs/diseno-comandos-telegram.md` | los comandos de Telegram (PRD 9): propuesta, servicio, seguridad, juez y 3 decisiones del propietario (25/09) |
| `docs/propuesta-vigilante.md` | el watchdog externo ("el bot se ha caido"): opciones y 3 decisiones del propietario |
