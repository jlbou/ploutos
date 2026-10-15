# Hallazgos de las fases 0 y 1

Movido de CLAUDE.md el 22/09/2026, **sin cambiar una palabra**: ingesta, despliegue, OKX (quote, hosts, demo, IPv6, claves).
Lo que sigue vigente como regla, decision o aviso esta resumido en CLAUDE.md;
aqui queda el como y el por que, con los numeros.

---

## Hallazgos de la fase 1 (22/09/2026, medidos contra OKX)

- **Minimo por orden = `minSz` x precio, y OKX NO publica minimo nocional.**
  `limits.cost.min` viene a `None` en ccxt para todos los pares; hay que calcularlo.
  BTC/USDC: 0,0001 BTC = **8,58 $**. Con posiciones de 15 $, **una salida parcial del
  50 % (7,50 $) quedaria por debajo del minimo** y dejaria polvo no vendible.
  El resto de la whitelist esta entre 0,35 $ y 4,42 $ y no tiene el problema.
  Consecuencia: **el disenyo no lleva salidas parciales** (el PRD tampoco las pide).
  Si alguna vez se anyaden, la regla del minimo nocional hay que comprobarla tambien
  en la salida, no solo en la entrada.
- **Comisiones segun ccxt: maker 0,10 %, taker 0,15 %. NO son las de la cuenta.**
  Son los valores genericos que ccxt pone a todos los mercados de OKX; la tabla
  `instruments` los copia tal cual. Las reales de la UE, en el anuncio oficial
  "Important Notice - Upcoming Spot Fee Adjustment EEA" (publicado el 11/09/2026,
  leido el 23/09 por la API publica `/api/v5/support/announcements`, tipo
  `announcements-trading-updates`) y en la pagina "Spot Fees comparison: X-Perps
  account vs Regular account" (18/05/2026):

  | Cuenta solo spot, nivel Regular | maker | taker |
  |---|---|---|
  | hasta el 25/09/2026 10:00 CEST (08:00 UTC) | 0,20 % | **0,35 %** |
  | **desde el 25/09/2026 08:00 UTC** | **0,10 %** | **0,20 %** |
  | lo que usa el modelo (ccxt) | 0,10 % | 0,15 % |

  "Solo spot" = sin cuenta de derivados (X-Perps); con ella las comisiones son otras
  (0,08 % / 0,10 %), pero la regla 1 prohibe los derivados. Los pares entre
  stablecoins llevan su propia tabla (0 % / 0,05 %); los `X/USDC` van por la general.
  Coincide con el informe §2.2 (0,10 % / 0,20 % desde el 25/09).

  **Lo que cambia (recorrido del baseline, misma historia, solo cambian las comisiones):**

  | Comisiones | 4 h: op. | 4 h: neto | 4 h: comisiones/bruto | 1 h: neto |
  |---|---|---|---|---|
  | 0,10 / 0,15 (modelo) | 11 | +7,829 $ | 3 % | -4,55 $ |
  | 0,10 / 0,20 (desde el 25/09) | 11 | +7,797 $ | 4 % | -4,73 $ |
  | 0,20 / 0,35 (hoy) | 11 | +7,497 $ | 7 % | -6,63 $ |

  En 4 h casi no se nota (las mismas 11 operaciones, 3 centimos menos): la decision de
  operar en 4 h aguanta. En 1 h empeora lo que ya era negativo.
  **El taker del modelo se queda corto 0,05 puntos** desde el 25/09: el coste de ida y
  vuelta de la regla 16 sale algo mas barato de lo que es. **Decidido por el propietario el
  23/09:** van a `settings.yaml` (0,10 % / 0,20 %) tras el cierre del viernes, y en la
  fase 4 se comparan con las reales de la cuenta (ver CLAUDE.md).
