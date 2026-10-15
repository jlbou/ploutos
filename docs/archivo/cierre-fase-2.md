# Cierre de la fase 2

**Estado: PREPARADO, pendiente de los resultados del viernes 25/09/2026.**
Redactado el 22/09/2026; revisado la madrugada del 25/09 (seccion 0, reinicios y pendientes). La seccion "Resultados" se rellena el viernes con la salida
de los comandos, tal cual, sin resumir.

La convencion (CLAUDE.md): al terminar una fase, parar, ensenyar que hay, como se
prueba y si se cumple el criterio. No empezar la fase 3 sin el OK del propietario.

---

## 0. El guion del viernes, en orden

| Hora (UTC) | Que | Donde |
|---|---|---|
| 07:05 | Revisar el VPS tras las actualizaciones automaticas (06:00-07:00): servicios activos, `ActiveEnterTimestamp`, log de `unattended-upgrades` | seccion 1, VPS |
| cuando sea | Tests y mutacion sobre `main` (criterios 1 y 3) | portatil |
| desde 14:29 | `check_gaps.py` (criterio 0) | VPS |
| desde ~16:05 | `check_paper.py` (criterio 2): necesita 18 filas de equity; la 18a es la vela de las 16:00 | VPS |
| despues | Pegar las salidas en la seccion 7, tal cual, y el veredicto | aqui |
| con el OK del propietario | Desplegar la fase 3 con `docs/archivo/despliegue-fase-3.md` (rama `fase-3-integracion`) | los dos |

**El codigo que se juzga (comprobado el 25/09 de madrugada, comparando la huella de cada fichero
de `main` con el del VPS):** el VPS lleva `main` salvo diferencias que NO cambian lo que se mide:
- `scripts/check_gaps.py`: `main` tiene ademas `--db` y `--until` (para el simulacro de
  restauracion del 22/09). Sin opciones, como se lanza aqui, juzga igual. La correccion que importa
  ("daba por buenas 72 h con la ingesta muerta") SI esta en el VPS.
- `deploy/backup.sh` (y su copia `/usr/local/bin/ploutos-backup`): solo cambia el recuento del log.
- `ai/` y herramientas del portatil (`analyze_spread`, `dry_run_analyst`, `verify_backups`): no
  estan en el VPS y no las importa ningun servicio.

## 1. Los criterios, y como se comprueba cada uno

La fase 1 tiene que estar cerrada ANTES (leccion de la fase 0: no empezar una fase
sin cerrar la anterior). Por eso su criterio va primero.

| # | Criterio | Origen | Comando | Cuando |
|---|---|---|---|---|
| 0 | Fase 1: 72 h sin huecos | PRD seccion 12 | `check_gaps.py` | viernes 25/09, desde las **14:29 UTC** |
| 1 | Tests de propiedades en verde | PRD seccion 12 | `pytest` | ya |
| 2 | Baseline en papel >= 72 h con operaciones coherentes | el propietario, 22/09 (a) | `check_paper.py` | viernes 25/09, desde las **~16:00 UTC** |
| 3 | Cada regla dura rota a proposito pone un test en rojo | el propietario, 22/09 (b) | `mutation_check.py` | ya |

Codigos de salida de los dos jueces: **0** cumplido, **1** incumplido (dicen por que),
**2** aun sin evidencia suficiente (poco tiempo, o ninguna orden).

### En el VPS (criterios 0 y 2)

```bash
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_gaps.py; echo "exit=$?"'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_paper.py; echo "exit=$?"'
# NRestarts NO cuenta los reinicios de needrestart (23/09): mirar CUANDO arranco cada servicio.
ssh ploutos 'systemctl show ploutos-ingest ploutos-paper -p ActiveState -p ActiveEnterTimestamp -p NRestarts'
ssh ploutos 'sudo grep -h "Restarting services\|systemctl restart" /var/log/unattended-upgrades/unattended-upgrades-dpkg.log'
```

