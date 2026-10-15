# Ploutos — memoria del proyecto

Bot de trading **spot** de cripto, 100 % autónomo, 50 $ de capital, decisiones asistidas
por Claude vía `claude -p`, dentro de reglas deterministas que la IA **no puede modificar**.

Éxito = (1) las reglas duras se cumplen siempre, (2) trazabilidad total de cada decisión,
(3) saber con datos si la IA aporta ventaja sobre un baseline sin IA. **La rentabilidad es secundaria.**
**Cambio aprobado (el propietario, 09-11/10), aun sin aplicar:** el objetivo pasa a ser ganar dinero con L (`docs/archivo/propuesta-prd-v3.md`);
se aplica solo si L pasa su papel (11/01/2027) y el propietario decide. Hasta entonces manda el PRD v2.

**Este fichero es el resumen.** El detalle de cada decision y hallazgo hasta el 06/10/2026 esta en
`docs/historial-claude-md.md` (copia integra del CLAUDE.md anterior): buscar ahi antes de re-decidir o re-medir.

## Jerarquía de documentos

1. `docs/archivo/prd-ploutos-v2.md` — **fuente de verdad**.
2. `docs/informe-ploutos.md` — el *cómo*. Solo manda donde el PRD calla.
3. Si ninguno lo cubre y afecta a riesgo, dinero o reglas duras → **preguntar al propietario**, no decidir.

Resuelto a favor del PRD (no re-litigar): solo `X/USDC` (nada de `X/BTC`); tope de **6** op./dia aunque el informe
diga 7-8; papel de **2-3 semanas**.

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
`CLOSE_ONLY_CAPITAL`, `HALTED` (y `CLOSE_ONLY_MANUAL`, la pausa de Telegram). El efectivo es **el más restrictivo**.
`CLOSE_ONLY_CAPITAL` es enclavado. Al entrar en cualquier `CLOSE_ONLY_*`: cancelar entradas pendientes,
verificar/crear la OCO de cada posición, gestionar con reglas deterministas, notificar.

**Papel de la IA** (PRD §6): analista, no operador. Elige entre candidatos ya filtrados por código,
puntúa y justifica. No emite órdenes, no crea pares, no toca límites. Solo puede **reducir** el tamaño
(`size_multiplier` ∈ [0,5; 1,0]). Salida inválida o timeout = **no hacer nada**.
Las noticias son solo filtro de riesgo, nunca señal de compra, y son texto no confiable. La IA no lee titulares,
salvo en el embudo de noticias de L, en sombra (el propietario, 11/10: `docs/diseno-embudo-noticias.md`).

## Estructura

```
config/   settings.yaml (limites duros, whitelist, slider); .env NO en git
core/     modos, eventos, reloj, logging, secretos, salud (DEGRADED)
data/     ingesta WS/REST, store (+ migraciones), validacion, cobertura, usdc, news
features/ indicadores, regimen, correlaciones, paridad de USDC, noticias
strategy/ costes, filtros, setups, candidatos, pipeline, baseline sin IA
ai/       contrato, parser, prompt, presupuesto, cuota, invocacion, decisor   [solo en ploutos-paper-ai]
risk/     motor de riesgo: 19 reglas, sizing, limites, equity
execution/ ids, guardia, peticiones, ordenes, OCO, conciliacion, ejecutor, juez [fase 4]
portfolio/ simulador de papel, bucle compartido, persistencia, juez de papel
notify/   avisos de Telegram, comandos, latidos a Healthchecks
api/ ui/  el panel     learning/  vacio (fase 8)
scripts/  servicios, jueces, verificaciones, recorridos     deploy/ instalacion, systemd, copias, sync
tests/    unit, property-based     docs/estudios/  estudios con la historia (no tocan el bot)
claude_runtime/  directorio VACIO desde el que se ejecuta claude -p
```

## Invariantes de arquitectura (hay tests que las comprueban con AST)

- **`risk/` no importa NADA de `ai/`.** `core`, `data`, `features`, `strategy` y `portfolio` tampoco: la IA entra
  en el bucle pasada desde fuera. `features/` no importa `strategy/`, `risk/` ni `ai/`; `strategy/` no importa `execution/`.
- **El simulador (`portfolio/paper.py`) no importa `strategy`, `features` ni `ai`**. El bucle (`portfolio/loop.py`) si encadena capas.
- **La ingesta y el bucle del BASELINE no importan `ai/`**: el grupo de control no depende de la IA ni para arrancar.
- El CLI de Claude con **`DISABLE_UPDATES=1`** y version fija (`ai.invoke.VERIFIED_VERSION`), SOLO en la llamada del
  bot (con esa variable el instalador no instala nada y dice que si).
- El estado verdadero es el del **exchange** (reconciliacion al arrancar y cada 5 min).
- Cada regla dura se comprueba en **al menos dos sitios**. Indicadores **solo sobre velas cerradas**.
- `deploy/*.sh`, `*.service` y `*.timer` **sin CRLF** (hay test).
- El panel solo sale a la red desde `api/cambio.py` (USDC/EUR del CSV fiscal; hay test).

