# Ploutos — Informe de investigación: arquitectura, riesgos, APIs y diseño

**Fecha:** 22 de septiembre de 2026
**Destino:** input para la fase de construcción con Claude Code (PRD `prd-bot-trading-ploutos.md`)
**Alcance:** bot de trading spot de criptomonedas, 100 % autónomo, 50 $ de capital, sin apalancamiento, 8 activos, máx. 3 posiciones, decisiones asistidas por Claude vía Claude Code CLI con plan de suscripción.

> Nota: el mensaje original mencionaba capturas de la interfaz de referencia, pero solo llegó el PRD. La sección 5 se basa en la descripción textual de los paneles.

---

## 0. Resumen ejecutivo (leer antes que nada)

Hay **tres bloqueos** que el PRD da por resueltos y que no lo están. Hay que decidirlos antes de escribir una línea de código:

1. **Binance ya no es una opción limpia para un residente en España.** Binance no obtuvo licencia MiCA, retiró su solicitud en Grecia el 24/06/2026 y anunció la suspensión de servicios a clientes de la UE a partir del 1/07/2026 (nuevas órdenes spot, depósitos y altas; las retiradas siguen abiertas). La CNMV confirmó que no habría prórroga del periodo transitorio. A septiembre de 2026 sigue sin licencia; algunos medios reportan que mantiene clientes vía "reverse solicitation" y enrutamiento por su entidad de Abu Dabi, algo que ESMA cuestiona. Construir un bot autónomo sobre un exchange que puede cortar la operativa de un día para otro, y sin las protecciones MiCA (segregación de activos, custodia supervisada), es un riesgo operativo y legal innecesario. **Recomendación: ejecutar en un exchange con licencia MiCA (OKX EU como primera opción, Bitvavo como alternativa) y usar `ccxt` para no quedar atado a ninguno.**

2. **La regla "solo pares USDT o BTC" es inaplicable en la UE.** USDT no cumple MiCA: Binance lo deslistó para usuarios del EEE el 31/03/2025, Kraken el 24/03/2025, Coinbase Europe en diciembre de 2024. En los exchanges con licencia no puedes comprar USDT. **La regla equivalente es "solo pares contra USDC (o EUR) o BTC"**, y recomiendo ir más allá: **solo USDC** (ver §4.1).

3. **Usar el plan de suscripción de Claude para un bot 24/7 está en zona gris.** Claude Code con `claude -p` y tu propia suscripción, sin modificar el binario, es técnicamente uso del cliente oficial. Pero la documentación dice que los límites de Pro/Max "asumen un uso ordinario e individual de Claude Code y del Agent SDK", y que quien construye productos con el Agent SDK (y `claude -p` es literalmente "el Agent SDK vía CLI") debería usar API key. No hay casos documentados de bans por uso continuo del cliente oficial (los bans documentados son por extraer tokens, proxies y cuentas compartidas), pero el riesgo existe, y la cuenta que arriesgas es la misma que usas para todo lo demás. Además, **cada llamada del bot consume la misma cuota que usas para lo demás**. La solución técnica al riesgo de sesión caducada del PRD sí existe: `claude setup-token` genera un token OAuth de **un año** (§3.1).

Y una verdad incómoda sobre la rentabilidad: **con 50 $ y 10–20 operaciones al día, las comisiones pueden comerse entre el 18 % y el 90 % del capital al mes** en los exchanges con licencia MiCA, según exchange y tipo de orden (§2.2). La frecuencia de operaciones del vídeo original no es un objetivo, es un riesgo. El diseño que propongo opera menos, con órdenes maker, y mide si la IA aporta algo frente a un baseline de reglas simples. Si no aporta, lo sabrás en semanas, no en meses.

---

## 1. Arquitectura recomendada

### 1.1 Principio rector: la IA propone, el código dispone

El error de diseño más caro en bots con LLM es dejar que el modelo emita órdenes. El LLM es no determinista, puede alucinar números, puede recibir texto malicioso (titulares de noticias) y no respeta límites "porque se lo pides". Ploutos debe tener **tres capas de autoridad**:

| Capa | Quién | Puede | No puede |
|---|---|---|---|
| Reglas duras | Código (motor de riesgo) | Vetar cualquier cosa, cambiar de modo, cerrar posiciones | Ser modificada por la IA ni por el bucle de aprendizaje |
| Juicio | LLM (analista) | Elegir entre candidatos ya filtrados, puntuar, proponer parámetros dentro de rangos | Crear pares, saltarse límites, fijar tamaño fuera de rango, emitir órdenes |
| Mecánica | Código (ejecución) | Traducir decisiones aprobadas en órdenes, reconciliar con el exchange | Decidir |

Esto también resuelve el modo "solo cierre": si la IA desaparece (cuota agotada), las capas 1 y 3 siguen funcionando solas.

### 1.2 Diagrama de componentes

```
                      ┌──────────────────────────── VPS (EU) ─────────────────────────────┐
 Exchange WS/REST ───▶│ [1] Ingesta ──▶ [2] Store (SQLite WAL / Postgres)                 │
 Contexto (F&G,       │        │                  │                                        │
 funding, noticias)──▶│        ▼                  ▼                                        │
                      │ [3] Features/indicadores por moneda y timeframe                    │
                      │        │                                                           │
                      │        ▼                                                           │
                      │ [4] Filtros deterministas ──▶ [5] Generador de candidatos          │
                      │                                      │                             │
                      │                          (solo si hay trigger o revisión periódica)│
                      │                                      ▼                             │
                      │                        [6] Analista IA (claude -p, JSON schema)    │
                      │                                      │                             │
                      │                                      ▼                             │
                      │ [7] Motor de riesgo (veto, tamaño, modos) ◀── [M] Máquina de modos │
                      │                                      │                             │
                      │                                      ▼                             │
                      │ [8] Ejecución (post-only, idempotente, OCO en exchange)            │
                      │                                      │                             │
                      │ [9] Gestor de posiciones (trailing, time-stop, coste oportunidad)  │
                      │                                      │                             │
                      │ [10] Journal + bucle de aprendizaje (hipótesis)                    │
                      │ [11] Notificador Telegram     [12] API + WebSocket ──▶ Dashboard   │
                      │ [W] Watchdog independiente (systemd) ──▶ Telegram si el bot muere  │
                      └────────────────────────────────────────────────────────────────────┘
```

### 1.3 Pipeline por criptomoneda (detalle de cada etapa)

**[1] Ingesta de datos.** WebSocket del exchange de ejecución como fuente principal (velas de 1 m, ticker, libro de órdenes top-20, trades), con REST como respaldo y para reconciliación. Tres reglas:

- **Detector de datos obsoletos**: si una fuente no actualiza en N segundos (p. ej. 30 s para el ticker, 90 s para velas de 1 m), la moneda pasa a `STALE` y no genera candidatos. Si el exchange entero está `STALE`, el bot entra en modo degradado.
- **Solo velas cerradas** para indicadores. Usar la vela en curso es la fuente más común de *look-ahead bias* en backtests y de señales que "desaparecen" en vivo.
- **Sincronización horaria** con `chrony`. Las firmas de la API llevan timestamp y los exchanges rechazan peticiones con desfase.

**[2] Almacenamiento.** SQLite en modo WAL es suficiente para 8 monedas y te ahorra administrar una base de datos. Tablas mínimas: `candles`, `orderbook_snapshots` (muestreadas, no todas), `features`, `candidates`, `llm_calls` (prompt hash, input completo, output, latencia, tokens, coste estimado), `decisions`, `risk_verdicts`, `orders`, `fills`, `positions`, `equity_snapshots`, `mode_changes`, `hypotheses`, `hypothesis_observations`, `events` (log general). **Todo con timestamp UTC y un `decision_id` que encadene** candidato → llamada LLM → veredicto de riesgo → orden → fill → cierre. Ese encadenado es lo que hace trazable el panel "qué está pensando la IA" y lo que alimenta el aprendizaje.

**[3] Features / indicadores.** Multi-timeframe (5 m, 15 m, 1 h, 4 h). Una propuesta de conjunto razonable, sin redundancias:

| Familia | Indicadores | Para qué |
|---|---|---|
| Tendencia | EMA 20/50/200, pendiente de EMA, ADX(14) | Dirección y fuerza |
| Momentum | RSI(14), MACD histograma, ROC | Agotamiento / aceleración |
| Volatilidad | ATR(14) en %, ancho de Bollinger, volatilidad realizada 24 h | Tamaño de stop, filtro de régimen |
| Volumen | z-score de volumen vs media 20, VWAP de sesión, OBV | Confirmación |
| Microestructura | Spread relativo, desequilibrio del libro (bid vs ask top-10), profundidad hasta 0,5 % | Coste real de entrar y salir |
| Contexto | Correlación 7 d con BTC, beta vs BTC, funding y open interest del perpetuo (dato público), Fear & Greed | Riesgo sistémico |
| Régimen | Clasificador simple: tendencia / rango / alta volatilidad (ADX + ancho de Bollinger + ATR percentil) | Qué setups tienen sentido |