### En el portatil (criterios 1 y 3)

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/mutation_check.py
```

### Por que el juez de cada criterio es de fiar

Los dos jueces se escribieron o se arreglaron durante esta fase, y los dos estaban
ciegos o no existian:

- `check_gaps.py` **daba por cumplidas 72 h con la ingesta muerta** (solo veia
  huecos entre dos velas presentes). Reproducido y arreglado; ahora las velas
  esperadas salen del reloj. `tests/unit/test_check_gaps.py` lo lanza de verdad.
- `check_paper.py` no existia: "coherente" no lo definia nadie. Hace 16
  comprobaciones **sin reutilizar el codigo que juzga** (re-simula contra las
  velas). 24 mutaciones de la base de papel, 24 detectadas.

---

## 2. Que hay

| Pieza | Fichero | Nota |
|---|---|---|
| Motor de riesgo, 19 reglas | `risk/` | no importa nada de `ai/` (test de AST) |
| Modelo de costes | `strategy/costs.py` | comisiones de la tabla `instruments` |
| Filtros | `strategy/filters.py` | ahorran cuota, no son una capa de seguridad |
| Regimen | `features/regime.py` | ADX + Bollinger + percentil del ATR |
| Setups | `strategy/setups/` | pullback, ruptura de rango, reversion (stop propio) |
| Candidatos | `strategy/candidates.py` | whitelist, regimen, R:R, coste |
| Correlaciones | `features/context.py` | de rendimientos; sin medir = correlacionada |
| Paridad de USDC | `features/usdc.py`, `data/usdc.py` | A con control C |
| Baseline sin IA | `strategy/baseline.py` | deliberadamente tonto |
| Simulador de papel | `portfolio/paper.py` | seis suposiciones, todas en contra |
| Bucle compartido | `portfolio/loop.py` | el mismo para historico y vivo; con modos |
| Bucle en vivo | `scripts/run_paper.py`, `deploy/ploutos-paper.service` | en el VPS |
| Juez de papel | `portfolio/audit.py`, `scripts/check_paper.py` | 16 comprobaciones |
| Recorrido historico | `scripts/replay_baseline.py` | SUPONE la paridad de USDC |

---

## 3. Lo que se encontro por el camino

Casi todo lo importante salio de medir o de leer con la pregunta "que tendria que
ser cierto aqui", **no de la suite, que estaba en verde con todo dentro**. El patron
que mas se repitio: **codigo escrito, probado y sin enchufar**.

**Sin enchufar:** los filtros, las correlaciones, la regla 17 (la desviacion valia
0,0 por defecto y no podia saltar nunca) y la maquina de modos (el bucle vivia
siempre en NORMAL y la regla 7 no enclavaba).

**Brechas de reglas duras:** la regla 15 dejaba llegar al 100 % de exposicion; la 16
subestimaba el coste; las reglas 10, 11 y 14 se olvidaban de todo al reiniciar el
servicio; una correlacion sin medir contaba como independiente.

**Datos que no eran lo que parecian:** el bucle podia aplicar una vela dos veces tras
un fallo, duplicaba decisiones si moria entre dos transacciones y reescribia la
historia de la curva; el equity no restaba la comision de entrada; el redondeo al
lote perdia un lote por la coma flotante.

**Honestidad de los numeros:** el baseline rinde MENOS que comprar y esperar en un
tramo alcista (+19,6 % contra +31,4 %); el bot no gana cuando el mercado cae (regla 1,
solo largos); 4 h gana a 1 h en todas las metricas.

El detalle de cada uno esta en CLAUDE.md y en los mensajes de commit.

---

## 4. Lo que las 72 h pueden y no pueden demostrar

- **Pueden:** que el bucle corre, sobrevive a reinicios (probado con `kill -9`), no
  reprocesa, respeta las reglas y deja traza de todo.
- **No pueden:** nada estadistico. 72 h de velas de 4 h son 18 velas: a 0,35
  operaciones al dia, **una operacion, quiza dos**. El criterio pide "coherentes",
  no "rentables", y era el criterio correcto.
- La orden de TRX de las 16:00 del 22/09 es anterior a que se guardara el contexto
  de mercado: el juez la cuenta como **SIN DATOS** en las reglas 15, 16 y 17.

## 5. Desviaciones del PRD que el propietario tiene que conocer

- **La maquina de modos esta conectada al bucle, y el PRD la pone en la fase 3.** Se
  propuso y se hizo el 22/09 sin advertirlo. Lo que hace es cumplir las reglas 7
  (enclavamiento) y 10 (solo cierre diario) y el PRD seccion 5 (cancelar pendientes),
  que son del motor de riesgo de esta fase. QUOTA sigue siendo de la fase 3.
- **El criterio de la fase 2 se amplio** (el propietario, 22/09) con el papel de 72 h y la
  prueba de mutacion.

## 6. Pendiente para fases siguientes (no es de esta)

| Que | Fase | Donde esta anotado |
|---|---|---|
| Instalar Node.js y `claude` en el VPS; token en `/opt/ploutos/.env` | 3 | hecho el instalador (`deploy/install-claude.sh`); se usa en el despliegue |
| El VPS tiene 2 GB sin swap y Claude Code pide 4 GB: medir una llamada y decidir | 3 | **decidido** (pieza 9): swap de 1 GB y `MemoryMax`; se mide en el paso 8 del despliegue |
| El parser tiene que rechazar un `cid` inventado (el esquema no lo impide) | 3 | **hecho** (`ai/parser.py`) |
| Redondear el precio de entrada al tick (`round_price_down` no lo llama nadie) | 4 | **hecho** en `fase-4-piezas-puras` (`execution/precios.py`); falta enchufarlo |
| La paridad de USDC deberia salir de la ingesta, no del bucle | 4 | CLAUDE.md, regla 17 |
| Modos QUOTA (fase 3) y DEGRADED (fase 4) en el bucle | 3-4 | QUOTA **hecho** en la rama; DEGRADED, fase 4 |
| Comisiones a `settings.yaml` (maker 0,10 %, taker 0,20 %), decidido por el propietario el 23/09 | tras el 25/09 | **hecho** en la rama; llega con el despliegue |
| ~~Cerrar la pregunta de X/USD contra X/USDC~~ cerrada el 23/09: no compensa, se queda X/USDC | - | `hallazgos-fase-0-1.md` |
| DOGE (0,054 %) y NEAR (0,0501 %) por encima del 0,05 %: decidir con el spread de `paper_market` | antes de la fase 7 | CLAUDE.md, decisiones del propietario |
| Decidir que hacer con las actualizaciones automaticas del VPS (reinician servicios) | - | **decidido** (el propietario, 25/09): reinicio solo si hace falta, 07:15 UTC; llega con el despliegue |
| Noticias como filtro de riesgo, servicio `ploutos-news` | entre 3 y 6 | **disenyada** y decidida (`docs/diseno-noticias.md`) |

---

## 7. Resultados (rellenar el viernes 25/09/2026)

### Criterio 0: fase 1, 72 h sin huecos

Pasado en el VPS el 25/09 a las 17:28 UTC (a las 14:29 no se pudo: una de las redes del
propietario corta el puerto 22; el VPS estaba bien). El juez mira las ultimas 72 h, asi que la ventana es
22/09 17:28 -> 25/09 17:28 UTC, entera dentro de la medicion.

```
$ ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_gaps.py'
Ventana: ultimas 72 h  (2026-09-22 17:28 -> 2026-09-25 17:28 UTC)