## Convenciones de trabajo

- **Por fases** (PRD §12). Al terminar una: parar, ensenyar que hay, como se prueba y si se cumple el criterio. No
  empezar la siguiente sin OK del propietario; comprobar que la anterior esta cerrada DE VERDAD, preguntando.
- **Stack:** Python 3.12, `ccxt` (fijada en `pyproject.toml`), `asyncio`, `pydantic`, `pandas`, SQLite en WAL,
  `pytest` + `hypothesis`, FastAPI + uvicorn (panel). Dependencia nueva = justificarla antes.
- **Python: `.venv/Scripts/python.exe`** (en el VPS, `.venv/bin/python`). Con `py -3.12` falla `pydantic`.
- **Configuracion** en `config/settings.yaml`, validada con pydantic: invalida → **el bot no arranca**.
- **Secretos:** solo en `.env` (en `.gitignore`; `.env.example` sin valores). Nunca en logs ni en el chat: el propietario los
  pone el mismo y **nunca se le pide que pegue un token**. **Nunca `source .env`** (lo ejecuta como shell). Leerlos con
  `core.secrets.Secrets`; los errores de Telegram pasan por `core.secrets.scrub_url`. Ningun test ve credenciales
  ni sale a la red (`tests/conftest.py`).
- **`ruff`** (0.16.9, solo en el portatil; E9, F, B) como un test mas (`tests/unit/test_ruff.py`).
- **Tests primero en `risk/`**; antes de dar por bueno un cambio ahi, `scripts/mutation_check.py` (16/16 en rojo).
- **Mirar el resultado de pytest ANTES de hacer el commit.** Push al acabar cada encargo; directorio siempre en `main`.
- **Formato de commit (fijo).** Las secciones opcionales se omiten ENTERAS si no aplican.

  ```
  <ambito>: <que se ha hecho, en minuscula, max 72 caracteres>

  QUE CAMBIA
  - una linea por pieza tocada, en orden de importancia

  POR QUE
  Parrafo corto. Si corrige algo, primero el sintoma y luego la causa.

  HALLAZGOS                  (opcional)
  1. ...

  MEDIDO                     (opcional: los numeros, con el tamanyo de la muestra)

  TESTS: N en verde | mutacion: 16/16      (la mutacion solo si se toco risk/)

  Co-Authored-By: <el modelo que hace el commit> <noreply@anthropic.com>
  ```
  Ambitos: `fase N`, `deploy`, `docs`, `fix`, `tests`. En Windows, el mensaje con `git commit -F <fichero>`.

- **Trazabilidad:** timestamp UTC y `decision_id` (= el `cid` de la IA) de candidato a cierre.
- **Dinero:** solo papel y el demo de OKX hasta la fase 7. Nunca se envia una orden de margen.
- **No anyadir funcionalidades** fuera del PRD: decirselo al propietario con argumentos.
- **Verificar, no suponer** lo que dependa de una API real.
- **El patron que mas ha costado:** codigo escrito, probado y SIN ENCHUFAR. Comprobar que alguien lo llama en el
  camino que corre. Un criterio sin juez automatico no es un criterio.
- **Estudios con la historia** (`docs/estudios/`): el criterio se fija y se sube ANTES de medir; exploracion USDT
  12/2020-06/2024; **la reserva (07/2024-08/2025) sin bajar**, una sola vez al final.
- **Durante la muestra de la fase 6** nada cambia el camino de decision sin decirlo (huella `f063d80147a9`; un cambio
  parte la muestra en tramos).
- **Imagen:** en el panel, Telegram y la web **nunca se nombra a Claude**: "la IA" o "el analista" (hay test).
  Telegram, codigo, logs, commits y este fichero, en castellano.
- Avisar al propietario antes de parar `ploutos-exec` (Healthchecks avisa a los ~20 min).

## Verificado (no re-suponer)

Detalle en `docs/hallazgos-*.md`, `docs/preparacion-fase-4.md` y `docs/historial-claude-md.md`.

**OKX**
- **Cuentas EU: `hostname: eea.okx.com`** (con `www.okx.com`, `50119` con cualquier clave). `50119` = host, IP fuera
  de la lista o clave mal copiada (no dice cual); `50101` = clave de un entorno contra el otro; **`50123` = moneda no
  permitida en la clave** (comprobar tambien la de cotizacion al crear la real). 403 al User-Agent de Python.
- **La whitelist vive en DOS sitios:** `settings.yaml` y la clave de OKX (por moneda base). Si cambia una, la otra.
- Minimo por orden = `minSz` x precio (BTC ~8,6 $): por eso **no hay salidas parciales**.
- **Comisiones de la cuenta (spot, Regular, desde el 25/09): maker 0,10 %, taker 0,20 %**, en `settings.yaml`; las de
  ccxt no son las reales. `GET /api/v5/account/trade-fee`: signo al reves y, contra USDC, `takerUSDC`/`makerUSDC`.
  Va por GRUPO de instrumento: en el demo NEAR (grupo 13) paga 0,20/0,35 %; en la real las de USDC son grupo 12.
  **Si las reales de un par son MAS CARAS que las configuradas, ese par no se opera** (el ejecutor lo mira al arrancar).