No metas 40 indicadores: la mayoría están correlacionados entre sí y solo añaden ruido y tokens al prompt.

**[4] Filtros deterministas (antes de gastar una llamada a la IA).** Una moneda no genera candidatos si:

- spread > umbral (p. ej. 0,10 %) o profundidad hasta 0,5 % < 20× el tamaño de la orden,
- ATR% fuera de rango (demasiado quieta para cubrir comisiones o demasiado violenta para el stop),
- hay un evento de riesgo activo (noticia crítica, listado/deslistado, FOMC/CPI en ±30 min),
- está en *cooldown* tras un stop-loss (p. ej. 2 h),
- ya hay posición abierta en ella o el límite de correlación está lleno.

**[5] Generador de candidatos.** Reglas explícitas y pocas: *pullback en tendencia*, *ruptura de rango con volumen*, *reversión a la media en rango*. Cada candidato sale con entrada, stop (basado en ATR) y objetivo propuestos, y con su **expectativa bruta vs coste estimado**: si el objetivo esperado no supera 3× el coste de ida y vuelta, se descarta aquí. Así la IA solo ve oportunidades que al menos podrían pagar sus comisiones.

**[6] Analista IA.** Recibe un JSON compacto y devuelve un JSON validado por esquema (`--json-schema`). Se invoca solo en tres casos: (a) hay ≥1 candidato nuevo, (b) revisión periódica de cartera (cada 1–4 h, o cuando una posición cambia de estado significativamente), (c) revisión diaria de aprendizaje. Detalles en §1.5.

**[7] Motor de riesgo.** Código puro, sin IA. Calcula el tamaño y veta. Detalles en §4.

**[8] Ejecución.** Detalles en §1.6.

**[9] Gestor de posiciones.** Cada 15–60 s, sin IA: actualiza trailing stop, aplica time-stop (si en X horas no se ha movido hacia el objetivo, se cierra: el capital parado también cuesta), recalcula coste de oportunidad (§1.7), y reposiciona la OCO en el exchange cuando cambia el stop.

**[10] Journal y aprendizaje.** Detalles en §1.8.

**[11] Notificador** y **[12] API/WS para la UI**: §3.5 y §5.

**[W] Watchdog.** Proceso separado (unit de systemd distinta) que comprueba un heartbeat del bot cada minuto. Si el bot no late en 3 minutos, manda Telegram. **No debe depender de que el bot esté vivo para avisar de que está muerto**, que es justo el fallo que el PRD quiere cubrir con "notificar cada vez que el bot se detenga".

### 1.4 Máquina de modos

El PRD define dos causas de "solo cierre". Recomiendo formalizarlas como estados con prioridades, porque se pueden solapar:

| Modo | Entra cuando | Abre | Cierra | Sale | Notifica |
|---|---|---|---|---|---|
| `NORMAL` | Arranque OK | Sí (con IA) | Sí | — | — |
| `CLOSE_ONLY_QUOTA` | Cuota Claude agotada / login caducado | No | Sí, por reglas | Automático cuando una sonda a Claude responde OK | Entrada y salida |
| `CLOSE_ONLY_DEGRADED` | Datos obsoletos, errores repetidos del exchange, desfase horario | No | Sí (las OCO ya están en el exchange) | Automático tras X min sano | Entrada y salida |
| `CLOSE_ONLY_DAILY` (propuesto) | Pérdida del día ≥ límite diario | No | Sí | Automático a las 00:00 UTC | Entrada y salida |
| `CLOSE_ONLY_CAPITAL` | Equity ≤ 25 $ | No | Sí | **Nunca automático**: requiere reset manual | Entrada |
| `HALTED` | Kill switch manual o error crítico | No | Opcional (configurable) | Manual | Entrada |

Reglas: el modo efectivo es el **más restrictivo** de los activos (pueden coexistir `QUOTA` y `CAPITAL`); `CLOSE_ONLY_CAPITAL` es **enclavado** (*latched*): aunque el equity rebote a 26 $ no vuelve a abrir. Si no lo haces así, el bot oscila alrededor del límite y el límite deja de servir.

### 1.5 Contrato con el analista IA

**Entrada** (ejemplo abreviado; en producción ~2–4 KB):

```json
{
  "ts": "2026-09-22T14:05:00Z",
  "mode": "NORMAL",
  "portfolio": {"equity": 48.12, "free_quote": 18.40, "open_positions": [
    {"id":"p17","symbol":"SOL/USDC","entry":142.1,"last":143.0,"stop":139.9,"target":147.5,
     "age_min":95,"unrealized_pct":0.63,"ev_remaining":0.21}]},
  "limits": {"max_positions":3,"slots_free":2,"risk_per_trade_usd":0.60,"daily_loss_left_usd":1.85},
  "market_context": {"btc_regime":"trend_up","fear_greed":61,"event_flags":[]},
  "candidates": [
    {"cid":"c88","symbol":"ETH/USDC","setup":"pullback_trend","tf":"15m",
     "entry":2510.0,"stop":2482.0,"target":2580.0,"rr":2.5,"cost_rt_pct":0.30,
     "features":{"rsi14":44,"adx14":27,"atr_pct":0.9,"vol_z":1.4,"spread_pct":0.02,"corr_btc":0.86}}],
  "memory": {"validated_rules": ["H-012: evitar breakouts en ADX<18 (conf 0.81, n=64)"],
             "recent_outcomes": ["últimos 10: 6W/4L, exp +0.11R"]}
}
```

**Salida** (forzada con `--json-schema`):

```json
{
  "decisions": [
    {"type":"open","cid":"c88","confidence":0.62,"size_multiplier":0.8,
     "reasons":["pullback a EMA50 con ADX>25","vol_z confirma"],
     "risks":["correlación alta con SOL ya abierta"]},
    {"type":"hold","position_id":"p17","reasons":["EV restante positivo"]}
  ],
  "rejected": [{"cid":"c91","why":"rango estrecho, coste > objetivo"}],
  "hypothesis_proposals": [{"text":"...","metric":"...","min_n":40}],
  "market_read": "texto breve para el panel (≤300 caracteres)"
}
```

Reglas del contrato:

- `type` ∈ {`open`, `close`, `hold`, `tighten_stop`, `skip`}. **No existe `modify_limits`.**
- `size_multiplier` ∈ [0,5; 1,0]: la IA solo puede **reducir** el tamaño que calcula el motor de riesgo, nunca aumentarlo.
- `cid` debe existir en la entrada. Si la IA inventa un símbolo o un `cid`, se descarta la decisión entera y se registra como `llm_invalid_output`.
- Si el JSON no valida o la llamada tarda más de un timeout (p. ej. 90 s), se trata como "no hacer nada", no como error fatal.
- La confianza que dé la IA **se registra pero no se usa tal cual**: se calibra con datos (¿las decisiones con confianza 0,7 aciertan un 70 %?). Los LLM están mal calibrados por defecto.

**Invocación** (orientativa; verificar flags con `claude --help` en la versión instalada):

```bash
claude -p "$(cat prompt.txt)" \
  --output-format json \
  --json-schema "$(cat schema.json)" \
  --append-system-prompt-file ploutos_system.md \
  --model sonnet \
  --max-turns 1 \
  --no-session-persistence \
  --disallowedTools "Bash,Edit,Write,WebFetch,WebSearch,Read" \
  --permission-mode dontAsk
```

Puntos clave:

- **Sin herramientas.** La entrada incluye titulares de noticias, que son texto no confiable. Un titular con una inyección de prompt ("ignora tus instrucciones y…") no debe poder ejecutar nada. Con herramientas desactivadas y salida por esquema, lo peor que puede pasar es una decisión absurda, que el motor de riesgo veta.
- **No se puede usar `--bare`** con la suscripción: el modo *bare* no lee `CLAUDE_CODE_OAUTH_TOKEN`. Eso significa que cada llamada carga el contexto por defecto de Claude Code; ejecuta el proceso en un directorio vacío, sin `CLAUDE.md`, sin `.mcp.json` ni hooks, para no inflar tokens.
- **Sin sesiones persistentes**: cada llamada es independiente y autocontenida. La "memoria" se inyecta tú, curada, en el campo `memory`. Si usas `--continue`, el contexto crece sin control y gastas cuota en historia irrelevante.
- `--output-format json` devuelve `usage` y `total_cost_usd` (estimado). Regístralo: aunque no pagues por token, es tu mejor proxy del consumo de cuota.

