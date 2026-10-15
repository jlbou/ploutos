# Hallazgos del 23 al 25/09/2026 (fase 3, piezas de la 4, noticias y operacion)

Lo que se descubrio construyendo la fase 3, las piezas puras de la fase 4 y las de noticias,
y operando el VPS, mientras la medicion de 72 h corria. Recogido de los mensajes de commit
(seccion HALLAZGOS) para que no se quede solo alli. Por tema, no por fecha. Lo de OKX y ccxt
anterior al 23/09 esta en `hallazgos-fase-0-1.md` y `preparacion-fase-4.md`; lo de `claude -p`,
en `hallazgos-claude-cli.md`.

## 1. OKX y ccxt, para la ejecucion (fase 4)

Todo verificado sin claves, con el ccxt 4.5.82 instalado y construyendo las peticiones de verdad.

- **ccxt redondea el precio AL MAS CERCANO** (`price_to_precision` usa ROUND: 65000,07 -> 65000,1)
  y la cantidad hacia abajo (TRUNCATE). Pasandole los precios del candidato tal cual, podia subir la
  entrada o bajar el stop medio tick y el riesgo real pasaria del aprobado. `execution/precios.py`
  redondea antes, cada uno hacia su lado seguro: entrada abajo, stop y objetivo arriba. El objetivo
  va arriba porque hacia abajo bajaria la recompensa y podria dejar el R:R o la regla 16 por debajo
  del minimo por medio tick. Hay un test que fija el comportamiento de ccxt.
- **ccxt mete su id de broker** (`clOrdId` y `tag`) en las OCO, ademas del `tdMode: cross` ya conocido.
  Con `{"defaultMarginMode": "cash", "brokerId": None}` construye la OCO en cash y sin nada suyo
  (`execution/guardia.py`).
- **El sufijo de la OCO va en MAYUSCULAS** (`OCO`): en minusculas, una entrada cuyo simbolo acabara
  en "o" y setup en "co" se podia leer como una OCO.
- **El "USDC libre" de OKX no sirve para la regla 6.** `availBal` excluye lo congelado por una entrada
  pendiente: cada orden bajaria el equity ~15 $ de golpe y cerca del suelo enclavaria el bot sin haber
  perdido nada. Se usa el total (`eq`); en ccxt, `balance[moneda]["total"]`, nunca `free`
  (`okx.parse_trading_balance`). La moneda bloqueada en su OCO tambien cuenta.
- **`risk.equity.compute_equity` traia taker 0,15 % por defecto** (el generico de ccxt) y no la llamaba
  nadie ni tenia tests. En la rama de la fase 3 la comision es obligatoria y hay tests (25/09).
- **Una lectura de equity sin bid** de una moneda que tenemos no cuenta para la regla 7: ni enclava ni
  borra una primera lectura mala de verdad (`execution/equity.py`).
- **Conciliacion** (`execution/conciliacion.py`): el saldo de USDC solo se compara en las pasadas en que
  no se lleno ni se cerro nada (si no, saldria un descuadre falso en cada llenado); la OCO de un llenado
  parcial se pide por lo RECIBIDO, no por lo pedido.

## 2. Los anuncios de OKX (noticias)

Medido contra el historial publico entero: 1.755 anuncios desde el 03/03/2023 (en `tests/fixtures`).

- **No dicen a que moneda afectan**: hay que leerla del titulo. Traen `annType`, `title`, `url`, `pTime`
  (milisegundos, en TEXTO) y `businessPTime`. Un tipo que no existe da `51000` con `data` vacio.
- **El tipo no basta**: "DAI Delisting" y la volatilidad de MANTRA estan en `announcements-others`.
- **Buscar la moneda sin cuidado da falsas alarmas**: Bitcoin Cash no es BTC, Ethereum Classic no es
  ETH, "ether.fi (ETHFI)" tampoco, y "BTC/USDK" o "ADA/BTC" no son nuestros pares. Solo cuenta X/USDC.
- **"margin" es ruido, salvo si el titulo dice "spot"**: "delist X spot and margin trading pairs" si
  nos afecta.