- **ccxt redondea el precio AL MAS CERCANO:** antes, `execution/precios.al_tick` (entrada hacia abajo, stop y objetivo
  hacia el lado seguro). El equity lee el USDC TOTAL (`eq`), nunca el `free`.
- **OCO:** ccxt la manda con `tdMode: cross` (margen): siempre `tdMode: cash`. `clOrdId` alfanumerico <= 32 y unico
  solo entre pendientes. La adjunta a la entrada nace al llenarse ENTERA (a medias, al cancelar el resto). **El
  objetivo no puede ser limit en spot (`51094`): sale a mercado, taker**; el papel y la M1 lo cobran maker (~0,03 R
  optimista por objetivo; se corrige tras el veredicto de la fase 6). `51279`: TP por debajo del ultimo precio.
  `tradeQuoteCcy: "USDC"` explicito (el "Unified USD Orderbook": `X/USD` en pantalla = `X-USDC`).
- **OKX retiro `BTC/USD` el 30/09/2026**; un par que no existe responde `50013` ("busy"), no `51001`.
- **El demo:** solo 5 de los 8 contra USDC (BTC, ETH, SOL, DOGE, NEAR); ticks 10x mas gruesos; el `last` casi no se
  mueve; el deslizamiento no sirve. Fondos por defecto de OKX (de ahi el saldo virtual).
- `watch_ohlcv` devuelve SOLO la vela en curso: el cierre lo decide el secuenciador, no el reloj.
- `account/trade-fee` tiene limite por clave: dos procesos a la vez dan `429`/`50011` (03/10; con uno no pasa).
- Anuncios oficiales: API publica `/api/v5/support/announcements`.

**`claude -p` (v2.1.266, congelada hasta el veredicto de la fase 6)** — `docs/hallazgos-claude-cli.md`
- `--json-schema` EN LINEA; no hay `--max-turns`; las herramientas vienen ENCENDIDAS: `--restricted
  --disable-slash-commands --strict-mcp-config --setting-sources '' --no-session-persistence`, desde
  `claude_runtime/`, con `< /dev/null`. `--bare` no sirve con la suscripcion. Salida en `structured_output`; el
  esquema no impide un `cid` inventado (lo para `ai/parser.py`).
- ~0,075 $ equivalentes por llamada (cuota, no dinero), 10-50 s; 230-500 MB de memoria. Decide `claude-sonnet-5`.
- Token verificado sin sesion; caduca ~22/09/2027 (`claude.token_expires_on`, aviso 14 dias antes).

**Mercado y estrategia** — `docs/hallazgos-fase-2.md`, `docs/estudios/`
- **4 h**, stop 1,9xATR (~3,3 %), posiciones de ~15 $ (tope 20 $). **Operaciones de horas (1 h), medidas el 06/10:
  pierden** (-0,12/-0,13 R; las comisiones, hasta el 165 % del bruto).