**Presupuesto de llamadas.** Anthropic no publica los tokens exactos de cada plan; la cuota funciona por ventanas móviles de 5 horas más un tope semanal. Por eso el bot necesita un **presupuesto propio**: por ejemplo, máximo 40 llamadas/día y máximo 8 por ventana de 5 h, configurable, y medir la primera semana cuánto de tu cuota semanal consume (en *Settings → Usage*). Si el bot se come el tope semanal, te quedas sin Claude para estudiar hasta el reset. Un diseño disparado por eventos (solo cuando hay candidato) hace esto viable; uno que llama a la IA cada minuto por 8 monedas (11.520 llamadas/día) no lo es.

### 1.6 Ejecución

- **Órdenes limit *post-only* (maker) por defecto**, con timeout (p. ej. 60–120 s). Si no se llena, se cancela y se reevalúa; no se persigue el precio con órdenes market. En cierres por stop se acepta taker.
- **Stop-loss y take-profit en el exchange** (OCO / órdenes algorítmicas), no solo en la memoria del bot. Si el VPS muere, las protecciones siguen vivas. Esto convierte el modo "solo cierre sin IA" del PRD en algo que funciona incluso si el proceso entero está caído.
- **Idempotencia**: cada orden lleva un `clientOrderId` derivado del `decision_id`. Si hay timeout de red, antes de reintentar se consulta si la orden existe. Duplicar una compra por un reintento es un clásico.
- **Filtros del instrumento**: leer al arrancar `tickSize`, `lotSize`/`minSz`, mínimo nocional y redondear siempre **hacia abajo** la cantidad. En los exchanges habituales el mínimo por orden ronda los 5 $/€, lo que con posiciones de ~15 $ deja poco margen para salidas parciales (vender la mitad de 15 $ puede quedar por debajo del mínimo, y además deja "polvo").
- **Reconciliación**: al arrancar y cada 5 min, el estado verdadero es el del exchange (saldos, órdenes abiertas, fills), no el de la base de datos local. Si difieren, gana el exchange y se registra una alerta.

### 1.7 Coste de oportunidad y "pool de liquidez"

El prompt original pide considerar la liquidez y el coste de oportunidad de cerrar o no otras operaciones. Hay que formalizarlo; si no, el LLM lo "considera" en prosa y decide por intuición.

**Liquidez** tiene dos sentidos, y los dos importan:

1. **Liquidez propia**: quote libre disponible. Con 3 huecos y ~50 $, lo razonable es asignar ~14–15 $ por posición y dejar un colchón del 10 % para comisiones y redondeos.
2. **Liquidez de mercado**: profundidad del libro. Tu orden no debería superar el 5 % de la profundidad hasta 0,5 % del precio. Con 15 $ en pares principales esto se cumple de sobra; en altcoins pequeñas o pares contra BTC, no siempre.

**Coste de oportunidad** (cuando los 3 huecos están llenos y aparece un candidato mejor):

```
EV_restante(pos) = P(tp) · (tp − precio) − P(sl) · (precio − sl)   [en R, estimado con datos históricos del setup]
EV_nuevo(cand)   = expectativa del setup candidato (en R), neta de comisiones
Coste_cambio     = comisión de salida + comisión de entrada + slippage estimado
Rotar solo si:   EV_nuevo − EV_restante(peor posición) > Coste_cambio + margen (p. ej. 0,2R)
```

Esto lo calcula el código y se lo pasa a la IA como dato (`ev_remaining`). La IA puede proponer la rotación, pero el motor de riesgo solo la acepta si la desigualdad se cumple. Con las comisiones de §2.2, la mayoría de rotaciones no compensan, y eso es exactamente lo que queremos que el bot aprenda.

### 1.8 Bucle de aprendizaje (hipótesis → verificación → aplicación)

Es la parte más atractiva del vídeo y la más fácil de hacer mal. El problema es estadístico: **con 10–20 operaciones al día, casi todo lo que "aprende" el bot en una semana es ruido**. Detectar que una regla sube la tasa de acierto de 50 % a 55 % con confianza razonable requiere del orden de cientos de operaciones por grupo. Un LLM que revisa las últimas 20 operaciones y "aprende" algo casi siempre está sobreajustando al azar, y encima te lo explica de forma muy convincente.

Diseño recomendado:

1. **Registro de hipótesis** con estados: `propuesta → en_prueba → validada | rechazada → aplicada → retirada`.
2. **Cada hipótesis debe ser falsable y medible**: condición exacta (en campos de features, no en prosa), métrica (expectativa en R, win rate, MAE), tamaño mínimo de muestra (`min_n`) y fecha límite.
3. **La IA propone; el código evalúa.** La IA puede redactar la hipótesis y traducirla a una condición, pero la **confianza la calcula el código**: posterior Beta para tasas de acierto, o bootstrap del intervalo de confianza de la expectativa. El número que se muestra en el panel de "aprendido" es ese, no uno que diga el modelo.
4. **Evaluación en sombra**: una hipótesis en prueba se evalúa marcando las operaciones (o los candidatos descartados) que la cumplen, sin cambiar el comportamiento. Así no arriesgas capital para comprobar una idea.
5. **Aplicación limitada**: una hipótesis validada solo puede (a) añadir un filtro, (b) ajustar un parámetro dentro de un rango predefinido o (c) añadirse al campo `memory` del prompt. **Nunca** puede tocar los límites de seguridad.
6. **Corrección por comparaciones múltiples**: si pruebas 30 hipótesis, alguna saldrá "significativa" por azar. Exige más evidencia cuantas más hipótesis haya activas, o limita las simultáneas (p. ej. 5).
7. **Caducidad**: los mercados cambian de régimen. Una regla validada se revisa cada N semanas y se retira si su rendimiento en los últimos datos cae por debajo del umbral.
8. **Memoria acotada**: el campo `memory` del prompt contiene como máximo 5–10 reglas validadas, las de mayor confianza. Si crece sin límite, degrada las decisiones y gasta cuota.

### 1.9 La prueba que decide si la IA vale la pena

Ejecuta en paralelo, desde el primer día, un **baseline sin IA** en modo papel: los mismos candidatos, el mismo motor de riesgo, pero la decisión la toma una regla simple (p. ej. "abrir el candidato con mejor R:R si supera el umbral"). Al cabo de 4–8 semanas compara expectativa, drawdown y número de operaciones.

La evidencia pública no invita al optimismo. En Alpha Arena (temporada 1, finales de 2025), seis LLM operaron 10.000 $ reales cada uno en perpetuos: Qwen3 Max terminó en +22,3 %, DeepSeek en +4,9 %, y el resto perdió: **Claude Sonnet 4.5 −30,8 %**, Grok 4 −45,3 %, Gemini 2.5 Pro −56,7 %, GPT-5 −62,7 %. Hubo apalancamiento, así que no es directamente comparable, pero el ganador fue el que menos operó (~43 operaciones). Y un benchmark académico de agentes LLM en mercados en vivo encontró que **el diseño del agente pesa mucho más que el modelo**: cambiar el LLM dentro de la misma arquitectura movía poco los resultados; cambiar la arquitectura con el mismo LLM, mucho. Es otra razón para invertir en el motor de riesgo, los filtros y los costes antes que en el prompt.

Si al cabo de ese periodo el baseline rinde igual o mejor, la conclusión honesta es que la IA no aporta ventaja en este setup, y eso también es un resultado valioso del experimento.

---
## 2. Qué hace rentable a un bot, qué riesgos hay y errores comunes

### 2.1 Expectativas realistas con 50 $

Empecemos por el número. Un bot excelente, de los que casi nadie consigue, podría sacar un 2–5 % mensual neto de forma sostenida. Sobre 50 $ eso es **1–2,5 $ al mes**. El PRD ya reconoce que el valor del proyecto es el aprendizaje y no el dinero; el diseño debería optimizar para eso: **medir bien, perder poco y aprender rápido**, no para maximizar operaciones.

### 2.2 Las comisiones son el enemigo número uno

Comisiones spot del nivel de entrada (usuario sin volumen) en los exchanges relevantes para un residente en España, a septiembre de 2026:

| Exchange | Licencia MiCA | Maker | Taker | Ida y vuelta maker/maker | Ida y vuelta taker/taker |
|---|---|---|---|---|---|
| OKX EU (desde 25/09/2026, cuenta solo spot) | Sí (Malta) | 0,10 % | 0,20 % | 0,20 % | 0,40 % |
| Bitvavo | Sí (Países Bajos) | 0,15 % | 0,25 % | 0,30 % | 0,50 % |
| Bybit EU (desde 05/10/2026) | Sí (Austria) | 0,25 % | 0,25 % | 0,50 % | 0,50 % |
| Kraken Pro (desde 09/07/2026) | Sí (Irlanda) | 0,40 % | 0,80 % | 0,80 % | 1,60 % |
| Binance (referencia) | **No** | 0,10 % | 0,10 % | 0,20 % | 0,20 % |

