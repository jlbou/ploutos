# Diseno de la fase 4: ejecucion en el demo de OKX

Escrito el 24/09/2026, **antes** de empezar la fase: la fase 4 va despues de la 3
("1 semana estable") y con el OK del propietario. Es un plan para discutir, no codigo. Lo que
ya se verifico sin claves esta en `docs/preparacion-fase-4.md` y aqui no se repite:
se usa.

## 1. Que pide la fase

PRD seccion 12: **"Ejecucion en el demo de OKX: OCO, idempotencia, reconciliacion,
tests de caos. Criterio: 1 semana sin descuadres."** Mas lo que fijan las reglas y el
informe:

- Regla 13: stop y objetivo **en el exchange**, creados al abrir.
- Regla 6: equity **cada 15 s** con datos del exchange (hoy, en papel, una vez por vela).
- Regla 3, cuarto punto: la whitelist se comprueba **justo antes de enviar**.
- PRD seccion 13: "el estado real es siempre el del exchange (reconciliacion al
  arrancar y cada 5 min)".
- Informe 1.6: entradas **limit post-only** (maker); `clientOrderId` derivado del
  `decision_id`; ante un timeout, **consultar antes de reintentar**.
- `CLOSE_ONLY_DEGRADED` (PRD seccion 5): datos obsoletos, errores repetidos del
  exchange, desfase del reloj. Hoy no existe: nace aqui.
- **Nada de dinero real**: solo el demo (regla del proyecto hasta la fase 7).

## 2. Como se haria (mecanica)

**Un servicio nuevo, `ploutos-exec`, el UNICO que lee las claves de OKX.** Los bucles
de papel siguen sin claves. Si el ejecutor falla, las posiciones siguen protegidas por
sus OCO en el exchange (para eso existe la regla 13).

Piezas de `execution/` (hoy vacio), en el orden en que se harian:

| # | Pieza | Que hace |
|---|---|---|
| 1 | `ids.py` | `decision_id` -> `clOrdId` alfanumerico <= 32 (quitar guiones: `d20260922T0000nearpb`) y el de su OCO (sufijo). Deterministas: trazables a mano |
| 2 | `guardia.py` | Justo antes de enviar, CUALQUIER peticion: `tdMode == "cash"` (regla 1; ccxt manda `cross` por defecto), par de la whitelist (regla 3, cuarto punto), lado y tipo esperados. Si no, no sale |
| 3 | `ordenes.py` | Entrada limit post-only con su `clOrdId`; cancelar; consultar por `clOrdId`. **Consultar antes de reenviar**: el `clOrdId` solo es unico entre ordenes pendientes |
| 4 | `proteccion.py` | Al llenarse (entera o en parte): la OCO por la cantidad REAL recibida, stop a mercado, `tdMode=cash`. Y "verificar/crear la OCO de cada posicion" (PRD seccion 5) |
| 5 | `conciliacion.py` | Al arrancar y cada 5 min: saldos, ordenes, OCO y fills del exchange contra lo local. **Gana el exchange**, se apunta y se avisa ("fallo de reconciliacion", PRD seccion 9) |
| 6 | `equity.py` | Regla 6 cada 15 s con el mejor bid del exchange (`risk/equity.compute_equity`, hoy sin usar) y la regla 7 con dos lecturas seguidas |
| 7 | Modo DEGRADED | Datos viejos, errores repetidos, reloj desfasado -> solo cierre; sale solo tras X min sano |
| 8 | El juez de la fase 4 | `scripts/check_exec.py`: compara lo que dice el exchange (fills, ordenes, OCO, saldo) con el journal local, sin reutilizar el codigo del ejecutor. **"Sin descuadres" tiene que tener juez**, como las 72 h. **El nucleo puro, hecho el 26/09** (`execution/juez.py`, 7 comprobaciones, mutacion 22/22; un test de arquitectura le prohibe importar nada de `execution/` salvo `ids`). Falta el script: pedir el historial a OKX y leer la base del ejecutor, que aun no existe |
| 9 | Tests de caos | Ver seccion 4 |