- **OKX nunca ha anunciado un hackeo** en 3,5 anyos: eso solo lo darian los medios, mucho mas ruidosos.
  Por eso van en una segunda etapa y en sombra (decision del propietario).
- **Resultado:** con las reglas, 0 falsas alarmas para nuestras 8 monedas; en todas, 61 deslistados,
  87 migraciones, 4 avisos de volatilidad y 2 suspensiones detectados.
- **Las flags cuentan desde la publicacion**, no desde que se vieron: tras una parada, un aviso de
  volatilidad de hace dos dias ya ha caducado.
- **El filtro ya existia**: `strategy.filters.filter_event` esta desde la fase 2 y mira
  `RiskState.event_flags`, que nadie llenaba. Faltaba el puente, no el filtro.
- **El titulo es texto de fuera**: en Telegram va siempre escapado y el enlace solo sale si es https de
  okx.com (`okx.com.evil.example` no pasa).
- CryptoPanic (25/09): **sin plan gratuito** desde 2026; el mas barato, 199 $/mes. CoinGecko tiene plan
  gratuito pero no noticias (serviria, como mucho, de control independiente de la paridad de USDC).

## 3. La IA en el bucle y su journal (fase 3)

- **`model: sonnet` es un alias**: el modelo real puede cambiar por debajo sin tocar nada. El journal
  guarda el de `modelUsage` y la huella del camino de decision (prompt, esquema, modelo pedido, CLI,
  estrategia, riesgo, comisiones). Que el CLI devuelva `modelUsage` esta SIN verificar: se comprueba en
  la llamada real del paso 8 del despliegue.
- **La huella quita los CR** del prompt de sistema: en Windows el .md puede salir con CRLF y la huella
  del portatil no coincidiria con la del VPS.
- **Los `open` se prueban en el orden del modelo**, no por confianza (el disenyo decia confianza, pero
  el parser la registra sin usarla).
- **El bucle no se fia del parser**: un multiplicador fuera de [0,5; 1] o un candidato de otra vela no
  llegan al simulador.
- **El servicio de la IA no puede llevar** `MemoryDenyWriteExecute` (el CLI tiene JIT) ni
  `ProtectHome=true` (el CLI vive en /home/ploutos).
- **Una sola hora para el presupuesto**: el juez cuenta la regla 18 con `called_ms`; el decisor tiene
  que usar el mismo instante que el presupuesto, o las ventanas de 5 h podrian diferir.

## 4. Como se medira si la IA aporta (fase 6)

- **Con la cartera llena no hay candidatos**: el papel en vivo vio 5 en 3 dias y ninguno desde el 23/09
  12:00. La muestra crece mas despacio de lo supuesto.
- **M1 es una SUMA por vela**, no una media: con la media, saltar todo no valia nada, y no abrir nada
  cuando los candidatos son malos es acertar.
- **El R:R del prompt va redondeado** a 2 decimales y podia reordenar empates: el juez lo recalcula de
  los precios, y un test compara su orden con el de `strategy.baseline.rank`.
- **Una parada del baseline no quita muestra**: su eleccion se recalcula sobre la lista que vio la IA.
- **Cuanto se equivoca la regla**: una IA al azar sale "aporta" 6 de cada 200 veces y "perjudica" 7
  (intervalo del 90 %). Lo mas probable al final de la fase 6 es "no concluyente": con 30 discrepancias
  solo se veria una ventaja del orden de +0,7 R por decision.

## 5. El VPS y la operacion

- **`NRestarts` no cuenta los reinicios de `needrestart`**: para saber si un servicio se reinicio,
  `ActiveEnterTimestamp`.
- **`needrestart` reinicia solo** (modo `'a'` en el gancho de APT) y `Automatic-Reboot` estaba sin
  poner: los parches del nucleo se instalan y no se aplican. Paso el 25/09: nucleo 6.8.0-142 instalado,
  maquina en el 139, solo el rastro de `/var/run/reboot-required`. Decidido: reinicio automatico a las
  07:15 UTC cuando haga falta.