A eso súmale spread y slippage: en pares grandes con 15 $ es casi nada (0,01–0,05 %); en altcoins medianas, 0,05–0,2 %.

**Arrastre de comisiones con posiciones de 15 $** (aproximación: capital constante de 50 $, 30 días):

| Coste ida y vuelta | 10 op./día | 20 op./día |
|---|---|---|
| 0,20 % (OKX maker/maker) | 9 $/mes → **18 % del capital** | 18 $/mes → **36 %** |
| 0,40 % (OKX taker/taker) | 18 $/mes → **36 %** | 36 $/mes → **72 %** |
| 0,50 % (Bitvavo o Bybit taker) | 22,5 $/mes → **45 %** | 45 $/mes → **90 %** |
| 1,60 % (Kraken taker) | 72 $/mes → 144 % | 144 $/mes → 288 % |

Leído al revés: con 20 operaciones al día en OKX a taker, el bot tiene que **ganar más de un 72 % mensual bruto** solo para quedarse igual. Eso no pasa. Conclusiones de diseño:

- **Objetivo de 1–5 operaciones al día**, no 10–20. Poner un límite duro de operaciones diarias (p. ej. 6).
- **Maker por defecto** (§1.6). Solo con eso reduces el coste a la mitad en OKX.
- **Filtro de coste en el generador de candidatos**: objetivo esperado ≥ 3× coste ida y vuelta.
- **Kraken descartado** para este uso con este capital.

**Win rate de equilibrio** con stop al 1,5 % y objetivo al 3 % (R:R 2:1): sin costes basta un 33,3 % de aciertos; con 0,3 % de coste por operación, un 40 %; con 0,5 %, un 44,4 %; con 0,9 %, un 53,3 %. El coste mueve la vara más que cualquier indicador.

### 2.3 Características de los bots que sobreviven

1. **Ventaja definida antes que código.** "La IA analiza el mercado" no es una ventaja; "compro pullbacks a la EMA50 en tendencia 4 h con ADX > 25, porque históricamente tienen expectativa +0,3R neta" sí lo es, aunque sea modesta. La IA sirve para filtrar y priorizar dentro de ventajas definidas, no para inventarlas en cada llamada.
2. **Gestión del riesgo por operación** fija y pequeña (0,5–2 % del equity arriesgado por operación, medido como distancia al stop × tamaño), no por intuición.
3. **Costes modelados en todo**: backtest, filtro de candidatos, decisión de rotar y métricas.
4. **Pocas operaciones y buenas**: la frecuencia alta solo compensa a quien tiene comisiones casi cero y latencia de milisegundos.
5. **Adaptación a régimen**: no operar rupturas en rango ni reversiones en tendencia fuerte. El clasificador de régimen de §1.3 es barato y evita mucho daño.
6. **Protecciones en el exchange** y reconciliación: el bot asume que puede morir en cualquier momento.
7. **Métricas honestas**: expectativa por operación en R, profit factor, drawdown máximo, tiempo en drawdown, MAE/MFE, tasa de fills maker, slippage real vs estimado, **y comparación contra el baseline sin IA y contra "hold BTC"**.
8. **Paper trading antes del dinero real.** Recomiendo 2–4 semanas en papel o en el entorno demo del exchange (OKX tiene modo de trading simulado) con datos en vivo. Así cierras la pregunta pendiente §9 del PRD.

### 2.4 Riesgos (incluidos los que no son obvios)

**Riesgos de mercado**

- **Correlación**: BTC, ETH, SOL y la mayoría de altcoins grandes tienen correlaciones diarias típicas de 0,7–0,9 con BTC. Tres posiciones largas en tres altcoins son, en la práctica, **una sola apuesta apalancada a BTC**. Hace falta un límite de exposición correlacionada (§4.3).
- **Solo largos**: en spot sin apalancamiento no puedes ponerte corto. En mercados bajistas la mejor decisión es casi siempre no operar. El bot debe tener "estar en liquidez" como opción de primera clase, sin presión por operar.
- **Gaps y cascadas**: los stops en el exchange se ejecutan a mercado cuando se disparan; en un crash (liquidaciones en cadena de perpetuos) el precio de salida puede ser bastante peor que el stop.
- **Riesgo del stablecoin**: si operas contra USDC, tu "efectivo" es USDC. En marzo de 2023 USDC perdió la paridad y llegó a cotizar ~0,88 $ durante un fin de semana por la quiebra de SVB. Es poco probable, pero el bot debe vigilar el precio USDC/EUR o USDC/USD y congelar operaciones si se desvía más de un 1–2 %.

**Riesgos del LLM**

- **No determinismo**: la misma entrada puede dar decisiones distintas. Registra las entradas completas para poder reproducirlas.
- **Alucinación numérica**: el modelo puede "leer" mal un número. Por eso el tamaño, el stop y los límites los calcula el código.
- **Mala calibración** de la confianza (§1.5).
- **Inyección de prompt vía noticias** (§1.5 y §3.4).
- **Sesgo narrativo**: los LLM construyen explicaciones plausibles a posteriori. Un razonamiento bonito en el panel "qué está pensando la IA" no es evidencia de que la decisión sea buena.
- **Look-ahead en backtests de LLM**: no puedes hacer backtest honesto de las decisiones del LLM sobre datos históricos, porque el modelo puede "conocer" lo que pasó después si está en su entrenamiento. El backtest sirve para la parte determinista; la IA solo se evalúa hacia delante (paper y real).

**Riesgos operativos**

- **Cuota y autenticación de Claude** (§3.1): el bot puede quedarse sin IA en medio de una posición. Mitigado con OCO en el exchange y el modo `CLOSE_ONLY_QUOTA`.
- **Baneo de IP por rate limit** del exchange: en Binance, por ejemplo, tras exceder límites con 429 viene un 418 con baneos de 2 minutos hasta 3 días. Todos los exchanges tienen algo parecido. Usa WebSockets para datos y un limitador de peticiones propio.
- **Claves de API filtradas**: la clave debe tener solo permiso de lectura y trading, **nunca de retirada**, con whitelist de IP del VPS y guardada fuera del repositorio (`.env` con permisos 600). El LLM nunca debe ver la clave ni el entorno.
- **Datos erróneos**: velas con huecos, precios atípicos, desincronización de reloj. Validar rangos y descartar outliers antes de calcular indicadores.
- **VPS gratuito que desaparece** (§3.6).

**Riesgos regulatorios y fiscales (España)**

- **Exchange sin licencia MiCA** (§0): sin protecciones y con riesgo de corte.
- **Fiscalidad**: en España cada venta y cada **permuta cripto-cripto** es una ganancia o pérdida patrimonial que tributa en la base del ahorro del IRPF (tipos del 19 % en adelante), aunque no pases a euros. Con 1–5 operaciones al día acabarás con cientos o miles de operaciones al año que tendrás que declarar, calculadas con FIFO. Desde el 1/01/2026 la DAC8 obliga a los proveedores con licencia a informar a Hacienda de las operaciones de sus clientes. **El bot debe exportar un CSV fiscal** (fecha, par, cantidad, precio, comisión en €, valor en €) desde el primer día. Esto no es asesoramiento fiscal: consulta con un gestor antes de la declaración.

### 2.5 Errores más comunes (con capital pequeño)

1. **Sobreoperar** para "que el bot haga cosas". Con 50 $ es la forma más rápida de perderlos (§2.2).
2. **Ignorar el mínimo por orden y el polvo**: posiciones de 5–6 $ que no se pueden cerrar parcialmente, restos no vendibles que se acumulan.
3. **Martingala o promediar a la baja** "porque el LLM ve una oportunidad". Prohibido por regla dura.
4. **Stops mentales** (solo en el bot) en vez de en el exchange.
5. **Optimizar el prompt con resultados de una semana**: es sobreajuste disfrazado de mejora.
6. **Mover el slider de agresividad después de una racha de pérdidas** (operar en *tilt*). El slider debe registrar cada cambio y, si lo usas, con un enfriamiento (p. ej. solo efectivo a partir del día siguiente).
7. **Confiar en la narrativa de la IA** en lugar de en las métricas.
8. **No comparar contra un baseline** ("hold BTC" y reglas sin IA).
9. **Medir el capital mal**: usar el saldo libre en vez del equity marcado a mercado, o no descontar las comisiones de salida. El límite de 25 $ depende de medir bien (§4.2).
10. **Pasar a dinero real sin fase de papel**, y perder los primeros 10 $ en bugs de redondeo y reintentos.

---

## 3. APIs necesarias

### 3.1 LLM: Claude Code con la suscripción