- **El baseline pierde en un anyo USDC** (08/2025-09/2026: -0,38 R, de 50 a 37,74 $). En la exploracion de 3,5 anyos,
  +0,12 R (objetivo taker) con IC que incluye el 0: gana cuando sube, pierde cuando baja. Primera ronda (5 ideas) y
  cortos: ninguna pasa. La reversion pierde siempre. **07/10, ideas C y D en la exploracion: no pasan**
  (`docs/estudios/segunda-ronda/`): el time-stop de 18 velas empeora (-0,01 R, corta posiciones que iban ganando);
  sin la reversion, +0,28 R (IC +0,10 a +0,48, no llega a +0,13; sigue perdiendo en 2022). **08/10, 2 + D (tendencia
  de BTC y sin reversion): no pasa por dos milesimas** (taker +0,36 R, IC +0,128 a +0,616; maker si pasa; 256 op.,
  116 $ frente a 124 $ de la referencia). **08/10, A' (cortos de mercado bajista): no pasa** (166 cortos a +0,06 R,
  IC -0,18 a +0,28; ganan en 2022 y pierden en los giros). **08/10, Kronos (modelo de prediccion de velas) en el anyo
  USDC: no acierta** (Spearman -0,04 a 24 h, 2 de 8 monedas positivas; `docs/estudios/kronos/`). Ninguna estrategia
  ha pasado todavia: sin eso no hay fase 7. **2 + D, guardada como CANDIDATA** (el propietario, 09/10), sin llevarla a la reserva.
  **09/10, idea I (stop a +1 R tras +2 R) sobre 2 + D: empeora** (+0,36 -> +0,21 R; lo que sale pronto deja hueco a
  operaciones que pierden, como el time-stop). **09/10, tendencia (`docs/estudios/tendencia/`): F (rotacion semanal)
  50 -> 290 $, caida 50 %, Sharpe 1,30, falla 2022 (-34 %) y el Sharpe deflactado por poco (0,942); H (BTC + ETH con
  el filtro de BTC) 50 -> 130 $, caida 42 %, Sharpe 1,00, 2022 +2 %, falla solo el deflactado (0,84).** BTC mantenido:
  +226 %, caida 77 %, Sharpe 0,84. Ninguna pasa; la reserva, sin tocar. **La combinacion J (un tercio a cada una):
  50 -> 179 $, caida 30 %, Sharpe 1,32, 2022 -16 %; falla solo el deflactado (0,939).** Las cuatro candidatas
  (2 + D, F, H, J) se quedan en 0,84-0,94: con 3,5 anyos no se distingue de la suerte; decidiria la reserva.
  **09/10, F en la RESERVA (el propietario la eligio): NO PASA** (+20,5 % frente a +79 % de BTC mantenido; caida 33,6 %, mas
  que BTC). F descartada. **La reserva queda GASTADA.** Queda sin ver para 2 + D el anyo USDC. **10/10, segunda tanda (`docs/archivo/diseno-tendencia-2.md`), en la exploracion ampliada 12/2020-08/2025: PASAN L (rotacion
  con 4 plazos: 50 -> 421 $, caida 44,5 %, Sharpe 1,46, deflactado 0,978) y M (mitad K, mitad 2 + D: caida 23 %); no
  pasan H, 2 + D ni K. L va al anyo USDC (la reserva nueva); buena parte de L viene de 12/2020-05/2021.** **10/10, el anyo USDC (01/09/2025-27/09/2026, calentado en USDT): NO PASA NINGUNA** (L -6,9 %, caida 20,5 %; M -0,02 %,
  caida 13 %; BTC -22,3 %, caida 53 %): protegen, pero pierden. 2 + D +3,1 % (solo informacion). No queda ninguna prueba
  limpia del pasado. **Robustez de L (10/10, `docs/estudios/tendencia/robustez-l.md`): SOLIDA** (12 de 12 variantes pasan en la
  exploracion; L queda en medio; en el anyo USDC la familia va de -7 a +13 %: cifras inciertas, idea solida).
- La profundidad nunca ata con 15 $; **el spread si**. Historia contra USDC desde el 20/08/2025; contra USDT, anyos.

## Decisiones del propietario (resumen; detalle en `docs/historial-claude-md.md` y en cada documento)

- **Whitelist** (22/09): `BTC, ETH, SOL, XRP, DOGE, AVAX, TRX, NEAR`. **Revisada el 09/10: se queda como esta, con
  LINK como primera alternativa** (`docs/archivo/decision-whitelist-0910.md`: las 8 pasan; LINK y NEAR empatadas). Un cambio
  se aplicaria tras el veredicto de la fase 6 y cambiaria tambien la clave de OKX.
- **Dimensionado** (22/09): 1 % de riesgo, ~15 $, tope 20 $, velas de 4 h. **Regla 4 en 3** (28/09).
- Reversion con stop propio bajo el suelo del rango; correlacion sin medir = correlacionada (22/09).
- **Regla 17, solo con A** (`USDC/USDT x USDT/USD`) y aviso de Telegram al cambiar (01/10).
- **Fase 3** (`docs/archivo/plan-fase-3.md`): Sonnet; solo con candidatos nuevos; cartera de papel propia; solo `open`/`skip`;
  suscripcion; sin noticias. La IA en servicio aparte con protecciones de memoria; tras una parada, solo la ultima
  vela; presupuesto agotado = `CLOSE_ONLY_QUOTA`.
- **Noticias** (`docs/diseno-noticias.md`): servicio propio, solo anuncios de OKX, mismas flags para las dos carteras;
  flag critica con posicion = vender a mercado; deslistado: vende, avisa y el propietario decide. **Medios en sombra: la RECOGIDA
  adelantada al 07/10** (el propietario, opcion A; `docs/diseno-medios-sombra.md`): 24 RSS, clasificador de OKX tal cual, se
  juzgan UNA vez tras el veredicto de la fase 6 con el criterio ya escrito. Nunca senyal de compra (PRD 6).
- **Comandos de Telegram** (`docs/diseno-comandos-telegram.md`): `/status`, `/pause` (`/closeonly`), `/kill`,
  `/resume`; desde el movil solo se levanta la pausa (`/si` en 60 s); siempre las dos carteras; "cerrar todo" no va.
- **Vigilante:** Healthchecks.io, latido solo cuando va bien de verdad (`notify/latido.py`).
- **Actualizaciones** (`docs/propuesta-actualizaciones.md`): reinicio a las 07:15 UTC solo si un parche lo pide;
  revision los domingos 07:30 UTC (solo aviso). CLI de la IA congelado hasta el veredicto de la fase 6.
- **Panel** (`docs/diseno-api-panel.md`): solo por Tailscale, solo lectura, controles sin PIN, slider bloqueado en 3,
  CSV fiscal en euros. Logo: la Π con dos velas (`assets/logo/README.md`).
