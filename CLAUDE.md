# Ploutos — memoria del proyecto

Bot de trading **spot** de cripto en OKX EU, 50 $ de capital, dentro de 19 reglas deterministas que ni la IA ni el
bucle de aprendizaje pueden modificar. Lo personal (nombre del propietario, servidor, rutas, Healthchecks) va en
**`CLAUDE.local.md`** (fuera de git, se carga solo).

**El repositorio se construye para ser PUBLICO** (propietario, 15/10/2026): todo lo que entra en git se puede leer en
internet. Se publica cuando Claude diga que esta preparado y el propietario lo haga. Ver "Repositorio publico".

## Estado: PAUSA y replanteamiento (desde el 15/10/2026)

En Ploutos se construyo la infraestructura antes de tener una estrategia con ventaja; tras ~35 intentos, ninguna
estrategia pasa el liston contra la suerte contando todos los intentos (`docs/preregistro-papel-l.md` 1). La busqueda
fue con prisa. **Ahora se trabaja como en Ebisu, en este orden y sin saltarse pasos:**

0. **Inventario y limpieza** (`docs/inventario-1510.md`): que se queda, que se reaprovecha, que se descarta.
1. **Decisiones de fondo otra vez**, una por mensaje: objetivo, capital, mercado, apalancamiento, papel de la IA,
   tiempo. Cada una escrita en `docs/decisiones/`. De ahi, un PRD nuevo (el v3 del 11/10, archivado, no vale).
2. **Estudio profundo**: literatura y datos limpios primero; cuantos anyos de datos hacen falta; el criterio subido a
   git ANTES de medir; N >= 35 intentos en el deflactado; por tipo de mercado; lo no visto, UNA sola vez.
3. **Construir solo si una estrategia pasa**, con la prueba de oro (el bot hace lo mismo que el simulador). Aqui se
   limpia el codigo de los setups (`archivo/antes-de-limpiar`) y se arregla el hueco S5 del panel.

**Sigue en marcha, en silencio:** el papel de L (12/10/2026-11/01/2027, `docs/diseno-papel-l.md`), el embudo de
noticias en sombra (`docs/diseno-embudo-noticias.md`), los medios en sombra, las noticias de OKX, la ingesta,
Telegram, el panel, las copias y 4 jueces cada noche. **Retirados el 15/10, sin veredicto:** las dos carteras de la
fase 6 y el demo (`docs/cierre-fase-6.md`).

## Jerarquia de documentos

1. `docs/prd-ploutos-v2.md` — fuente de verdad hasta que el paso 1 de un PRD nuevo.
2. `docs/informe-ploutos.md` — el *como*; solo manda donde el PRD calla.
3. Si ninguno lo cubre y afecta a riesgo, dinero o reglas duras → **preguntar al propietario**, no decidir.

`docs/archivo/` guarda lo superado (fases cerradas, propuestas decididas, el CLAUDE.md anterior en
`docs/archivo/claude-md-1510.md`); `docs/historial-claude-md.md`, el de antes del 06/10. Buscar ahi antes de
re-decidir o re-medir.

## Las 19 reglas duras (PRD §4)

1. Sin apalancamiento. Solo spot. Nunca margin, futuros ni prestamos.
2. Exchange: OKX EU, via `ccxt`.
3. Solo `X/USDC` de una whitelist explicita de **8 monedas** (`BTC, ETH, SOL, XRP, DOGE, AVAX, TRX, NEAR`). Validado en
   4 puntos: arranque, generador de candidatos, motor de riesgo y justo antes de enviar la orden.
4. Max. **3 posiciones simultaneas**; las entradas pendientes **cuentan**. Max. 1 por simbolo. Sin promediar a la baja.
5. `initial_capital = 50`, `floor = 25`, en configuracion. Solo se cambian a mano.
6. `equity` = USDC libre + Σ(cantidad × mejor bid) − comisiones estimadas de salida, cada 15 s, del **exchange**.
7. Equity ≤ 25 $ en **dos lecturas consecutivas** → `CLOSE_ONLY_CAPITAL`, **enclavado** (solo reset manual) + Telegram.
8. Se abre solo si, con **todas** las posiciones (incluida la nueva) cerradas en su stop y con la comision de salida,
   el equity queda ≥ 25 $ + 1 $ de colchon.