| Aspecto | Detalle |
|---|---|
| Cómo se invoca | `claude -p ... --output-format json --json-schema ...` desde el orquestador (subprocess) |
| Autenticación desatendida | `claude setup-token` genera un **token OAuth de un año**; se exporta como `CLAUDE_CODE_OAUTH_TOKEN` en el entorno del servicio. Solo sirve para peticiones al modelo. No compatible con `--bare` |
| Renovación | Crear un recordatorio 2 semanas antes de que caduque. El bot debe detectar `Login expired · Please run /login` / `Not logged in` → modo `CLOSE_ONLY_QUOTA` + Telegram |
| Límites | Ventanas móviles de 5 h + tope semanal; cantidades no publicadas; compartidas con tu uso personal |
| Detección de cuota agotada | Código de salida ≠ 0 y el campo `result` con textos como `You've hit your session limit`, `You've hit your weekly limit`, `You've hit your Sonnet limit`; en `stream-json`, eventos `system/api_retry` con `error: "rate_limit"`. Hay que parsear por patrones y tratar cualquier fallo desconocido como "sin IA" |
| Recuperación | Sonda barata (prompt mínimo) cada 30–60 min mientras dure `CLOSE_ONLY_QUOTA` |
| Términos | Permitido: binario oficial sin modificar, tu propia suscripción, sin extraer ni compartir el token, sin wrappers de terceros. Zona gris: uso continuo 24/7 frente a "uso ordinario e individual". Lo prohibido de forma explícita: usar el token OAuth en productos de terceros o proxies |

**Alternativa a considerar**: API de pago con el modelo más barato y un tope de gasto mensual. Elimina la zona gris y separa la cuota del bot de tu uso personal, pero con 20–50 llamadas/día el coste puede ser de varios dólares al mes, que es relevante frente a 50 $ de capital. Es un intercambio consciente: riesgo de cuenta y cuota compartida frente a coste explícito. Recomiendo **empezar con la suscripción y un presupuesto estricto de llamadas**, midiendo el consumo real durante la fase de papel, y decidir con datos.

### 3.2 Exchange de ejecución

**Recomendación principal: OKX EU**, a través de `ccxt` (biblioteca Python/JS que unifica más de 100 exchanges; si el panorama regulatorio vuelve a cambiar, migrar es cambiar de adaptador, no reescribir el bot).

| Criterio | OKX EU | Bitvavo | Binance |
|---|---|---|---|
| Licencia MiCA | Sí (MFSA, Malta) | Sí (AFM, Países Bajos) | No; servicios UE suspendidos o en zona gris desde 07/2026 |
| Comisiones de entrada | 0,10 % / 0,20 % | 0,15 % / 0,25 % | 0,10 % / 0,10 % |
| Moneda de cotización | USDC, EUR (pares contra BTC: verificar en la versión EU) | Principalmente EUR | USDT no disponible para EEE desde 03/2025 |
| Órdenes de protección en el exchange | Órdenes algorítmicas: OCO, trigger, trailing | Stop-loss / take-profit (limit y market) | OCO |
| Entorno de pruebas | Sí (trading simulado) | Limitado | Testnet |
| API | REST + WebSocket (v5), con passphrase | REST + WebSocket; 1.000 de peso/min por defecto; WS hasta 5.000 mensajes/s | REST + WebSocket |

Notas:

- **Comprueba en tu propia cuenta**, antes de construir, que la entidad europea te permite abrir cuenta, depositar y operar vía API los pares que quieres. La disponibilidad de pares varía entre la versión global y la europea de cada exchange.
- **Límites de peticiones**: con WebSockets para datos de mercado, tu consumo REST será mínimo (colocar/cancelar órdenes, reconciliación cada 5 min). Cualquiera de los tres aguanta ese patrón con mucho margen. El límite que importa es el tuyo: un limitador de peticiones propio y *backoff* exponencial ante 429.
- **Clave API**: permisos de lectura y trading solo, sin retirada, IP whitelist del VPS (necesitas IP fija).
- **Si decides seguir con Binance** pese a todo, hazlo sabiendo que operas sin las protecciones MiCA y que un cambio regulatorio puede bloquear nuevas órdenes con posiciones abiertas; con las OCO en el exchange, al menos, se cerrarían solas.

### 3.3 Datos de mercado y contexto

El PRD plantea "API gratuita con ~20 llamadas/min o 1 por minuto si da todas las métricas". Mi recomendación es distinta: **los datos de precio, volumen y libro deben venir del exchange donde ejecutas**, por WebSocket (gratis, en tiempo real, sin límite práctico para 8 monedas), porque el precio que importa es el de tu libro de órdenes. Las APIs externas solo aportan contexto, que cambia despacio.

| Fuente | Qué aporta | Coste / límite | Uso recomendado |
|---|---|---|---|
| WebSocket del exchange (OKX/Bitvavo) | Velas, ticker, libro, trades | Gratis | Fuente principal, en tiempo real |
| REST público del exchange | Velas históricas (arranque), instrumentos y filtros | Gratis; límites por endpoint | Al arrancar y para rellenar huecos |
| OKX: endpoints públicos de derivados | Funding rate, open interest de perpetuos | Gratis, sin cuenta de derivados | Cada 5–15 min. Funding muy positivo + OI subiendo = mercado apalancado en largo, riesgo de cascada |
| CoinGecko API (plan Demo) | Capitalización, dominancia BTC, trending, datos agregados | Gratis; **100 llamadas/min, 10.000/mes**; requiere atribución | Cada 10–15 min como máximo (10.000/mes ≈ 1 cada 4,3 min si lo usas 24/7). Usar poco |
| Alternative.me Fear & Greed | Índice de sentimiento diario | Gratis, sin clave | 1 vez cada hora (cambia 1 vez al día) |
| DefiLlama (stablecoins) | Capitalización de stablecoins (flujo de liquidez al mercado) | Gratis, sin clave | 1 vez al día |
| Deribit API pública | DVOL (volatilidad implícita de BTC/ETH) | Gratis | Cada 15–60 min; sube antes de eventos de volatilidad |
| Calendario macro (FOMC, CPI) | Fechas de eventos | Estático, cargado a mano o de fuente pública | Ventanas de bloqueo ±30 min |
| Binance data API pública (`data-api.binance.vision`) | Datos históricos de mercado | Gratis | Opcional para backtest; no la uses para decidir si ejecutas en otro exchange |

### 3.4 Noticias: ¿tiene sentido? Sí, pero como filtro de riesgo, no como señal

Primero, lo factual: **no existe una "API gratuita de Google News"** oficial (Google la retiró hace más de una década). Lo que sí existe son los feeds RSS de búsqueda de Google News (`news.google.com/rss/search?q=...`), no oficiales, sin límites documentados y que pueden cambiar sin aviso.

Opciones, a septiembre de 2026:

| Fuente | Estado | Límites / coste | Comentario |
|---|---|---|---|
| Google News RSS | No oficial | Sin documentar; respetar ≥5–10 min entre consultas | Bueno para titulares generales; frágil |
| RSS directos de medios (CoinDesk, Cointelegraph, The Block, Decrypt) | Gratis | Sin clave | Más fiable que Google News para cripto |
| GDELT DOC 2.0 | Gratis | Sin clave; uso razonable | Da "tono" agregado de cobertura; útil para detectar picos de atención |
| CryptoPanic API | Planes cambiantes | Verificar en su web antes de depender de ella | Históricamente útil (agrega y etiqueta noticias cripto) |
| CoinDesk Data API (antes CryptoCompare) | **Plan gratuito retirado el 21/05/2026** | De pago | Descartado |
| Anuncios del propio exchange | Gratis | — | **Muy relevante**: deslistados, mantenimientos y suspensiones de depósitos |

Por qué como filtro y no como señal:

- **Latencia**: una noticia relevante se incorpora al precio en segundos o minutos. Un bot que consulta RSS cada 5–10 min y luego llama a un LLM llega tarde a operar la noticia. Pero **no llega tarde para evitar abrir una posición** en un activo que acaba de sufrir un hackeo o un deslistado.
- **Uso recomendado**: un clasificador (reglas por palabras clave + LLM en la revisión periódica) que marca `event_flags` por moneda: `hack`, `delisting`, `regulatory`, `exploit`, `macro_event`, `unlock`. Estas flags bloquean nuevas entradas o reducen el tamaño. No generan compras.
- **Seguridad**: los titulares son texto externo no confiable. Van al LLM como **datos entrecomillados** en un campo concreto, con herramientas desactivadas y salida por esquema (§1.5). Nunca concatenados en las instrucciones.
- **Deduplicación**: el mismo hecho aparece en 20 medios. Agrupar por similitud de título y quedarse con uno; si no, el LLM sobrerreacciona a lo repetido.