- **Copias:** cada noche en el VPS (14 dias) y cada dia al portatil (tarea de Windows, `deploy/daily-backup.ps1`). En
  el portatil (el propietario, 07/10, opcion B): los ultimos 14 dias todas; de ahi a 8 semanas, una por semana (~1,8 GB en vez de ~5).
- **Estrategia** (`docs/archivo/propuesta-revision-estrategia.md`): lista cerrada, criterio antes de medir, reserva sin mirar.
  Segunda ronda tras el veredicto de la fase 6 (`docs/archivo/plan-segunda-ronda-estrategia.md`; cortos A' aprobados antes de
  medir; el **time-stop**, idea C, y **quitar la reversion**, idea D con el liston mas alto, las dos desde el 07/10). **Sin una estrategia que no pierda en la reserva, no hay fase 7** (sustituido el 11/10 por el PRD v3: la fase 7 pide que L pase su papel y la decision expresa del propietario). La regla 1 no cambia.
- **Aprendizaje (fase 8)** (`docs/archivo/diseno-aprendizaje.md`): por candidato, criba + sombra, solo a la IA, el propietario aprueba.
- **Protocolo de la fase 6** (`docs/archivo/protocolo-fase-6.md`): desde el 25/09, minimo 3 semanas, hasta 30 discrepancias,
  tope 8; decide la M1; no concluyente -> fase 7 con la IA. **Sombra opcion B** (02/10): con la cartera llena la IA
  decide "si hubiera hueco", no abre nada, juez aparte.
- **Fase 4** (`docs/archivo/diseno-fase-4.md`): el demo ESPEJA la cartera de la IA (misma cantidad, motor de riesgo entero con
  el estado del demo, caducidad propia, salidas no OCO a mercado); `feeType 1`; entradas post-only; `HALTED` no cierra;
  descuadre = no explicado en la pasada o sin OCO > 1 pasada; DEGRADED 3 errores / 2 s / 10 min sano; NEAR solo en
  papel; parcial = cancelar el resto; **saldo virtual de 50 $**; `51279` con el precio pasado = vender a mercado;
  **la semana solo vale con al menos una operacion completa**; ETH y SOL adoptadas el 03/10.
- **Repositorio publico: PREPARADO el 07/10, sin publicar** (el propietario: "per més endavant"; 11/10: esperar a saber si el bot
  es funcional, o sea, al final del papel de L). Codigo, tests y estudios,
  licencia MIT, un solo commit SIN `Co-Authored-By`, autor con el correo anonimo de GitHub; "el propietario" -> "el propietario".
  Copia en una carpeta hermana, `Ploutos-publico`; se regenera con `scripts/preparar_publico.py` (lo que solo existe
  en la publica, en `deploy/publico/`). Correo anonimo del propietario (15/10): `292183709+jlbou@users.noreply.github.com`, tambien el
  `user.email` LOCAL de este repositorio desde el 15/10 (GitHub bloquea los push con el personal). Falta su OK para
  publicar. El privado se llama `jlbou/ploutos-private` desde el 07/10 (lo renombro el propietario; `origin` ya apunta ahi); el nombre
  `ploutos` queda libre para la publica.
- **Otro bot (Ebisu, no cripto): aparcado hasta acabar Ploutos** (06/10; `docs/estudios/viabilidad-otros-activos.md`).

## Estado ahora — 11/10/2026 (actualizar al cambiar)

**15/10: PAUSA y replanteamiento (el propietario).** Plan: paso 0 inventario y limpieza (`docs/inventario-1510.md`), paso 1
decisiones de fondo otra vez (como en Ebisu), paso 2 estudio profundo, paso 3 construir solo si algo pasa. **Las dos
carteras de la fase 6 y el demo, RETIRADOS el 15/10 sin veredicto** (`docs/cierre-fase-6.md`): `ploutos-paper`,
`-paper-ai` y `-exec` parados y deshabilitados; quedan 4 jueces. Lo de abajo sobre ellos es historia.

| Fase | Estado |
|---|---|
| 0-2 | CERRADAS (22-25/09). `docs/archivo/cierre-fase-2.md` |
| 3. Analista en sombra | CERRADA (02/10). `docs/archivo/cierre-fase-3.md` |
| 4. Demo de OKX | **CERRADA (10/10).** Juez CUMPLIDO a las 10:19 UTC: 7,0 dias, 1.981 pasadas, todas cuadran, 2 operaciones completas. Caos 1 y 6, apuntados (cuando pasen). El ejecutor del demo SIGUE en marcha (ensayo de la fase 7). `docs/archivo/cierre-fase-4.md` |
| 5. Panel, Telegram, vigilante | CERRADA (03/10); el panel de hipotesis pasa a la fase 8. `docs/archivo/cierre-fase-5.md` |
| 6. IA contra baseline | **MIDIENDO** desde el 25/09 (tramo `f063d80147a9`): 5 de 30 discrepancias (10/10); minimo 16/10, tope 20/11 (lo probable). Las decisiones de ese dia, preparadas: `docs/archivo/dossier-veredicto-fase-6.md`. M1 en sombra desde el 02/10 (callada con razon: solo BTC, vetada por correlacion, y SOL, abierta) |
| Estrategia | **L (rotacion semanal con 4 plazos) en PAPEL del 12/10/2026 al 11/01/2027** (`docs/diseno-papel-l.md`), con el filtro de noticias en sombra (anuncios de OKX y el embudo de medios con la IA, `docs/diseno-embudo-noticias.md`). L paso la exploracion ampliada y es robusta, pero NO paso el anyo USDC (perdio un 7 %, BTC un 22 %). **PRD v3 para L, aprobado** (`docs/archivo/propuesta-prd-v3.md`): se aplica solo si L pasa su papel y el propietario decide. Lo descartado, en `docs/estudios/` y en "Verificado" |