**El flujo de una entrada:**
1. El bucle decide y el motor aprueba (como hoy).
2. `guardia` -> `ordenes`: limit post-only con `clOrdId`. Timeout de red: consultar por
   `clOrdId`; solo si no existe, reenviar.
3. Se llena (entera o en parte): `proteccion` pone la OCO por lo recibido.
4. Caduca (`ENTRY_BARS_TO_LIVE`): se cancela; si se lleno en parte, esa parte ya tiene
   su OCO del paso 3.
5. La OCO salta: el exchange cancela la otra pata; `conciliacion` lo ve y cierra la
   operacion en local.

## 3. Lo que solo el demo puede decir

La lista de 8 pruebas de `docs/preparacion-fase-4.md` (seccion 8) va **primero**,
antes de escribir `proteccion.py`: de ellas depende si la OCO va adjunta a la entrada
o aparte, y si el objetivo puede ser maker. Recordatorio: el demo solo tiene 5 de los
8 pares contra USDC (BTC, ETH, SOL, DOGE, NEAR).

## 4. Tests de caos (informe 4.7, adaptados)

En el demo, cada uno con lo que tiene que pasar:

| Caos | Lo que tiene que pasar |
|---|---|
| Matar el proceso justo despues de enviar una entrada | Al arrancar, la conciliacion la encuentra por `clOrdId`; ni duplicada ni perdida |
| Matarlo con una entrada llenada y SIN OCO todavia | Al arrancar, la conciliacion ve la posicion sin proteccion y crea la OCO |
| Cortar la red al enviar (timeout) | Consulta antes de reenviar: una sola orden |
| Llenado parcial y caducidad | La parte llenada tiene su OCO; la otra se cancela |
| Errores repetidos del exchange / datos viejos | `CLOSE_ONLY_DEGRADED`; sale solo tras X min sano |
| Reloj desfasado | DEGRADED (las firmas de OKX llevan hora) |
| Cancelar a mano una OCO desde la web del demo | La conciliacion la echa en falta y la vuelve a crear |
| Cuota de Claude agotada / JSON invalido | Ya cubierto en la fase 3: QUOTA / no hacer nada |

## 5. Las decisiones del propietario

**DECIDIDAS el 24/09/2026: las cinco recomendadas. REPASADAS con el propietario el 26/09/2026: se mantienen las
cinco**, con una precision en la 1 y una sexta decision (los umbrales de DEGRADED):

- **1, precisada: el demo es un ESPEJO de la cartera de la IA en papel.** Manda a OKX las mismas ordenes
  que decide esa cartera, sin llamadas nuevas a la IA. La cartera de papel sigue siendo la que mide la fase
  6 (que empezo el 25/09 y se solapara con la fase 4) y el demo no la toca: solo prueba que la ejecucion
  real (ordenes, OCO, conciliacion) funciona. Descartadas: una cartera de la IA propia en el demo (doble
  cuota y decisiones que se separan de las de papel) y el baseline (no prueba la cadena de la IA).
- **2, 3, 4 y 5: igual.** Nuevo desde el 24/09: la idea 1 de la revision de la estrategia (entrar al
  cierre pagando taker) salio peor, lo que refuerza el post-only (3); `/kill` ya esta hecho asi (4); la
  conciliacion ya esta escrita con esa definicion de descuadre (5).
- **6 (nueva): umbrales de `CLOSE_ONLY_DEGRADED`: 3 errores seguidos del exchange, 2 s de desfase de reloj
  y 10 min seguidos sano para salir.** Los 2 s son el mismo limite que ya usa la ingesta (se habian
  propuesto 5 s: dos numeros para lo mismo). Medido en el VPS del 23 al 26/09: desfase entre -0,10 y
  -0,41 s en 864 lecturas, y cero errores del exchange. Hecho en `core/salud.py` (rama `fase-4-piezas-puras`).
  Pendiente: la ingesta sale hoy de DEGRADED al momento; se corrige al enchufar esta pieza.