9. Escalones: < 45 $ → riesgo/op. a la mitad + Telegram; < 40 $ → max. 2 posiciones; < 35 $ → max. 1.
10. Perdida del dia ≥ 3 $ → `CLOSE_ONLY_DAILY` hasta las 00:00 UTC.
11. Max. **6 operaciones al dia**.
12. Riesgo por operacion: 1 % del equity por defecto, en **[0,5 %; 1,5 %]**.
13. Stop-loss y take-profit **siempre en el exchange** (OCO / orden algoritmica), creados al abrir.
14. Cooldown 2 h en un simbolo tras stop-loss; pausa 4 h tras 3 perdidas seguidas.
15. Exposicion max. 90 % del equity. Max. 2 posiciones con correlacion entre si > 0,8 (7 d).
16. No entrar con spread > **0,10 %** ni con objetivo esperado < **3×** el coste de ida y vuelta.
17. USDC desviado > 1,5 % de la paridad → sin entradas nuevas.
18. Presupuesto de la IA: max. **40 llamadas/dia** y **8 por ventana de 5 h**.
19. Claves API: solo lectura y trading, **nunca retirada**, IP whitelist del VPS, fuera del repo. La IA nunca ve
    claves ni variables de entorno.

**Modos** (PRD §5): `NORMAL`, `CLOSE_ONLY_QUOTA`, `CLOSE_ONLY_DEGRADED`, `CLOSE_ONLY_DAILY`, `CLOSE_ONLY_CAPITAL`,
`HALTED` (y `CLOSE_ONLY_MANUAL`). El efectivo es **el mas restrictivo**. Al entrar en `CLOSE_ONLY_*`: cancelar entradas
pendientes, verificar/crear la OCO de cada posicion, gestionar con reglas deterministas, notificar.

**Ya decidido para cuando haya estrategia** (revision del 15/10): la caida y su corte se miden vela a vela; la regla 10
cuenta lo realizado Y lo abierto si la estrategia se midio asi; el objetivo de OKX spot sale a mercado (taker).

## Estructura

```
config/   settings.yaml (limites duros, whitelist); .env NO en git
core/ data/ features/ strategy/ ai/ risk/ execution/ portfolio/ notify/ api/ ui/ learning/
scripts/  servicios, jueces, verificaciones      deploy/ instalacion, systemd, copias, sync
tests/    unit, property-based                    docs/estudios/  estudios (no tocan el bot): el registro de intentos
claude_runtime/  directorio VACIO desde el que se ejecuta claude -p
```

## Invariantes de arquitectura (hay tests con AST)

- **`risk/` no importa NADA de `ai/`**; `core`, `data`, `features`, `strategy` y `portfolio` tampoco. `features/` no
  importa `strategy/`, `risk/` ni `ai/`; `strategy/` no importa `execution/`. El simulador (`portfolio/paper.py`) no
  importa `strategy`, `features` ni `ai`.
- El estado verdadero es el del **exchange**. Cada regla dura se comprueba en **al menos dos sitios**. Indicadores
  **solo sobre velas cerradas**.
- `deploy/*.sh`, `*.service` y `*.timer` **sin CRLF** (hay test). El panel solo sale a la red desde `api/cambio.py`.
- El CLI de la IA con `DISABLE_UPDATES=1` y version fija (`ai.invoke.VERIFIED_VERSION`).

## Convenciones de trabajo

- **Con el propietario, en catalan** y con explicaciones sencillas; **una decision por mensaje**, con opciones y la
  recomendada marcada; **no cambiar nada sin su OK**. Llevarle la contraria con argumentos cuando haga falta.
  Codigo, commits, documentos, logs y Telegram, en castellano.
- **El metodo (15/10):** skills cuando sean utiles de verdad, y decir cuales; revisiones sobre revisiones (plan,
  revision con skills, correcciones, revision final); verificar, no suponer, y decir lo que no se comprobo.
  Skills del proyecto en `.claude/skills/` (ml4t y `council`, con su licencia en `NOTICE`); se pueden bajar de
  skills.sh, siempre dentro de este directorio.
- **Python: `.venv/Scripts/python.exe`** (en el VPS, `.venv/bin/python`). Stack: Python 3.12, `ccxt` fijada,
  `asyncio`, `pydantic`, `pandas`, SQLite en WAL, `pytest` + `hypothesis`, FastAPI. Dependencia nueva = justificarla.