**En el VPS** (el proveedor del VPS, Ubuntu 24.04, nucleo 6.8.0-142, swap 1 GB): `ploutos-ingest`, `ploutos-paper` (baseline),
`ploutos-paper-ai` (la IA, `MemoryMax`), `ploutos-news`, `ploutos-telegram`, `ploutos-panel`
(`http://ploutos.example.ts.net:8765`, solo `tailscale0`), `ploutos-exec` (el UNICO con las claves de OKX),
desde el 07/10 `ploutos-medios` (24 RSS de medios cada 10 min, EN SOMBRA: nadie que decide lee su base; sin Telegram).
Desde el 11/10, `ploutos-embudo.timer` (:20 y :50): el embudo de noticias para L, en sombra (`var/ploutos-embudo.db`;
la IA da el veredicto; 6 llamadas al dia como mucho y la regla 18 contada con el analista). Desde el 10/10,
`ploutos-papel-l.timer` (00:20 UTC; desde el 11/10 apunta tambien el filtro de noticias en sombra): el papel de L del 12/10/2026 al 11/01/2027 (`docs/diseno-papel-l.md`;
sin claves ni ordenes; Telegram con cada operacion; historia en `var/papel-l/historia.db`; en el panel, tarjeta
"Papel de L" desde el 10/10).
`ploutos-spread-extra` (temporal, ADA y LINK) PARADO y quitado el 09/10 09:56 UTC; su CSV sigue en `var/spread/`. El `.env` del VPS
tiene 15 claves. Healthchecks: 8 comprobaciones del VPS (desde el 07/10, tambien `HEALTHCHECK_MEDIOS`) + 1 del
portatil (`HEALTHCHECK_COPIA_PORTATIL`, la UNICA que va en el `.env` del portatil); las URL del VPS **solo** en su
`.env` (en el portatil lateria en nombre del VPS y taparia una caida; si el propietario pone una ahi, se mueve sin ensenyarla:
la linea por `ssh` a un script que quita el BOM de PowerShell, y se compara la huella del valor). La clave de Tailscale del VPS no caduca (el propietario, 26/09). Jueces cada noche a las 00:30 UTC
(`ploutos-jueces.timer`, once desde el 11/10 con el papel de L y el embudo; Telegram solo si alguno da FALLA). Copias a las 03:15 UTC de las seis bases
(`ploutos`, `-paper`, `-paper-ai`, `-news`, `-control`, `-exec`) y, desde el 07/10, `-medios`; el portatil las baja
desde las 12:00 (hora local).

**Ramas (15/10):** solo `main`; `revision-1510-b` juntada; `objetivo-taker` y `sombra-log`, en las etiquetas
`archivo/objetivo-taker` y `archivo/sombra-log` (el objetivo taker se rehace en el paso 3). Historia: `main` = lo desplegado (`fase-4-piezas-puras`, borrada el 10/10).
`revision-1510-b` (15/10, SIN desplegar): de la revision completa del codigo, el papel prudente con el objetivo en la
vela que llena (suposicion 7, tambien en el juez `portfolio/audit.py`) y la regla 8 con la comision de salida. Partiria
la muestra de la fase 6: tras el veredicto. **La revision del codigo del 15/10, CERRADA:** 9 hallazgos; 4 en `main` (medios, cursor del embudo, huecos
del papel de L, noticias antes de copiar), 2 en esta rama (1 y 5), y los del grupo C (el propietario): 6, la caida de L vela a vela solo
como informacion (el criterio sigue diario; en el bot, el corte vela a vela); 8, la regla 10 de L en el bot como su simulador
(realizado y abierto), las carteras de ahora sin tocar; 9, el redondeo solo con comentario y test. Con `main` del 15/10, la
rama junta sin conflictos y 1679 tests en verde. Los estudios de setups llevan una nota (sus R, algo inflados).
`sombra-log` (07/10, SIN desplegar): la sombra de la IA dice en el log lo que miro, tambien con 0; tras el veredicto.
`objetivo-taker` (07/10, SIN desplegar): el objetivo cobrado taker en el papel, su juez y la M1 desde
`exchange.objetivo_taker_desde` (null = maker como ahora; no toca la huella). Tras el veredicto: juntar, poner la
fecha al inicio de una vela de 4 h y desplegar.