- **El desfase de reloj es real y hay que vigilarlo.** La maquina de desarrollo iba
  ~10 s atrasada frente a OKX, Cloudflare y GitHub. En Windows se arregla con
  `w32tm /resync` (como administrador); en el VPS lo hace `chrony`. Consecuencia de
  disenyo: `data/validate.py` tolera hasta 60 s de timestamp "en el futuro", porque
  con el reloj atrasado las velas frescas lo parecen y rechazarlas nos dejaria sin
  datos. Quien detecta el desfase es `core.clock.SkewReading`, que avisa desde 2 s.
- **El grabador de eventos arranca antes que nada.** Si arranca despues del backfill,
  el evento de arranque y los huecos del escaneo inicial se publican sin oyentes y
  no llegan al journal.
- **`EventBus.subscription()` es la API buena, no `stream()`.** Salir de un `async for`
  con `break`/`return` no ejecuta el `finally` del generador, asi que el suscriptor
  queda colgado. En la fase 5 eso seria una fuga por cada desconexion de la UI.
- **`watch_ohlcv` de ccxt devuelve SOLO la vela en curso, no el historial.** Cuando
  una vela cierra, el siguiente mensaje ya trae la siguiente: la cerrada no vuelve a
  aparecer nunca. Decidir el cierre con nuestro reloj no funciona (la primera version
  corrio 7 minutos y guardo CERO velas del WebSocket). La solucion, en
  `data/ingest/sequencer.py`, usa la secuencia del propio exchange: si llega una vela
  con timestamp mayor, la anterior esta cerrada por definicion. Inmune al desfase de
  reloj porque no consulta el reloj. Verificado: 64 velas del WS coinciden al
  decimal con lo que devuelve el REST.
- **La costura backfill/WebSocket deja un hueco en cada arranque.** Con 8 monedas x
  5 timeframes el backfill tarda mas de un minuto, asi que los primeros simbolos
  pierden los minutos que median hasta que el WebSocket entrega. Se cierra con un
  escaneo de huecos 90 s despues de arrancar el WS (`SEAM_SCAN_SECONDS`), ademas del
  ciclo normal de 15 min. Medido: 8 huecos detectados y 8 rellenados en el arranque.


## Despliegue (PRD §11) — hecho el 22/09/2026

`deploy/` contiene el despliegue reproducible. Verificado de punta a punta contra el VPS:

- `install.sh` idempotente. **Se planta si el Python no es 3.12**: si algun dia se reinstala el
  sistema con la imagen equivocada, se sabe al instante y no tres semanas despues.
- Instala tambien las dependencias de desarrollo: el servidor es el entorno de referencia y
  poder lanzar la suite ALLI es lo que demuestra que el despliegue esta sano. **264 tests en verde
  en el VPS.**
- `ploutos-ingest.service` con `Restart=always` y `StartLimitIntervalSec=0`. **Probado con
  `kill -9`: systemd lo reinicio solo.** Sin esto, el criterio de 72 h es inalcanzable.
- `chrony` sincroniza el reloj: desviacion medida **0,0000005 s** (en Windows eran 10 s).
- `backup.sh` usa `VACUUM INTO`, no `cp`: copiar un SQLite en uso con `cp` da copias corruptas.
  Verifica la copia con `integrity_check` y la descarta si falla. Probado: 12.063 velas, 376 KB.
  Timer diario a las 03:15 UTC (lejos del reset de las 00:00 de las reglas 10 y 11).
- `fetch-backup.sh` baja las copias al portatil. **Hay que ejecutarlo a mano**: mientras no se
  haga, las copias viven en el mismo servidor que la base de datos y no son copias de verdad.
- Cortafuegos: solo SSH. El dashboard de la fase 5 ira por Tailscale, nunca expuesto.
- `harden-ssh.sh` **ejecutado y verificado** el 22/09/2026: `passwordauthentication no`,
  `permitrootlogin without-password`, `maxauthtries 3`. El servidor pasa de anunciar
  `(publickey,password)` a solo `(publickey)`: las contrasenyas que el proveedor del VPS mando por correo en
  texto plano ya no sirven para entrar.
- **Una sola clave autorizada**: `ploutos-vps`. Se retiro la clave antigua de marzo, cuya
  passphrase se perdio: una clave que no puedes abrir no es una clave de respaldo, solo una via
  de acceso que no controlas. Copia en `/root/.ssh/authorized_keys.bak-*`.