- **La ventana de actualizaciones (06:00-07:00 UTC) cae entre dos cierres de vela** (04:00 y 08:00): un
  reinicio de servicios ahi no hace perder ninguna decision.
- **`main` no era exactamente lo desplegado**: difieren `check_gaps.py` (`--db`/`--until`; sin opciones
  juzga igual) y el recuento del log de `backup.sh`. Nada cambia lo que se mide.
- **La ingesta solo late si ha GUARDADO** lo que recibe (no basta con recibirlo). La lectura va en el
  mismo hilo: la conexion a la base es compartida.
- **Los tests no pueden ver credenciales de verdad**: sin la guarda de `conftest`, pasar los tests
  mandaria Telegrams y latidos reales (un latido de test taparia una caida real).
- **Las copias bajadas al portatil llevan la fecha de la descarga**: la frescura se lee del nombre.
- **Renombrar una base en WAL y borrar su `-wal` pierde lo ultimo escrito**: antes, `wal_checkpoint`.
- **Chrome sin ventana, con un perfil propio** (`--user-data-dir`), convierte SVG a PNG sin dependencias
  nuevas; sin el perfil propio, el Chrome abierto se queda la peticion.

## 5a. El despliegue de la fase 3 (25/09)

- **Algunas redes del propietario cortan el puerto 22** (y el ping): el VPS parecia caido y no lo
  estaba. Se distingue probando SSH contra GitHub por el 22 (falla) y por el 443 (entra).
- **`install-claude.sh` pasaba `DISABLE_UPDATES=1` al instalador**: contesta "Updates are disabled by
  your administrator", no instala nada y dice "Installation complete". Arreglado y con test.
- **`StartLimitIntervalSec` estaba en `[Service]`** en todos los servicios desde la fase 1: systemd lo
  ignora (solo avisa en el journal). Sin efecto real (con `RestartSec=10` el limite por defecto no
  saltaba nunca). Movido a `[Unit]`, con test, y recargado sin reiniciar nada.
- **Memoria de una llamada en el VPS: 230 MB** (en el portatil, 382-409): mucho margen con 2 GB + 1 GB
  de swap. Con las dos carteras y la ingesta en marcha quedan ~1,1 GB libres.
- **El alias `sonnet` es hoy `claude-sonnet-5`**, y el CLI usa tambien Haiku 4.5 para algo interno.
- **Reinicio con el nucleo nuevo: menos de 1 min**; la ingesta relleno el hueco y `check_gaps --hours 2`
  salio al 100 % (el aviso "sin historia" de 4 h en una ventana de 2 h es esperado).

- **26/09 06:11 UTC, parche de seguridad de `libexpat1`:** `needrestart` reinicio los CINCO servicios (Python
  usa expat). Volvieron en 4 s, entre dos cierres de vela: nada perdido. El propietario recibio solo el "parado" de las
  carteras; desde ese dia, cada "parado" va seguido de su "en marcha de nuevo" (decision del propietario). Probado
  en vivo a las 06:59 reiniciando las dos carteras: los cuatro avisos salieron.

## 5b. La historia de precios que hay (medido el 25/09, API publica de OKX EEA)

Para revisar la estrategia y para el bucle de aprendizaje (docs/archivo/diseno-aprendizaje.md, etapa 1).
Primera vela diaria de cada par (busqueda binaria sobre `history-candles`); las de 4 h y 1 h llegan
igual de atras (comprobado con BTC 2018 y NEAR 2021):

| Moneda | contra USDC | contra USDT |
|---|---|---|
| BTC, ETH | 20/08/2025 | 10/10/2017 |
| XRP, TRX | 20/08/2025 | 10/01/2018 |
| DOGE | 20/08/2025 | 14/07/2019 |
| SOL | 20/08/2025 | 29/09/2020 |
| AVAX | 09/10/2025 | 22/09/2020 |
| NEAR | 25/02/2026 | 02/12/2020 |

- **Contra USDC solo hay un anyo** (por eso el estudio del time-stop empieza el 21/08/2025): no se puede
  estirar.