- **Configuracion** en `config/settings.yaml`, validada con pydantic: invalida → **el bot no arranca**.
- **Secretos:** solo en `.env` (`.env.example` sin valores). Nunca en logs ni en el chat; **nunca se le pide al
  propietario que pegue un token**; **nunca `source .env`**. Leerlos con `core.secrets.Secrets`.
- **`ruff`** como un test mas. **Tests primero en `risk/`** y `scripts/mutation_check.py` (16/16).
- **Mirar pytest ANTES del commit.** Push al acabar cada encargo; directorio siempre en `main`.
- **Formato de commit (fijo):** `<ambito>: <que, en minuscula, max 72>`, y QUE CAMBIA / POR QUE / HALLAZGOS /
  MEDIDO / TESTS (las opcionales se omiten enteras) y `Co-Authored-By: <el modelo> <noreply@anthropic.com>`.
  Ambitos: `fase N`, `deploy`, `docs`, `decision`, `estudio`, `fix`, `tests`. En Windows, `git commit -F <fichero>`.
- **Dinero:** nada real sin la decision expresa del propietario. Nunca una orden de margen.
- **El patron que mas ha costado:** codigo escrito, probado y SIN ENCHUFAR. Un criterio sin juez automatico no es un
  criterio.
- **Imagen:** en el panel, Telegram y la web **nunca se nombra a Claude**: "la IA" o "el analista" (hay test).
- Avisar al propietario antes de parar un servicio (Healthchecks avisa a los ~20 min).

## Repositorio publico (desde el 15/10/2026)

- **Nunca en git:** el nombre ni el correo personal del propietario, rutas de su ordenador, datos del servidor (IP,
  nombres de Tailscale, proveedor), claves, saldos reales ni detalles de su vida. Se escribe "el propietario". Lo
  personal, en `CLAUDE.local.md` o en `privado/` (los dos en `.gitignore`).
- Autor de los commits: el correo anonimo de GitHub (configurado en el repo, en `CLAUDE.local.md`).
- Antes de cada commit, mirar el diff buscando datos personales.
- **El historial y los documentos de antes del 15/10 SI tienen datos personales**: antes de publicar hay que decidir
  como se limpian: decidido (15/10, opcion a), con un historial NUEVO (un solo commit limpio), guardando antes el de
  ahora en privado. Reescribir la rama de GitHub es irreversible: se pide el OK justo antes.

## Verificado (no re-suponer)

**OKX** (detalle: `docs/hallazgos-*.md`, `docs/preparacion-fase-4.md`)
- Cuentas EU: `hostname: eea.okx.com` (con `www.okx.com`, `50119`). `50119` = host, IP fuera de la lista o clave mal
  copiada; `50101` = clave de un entorno contra el otro; `50123` = moneda no permitida en la clave.
- La whitelist vive en DOS sitios: `settings.yaml` y la clave de OKX (por moneda base).
- Minimo por orden = `minSz` x precio (BTC ~8,6 $): no hay salidas parciales.
- Comisiones de la cuenta (spot, Regular): maker 0,10 %, taker 0,20 % (las de ccxt no son las reales; van por grupo de
  instrumento). Si las reales de un par son mas caras que las configuradas, ese par no se opera.
- ccxt redondea el precio al mas cercano: antes, `execution/precios.al_tick` (hacia el lado seguro). El equity lee el
  USDC TOTAL (`eq`).
- OCO: siempre `tdMode: cash` (ccxt manda `cross`). `clOrdId` alfanumerico <= 32. **El objetivo no puede ser limit en
  spot (`51094`): sale a mercado, taker.** `tradeQuoteCcy: "USDC"` explicito. Un par que no existe responde `50013`.
- El demo: solo 5 de las 8 contra USDC; ticks 10x mas gruesos; el deslizamiento no sirve.
- `watch_ohlcv` devuelve SOLO la vela en curso. `account/trade-fee`: dos procesos a la vez dan `429`/`50011`.
- Historia: contra USDC desde el 20/08/2025; contra USDT, BTC y ETH desde 10/2017, XRP y TRX desde 01/2018, DOGE desde
  07/2019 (`docs/hallazgos-fase-3-4.md` 5b). Ningun estudio ha usado lo anterior a 12/2020.