par           tf  esperadas  presentes  huecos  faltan  cobertura
-----------------------------------------------------------------
BTC/USDC      1m       4317       4317       0       0   100.000%
BTC/USDC      5m        863        863       0       0   100.000%
BTC/USDC     15m        287        287       0       0   100.000%
BTC/USDC      1h         71         71       0       0   100.000%
BTC/USDC      4h         17         17       0       0   100.000%
ETH/USDC      1m       4317       4317       0       0   100.000%
ETH/USDC      5m        863        863       0       0   100.000%
ETH/USDC     15m        287        287       0       0   100.000%
ETH/USDC      1h         71         71       0       0   100.000%
ETH/USDC      4h         17         17       0       0   100.000%
SOL/USDC      1m       4317       4317       0       0   100.000%
SOL/USDC      5m        863        863       0       0   100.000%
SOL/USDC     15m        287        287       0       0   100.000%
SOL/USDC      1h         71         71       0       0   100.000%
SOL/USDC      4h         17         17       0       0   100.000%
XRP/USDC      1m       4317       4317       0       0   100.000%
XRP/USDC      5m        863        863       0       0   100.000%
XRP/USDC     15m        287        287       0       0   100.000%
XRP/USDC      1h         71         71       0       0   100.000%
XRP/USDC      4h         17         17       0       0   100.000%
DOGE/USDC     1m       4317       4317       0       0   100.000%
DOGE/USDC     5m        863        863       0       0   100.000%
DOGE/USDC    15m        287        287       0       0   100.000%
DOGE/USDC     1h         71         71       0       0   100.000%
DOGE/USDC     4h         17         17       0       0   100.000%
AVAX/USDC     1m       4317       4317       0       0   100.000%
AVAX/USDC     5m        863        863       0       0   100.000%
AVAX/USDC    15m        287        287       0       0   100.000%
AVAX/USDC     1h         71         71       0       0   100.000%
AVAX/USDC     4h         17         17       0       0   100.000%
TRX/USDC      1m       4317       4317       0       0   100.000%
TRX/USDC      5m        863        863       0       0   100.000%
TRX/USDC     15m        287        287       0       0   100.000%
TRX/USDC      1h         71         71       0       0   100.000%
TRX/USDC      4h         17         17       0       0   100.000%
NEAR/USDC     1m       4317       4317       0       0   100.000%
NEAR/USDC     5m        863        863       0       0   100.000%
NEAR/USDC    15m        287        287       0       0   100.000%
NEAR/USDC     1h         71         71       0       0   100.000%
NEAR/USDC     4h         17         17       0       0   100.000%