**Aviso del entorno de desarrollo:** en Windows hay DOS clientes SSH y no son intercambiables.
El agente que guarda la clave descifrada es el SERVICIO de Windows, y el `ssh` de Git Bash NO lo
ve: falla con "Permission denied (publickey)" aunque desde PowerShell la misma conexion funcione.
`deploy/_ssh.sh` elige el binario correcto y lo cargan `sync.sh` y `fetch-backup.sh`; para forzar
otro, `PLOUTOS_SSH=/ruta/ssh`.

**`sync.sh` no depende de rsync:** en Windows no suele estar, asi que cae a `tar` sobre ssh.

**`.env` no se copia al servidor** (`sync.sh` lo excluye, regla 19). La fase 1 no necesita
secretos. Cuando llegue la fase 5, hay que crear el `.env` en el VPS a mano con permisos 600.

## Pregunta resuelta y pregunta abierta sobre la quote (22/09/2026)

**RESUELTA — los pares X/USDC SI estan disponibles en la entidad europea.** La interfaz de
OKX Europa muestra la etiqueta `X/USD`, pero el formulario de compra tiene un desplegable de
moneda de cotizacion **que viene por defecto en USDC** (confirmado por el propietario en su cuenta). Es la
funcion `tradeQuoteCcyList` que se ve en los datos crudos del instrumento:
`['USDG', 'USD', 'USDC', 'RLUSD']`. La regla 3 se mantiene sin cambios.

**ABIERTA — `X-USD` y `X-USDC` son instrumentos con LIBROS SEPARADOS, y en BTC el de USD esta
mucho mas estrecho.** Medido (una sola muestra, no concluyente):

| Instrumento | Spread |
|---|---|
| BTC-USDC | 0,01719 % |
| BTC-USD  | **0,00012 %** (140x mas estrecho) |
| TRX-USDC | 0,03795 % |
| TRX-USD  | 0,03796 % (igual) |

Importa porque el spread es el coste dominante (la profundidad nunca ata con ordenes de 15 $).
**No se cambia nada por ahora**, y por tres motivos:

1. Una sola muestra descarta, no confirma. Hay que medirlo con `scripts/verify_okx_pairs.py`
   durante horas y en varias franjas antes de decir nada.
2. La regla dura 3 dice `X/USDC`. Cambiarla es decision del propietario, no del codigo.
3. **No sabemos que es "USD" en OKX.** No es una cripto: probablemente es una representacion
   unificada de las monedas dolar. Si operas contra "USD", *que tienes cuando vendes?* Eso afecta
   al calculo del equity (regla 6) y a la regla 17 del despegue del stablecoin. Hay que leer la
   documentacion de OKX, no mirar un libro de ordenes.

Si tras medirlo bien la diferencia se mantiene, plantearselo al propietario con numeros. Podria salir que
compensa en BTC y no en el resto.

**Medicion larga EN MARCHA desde el 22/09/2026 21:43 UTC, 24 h, en el VPS** (unidad
temporal `ploutos-spread`, `nice 19`). Las 8 bases contra USDC y contra USD, una
muestra cada 30 s, escrita al momento en `/opt/ploutos/var/spread/muestras-20260922.csv`
(hora, par, spread, profundidad a cada lado, precio medio). Termina hacia las 21:43
UTC del 23/09 y deja el resumen en `resumen-20260922.json`.

Se lanzo en el VPS y no en el portatil, al reves de lo que se dijo primero, y por
numeros: el portatil se duerme (el "mantener despierto" de la app solo aguanta ~5 min
de sesion inactiva), y la carga es **0,5 peticiones/s contra un limite de ~18/s** del
libro de ordenes (coste 0,5 a 110 ms en ccxt), en un endpoint que la ingesta no usa (la
ingesta va por WebSocket y solo usa REST para rellenar velas). Comprobado al arrancar:
ingesta con 0 reinicios y 0 avisos de limite.