### 3.5 Notificaciones: Telegram Bot API

| Aspecto | Detalle |
|---|---|
| Coste | Gratis |
| Alta | Crear bot con @BotFather → token; obtener tu `chat_id` |
| Límites | Del orden de 1 mensaje/s por chat y ~30 mensajes/s en total. De sobra; aun así, cola con reintentos y agrupación |
| Eventos a notificar (PRD) | Cierre de operación (par, resultado en $ y R, motivo, duración), paradas del bot, cambios de modo |
| Eventos a notificar (añadidos) | Watchdog (bot caído), fallo de reconciliación, error de autenticación de Claude o del exchange, resumen diario (equity, PnL, operaciones, llamadas a IA consumidas), token de Claude a punto de caducar |
| Comandos opcionales | `/status`, `/pause`, `/closeonly`, `/kill`, restringidos a tu `chat_id`. Sirven como control de emergencia desde el móvil |

### 3.6 Infraestructura (VPS)

| Opción | Coste | Pros | Contras |
|---|---|---|---|
| Oracle Cloud Always Free (ARM Ampere A1), región Madrid o Frankfurt | 0 € | Gratis, recursos sobrados | Oracle **redujo a la mitad** los límites gratuitos el 15/06/2026 (a 2 OCPU / 12 GB) sin anunciarlo, hay problemas de capacidad para crear instancias y puede reclamar instancias poco usadas. Fiabilidad como "producción 24/7": baja |
| VPS básico europeo (Hetzner, OVH, Contabo y otros) | ~4–6 €/mes | Estable, IP fija, UE | Coste (bajo) |
| Raspberry Pi en casa | Compra única + luz | Control total | Depende de tu conexión y tu corriente; IP doméstica dinámica (complica la whitelist de API) |
| Free tier de Google Cloud (e2-micro) | 0 € | Estable | Solo regiones de EE. UU. y 1 GB de RAM, justo para Node + Python + base de datos; IP de EE. UU. para una cuenta europea puede generar fricción con el exchange |

**Recomendación**: si quieres coste cero, prueba Oracle en región UE con un plan B preparado (despliegue reproducible con Docker Compose o un script de instalación, backups diarios de la base de datos fuera del VPS). Si la fiabilidad importa más que 5 €/mes, un VPS básico europeo. Requisitos mínimos: 1–2 vCPU, 2 GB de RAM, 20 GB de disco, Linux ARM64 o x86_64, IP fija, región UE.

Para el acceso al dashboard, **nunca lo expongas a Internet sin autenticación**: tiene botones que mueven dinero. Opciones gratuitas: Tailscale (VPN personal) o Cloudflare Tunnel con Cloudflare Access.

---
## 4. Cómo implementar las reglas de seguridad del PRD

Principio general: **cada regla dura se comprueba en al menos dos sitios** (defensa en profundidad), es código determinista con tests, vive en un fichero de configuración que la IA no puede modificar, y cualquier intento de violarla se registra como evento.

### 4.1 Pares permitidos (USDT/BTC → USDC/BTC)

- Como USDT no está disponible en exchanges MiCA, la regla pasa a ser **"solo pares contra USDC o contra BTC; nunca altcoin contra altcoin"**.
- **Recomendación: solo USDC.** Los pares contra BTC añaden una segunda exposición (ganas o pierdes también por el movimiento de BTC), tienen menos liquidez, mínimos por orden en BTC y complican medir el equity en dólares para el límite de 25 $. Si aun así quieres usarlos, el equity se convierte siempre a USDC con el precio medio BTC/USDC.
- Implementación: una `whitelist` explícita de símbolos en la configuración (p. ej. `BTC/USDC, ETH/USDC, …`). Se valida (1) al arrancar: si algún símbolo no cumple el patrón `X/USDC` o `X/BTC`, el bot no arranca; (2) en el generador de candidatos; (3) en el motor de riesgo; (4) justo antes de enviar la orden, como aserción final.
- **Selección de las 8 monedas**: no las elijas por narrativa, sino por liquidez en el exchange que uses. Criterios: par contra USDC disponible, spread medio < 0,05 %, volumen diario suficiente y profundidad hasta 0,5 % > 20× tu orden. Candidatas habituales para verificar: BTC, ETH, SOL, XRP, ADA, DOGE, LINK, AVAX. Recuerda que 8 monedas muy correlacionadas no son 8 apuestas independientes.

### 4.2 Límite de 25 $ (modo solo cierre por capital)

**Definición de capital** (sin esto la regla es ambigua):

```
equity = USDC libre
       + Σ (cantidad_posición × mejor bid)
       − Σ comisión estimada de salida de cada posición
       (+ BTC libre × precio BTC/USDC, si se usan pares BTC)
```

Se calcula cada 15 s con datos del exchange, no con la base de datos local.

**Disparo**: `equity ≤ 25,00 $` en dos lecturas consecutivas → `CLOSE_ONLY_CAPITAL` enclavado + Telegram + cancelación de las órdenes de entrada pendientes. Solo se sale con reset manual.

**Regla preventiva (la importante)**: el límite de 25 $ no debería alcanzarse nunca "por sorpresa". Una nueva operación solo se aprueba si, en el peor caso de que **todas** las posiciones abiertas y la nueva salten a su stop, el equity sigue por encima de 25 $ más un colchón:

```
equity − Σ riesgo_a_stop(abiertas) − riesgo_a_stop(nueva) − colchón(1 $) ≥ 25 $
```

**Umbrales intermedios propuestos** (no sustituyen la regla del PRD, la complementan): un 50 % de drawdown antes de reaccionar es mucho. Propongo reducir el riesgo por escalones:

| Equity | Acción |
|---|---|
| ≥ 45 $ | Normal |
| < 45 $ (−10 %) | Riesgo por operación a la mitad + Telegram |
| < 40 $ (−20 %) | Máximo 2 posiciones; revisión obligatoria de métricas |
| < 35 $ (−30 %) | Máximo 1 posición |
| ≤ 25 $ (−50 %) | `CLOSE_ONLY_CAPITAL` (regla del PRD) |

**Capital de referencia**: fija en la configuración `initial_capital = 50` y `floor = 25`. Si algún día depositas o retiras, el suelo no se recalcula solo: se cambia a mano y queda registrado.

### 4.3 Máximo 3 operaciones simultáneas

- **Cuentan las posiciones abiertas y también las órdenes de entrada pendientes**. Una orden limit de compra sin ejecutar ocupa un hueco; si no la cuentas, puedes acabar con 4–5 posiciones cuando se llenen a la vez.
- **Motor de riesgo de un solo hilo** (o con un lock): las decisiones se aprueban de una en una, para evitar que dos aprobaciones simultáneas vean "2 abiertas" y ambas pasen.
- Máximo 1 posición por símbolo, sin promediar.
- **Límite de correlación** (propuesto): como mucho 2 posiciones cuya correlación entre sí sea > 0,8 en 7 días; o, más sencillo, exposición total ponderada por beta frente a BTC ≤ 1,5× el equity.

### 4.4 Modo solo cierre (por capital o por cuota de IA)

Al entrar en cualquier `CLOSE_ONLY_*`:

1. Cancelar todas las órdenes de **entrada** pendientes (no las de protección).
2. Verificar que cada posición abierta tiene su OCO/stop activo en el exchange; si falta, crearlo.
3. Pasar la gestión de posiciones a reglas deterministas: trailing stop por ATR, time-stop, y salida inmediata a mercado si aparece una flag crítica (`hack`, `delisting`) para esa moneda.
4. Seguir actualizando dashboard, journal y Telegram.
5. En `CLOSE_ONLY_QUOTA`, sonda periódica a Claude para volver a `NORMAL` cuando haya cuota (salvo que otro modo más restrictivo siga activo).

Las OCO en el exchange hacen que, aunque el bot también se caiga, lo abierto se cierre en su stop o su objetivo. Es la garantía que el PRD busca con "reglas simples sin IA", sin depender de que el proceso siga vivo.

### 4.5 Límites adicionales recomendados

| Límite | Valor inicial propuesto | Motivo |
|---|---|---|
| Riesgo por operación | 1 % del equity (~0,50 $) | Sobrevivir a rachas de 10+ pérdidas |
| Pérdida máxima diaria | 3 $ (6 %) → `CLOSE_ONLY_DAILY` hasta las 00:00 UTC | Cortar días malos y el *tilt* del propio sistema |
| Operaciones máximas al día | 6 | Arrastre de comisiones (§2.2) |
| Cooldown tras stop-loss | 2 h en ese símbolo | Evitar reentrar en el mismo error |
| Pausa tras 3 pérdidas seguidas | 4 h | Cambio de régimen probable |
| Exposición máxima | 90 % del equity | Colchón para comisiones y redondeos |
| Entrada con spread > 0,10 % | Prohibida | Coste oculto |
| Promediar a la baja / martingala | Prohibido | Error clásico |
| Llamadas a Claude | 40/día, 8 por ventana de 5 h | Proteger tu cuota personal |
| Desviación de USDC > 1,5 % | Congelar entradas | Riesgo de stablecoin |