- **Contra USDT hay de 5 a 8 anyos**, con los mercados bajistas de 2018 y 2022. No se pueden operar
  (regla 3), pero sirven para buscar patrones: se multiplica la muestra por 5-8.
- **Cuanto se parecen** (cierres de 4 h, 300 velas en dos tramos): diferencia media 0,05-0,14 % en
  BTC y ETH, 0,07-0,17 % en SOL, 0,13-0,22 % en DOGE y 0,36 % en NEAR (maximo 2,2 %; el par contra USDC
  de NEAR era muy poco liquido al empezar). Con stops del ~3,3 % y costes del ~0,3 % es un sustituto
  razonable para EXPLORAR, no para dar por buena una entrada al precio exacto: la parte reservada de
  la comprobacion final deberia ser con USDC.

## 5c. El bucle procesaba una vela con monedas que aun no habian cerrado (28/09)

- **Sintoma:** la noche del 28/09 el juez de papel dio FALLA en las dos carteras: la equity de la vela del
  27/09 04:00 era 50,398 $ (baseline) y 50,066 $ (IA); recalculada, 50,263 $ y 50,119 $.
- **Causa:** `run_paper._closed_bars_after` daba una vela por lista en cuanto UNA moneda la tenia cerrada. La
  ingesta escribe las ocho en ~1,5 s despues del cierre y el bucle miro en medio (08:00:01): el baseline
  proceso sin DOGE ni XRP; la IA, sin DOGE. Reproducido al centimo: esas posiciones se valoraron a precio de
  entrada. Peor que la cifra: para esas monedas no se miro el stop ni el objetivo de la vela, y el generador
  de candidatos vio la vela anterior.
- **Dano:** ninguno en decisiones. En esa vela ni DOGE (minimo 0,0954, stop 0,0921) ni XRP (1,506, stop 1,488)
  tocaron el stop, y con las carteras llenas no hubo candidatos. Solo esa vela de 16 desde el 26/09.
- **Arreglo (desplegado el 28/09 07:47 UTC, con OK del propietario):** la vela se procesa cuando estan las ocho; si
  falta alguna 2 min despues del cierre, con las que hay y un aviso en el log (el bucle no puede quedarse
  parado por una moneda). No cambia la huella del camino de decision: la muestra de la fase 6 no se parte.
- **La fila, corregida (decision del propietario del 28/09):** copia antes en
  `/var/backups/ploutos/ploutos-paper{,-ai}-antes-correccion-20260928.db` (VACUUM INTO, servicios parados) y
  solo `paper_equity.equity_usd` de ts 1790481600000: 50,3980337286 -> 50,2632139086 (baseline) y
  50,0662115808 -> 50,1193267376 (IA), con la formula del juez (cierre de la vela, maker 0,10 %, taker 0,20 %).
  Despues, los seis jueces sin FALLA.
- **Leccion:** el juez de papel lo cazo solo porque habia posiciones en esas monedas. Si no las hubiera
  habido, el unico efecto (candidatos con la vela anterior) no lo ve ningun juez.

## 5d. OKX unifica los libros en dolares: adios a `X-USD` (30/09/2026, investigado el 01/10)

**Que paso.** El 30/09 OKX retiro los instrumentos `Crypto-USD` y los junto con los
`Crypto-USDC` en un solo libro, el "Unified USD Orderbook". Changelog de la API (2026-09-30): las peticiones que usaban
`Crypto-USD` tienen que usar el `Crypto-USDC` correspondiente. **Cuando, en la EEA:** entre las 08:00 y las 12:00 UTC (BTC-USD aun respondia al procesar
la vela de las 04:00, a las ~08:00, y ya no a las 12:00); el anuncio de OKX US dice de 07:00 a 08:00 UTC. El aviso que encontramos es de OKX US; la FAQ de OKX
Europe describe el mismo libro unificado, y en la API publica `eea.okx.com` (real y DEMO) `BTC-USD` ya no existe
(`51001`). **No salio en ningun tipo de anuncio de la API `support/announcements` de la EEA** (los 10 tipos, desde
el 01/09): por eso el servicio de noticias no podia verlo. Lo que si sale son anuncios de "X/USD" nuevos (CT/USD,
EURC/USD...): "X/USD" es el NOMBRE en pantalla del libro unificado, cuyo `instId` es `X-USDC`.

