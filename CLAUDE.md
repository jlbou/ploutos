# Ploutos — memoria del proyecto

Bot de trading **spot** de cripto en OKX EU (BTC/EUR y ETH/EUR), disenyado para escalar a 10.000 €, dentro de 17
reglas deterministas (PRD v3) que ni la IA ni nadie puede modificar desde el codigo. Lo personal (nombre del propietario, servidor, rutas, Healthchecks) va en
**`CLAUDE.local.md`** (fuera de git, se carga solo).

**El repositorio se construye para ser PUBLICO** (propietario, 15/10/2026): todo lo que entra en git se puede leer en
internet. Se publica cuando Claude diga que esta preparado y el propietario lo haga. Ver "Repositorio publico".

## Estado: PAUSA y replanteamiento (desde el 15/10/2026)

En Ploutos se construyo la infraestructura antes de tener una estrategia con ventaja; tras ~35 intentos, ninguna
estrategia pasa el liston contra la suerte contando todos los intentos (`docs/preregistro-papel-l.md` 1). La busqueda
fue con prisa. **Ahora se trabaja como en Ebisu, en este orden y sin saltarse pasos:**

0. **Inventario y limpieza** (`docs/inventario-1510.md`): que se queda, que se reaprovecha, que se descarta.
1. **Decisiones de fondo: HECHO el 15/10** (`docs/decisiones/01` a `09`) y **PRD v3 aprobado**
   (`docs/prd-ploutos-v3.md`): ganar a BTC en euros, escalable a 10.000 €, BTC/EUR y ETH/EUR, la IA de freno, 17 reglas.
2. **Estudio (EN CURSO):** criterio **aprobado y congelado el 15/10** (`docs/plan-estudio-paso-2.md`, etiqueta
   `criterio-paso2`): Bitstamp en euros, H1 medias / H2 Donchian / H3 momento (+ capa de volatilidad), N = 40, liston
   en dos etapas. **V5 recogiendo libros de ordenes hasta el 30/10** (`ploutos-libros.timer`, juez `check_libros.py`);
   **El simulador, HECHO el 16/10** (`docs/estudios/paso2/sim/`, `estudio.py`; validacion con datos reales:
   comprar y mantener = BTC mantenido, diferencia 0,00). Aclaraciones 1-5 aprobadas antes de medir (etiquetas
   `criterio-paso2-a1..a5`); la revision final del simulador, hecha (8 hallazgos corregidos). **Lo que sigue, en orden, desde el 30/10:** `calcular_v5.py` con la copia de
   `ploutos-libros.db` -> `estudio.py explorar` -> decision 4 (apalancamiento y cortos) con la candidata ->
   `estudio.py limpia` (una vez; deja un cerrojo) -> veredicto. Ninguna estrategia medida aun. **El 30/10, al acabar
   V5: desactivar `ploutos-libros.timer`** (el recolector se para solo, pero el temporizador sigue lanzandose).
3. **Construir solo si una estrategia pasa**, con la prueba de oro (el bot hace lo mismo que el simulador). Aqui se
   limpia el codigo de los setups (etiqueta `archivo/antes-de-limpiar`, en el repositorio privado del historial) y se
   arregla el hueco S5 del panel.

**Sigue en marcha, en silencio:** el papel de L (12/10/2026-11/01/2027, `docs/diseno-papel-l.md`; **desde el 16/10, solo
informacion: L ya no es candidata**, `docs/preregistro-papel-l.md` 4), el embudo de
noticias en sombra (`docs/diseno-embudo-noticias.md`), los medios en sombra, las noticias de OKX, la ingesta,
Telegram, el panel, las copias y 5 jueces cada noche (desde el 16/10, tambien el de los libros de ordenes). **Retirados el 15/10, sin veredicto:** las dos carteras de la
fase 6 y el demo (`docs/cierre-fase-6.md`).

## Jerarquia de documentos

1. `docs/prd-ploutos-v3.md` — **fuente de verdad** (aprobado el 15/10/2026, de las decisiones de `docs/decisiones/`).
   El v2, archivado (`docs/archivo/prd-ploutos-v2.md`).
2. `docs/informe-ploutos.md` — el *como*; solo manda donde el PRD calla.
3. Si ninguno lo cubre y afecta a riesgo, dinero o reglas duras → **preguntar al propietario**, no decidir.

`docs/archivo/` guarda lo superado (fases cerradas, propuestas decididas, el CLAUDE.md anterior en
`docs/archivo/claude-md-1510.md`); `docs/historial-claude-md.md`, el de antes del 06/10. Buscar ahi antes de
re-decidir o re-medir.

## Las reglas duras (PRD v3, seccion 4; numeracion del v2)