Primeras muestras (no concluyentes): BTC-USD y BTC-USDC salen IGUALES (0,0001 %), no
140 veces distintos. En las altcoins, el libro USD es PEOR: AVAX/USD 0,18 %, y con
profundidad de pocos miles de dolares frente a cientos de miles en USDC.

### Resultado de la medicion de 24 h (analizado el 23/09/2026 21:45 UTC)

`scripts/analyze_spread.py` sobre las 24 h exactas (22/09 21:43 -> 23/09 21:42 UTC,
38.640 muestras, 2.415 rondas, un dia laborable). La unidad se reinicio a las 06:40 por
una actualizacion automatica de Ubuntu (ver CLAUDE.md, trampas): el CSV se abre en modo
anyadir y no se perdio ninguna ronda; la medicion sigue sola hasta el 24/09 06:40 y lo
que pase de las 24 h no entra en este analisis.

**Contra USDC** (spread medio en %, criterio de la seleccion < 0,05 %):

| par | total | asia | europa | america | cierre | p95 | tiempo > 0,10 % | veredicto |
|---|---|---|---|---|---|---|---|---|
| BTC | 0,0037 | 0,0033 | 0,0034 | 0,0043 | 0,0037 | 0,015 | 0 % | pasa |
| ETH | 0,0114 | 0,0116 | 0,0083 | 0,0138 | 0,0096 | 0,024 | 0 % | pasa |
| TRX | 0,0258 | 0,0293 | 0,0253 | 0,0232 | 0,0245 | 0,044 | 0 % | pasa |
| XRP | 0,0339 | 0,0385 | 0,0342 | 0,0338 | 0,0212 | 0,084 | 2,4 % | pasa |
| SOL | 0,0365 | 0,0349 | 0,0370 | 0,0385 | 0,0347 | 0,053 | 0 % | pasa |
| AVAX | 0,0453 | 0,0396 | 0,0488 | 0,0484 | 0,0463 | 0,067 | 0,7 % | pasa, justa |
| NEAR | 0,0501 | 0,0468 | 0,0536 | 0,0538 | 0,0433 | 0,071 | 2,7 % | **falla por 0,0001** |
| DOGE | 0,0540 | 0,0540 | 0,0562 | 0,0532 | 0,0529 | 0,090 | 3,6 % | **falla, en todas las franjas** |

- **SOL, que preocupaba (0,048 % en la primera medida), pasa holgada: 0,037 %.**
- **DOGE falla de forma consistente** (0,053-0,056 % en las cuatro franjas). NEAR, en la
  media justa: por encima en Europa y America, por debajo en Asia y al cierre.
- La profundidad minima de todos es >= 1.000 $: con ordenes de 15 $ nunca ata.
- **Lo que cuesta en dinero:** con 15 $ y salida taker se paga medio spread. DOGE: 0,004 $
  por operacion; en el limite del 0,05 %, 0,0038 $. La diferencia (0,0003 $) es cien veces
  menor que la comision de ida y vuelta (0,045 $ con 0,10/0,20). Lo que SI cambia es cuanto
  tiempo bloquea la regla 16 (> 0,10 %): 3,6 % del tiempo en DOGE y 2,7 % en NEAR, frente a
  0 % en BTC, ETH, SOL y TRX.
- **Cautela:** es un solo dia laborable. El fin de semana suele ser mas fino.

**USD contra USDC, en la misma ronda:**

| base | USDC | USD | USD/USDC | rondas en que gana USD |
|---|---|---|---|---|
| BTC | 0,0037 | 0,0003 | 0,09 | 55 % |
| ETH | 0,0114 | 0,0059 | 0,52 | 68 % |
| SOL | 0,0365 | 0,0182 | 0,50 | 89 % |
| XRP | 0,0339 | 0,0198 | 0,58 | 68 % |
| TRX | 0,0258 | 0,0499 | 1,93 | 10 % |
| NEAR | 0,0501 | 0,0964 | 1,92 | 21 % |
| DOGE | 0,0540 | 0,0846 | 1,57 | 12 % |
| AVAX | 0,0453 | 0,1160 | 2,56 | 3 % |