TOTAL: 44440 velas esperadas, 0 faltan, 0 huecos -> cobertura 100.0000 %
Huecos registrados sin rellenar: 0

RESULTADO: CRITERIO CUMPLIDO. 72 h sin huecos.
exit=0
```

**CUMPLE.**

### Criterio 1: tests de propiedades

Pasado el 25/09 a las 07:13 UTC sobre `main` (el codigo que se juzga; ver seccion 0):

```
$ .venv/Scripts/python.exe -m pytest -q
810 passed in 16.12s
```

**CUMPLE.**

### Criterio 2: papel coherente durante 72 h

Pasado en el VPS el 25/09 a las 17:29 UTC, con el codigo DESPLEGADO (el de antes de la fase 3):

```
$ ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_paper.py'
Bucle de papel (4h): 18 velas procesadas, 2026-09-22 16:00 -> 2026-09-25 12:00 UTC (~72 h)
  ordenes 5, operaciones cerradas 2, posiciones abiertas 3

  OK    una fila de equity por vela, sin saltos                          [72 h]  (18 comprobados)
  OK    ninguna decision apuntada dos veces                              [reinicios]  (114 comprobados)
  OK    cadena candidato -> orden -> llenado -> cierre                   [PRD 13]  (5 comprobados)
  OK    lo guardado coincide con re-simular contra las velas             [simulador]  (5 comprobados)
  OK    comisiones, P&L y R de cada operacion                            [costes]  (2 comprobados)
  OK    equity y contadores de cada vela                                 [regla 6]  (18 comprobados)
  OK    solo pares de la whitelist y setups del slider                   [reglas 3 y slider]  (5 comprobados)
  OK    nunca mas huecos ocupados de los permitidos                      [reglas 4 y 9]  (4 comprobados)
  OK    riesgo, nocional y minimos de cada orden                         [reglas 12 y 9]  (5 comprobados)
  OK    exposicion nunca por encima del tope al entrar                   [regla 15]  (4 comprobados)
  OK    todo al stop deja el equity sobre suelo + colchon                [regla 8]  (4 comprobados)
  OK    perdida y operaciones del dia                                    [reglas 10 y 11]  (4 comprobados)
  OK    cooldown tras stop y pausa tras perdidas seguidas                [regla 14]  (5 comprobados)
  OK    spread y objetivo >= 3x el coste al entrar                       [regla 16]  (4 comprobados, 1 SIN DATOS)
  OK    nunca demasiadas posiciones correlacionadas                      [regla 15]  (4 comprobados, 1 SIN DATOS)
  OK    USDC en paridad al entrar                                        [regla 17]  (4 comprobados, 1 SIN DATOS)
  OK    ninguna entrada en modo de solo cierre, y pendientes canceladas  [PRD 5, reglas 7 y 10]  (5 comprobados)

  3 casos SIN DATOS: ordenes anteriores a que se guardara el contexto
  de mercado (22/09/2026). No son fallos, pero tampoco estan comprobados.

RESULTADO: criterio CUMPLIDO (72 h, 5 ordenes, todo coherente).
exit=0
```

**CUMPLE.** Los 3 "SIN DATOS" son de la MISMA orden (TRX, 22/09 16:00, anterior a que se guardara el
contexto de mercado, que empieza el 23/09 00:00; comprobado en la base: es la unica sin spread ni
paridad guardados): en esas tres reglas se ha comprobado 4 de 5 ordenes. La muestra es
pequenya (5 ordenes, 2 cerradas): demuestra que el papel es coherente, no que la estrategia gane.

### Criterio 3: prueba de mutacion

Pasado el 25/09 a las 07:14 UTC sobre `main`:

```
$ .venv/Scripts/python.exe scripts/mutation_check.py
Prueba de mutacion de las reglas duras
==========================================================================

Se desactiva cada regla y se comprueba que algun test se pone en rojo.
Una regla que se puede desactivar sin que nadie se entere no esta
protegida por ningun test.

Linea base (sin mutar): 88 tests en verde

 regla  nombre                      verde   ROJO  resultado