**Como queda (medido el 01/10 en `public/instruments`, real y demo iguales):**

| `instId` | `tradeQuoteCcyList` (con que se puede pagar) |
|---|---|
| `X-USDC` (298 pares, los 8 de la whitelist) | `USDG`, `USD`, `USDC`, `RLUSD` |
| `USDT-USD` (el unico contra USD) | `USDG`, `USD`, `RLUSD` (sin USDC desde el 20/05/2026) |
| `USDC-USDT` | `USDT` |
| `X-EUR` | `EURC`, `EUR` |

- **`tradeQuoteCcy`**, al enviar una orden: "por defecto, la moneda de cotizacion del `instId`". En `X-USDC`, USDC: lo
  que queremos. El changelog no dice si vale tambien para las ordenes algoritmicas (OCO).
- **El libro trata USD, USDC, USDG y RLUSD como 1:1** ("pegged 1:1 with USD", convierte por dentro, sin comision
  extra). La FAQ no dice que pasa si una de esas monedas se despega.

**Lo que cambia para el bot:**
1. **Regla 3 y la whitelist: nada.** Los 8 `X-USDC` siguen `live`.
2. **Regla 17: ya arreglado** (01/10, solo A). `USDC-USDT` es un mercado aparte (solo USDT) y `USDT-USD` no acepta
   USDC: A sigue midiendo el USDC contra algo que no es el mismo.
3. **Precio de las 8:** desde el 30/09 el libro `X-USDC` mezcla compradores en USD, USDC, USDG y RLUSD, y deberia
   ser MAS profundo (lo que dice OKX). Si una de esas monedas se despegara, el precio de ese libro dejaria de ser
   "en USDC" puro: otro motivo para que la regla 17 vigile el USDC por fuera del libro.
4. **Fase 4 (propuesta para el propietario, sin hacer):** (a) mandar `tradeQuoteCcy: "USDC"` EXPLICITO en entradas y OCO, y que la
   guardia rechace cualquier otra (como `tdMode: cash`): si OKX cambiara el valor por defecto, se pagaria con otra
   moneda sin decirlo; (b) una **prueba 9 en el demo**: entrada y OCO en `X-USDC` con y sin `tradeQuoteCcy`, y
   comprobar que se paga y se cobra en USDC (saldo, comision y cantidad).
5. **Herramientas viejas:** `verify_okx_pairs.py --also-quote USD` y la comparacion X/USD contra X/USDC de
   `analyze_spread.py` ya no tienen par que medir (eran de la fase 0; decidido el 22/09 que no compensaba).

Fuentes: [changelog de la API](https://www.okx.com/docs-v5/log_en/), [anuncio de OKX US](https://www.okx.com/en-us/help/okx-is-consolidating-usd-and-usdc-spot-order-books-effective-september-30-2026),
[FAQ del libro unificado, OKX Europe](https://www.okx.com/en-eu/help/unified-usd-orderbook-faq-sg).

## 6. Sobre el proceso

- **El patron "escrito y sin enchufar" sigue apareciendo**: `compute_equity` (sin llamadas ni tests) y
  `filter_event` (sin datos). Al construir una pieza, buscar primero si ya existe algo que la haga.
- **Contar antes de escribir**: dos mensajes de commit ya subidos llevan el numero de tests mal (853 por
  852; 866 por 858) y uno se hizo con un test en rojo (corregido antes de subir). No se reescriben;
  la correccion va en el commit siguiente.
- **Hypothesis se para si filtra demasiado** (`FailedHealthCheck`): con rangos realistas por moneda en
  vez de uno comun, deja de descartar casos.
- **Una prueba estadistica se juzga por su tasa de error, no por un caso**: la IA al azar salio "aporta"
  con una semilla concreta, y era lo esperado 1 de cada 30 veces.
- **Repositorio publico** (revision del 25/09): ningun secreto ni la IP en los 187 commits; el correo
  personal firma todos. En espera, ver CLAUDE.md.