**1. Que decisiones ejecuta el demo.** El demo tiene una cuenta y dos carteras de papel
(baseline e IA) no caben en una.
- **Recomendado: las de la IA**, que es la que ira a dinero real en la fase 7: se prueba
  la cadena entera (IA -> motor -> orden -> OCO -> cierre) antes de que cueste nada.
- Alternativa: las del baseline (mas predecible, sin cuota de Claude).
- En los dos casos, solo los 5 pares que tiene el demo; los otros 3 se quedan en papel.

**2. La comision en USDC (`feeType = 1`)** en la cuenta del demo (y despues en la real).
- **Recomendado: si.** La cantidad comprada es exacta, la OCO vende lo que hay y la
  contabilidad coincide con la del papel. Con la de por defecto, comprar 0,15 ETH deja
  0,14985 y hay que restar la comision en cada OCO.
- Es un ajuste de la cuenta de OKX: lo pondria el propietario, o yo con su permiso expreso.

**3. Entradas post-only** (el informe las recomienda).
- **Recomendado: si.** Son las que supone el modelo de costes (entrada maker). Contra:
  si el precio ya cruzo al enviar, OKX la rechaza y ese candidato se pierde (en el
  papel se habria llenado). Se mide en el demo cuantas pasa.

**4. `HALTED` (kill switch): cerrar las posiciones o no.** El informe lo deja
configurable.
- **Recomendado: no cerrarlas**, porque las OCO ya las protegen; cerrar a mercado en un
  momento de panico suele ser el peor precio. Se puede pedir aparte "cerrar todo".

**5. El criterio "1 semana sin descuadres"**: que cuenta como descuadre.
- **Propuesta:** cualquier diferencia entre exchange y local que la conciliacion no
  explique en la misma pasada (una orden, un fill, una OCO o un saldo), o una posicion
  sin OCO durante mas de una pasada (5 min). El juez de la pieza 8 lo mide.

## 6. Fuera de la fase 4

Dinero real (fase 7), el watchdog independiente y los comandos de Telegram (fase 5),
la interfaz (fase 5), las noticias (entre la 3 y la 6).

## Decision del 02/10/2026: el saldo virtual del demo (el propietario, opcion A)

Al comprobar la cuenta (`scripts/comprobar_cuenta_demo.py`, paso 2 del guion) salio que el demo NO tiene 50 $: tiene
los fondos por defecto de OKX (5.000 USDC, 1 BTC, 1 ETH, 50.000 XRP, 5.000 USD y 4.600 EUR). Con la regla 6 tal cual,
el equity pasaria de 100.000 $, las reglas 7, 8, 9 y 15 no medirian nada y XRP (sin par contra USDC en el demo) daria
una lectura no fiable para siempre.

**Decidido: saldo virtual.** Al arrancar, el ejecutor guarda una FOTO del saldo (en su base, para que sobreviva a un
reinicio). El dinero del bot es 50 USDC + lo que cambie desde la foto:
- equity (regla 6) = 50 + (USDC total - USDC de la foto) + sum((cantidad - cantidad de la foto) x mejor bid) -
  comisiones estimadas de salida; solo cuentan las monedas cuya cantidad haya cambiado (XRP no, si no se toca);
- la conciliacion compara los CAMBIOS de saldo con las ordenes y fills del bot;
- un movimiento a mano en el demo no lo explica ninguna orden: sale como descuadre (decision 5).

Afecta a `execution/equity.py` (rama `fase-4-piezas-puras`: hoy lee los saldos absolutos) y a la conciliacion. Sirve
igual en la fase 7 si la cuenta real tiene otros fondos (los EUR del ingreso, por ejemplo).


## Decisiones del 02/10/2026 tras las 9 pruebas del demo (el propietario, las tres recomendadas)

Resultados en `preparacion-fase-4.md` 11.

1. **El objetivo sale a mercado (taker):** OKX no admite objetivo limit en spot (`51094`). El simulador de papel y la
   M1 de la fase 6 lo cobran como maker; **no se tocan durante la muestra** y se corrigen tras el veredicto, antes de la
   segunda ronda de estrategia y de la fase 7. En el demo, la diferencia con el papel por esto es esperada.