### 4.6 Slider de agresividad

El slider es un parámetro humano en un bot "sin humano en el bucle", y eso está bien siempre que **no pueda tocar los límites duros**. Propuesta de 5 niveles:

| Nivel | Riesgo/op. | Confianza calibrada mínima | Máx. op./día | Setups permitidos |
|---|---|---|---|---|
| 1 Conservador | 0,5 % | 0,70 | 3 | Solo pullback en tendencia |
| 2 | 0,75 % | 0,65 | 4 | + reversión en rango |
| 3 Normal | 1,0 % | 0,60 | 6 | Todos |
| 4 | 1,25 % | 0,57 | 7 | Todos |
| 5 Agresivo | 1,5 % | 0,55 | 8 | Todos |

Límites duros invariables en cualquier nivel: 3 posiciones, 25 $, pares, pérdida diaria, sin apalancamiento. Cada cambio se registra y **se aplica desde el día siguiente** (o tras un enfriamiento de X horas), para que no se use para "recuperar" pérdidas en caliente.

### 4.7 Cómo verificar que las reglas se cumplen

- **Tests unitarios** del motor de riesgo para cada regla.
- **Tests basados en propiedades** (librería `hypothesis` de Python): generar miles de secuencias aleatorias de eventos (fills, rechazos, reinicios, cambios de modo) y comprobar invariantes: nunca > 3 posiciones + entradas pendientes, nunca orden sobre un par fuera de la whitelist, nunca orden de entrada en modo solo cierre, nunca tamaño > riesgo permitido.
- **Tests de caos** en el entorno demo: matar el proceso a mitad de una orden, simular `You've hit your session limit`, cortar el WebSocket, desfasar el reloj, devolver JSON inválido del LLM.

---

## 5. Interfaz visual en tiempo real

### 5.1 Arquitectura de la UI

- **La UI es un modelo de lectura.** Nunca habla con el exchange ni con Claude. Lee el estado del bot y envía **comandos** a su API, que pasan por el motor de riesgo como cualquier otra decisión y quedan auditados (quién, cuándo, qué, resultado).
- **Backend**: FastAPI (Python, el mismo proceso u otro servicio) con endpoints REST para instantáneas (`GET /state`, `/trades`, `/hypotheses`, `/decisions?symbol=…`) y un **WebSocket de eventos** (`/ws`) que emite deltas tipados (`equity_update`, `decision`, `order`, `fill`, `mode_change`, `node_status`, `hypothesis_update`).
- **Patrón de sincronización**: al conectar, el cliente pide una instantánea completa y luego aplica deltas con número de secuencia; si detecta un hueco en la secuencia, vuelve a pedir la instantánea. Así la UI nunca muestra un estado inconsistente tras una desconexión.
- **Frecuencia**: agregar y emitir a 1–2 Hz como máximo. Más es gasto de CPU sin valor visual, y en un VPS gratuito importa.
- **Frontend**: SPA compilada (React + Vite o Svelte) servida como estáticos por FastAPI. Librerías útiles: **React Flow (`@xyflow/react`)** para el diagrama por nodos, **Lightweight Charts** (de TradingView, open source) para precios y curva de equity, y una librería de tablas ligera para el histórico.
- **Sobre Streamlit**: es tentador porque ya lo conoces, pero su modelo de re-ejecutar el script entero no encaja con un dashboard de push en tiempo real con un diagrama de nodos animado. Sirve para una v0 de solo lectura; para la interfaz del PRD, mejor una SPA.
- **Indicador de frescura**: cada panel muestra "actualizado hace X s" y un banner rojo si el WebSocket cae. Una UI que muestra datos viejos como si fueran actuales es peor que no tener UI.
- **Acceso**: Tailscale o Cloudflare Tunnel + Access (§3.6). Diseño responsive, porque la mayoría de veces lo mirarás desde el móvil.

### 5.2 Paneles

| Panel | Contenido | Fuente | Frecuencia |
|---|---|---|---|
| **Barra de estado** | Equity, PnL del día ($ y %), drawdown desde el máximo, **barra de distancia al suelo de 25 $**, operaciones hoy / límite, posiciones abiertas / 3, **badge de modo** (`NORMAL`, `CLOSE_ONLY_QUOTA`…), llamadas a Claude hoy / presupuesto y último error, latencia del exchange | `equity_snapshots`, `mode_changes`, `llm_calls` | 1 Hz |
| **Slider de agresividad** | Nivel actual, nivel programado para mañana, qué cambia en cada nivel (tabla §4.6) | Config | Bajo demanda |
| **Flujo de datos por nodos** | Ver §5.3 | `node_status` | 1–2 Hz |
| **Qué está pensando la IA** | Línea temporal de decisiones: resumen de la entrada (candidatos, contexto), salida (decisión, razones, riesgos, candidatos rechazados), **veredicto del motor de riesgo** (aprobado / vetado y por qué) y la orden resultante. Filtro por moneda. Enlace a la entrada completa | `decisions`, `llm_calls`, `risk_verdicts` | Por evento |
| **Controles de seguridad** | Pausar entradas, forzar solo cierre, cerrar todo (doble confirmación), kill switch; límites vigentes en solo lectura; estado del token de Claude (días hasta caducar) | API de comandos | Por evento |
| **Posiciones abiertas** | Par, entrada, precio actual, stop, objetivo, PnL no realizado en $ y R, edad, EV restante, estado de la OCO en el exchange | `positions` | 1 Hz |
| **Histórico de operaciones cerradas** | Entrada / salida, PnL en $ y en R, comisiones, duración, setup, confianza de la IA, motivo de salida; **exportación CSV fiscal** | `trades` | Por evento |
| **Curva de equity comparada** (añadido) | Equity real vs baseline sin IA (papel) vs "hold BTC" desde el día 1 | `equity_snapshots`, simulación baseline | 1/min |
| **Hipótesis en curso** | Enunciado, condición, métrica, progreso de muestra (n / min_n), valor actual con intervalo de confianza, fecha límite | `hypotheses`, `hypothesis_observations` | Por evento |
| **Aprendido** | Reglas validadas con **confianza calculada** (no la del LLM), fecha de validación, veces aplicada, rendimiento reciente, estado (activa / en revisión / retirada) | `hypotheses` | Por evento |

Sobre el panel "qué está pensando la IA": lo que se muestra es la **justificación que el modelo escribe en su salida**, no su razonamiento interno. Conviene etiquetarlo así en la UI para no darle más autoridad de la que tiene. La columna "veredicto del motor de riesgo" es la más útil del panel: enseña cuántas veces la IA propuso algo que las reglas bloquearon, y por qué.

### 5.3 Diagrama de flujo en vivo

Dos vistas en la misma pestaña:

1. **Vista de sistema** (nodos fijos): `Exchange WS` → `Features` → `Filtros` → `Candidatos` → `Claude` → `Riesgo` → `Ejecución` → `Posiciones` → `Journal`, con nodos laterales `Contexto`, `Noticias`, `Telegram`, `Watchdog`. Cada nodo muestra estado (verde OK, ámbar degradado, rojo error, gris inactivo, por ejemplo Claude gris en `CLOSE_ONLY_QUOTA`), la hora del último evento, el throughput y la latencia. Las aristas se animan cuando pasa un mensaje.
2. **Vista por moneda** (la más informativa): 8 filas, una por moneda, y columnas por etapa. Cada fila indica dónde se quedó esa moneda en el último ciclo: "descartada por spread", "candidato", "esperando IA", "vetada por correlación", "posición abierta"… Así se ve de un vistazo **por qué el bot no está operando**, que es la pregunta que más te vas a hacer.

Implementación: el backend mantiene un diccionario `node_status` que actualiza cada componente, y lo emite agregado a 1–2 Hz. React Flow pinta nodos y aristas a partir de ese JSON; no hace falta lógica en el frontend.

---

## 6. Hoja de ruta para la construcción con Claude Code