**El CLI de la IA (`claude -p`, v2.1.266)** — `docs/hallazgos-claude-cli.md`: `--json-schema` en linea; herramientas
encendidas por defecto (`--restricted --disable-slash-commands --strict-mcp-config --setting-sources ''
--no-session-persistence`, desde `claude_runtime/`, con `< /dev/null`); salida en `structured_output`.

**Estrategia** (detalle en `docs/estudios/` y `docs/archivo/claude-md-1510.md`)
- ~35 intentos (`docs/preregistro-papel-l.md` 1). Los 3 setups de 4 h pierden (el baseline, -0,38 R en el anyo USDC);
  la reversion pierde siempre; operaciones de 1 h, cortos y Kronos, tampoco.
- **L** (rotacion semanal con medias de 20/50/100/200 dias): paso la exploracion ampliada con N = 10 (deflactado
  0,978), NO paso el anyo USDC (-6,9 %, BTC -22 %); robusta como idea, cifras inciertas. En papel hasta el 11/01/2027.
- **Datos gastados:** USDT 12/2020-08/2025 (exploracion y reserva) y el anyo USDC 09/2025-09/2026. Limpios: lo
  anterior a 12/2020 (5 monedas) y lo que venga.
- La profundidad nunca ata con 15 $; el spread si.

## Trampas y avisos vigentes

- **SSH:** por la IP publica a veces hace timeout (redes del propietario): usar el alias por Tailscale
  (`CLAUDE.local.md`). Windows tiene DOS clientes SSH (`deploy/_ssh.sh` elige el bueno).
- **`sync.sh` NO reinicia nada y no copia `.env`.** `/usr/local/bin/ploutos-backup` es una COPIA de `deploy/backup.sh`.
- **Ficheros desde Windows salen con CRLF**; redirigir con `>` en PowerShell pone BOM; `Path.write_text` en Windows
  escribe CRLF.
- **IPv6:** el VPS salia por IPv6 y OKX lo veia como IP no autorizada (`/etc/gai.conf`).
- **SQLite en WAL: un escritor por base**; los demas en `mode=ro`. Copiar una base en uso: `VACUUM INTO`. Una base que
  se copia con lectores de solo lectura y sistema de ficheros protegido: `journal_mode=DELETE` (el embudo).
- **En bash, `set -e` NO vale dentro de una funcion llamada con `||`**; `sqlite3` sobre un fichero que no existe lo
  CREA vacio.
- **Lo que vive en memoria se pierde al reiniciar:** todo estado de una regla se deriva de lo guardado.
- **`needrestart` reinicia servicios**: mirar `ActiveEnterTimestamp`.
- **Una vela solo esta lista con las OCHO monedas cerradas.** Un par que OKX retira puede bloquear una regla en
  silencio.

## Operacion

```bash
bash deploy/sync.sh <alias>                                   # copia; NO reinicia
ssh <alias> 'systemctl restart ploutos-panel'                 # reiniciar SOLO lo que toca; la ingesta no
ssh <alias> 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/jueces_diarios.py --seco'   # los 4 jueces
ssh <alias> 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_papel_l.py'           # el papel de L
bash deploy/fetch-backup.sh <alias>                           # bajar y verificar copias
```

## Documentos vigentes

| Documento | Que hay |
|---|---|
| `docs/inventario-1510.md` | el paso 0: lo que hay y lo decidido pieza a pieza |
| `docs/cierre-fase-6.md` | la retirada de las carteras de la fase 6 y el demo, sin veredicto |
| `docs/preregistro-papel-l.md` | intentos, anyos de datos necesarios y que puede decir el papel de L (en pausa) |
| `docs/diseno-papel-l.md`, `docs/diseno-embudo-noticias.md`, `docs/diseno-medios-sombra.md`, `docs/diseno-noticias.md` | lo que sigue en marcha |
| `docs/diseno-comandos-telegram.md`, `docs/diseno-api-panel.md`, `docs/propuesta-vigilante.md`, `docs/propuesta-actualizaciones.md` | Telegram, el panel, Healthchecks, actualizaciones |
| `docs/hallazgos-*.md`, `docs/preparacion-fase-4.md` | lo verificado de OKX, el CLI de la IA y el mercado |
| `docs/estudios/` | todos los estudios: el registro de los intentos |
| `docs/archivo/` | lo superado (fases cerradas, propuestas decididas, el PRD v3, el CLAUDE.md anterior) |