2. **La comision se compara par por par** al arrancar (`/api/v5/account/trade-fee` con el `instId`): un par mas caro
   que lo configurado no se opera. En el demo eso deja **NEAR solo en papel** (grupo 13: 0,20 % / 0,35 %); el ejecutor
   opera BTC, ETH, SOL y DOGE.
3. **Entrada llenada a medias -> cancelar el resto en el momento** (pieza b): OKX crea la OCO adjunta por lo llenado al
   cancelar (prueba 4); mientras la entrada esta a medias, no hay stop. La conciliacion (al arrancar y cada 5 min)
   comprueba ademas que cada posicion tiene una OCO que cubre su cantidad y, si no, la crea.

## Decisiones del 02/10/2026 sobre el ejecutor (pieza c; el propietario, las cuatro recomendadas)

El demo es un espejo de la cartera de la IA en papel (decision 1, precisada el 26/09). Lo que eso quiere decir:

1. **Cantidad:** la MISMA que la orden de papel, con su precio, stop y objetivo. Las dos carteras empiezan con 50 $ y
   se separan poco (comisiones reales, NEAR solo en papel). Descartado: recalcularla con el equity del demo (ya no
   seria la misma orden).
2. **Las reglas duras otra vez, con el estado del demo:** antes de enviar cada entrada copiada, el motor de riesgo
   entero (`risk/`, las 19) con el equity, las posiciones, la perdida del dia y las operaciones del DEMO, y el mercado
   de la ingesta. Si veta, no se copia y se apunta la regla. Es lo que pide el PRD (reglas 6 y 7 con datos del
   exchange) y la convencion de cada regla en dos sitios. Descartado: copia ciega.
3. **Caducidad con reloj propio:** la misma regla que el papel (`ENTRY_BARS_TO_LIVE`: 3 velas desde que se crea), contada
   por el ejecutor. Si el papel la lleno y el demo no, el demo la cancela a su hora. Descartado: seguir al papel (una
   entrada que el papel diera por llenada quedaria viva en el demo sin nadie que la cancelara).
4. **Salidas que no son stop ni objetivo** (flag critica de noticias, "cerrar todo"): el demo cancela la OCO y vende a
   mercado con un id propio. Hace falta un tercer tipo de peticion (venta a mercado) en la guardia. Descartado: salir
   solo por la OCO (una noticia de hackeo no sacaria al demo de la moneda).

## Revision del ejecutor (03/10/2026, ya desplegado)

Leido de punta a punta tras un dia de cambios. Tres fallos, arreglados con su test (y mutacion en rojo):

1. **Vender dos veces.** Si el papel cerraba por noticias justo cuando la OCO ya habia saltado (y la conciliacion aun no
   lo habia visto), cancelar la OCO contestaba "ya no estaba" y el ejecutor vendia igual. En el demo OKX no lo habria
   impedido: la venta se habria comido el ETH de la foto (fondos que no son del bot), y en la fase 7 pasaria lo mismo
   con otros fondos. Ahora, con "ya no estaba", se mira la OCO: si salto, no se vende.
2. **Una foto nueva con posiciones del bot vivas.** Si se perdiera la base del ejecutor, al arrancar haria otra foto y
   contaria como ajeno lo que es del bot. Ahora, sin foto y con ordenes u OCO nuestras vivas en OKX, no la hace: hay que
   restaurar la base de la copia (y lo avisa, como mucho una vez por hora).
3. **Una entrada llenada por debajo de su stop** (un hueco mientras esperaba) hacia fallar cada copia: el motor no
   acepta una posicion con el stop por encima de la entrada. Ahora cuenta con riesgo cero hasta el stop.

Y una limitacion conocida, sin arreglar: si el precio de salida de una OCO hubiera que ESTIMARLO (OKX no diera la orden
que lanza), la conciliacion del USDC daria descuadre en cada pasada desde entonces. La prueba 10 dice que OKX la da; si
pasara, se veria el mismo dia (aviso de cierre con "precio ESTIMADO") y se corregiria a mano.