**Pendiente con fecha:**
- **13/10 00:20 UTC:** la primera pasada del papel de L que cuenta (y del embudo): resumirsela al propietario.
- **Del 16/10 al 20/11:** veredicto de la fase 6 y las siete decisiones de `docs/archivo/dossier-veredicto-fase-6.md` (lo
  recomendado: retirar las dos carteras viejas y el demo; no desplegar `objetivo-taker` ni `sombra-log`; juzgar una vez
  los medios en sombra; actualizar el CLI de la IA si sigue; cerrar la segunda ronda). Avisar antes de parar `ploutos-exec`.
- **Caos 1 del demo:** si antes del veredicto aparece una entrada copiada viva, hacerlo (~10 min, avisando al propietario).
- **11/01/2027:** fin del papel de L (`check_papel_l.py`); el propietario etiqueta a ciegas los casos del embudo
  (`docs/diseno-embudo-noticias.md` 5). Si L pasa y el propietario dice si: PRD v3, L en el bot (con sus caos), demo, clave real
  con las 8 monedas y USDC (la pone el propietario) y 50 $.
- **Tras el papel de L:** decidir si se publica el repositorio publico (el propietario, 11/10: cuando se sepa si el bot funciona).

## Trampas y avisos vigentes

- **SSH por la IP publica con timeout** (algunas redes del propietario): `ssh ploutos-ts` (Tailscale, misma clave);
  `sync.sh ploutos-ts`. La copia diaria lo usa sola.
- **Windows tiene DOS clientes SSH**: el de Git Bash no ve el agente (`deploy/_ssh.sh` elige el bueno). Desde
  PowerShell 5.1, las comillas dobles dentro de `ssh '...'` se rompen: para algo complejo, subir un script con `scp`.
- **`sync.sh` NO reinicia nada y no copia `.env`.** `/usr/local/bin/ploutos-backup` es una COPIA de `deploy/backup.sh`:
  si cambia uno, reinstalar.
- **Ficheros desde Windows salen con CRLF** (en Linux fallan raro). Redirigir con `>` en PowerShell pone BOM.
- **IPv6:** el VPS salia por IPv6 y OKX lo veia como IP no autorizada (arreglado en `/etc/gai.conf`; una sola linea
  `precedence` descarta la tabla entera). `curl -s https://api64.ipify.org` tiene que dar la IPv4.
- **SQLite en WAL: un escritor por base**; los demas leen en `mode=ro`. Copiar una base en uso: `VACUUM INTO`.
- **En bash, `set -e` NO vale dentro de una funcion llamada con `||`** (12/10: la copia del embudo salio vacia y se dio
  por buena). Mirar el codigo de salida a mano; y `sqlite3` sobre un fichero que no existe lo CREA vacio (e "integro").
- **Lo que vive en memoria se pierde al reiniciar** (`Restart=always`): todo estado de una regla se deriva de lo guardado.
- **`needrestart` reinicia servicios** con las actualizaciones; `NRestarts` no lo cuenta: mirar `ActiveEnterTimestamp`.
- **Una vela solo esta lista con las OCHO monedas cerradas** (`run_paper._closed_bars_after`).
- **Un par que OKX retira puede bloquear una regla en silencio** (01/10, regla 17): si una cartera lleva velas sin
  candidatos, mirar `paper_decisions` (`detail`) antes de achacarlo al mercado.
- **`CLOSE_ONLY_CAPITAL` solo sale a mano:** `run_paper.py --reset-capital "motivo"` y reiniciar el servicio.

## Operacion

```bash
bash deploy/sync.sh ploutos                                   # copia; NO reinicia
ssh ploutos 'systemctl restart ploutos-paper'                 # reiniciar SOLO lo que toca; la ingesta no
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/jueces_diarios.py --seco'   # los once jueces
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/run_exec.py --status'      # el demo
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/run_paper_ai.py --status'  # y run_paper.py
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_exec.py'             # juez fase 4
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_fase6.py'            # (--sombra)
bash deploy/fetch-backup.sh ploutos                           # bajar y verificar copias
.venv/Scripts/python.exe scripts/verify_claude_cli.py --sin-sesion   # 1 llamada real, sin la sesion
```

Simulacro de restauracion (el ultimo, el 06/10, con las SEIS bases de la copia de las 03:18: las seis integras, los
ocho jueces de cada noche que no son del demo y `check_gaps.py`, sin FALLA, y los tres `--status` arrancan con su estado): descomprimir las copias
de una misma hora y lanzar los jueces con `--db` / `--main-db` / `--paper-db` / `--ai-db` / `--ahora-ms`; detalle en
`docs/historial-claude-md.md` ("Operacion"). **`check_exec.py` solo corre en el VPS** (pide el historial a OKX con la
clave del demo): sobre una copia, con `--exec-db`, `--paper-db` y `--ahora-ms` (desde el 07/10; quita lo que OKX hizo
despues: fills, ordenes, OCO y su efecto en los saldos). Con la copia del 06/10 03:18: sin descuadres, 767 pasadas.