**Segunda ventana (resumen automatico del propio script, 24/09).** Tras el reinicio de las 06:40
del 23/09, el proceso conto sus 2.880 rondas desde cero, asi que su resumen
(`resumen-20260922.json`) cubre OTRA ventana: 23/09 06:40 -> 24/09 11:17 UTC (28,6 h; cada ronda
dura ~36 s, no 30). En ella **DOGE pasa (0,046 %) y NEAR falla (0,0525 %)**, al reves que en las
primeras 24 h (DOGE 0,054 %, NEAR 0,0501 %). El resto, igual: BTC 0,0035, ETH 0,013, TRX 0,023,
XRP 0,030, SOL 0,036 y AVAX 0,045 %. **Conclusion: DOGE y NEAR estan en el borde del 0,05 %, y cual
"falla" depende de que horas se midan.** Refuerza la decision del propietario de decidirlo con semanas de
datos (`paper_market`) y no con uno o dos dias. El script sale con codigo 1 cuando pasan menos de
8 (por eso la unidad quedo `failed`): es su veredicto, no una averia.

**La pregunta abierta sobre la quote se CIERRA: no compensa cambiar.** USD es mas estrecho en
BTC, ETH, SOL y XRP y bastante peor en las otras cuatro; en BTC la diferencia son 0,0005 $ por
operacion de 15 $; y sigue sin saberse que es "USD" en OKX (que tienes al vender, como entra en
el equity y en la regla 17). La regla 3 se queda como esta: `X/USDC`.

## La regla 3 tiene un QUINTO punto de validacion: el propio OKX (22/09/2026)

Al crear la clave de API con permiso de "Operar", OKX obliga a listar las criptos permitidas:
*"Limita esta clave API unicamente a los pares que comiencen con las criptos que hayas anyadido."*

Se anyadieron las 8 bases de la whitelist: `BTC ETH SOL XRP DOGE AVAX TRX NEAR`.
**NO se anyadio USDC**: la restriccion es sobre la moneda BASE (la parte izquierda del par), y
anyadir USDC abriria ademas pares como `USDC/EUR` o `USDC/USDT` que no hacen falta.

Esto convierte los 4 puntos de validacion de la regla 3 en **5**, y el quinto es el mas fuerte
porque **no depende de que nuestro codigo sea correcto**: si todas las capas de Ploutos fallaran a
la vez e intentara comprar un par fuera de la lista, el exchange rechazaria la orden.

**CONSECUENCIA OPERATIVA:** la whitelist vive ahora en DOS sitios, `config/settings.yaml` y la
clave de API de OKX. Si algun dia cambia (p. ej. si la medicion larga tumba a SOL, que iba justo
de spread), **hay que actualizar tambien la clave en OKX** o las ordenes rebotaran con un error de
permisos dificil de interpretar.

Nota: esta restriccion NO afecta a la regla 17 (vigilar el despegue de USDC), porque los datos de
mercado que necesita son publicos y no pasan por la clave.

## El entorno DEMO de OKX no tiene los 8 pares (22/09/2026)

Medido con la cabecera `x-simulated-trading: 1` contra `/api/v5/public/instruments`:

| Entorno | Instrumentos spot live | Bases con par /USDC |
|---|---|---|
| Real | 1.412 | 296 |
| **Demo** | 594 | **29** |

De la whitelist, en DEMO solo existen contra USDC: **BTC, ETH, SOL, DOGE, NEAR**.
**Faltan XRP, AVAX y TRX** (en demo solo estan contra USDT).

**La clave de API de demo lleva solo esas 5 bases.** La clave real de la fase 7 llevara las 8.

**NO usar los pares USDT del demo como sustituto:** lo prohibe la regla 3 y ademas USDT no esta
disponible en la UE, asi que se estaria probando algo que nunca se hara.