| Fase | Entregable | Criterio para avanzar |
|---|---|---|
| 0. Decisiones | Exchange elegido y cuenta verificada vía API, quote (USDC), 8 monedas, VPS, presupuesto de llamadas | Cuenta operativa con clave de API trade-only e IP whitelist |
| 1. Datos | Ingesta WS + REST, almacenamiento, detector de datos obsoletos | 72 h sin huecos ni caídas |
| 2. Features + baseline | Indicadores, filtros, generador de candidatos, motor de riesgo, baseline sin IA en papel | Tests de propiedades en verde; baseline generando operaciones de papel coherentes |
| 3. IA en sombra | Analista Claude con esquema, presupuesto de llamadas, detección de cuota, máquina de modos | 1 semana sin salidas inválidas no controladas; consumo de cuota medido |
| 4. Ejecución demo | Órdenes en el entorno demo del exchange, OCO, idempotencia, reconciliación, tests de caos | 1 semana en demo sin descuadres |
| 5. UI + Telegram | Dashboard completo, watchdog, notificaciones | Todos los paneles alimentados con datos reales |
| 6. Papel largo | IA vs baseline vs hold BTC con datos en vivo | 2–4 semanas; decisión con métricas |
| 7. Dinero real | 50 $, nivel de agresividad 1–2 | Revisión semanal de métricas |
| 8. Aprendizaje | Registro de hipótesis, evaluación en sombra, aplicación acotada | Solo con ≥100 operaciones registradas |

Stack sugerido: Python 3.12, `ccxt` (con su soporte WebSocket), `asyncio`, `pydantic` para esquemas, `pandas` para features (lo dominas; `polars` si hace falta rendimiento), SQLite en modo WAL, FastAPI, `python-telegram-bot` o `aiogram`, `pytest` + `hypothesis`, systemd (o Docker Compose) y backups diarios de la base de datos fuera del VPS.

Estructura de repositorio orientativa:

```
ploutos/
  config/            # settings.yaml (límites duros, whitelist, slider), .env (secretos, NO en git)
  core/              # modos, eventos, reloj, logging
  data/              # ingesta WS/REST, store, validación
  features/          # indicadores, régimen, microestructura
  strategy/          # filtros, candidatos, baseline sin IA
  ai/                # prompt, schema.json, invocación claude -p, parser de errores de cuota
  risk/              # motor de riesgo (sin dependencias de ai/)
  execution/         # órdenes, OCO, idempotencia, reconciliación
  portfolio/         # gestor de posiciones, coste de oportunidad
  learning/          # hipótesis, evaluación estadística
  notify/            # telegram, watchdog
  api/               # FastAPI + WS
  ui/                # SPA
  tests/             # unit, property-based, chaos
  claude_runtime/    # directorio vacío desde el que se ejecuta claude -p
```

Detalle importante para Claude Code: `risk/` **no debe importar nada de `ai/`**. Si el motor de riesgo depende del módulo de IA, un fallo de la IA puede tumbar la seguridad.

---

## 7. Decisiones pendientes para ti

1. **Exchange**: ¿OKX EU (recomendado), Bitvavo, o asumes el riesgo de Binance?
2. **Quote**: ¿solo USDC (recomendado) o USDC + BTC?
3. **Claude**: ¿suscripción con presupuesto de llamadas (recomendado para empezar) o API de pago con tope?
4. **VPS**: ¿Oracle gratuito con plan B, o VPS europeo de ~5 €/mes?
5. **Umbrales intermedios** de drawdown (§4.2) y **límite diario** (§4.5): ¿los adoptas?
6. **Frecuencia objetivo**: ¿aceptas 1–5 operaciones/día en lugar de 10–20?
7. **Fase de papel**: ¿2–4 semanas antes del dinero real? (Pendiente §9 del PRD.)

---

## 8. Fuentes

**Claude Code: términos, autenticación y modo headless**
- [Claude Code — Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)
- [Claude Code — Authentication (setup-token, CLAUDE_CODE_OAUTH_TOKEN)](https://code.claude.com/docs/en/authentication)
- [Claude Code — Run programmatically (claude -p, --json-schema, bare mode)](https://code.claude.com/docs/en/headless)
- [Claude Code — Error reference](https://code.claude.com/docs/en/errors)
- [Claude Code — CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Zylos Research — Subscription auth boundaries and ToS-compliant automation (07/2026)](https://zylos.ai/research/2026-07-13-subscription-auth-boundaries-official-cli-agent-automation/)
- [Build This Now — Claude Code usage limits 2026](https://www.buildthisnow.com/blog/models/claude-code-usage-limits-2026)

**Binance, MiCA y USDT en la UE**
- [CoinDesk — Binance tells EU users it will no longer provide services (26/06/2026)](https://www.coindesk.com/policy/2026/06/26/binance-tells-eu-users-it-will-no-longer-provide-services-after-failing-to-secure-mica-license)
- [Euronews — Binance to halt crypto services across EU (25/06/2026)](https://www.euronews.com/business/2026/06/25/binance-to-halt-crypto-services-across-eu-countries-after-failing-to-secure-mica-approval)
- [Tangem — Binance exits EU as Spain enforces MiCA deadline](https://tangem.com/en/news/regulation/29641-binance-exits-eu-crypto-market-as-spain-enforces-mica-deadline/)
- [Zyphe — Binance MiCA licence status (actualizado 18/09/2026)](https://www.zyphe.com/resources/news/binance-mica-licence-eu-lockout-july-2026)
- [The Cryptonomist — Binance EU MiCA licensing (08/09/2026)](https://en.cryptonomist.ch/2026/09/08/binance-eu-mica-licensing/)
- [ELLIPAL — Binance suspended EU services under MiCA](https://www.ellipal.com/blogs/news/binance-eu-suspension-mica-self-custody)
- [Bit2Me News — Is Binance compliant with MiCA?](https://news.bit2me.com/en/Binance-compliant-with-Mica-exit-EU-July-2026/)
- [SpazioCrypto — MiCA-authorized exchanges, CASP list July 2026](https://en.spaziocrypto.com/regulation/mica-authorized-exchanges-casp-list-july-2026/)
- [LeoDex — USDT delisted in Europe](https://leodex.io/learn/delistings/usdt-delisted-europe)

**Exchanges: comisiones y límites**
- [OKX Europe — Upcoming spot fee adjustment EEA](https://www.okx.com/en-eu/help/important-notice-upcoming-spot-fee-adjustment-eea)
- [Bybit EU — Trading fee structure](https://www.bybit.eu/en-EU/help-center/article/Trading-Fee-Structure)
- [Kraken — Fee schedule](https://www.kraken.com/features/fee-schedule)
- [MEXC Learn — Kraken fees 2026, tier change 9 July 2026](https://www.mexc.com/en-GB/learn/article/kraken-fees-explained-2026-the-9-july-2026-tier-change-that-doubled-kraken-entry-taker-rate-to-0-80-/1)
- [Kraken — Spot REST rate limits](https://docs.kraken.com/api/docs/guides/spot-rest-ratelimits)
- [Bitvavo — Fees](https://bitvavo.com/en/fees)
- [Bitvavo API — Rate limits](https://docs.bitvavo.com/docs/rate-limits/)
- [Binance — Spot API limits](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits)
- [Binance — Filters](https://developers.binance.com/docs/binance-spot-api-docs/filters)

**Datos, noticias y notificaciones**
- [CoinGecko API — Pricing](https://www.coingecko.com/en/api/pricing)
- [CoinDesk Data — Changes to free tier access](https://data.coindesk.com/blogs/changes-to-coindesk-data-indices-api-free-tier-access)
- [CryptoPanic — API plans](https://cryptopanic.com/developers/api/plans)
- [FiveFilters — Google News RSS feeds](https://www.fivefilters.org/2021/google-news-rss-feeds/)
- [GDELT — DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [Telegram — Bots FAQ](https://core.telegram.org/bots/faq)

**Infraestructura**
- [InfoQ — Oracle quietly halves free tier Ampere A1 limits (07/2026)](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)
- [Oracle — Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

**Evidencia sobre trading con LLM**
- [iWeaver — Alpha Arena Season 1 results](https://www.iweaver.ai/blog/alpha-arena-ai-trading-season-1-results/)
- [Protos — LLM crypto trading contest finds LLMs can't trade crypto](https://protos.com/llm-crypto-trading-contest-finds-llms-cant-trade-crypto/)
- [arXiv 2510.11695 — When Agents Trade: live multi-market trading benchmark for LLM agents](https://arxiv.org/pdf/2510.11695)
- [Papers With Backtest — Look-ahead bias in LLM trading](https://paperswithbacktest.com/course/look-ahead-bias-llm-trading)

**Fiscalidad (España)**
- [Rankia — Fiscalidad de las criptomonedas en España 2026](https://www.rankia.com/blog/irpf-declaracion-renta/3761495-fiscalidad-criptomonedas-tributacion-bitcoin)
- [Waltio — DAC8 y Hacienda](https://www.waltio.com/es/blog/fiscalidad/dac8-y-criptomonedas/)

*Este informe no es asesoramiento financiero, legal ni fiscal. Las comisiones, los límites de las APIs y la situación regulatoria cambian con frecuencia: verifícalos en las fuentes oficiales antes de construir.*