## Documentos

| Documento | Que hay |
|---|---|
| `docs/archivo/prd-ploutos-v2.md` / `docs/informe-ploutos.md` | la fuente de verdad / el como |
| `docs/historial-claude-md.md` | el CLAUDE.md completo hasta el 06/10: cada decision y hallazgo con su detalle |
| `docs/cierre-fase-{2,3,4,5}.md` | criterios, jueces, resultados y veredicto de cada fase (la 4, preparada) |
| `docs/hallazgos-fase-0-1.md`, `-fase-2.md`, `-fase-3-4.md`, `hallazgos-claude-cli.md` | lo verificado, con detalle |
| `docs/archivo/plan-fase-3.md`, `diseno-pieza-9.md`, `despliegue-fase-3.md` | la fase 3: piezas, la IA en el bucle, el despliegue |
| `docs/archivo/diseno-fase-4.md`, `guion-fase-4.md`, `preparacion-fase-4.md`, `caos-fase-4.md`, `parada-mantenimiento-fase-4.md` | la fase 4: decisiones, guion, OKX y ccxt (las 9 pruebas y la 10), tests de caos, la parada |
| `docs/archivo/protocolo-fase-6.md`, `propuesta-candidatos-sombra.md`, `estudios/potencia-fase-6/` | como se decide si la IA aporta, la sombra y lo que puede ver la fase 6 |
| `docs/diseno-noticias.md`, `diseno-comandos-telegram.md`, `propuesta-vigilante.md`, `propuesta-actualizaciones.md` | noticias, comandos, Healthchecks, actualizaciones |
| `docs/diseno-medios-sombra.md` | los medios en sombra (07/10): fuentes, seguridad del XML y el criterio para juzgarlos, fijado antes |
| `docs/diseno-api-panel.md`, `esbozo-panel-fase-5.html` | el panel y su maqueta |
| `docs/archivo/propuesta-revision-estrategia.md`, `plan-segunda-ronda-estrategia.md`, `estudios/revision-estrategia/` | la revision de la estrategia: metodo, primera ronda, cortos, segunda ronda |
| `docs/estudios/operaciones-cortas/`, `estudios/viabilidad-otros-activos.md` | operaciones de horas (no pasan) y el bot aparte con otros activos (06/10) |
| `docs/archivo/propuesta-time-stop.md`, `diseno-cortos-bajistas.md`, `diseno-cartera-cortos.md`, `estudios/divergencia-atr/` | time-stop, cortos A', cartera de cortos (sin construir), techo de ATR |
| `docs/archivo/decision-whitelist-0910.md` | la decision del 09/10 preparada |
| `docs/archivo/decision-fase-7.md` | para que es la fase 7 (09/10). **el propietario: el objetivo es ganar dinero** |
| `docs/archivo/propuesta-prd-v3.md`, `docs/archivo/diseno-tendencia.md` | (09/10; **el PRD v3 para L, APROBADO por el propietario el 11/10**, los 15 cambios: se aplica solo si L pasa su papel y el propietario decide ir al dinero real) los cambios al PRD para el objetivo nuevo y el criterio de la estrategia de tendencia (F: rotacion semanal; H: BTC+ETH con el filtro de BTC) |
| `docs/diseno-papel-l.md` | (10/10, APROBADA: 12/10/2026-11/01/2027, Telegram con cada operacion) seguir L en papel hacia adelante: pasos, opciones, criterio y lo que vendria despues |
| `docs/archivo/diseno-tendencia-2.md` | (10/10, APROBADA por el propietario antes de medir; deflactado opcion b) K (H con 4 plazos), L (F con 4 plazos), M (K + 2 + D); la exploracion ampliada con la reserva; una sola al anyo USDC |
| `docs/estudios/recerca-trading-cripto.md` | que dice la literatura sobre operar cripto (09/10) y lo que encaja con Ploutos |
| `docs/archivo/guion-fase-7.md` | del demo al dinero real (07/10): condiciones (la que manda, la estrategia), decisiones del propietario, cuenta y clave real, piezas, pruebas, revision semanal y cuando parar |
| `docs/archivo/diseno-aprendizaje.md` | el bucle de aprendizaje (fase 8) |
| `docs/archivo/dossier-veredicto-fase-6.md` | (11/10) las decisiones del dia del veredicto de la fase 6, con la recomendada |
| `docs/archivo/propuesta-noticias-l.md`, `docs/diseno-embudo-noticias.md` | (11/10) noticias con L. **el propietario: anuncios de OKX en sombra en el papel de L; medios por un embudo (palabras, fuentes y precio, y la IA con el veredicto final): cambia la decision F del 22/09 solo para esto.** El disenyo del embudo, pendiente de sus numeros |
| `docs/archivo/dossier-02-10.md` | las decisiones del 02/10 en una pagina |