**No cambia la whitelist.** Solo afecta a la fase 4:
- Fases 1-3 usan datos publicos del mercado REAL: los 8 estan.
- Fase 7 opera contra el mercado REAL: los 8 estan.
- Fase 4 ejercitara la ejecucion con 5 de 8. Es aceptable: OCO, idempotencia, reconciliacion y
  tests de caos son el MISMO codigo para todos los pares.

**Lo que hay que tapar en la fase 4:** los 5 pares del demo no ejercitan los parametros propios de
los otros 3 (XRP `minSz` 1, AVAX 0,1, TRX 1), y el redondeo hacia abajo y el minimo nocional son
donde se cometen los errores caros. Anyadir tests que usen los parametros REALES de los 8
instrumentos, que ya estan en la tabla `instruments` desde la fase 1. No hace falta poder operar
un par para comprobar que se le calcula bien el tamanyo.

## CRITICO: las cuentas de OKX EUROPA necesitan `eea.okx.com`, no `www.okx.com`

Medido el 22/09/2026 con la clave real del propietario, desde la IP de la lista blanca:

| Host | demo | real |
|---|---|---|
| `www.okx.com` | **50119** | **50119** | <- el que ccxt usa POR DEFECTO |
| `eea.okx.com` | **OK** | 50101 |
| `my.okx.com`  | **OK** | 50101 |
| `app.okx.com` | 50119 | 50119 |

`hostname: eea.okx.com` esta en `config/settings.yaml` y lo aplica `data/exchange.py`.
Sin eso, toda la fase 4 habria fallado.

**Los datos PUBLICOS son identicos en todos los hosts**: se compararon los libros de
BTC/ETH/TRX (precios dentro del 0,05 %) y los catalogos de instrumentos (1.412 y 296 bases
/USDC en ambos). **Las mediciones de spread de la fase 1 siguen siendo validas.**

**`50119` no significa lo que dice.** OKX responde "API key doesn't exist" en TRES situaciones
distintas y nunca dice cual:
1. host equivocado (una cuenta EU preguntando a `www.okx.com`),
2. peticion desde una IP que no esta en la lista blanca,
3. la clave esta mal copiada.

Es deliberado: no confirmar que una clave existe a quien no deberia saberlo. Pero cuesta horas
de depuracion. `scripts/verify_okx_key.py` ahora lo explica y lista las tres causas en orden.

`50101` = "broker id of APIKey does not match current environment", o sea clave de un entorno
pedida contra el otro. Sirve para CONFIRMAR que una clave es de demo: si falla con 50101 contra
el real, es que es de demo.

## Y ANTES DE ESO: el VPS salia por IPv6 (22/09/2026)

El servidor tiene IPv4 fija (la de la lista blanca de OKX) **y** tambien IPv6. Ubuntu
prefiere IPv6 y `www.okx.com` resuelve por IPv6, asi que OKX veia las peticiones llegando desde
una direccion NO autorizada. Se arregla en `deploy/install.sh` con `/etc/gai.conf`.

**Trampa de `gai.conf`:** en cuanto aparece UNA linea `precedence`, la tabla por defecto se
descarta ENTERA. Hay que repetirla toda, no solo la linea de IPv4. El primer intento solo puso
la de IPv4 y no sirvio de nada.

Comprobacion rapida en el VPS: `curl -s https://api64.ipify.org` debe devolver la IPv4.

## Estado de la clave de API de OKX (22/09/2026)

`ploutos-demo` (V5), entorno DEMO, verificada con `scripts/verify_okx_key.py` desde el VPS:

- autentica OK contra `eea.okx.com` con `x-simulated-trading: 1`
- permiso de lectura OK, **sin permiso de retirada** (regla 19)
- limitada a las bases `BTC ETH SOL XRP DOGE AVAX TRX NEAR` (quinto punto de la regla 3)
- lista blanca: solo la IPv4 del VPS
- **5 de 8 pares operables en demo** (faltan XRP, AVAX, TRX: no existen contra USDC en el
  catalogo simulado). Esperado y ya documentado.
- No caduca: OKX solo caduca por inactividad las claves de trading SIN direccion de red.