-----------------------------------------------------------
     1  sin apalancamiento             87      1  PROTEGIDA
     2  exchange OKX                    -      -  no mutable
     3  whitelist X/USDC               83      5  PROTEGIDA
     4  maximo de posiciones           82      6  PROTEGIDA
     5  capital de referencia           -      -  no mutable
     6  equity valido                  86      2  PROTEGIDA
     7  suelo de capital               86      2  PROTEGIDA
     8  preventiva del suelo           86      2  PROTEGIDA
     9  escalones de drawdown          86      2  PROTEGIDA
    10  limite diario                  85      3  PROTEGIDA
    11  operaciones al dia             86      2  PROTEGIDA
    12  riesgo por operacion           86      2  PROTEGIDA
    13  stop y objetivo                86      2  PROTEGIDA
    14  cooldown y pausa               86      2  PROTEGIDA
    15  exposicion y correlacion       84      4  PROTEGIDA
    16  spread y coste                 83      5  PROTEGIDA
    17  paridad de USDC                84      4  PROTEGIDA
    18  presupuesto de Claude          87      1  PROTEGIDA
    19  credenciales                    -      -  no mutable

(89 s)

Reglas no mutables, y por que:
   2. exchange OKX: se valida en core.config al arrancar (test_config.py); aqui solo confirma
   5. capital de referencia: es configuracion, se valida en core.config al arrancar
  19. credenciales: el motor de riesgo NUNCA ve credenciales; que no pueda comprobarlas es la regla cumpliendose. Se verifica con scripts/verify_okx_key.py

RESULTADO: CORRECTO. Las 16 reglas mutables estan protegidas.
```

**CUMPLE.**

### Reinicios de los servicios durante la ventana

Ya sabido antes del viernes: el 23/09 a las 06:40 UTC `needrestart` reinicio `ploutos-ingest` (y
`ploutos-spread`) tras actualizar `sudo`; la ingesta relleno 301 velas por timeframe y el juez no
vio huecos. `ploutos-paper` no se reinicio (arriba desde el 22/09 22:36). El 24/09 no hubo
actualizaciones.

**Viernes 25/09, 06:59-07:00 UTC** (revisado a las 07:05): se instalaron el nucleo 6.8.0-142
(`linux-image-generic` y compania) y `libisns0t64`. **Ningun servicio se reinicio** (ingesta desde el
23/09 06:40, papel desde el 22/09 22:36). Queda `/var/run/reboot-required`: la maquina sigue con el
nucleo 6.8.0-139 hasta reiniciar. Es el riesgo B de `docs/propuesta-actualizaciones.md`, ya decidido;
el reinicio se hace en el despliegue de la fase 3, no antes (cortaria la medicion). `check_gaps` a
las 07:06: 9.896 velas esperadas, 0 faltan, cobertura 100 %.

A las 17:28 UTC (el VPS arriba 3 dias y 4:58 h, sin reiniciar):

```
$ grep ... /var/log/unattended-upgrades/unattended-upgrades.log
2026-09-23 06:40:31 INFO Packages that will be upgraded: sudo
2026-09-24 06:19:48 INFO No packages found that can be upgraded unattended and no pending auto-removals
2026-09-25 06:59:55 INFO Packages that will be upgraded: libisns0t64 linux-generic linux-headers-generic linux-image-generic linux-libc-dev linux-tools-common
2026-09-25 07:00:53 INFO All upgrades installed

$ systemctl show ploutos-ingest ploutos-paper -p Id -p ActiveEnterTimestamp -p NRestarts
Id=ploutos-ingest.service   ActiveEnterTimestamp=Wed 2026-09-23 06:40:39 UTC   NRestarts=0
Id=ploutos-paper.service    ActiveEnterTimestamp=Tue 2026-09-22 22:36:47 UTC   NRestarts=0
```

Un solo reinicio en toda la medicion: la ingesta el 23/09 06:40 (ya conocido, sin huecos).

### Veredicto

**LA FASE 2 CUMPLE SU CRITERIO DE AVANCE, y la fase 1 tambien** (25/09/2026, 17:30 UTC).

| Criterio | Resultado |
|---|---|
| 0. Fase 1: 72 h sin huecos | **CUMPLE**: 44.440 velas, 0 huecos, 100 % |
| 1. Tests de propiedades en verde | **CUMPLE**: 810 en verde |
| 2. Papel coherente >= 72 h | **CUMPLE**: 18 velas, 5 ordenes, 17 de 17 comprobaciones |
| 3. Prueba de mutacion | **CUMPLE**: 16 de 16 reglas mutables protegidas |

Lo que NO dice: que la estrategia gane. Con 2 operaciones cerradas no se puede decir nada del
resultado, y el anyo medido (docs/archivo/propuesta-time-stop.md) dice que el baseline pierde; eso se revisa
antes de la fase 7 (decision del propietario del 25/09). Lo siguiente, con el OK del propietario: desplegar la fase 3
(`docs/archivo/despliegue-fase-3.md`), que incluye el reinicio pendiente por el nucleo nuevo.