1. Solo spot, sin apalancamiento ni cortos (revision solo con las condiciones de `docs/decisiones/04`).
2. OKX EU via `ccxt`.  3. Solo **BTC/EUR y ETH/EUR**, validado en 4 puntos; la clave, con BTC, ETH y EUR.
4. 1 posicion por moneda (2 en total), pendientes cuentan; nunca promediar a la baja ni martingala.
5. Capital de referencia en euros, a mano; **suelo al 50 %**.  6. Equity en euros cada 15 s, del exchange.
7. Suelo dos lecturas -> `CLOSE_ONLY_CAPITAL` enclavado.  8. Preventiva con stops y comision; colchon 2 %.
9. Escalones −10 / −20 / −30 %.  10. Perdida del dia (cerrado y abierto) >= 6 % -> `CLOSE_ONLY_DAILY`.
11. Max. 6 operaciones al dia.  12. Riesgo hasta el stop: lo fija el estudio; techo 5 % por posicion, 10 % total.
13. El stop siempre en el exchange.  14. *(retirada)*  15. Exposicion max. 90 %.
16. Spread max. 0,10 %; 3x el coste solo con objetivo fijo.  17. *(retirada)*  18. IA: 40/dia, 8 por 5 h.
19. Claves sin retirada, IP del VPS, fuera del repo; la IA nunca las ve.

**Hasta construir la estrategia nueva (paso 3), el CODIGO sigue con las 19 del v2** (en dolares, 8 monedas contra
USDC): lo que corre hoy (papel de L, embudo) no opera.

**Modos** (PRD §5): `NORMAL`, `CLOSE_ONLY_QUOTA`, `CLOSE_ONLY_DEGRADED`, `CLOSE_ONLY_DAILY`, `CLOSE_ONLY_CAPITAL`,
`HALTED` (y `CLOSE_ONLY_MANUAL`). El efectivo es **el mas restrictivo**. Al entrar en `CLOSE_ONLY_*`: cancelar entradas
pendientes, verificar/crear la OCO de cada posicion, gestionar con reglas deterministas, notificar.

**Ya decidido** (revision del 15/10): la caida y su corte se miden vela a vela; el objetivo de OKX spot sale a mercado (taker).

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
- **El `.env` (15/10, el propietario): se edita en el PORTATIL** (los valores los pone el; Claude deja las lineas
  preparadas) y **Claude copia al VPS solo las claves nombradas** con `deploy/env_a_vps.py <alias> CLAVE ...` (no
  ensenya valores, no toca el resto, compara la huella). Nunca el fichero entero: `HEALTHCHECK_COPIA_PORTATIL` es
  solo del portatil y las URL de Healthchecks del VPS, solo del VPS.
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
- **Historial NUEVO desde el 15/10** (opcion a): un repositorio nuevo con un solo commit limpio; el historial de
  trabajo anterior (con datos personales) vive en un repositorio PRIVADO aparte y en una copia local
  (`CLAUDE.local.md`). **Nunca** se trae ese historial aqui (ni ramas, ni etiquetas, ni `git push --all`).
- Las etiquetas `archivo/...` (ramas archivadas y `antes-de-limpiar`) estan en ese repositorio privado.

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
ssh <alias> 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/jueces_diarios.py --seco'   # los 5 jueces
ssh <alias> 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_papel_l.py'           # el papel de L
bash deploy/fetch-backup.sh <alias>                           # bajar y verificar copias
```

## Documentos vigentes

| Documento | Que hay |
|---|---|
| `docs/inventario-1510.md` | el paso 0: lo que hay y lo decidido pieza a pieza |
| `docs/cierre-fase-6.md` | la retirada de las carteras de la fase 6 y el demo, sin veredicto |
| `docs/prd-ploutos-v3.md`, `docs/decisiones/` | la fuente de verdad y las 9 decisiones de fondo de las que sale |
| `docs/plan-estudio-paso-2.md`, `docs/estudios/paso2/` | el criterio congelado del paso 2 (y sus 5 aclaraciones), la literatura, V4/V5 y el simulador |
| `docs/preregistro-papel-l.md` | intentos, anyos de datos necesarios; L ya no es candidata (su papel, solo informacion) |
| `docs/diseno-papel-l.md`, `docs/diseno-embudo-noticias.md`, `docs/diseno-medios-sombra.md`, `docs/diseno-noticias.md` | lo que sigue en marcha |
| `docs/diseno-comandos-telegram.md`, `docs/diseno-api-panel.md`, `docs/propuesta-vigilante.md`, `docs/propuesta-actualizaciones.md` | Telegram, el panel, Healthchecks, actualizaciones |
| `docs/hallazgos-*.md`, `docs/preparacion-fase-4.md` | lo verificado de OKX, el CLI de la IA y el mercado |
| `docs/estudios/` | todos los estudios: el registro de los intentos |
| `docs/archivo/` | lo superado (fases cerradas, propuestas decididas, el PRD v2 y el borrador de v3 del 11/10, el CLAUDE.md anterior) |
