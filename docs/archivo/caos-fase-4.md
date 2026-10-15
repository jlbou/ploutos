# Tests de caos de la fase 4, en el demo

Paso 8 del guion (`docs/archivo/guion-fase-4.md`); la tabla sale de `docs/archivo/diseno-fase-4.md` seccion 4. Se hacen DURANTE la
semana del demo (que cuenta desde el 03/10 10:16:28 UTC): bien hechos, **ninguno deja un descuadre**, porque cada uno
es justo lo que el ejecutor tiene que saber explicar. Si alguno deja uno, el juez de la noche lo vera y la semana
vuelve a empezar: eso es lo que se quiere saber.

## Como se comprueba cada uno

En el VPS (sin hablar con OKX):

```bash
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/run_exec.py --status'
ssh ploutos 'journalctl -u ploutos-exec --since "-15min" --no-pager -o cat | cut -c1-200'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos sqlite3 "file:var/ploutos-exec.db?mode=ro" "SELECT datetime(ts_ms/1000,\"unixepoch\"), cuadra, descuadres FROM exec_pasadas ORDER BY ts_ms DESC LIMIT 5;"'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/check_exec.py'     # el juez, a mano
```

Y en el panel: el panel "Demo de OKX" (modo, conciliacion, la OCO de cada posicion).

**Avisos esperados:** los cambios de modo del demo llegan por Telegram ("Demo · Entra en CLOSE_ONLY_DEGRADED...").
Healthchecks solo avisa si el ejecutor no late en 20 min (5 + 15): los tests de abajo duran menos.

## Los tests

| # | Caos | Cuando | Quien | Como | Lo que tiene que pasar |
|---|---|---|---|---|---|
| 1 | Matar el proceso con una ENTRADA viva en OKX | con una entrada copiada y aun sin llenar | yo | `systemctl kill -s KILL ploutos-exec` (systemd lo relanza a los 10 s) | Arranca con la MISMA foto; la entrada sigue en OKX y en la base, **una sola** (consultar antes de reenviar); la primera pasada cuadra |
| 2 | Matar el proceso con una POSICION abierta | con una posicion con su OCO | yo | igual que el 1 | La OCO sigue en OKX (el ejecutor no la toca); la primera pasada cuadra; el equity sale igual que antes de matarlo |
| 3 | Sin red (timeouts) | mejor con una posicion abierta y SIN entradas pendientes (DEGRADED las cancela: PRD 5) | yo | cortar la red SOLO al ejecutor 90 s: `systemctl set-property --runtime ploutos-exec IPAddressDeny=any`, y despues `IPAddressDeny=` (vacio). La ingesta y las carteras no se enteran | A los 3 errores seguidos (~45 s), `CLOSE_ONLY_DEGRADED` y aviso; al volver la red, **10 min seguidos sano** y sale (aviso); la OCO, intacta en OKX; ninguna orden duplicada; la primera pasada tras volver cuadra |
| 4 | Errores repetidos del exchange | el mismo que el 3 | yo | el 3 lo cubre (cada vuelta sin red es un error del exchange) | igual que el 3 |
| 5 | Cancelar A MANO una OCO desde la web del demo | con una posicion abierta | **el propietario** (web del demo, Trading > Ordenes > Algoritmicas: cancelar la OCO de la posicion) | yo miro | En la pasada siguiente (<= 5 min) la conciliacion la echa en falta y la crea otra vez con el mismo id; el panel pasa por "SIN OCO" y vuelve a "OCO viva"; **no es descuadre** (decision 5: solo lo es si sigue sin OCO en la pasada siguiente). Si el precio ya hubiera pasado el stop o el objetivo, vende a mercado (decision del 03/10) |
| 6 | Llenado parcial y caducidad | cuando pase solo | - | no se puede forzar: el libro del demo se repone al momento (prueba 4b del 02/10) | Parcial: el resto se cancela en <= 15 s y OKX crea la OCO por lo llenado (prueba 4 del demo; tests del ejecutor). Caducidad: la entrada se cancela a las 4 velas de su `created_ts_ms` |
| 7 | Reloj desfasado | - | - | **no se hace en el demo**: mover el reloj del VPS afectaria a la ingesta y a las dos carteras de la fase 6 | Cubierto por los tests de `core/salud.py` (2 s, el mismo limite que la ingesta) y por la vuelta del ejecutor, que mira la hora de OKX en cada pasada |
| 8 | Reinicio del servicio o del VPS | cuando toque (las actualizaciones reinician a las 07:15 si un parche lo pide) | - | `systemctl restart ploutos-exec` es el 1-2 sin el KILL | igual que el 1 y el 2 |
| 9 | Cuota de la IA agotada / JSON invalido | - | - | ya cubierto en la fase 3 | la cartera de la IA no decide; el demo no recibe nada que copiar |

**Orden propuesto:** el 3 ahora mismo (no hay nada abierto: prueba la red y DEGRADED sin arriesgar ninguna copia);
el 1 con la primera entrada copiada; el 2 y el 5 con la primera posicion (el 5 lo hace el propietario); el 6 y el 8, cuando pasen.

**Decision del propietario (11/10/2026), los caos 1 y 6:** se quedan apuntados (opcion a). No se pueden forzar: el 1 pide una
entrada copiada viva en el demo (con el mercado bajista, la estrategia de 4 h no da candidatos) y el 6, un llenado
parcial (el libro del demo se repone al momento). Si antes del veredicto de la fase 6 aparece una entrada en el demo,
se hace el 1 (~10 min, avisando al propietario antes de parar `ploutos-exec`). **L tendra sus propios caos** si se construye
(parar a mitad de rotacion, que falle la venta tras cancelar la OCO, que OKX rechace la OCO): esos si se pueden
provocar en el demo.

## Resultados

| # | Fecha (UTC) | Lo que paso | Descuadre |
|---|---|---|---|
| 3 | 03/10 10:45:46-10:47:16 | Red cortada SOLO al ejecutor 90 s (`IPAddressDeny`, comprobado: `0.0.0.0/0 ::/0`). Errores al leer OKX a las 10:46:08, 10:46:23 y 10:46:38: **DEGRADED a las 10:46:38** (52 s). El aviso de Telegram no salio sin red; quedo en la base y salio al volver (10:47:24). Primera vuelta sana 10:47:23; **sale de DEGRADED a las 10:57:32** (10 min) con su aviso. Pasadas 10:41, 10:47, 10:52 y 10:57: **todas cuadran**; hueco 5 min 44 s (< 15). 0 reinicios; la ingesta y las carteras, sin un error. No habia nada abierto (la OCO intacta se ve en el 2) | no |
| 1 | | | |
| 2 | 03/10 14:46:59 | `SIGKILL` con ETH y SOL abiertas (adoptadas) y sus 2 OCO vivas. systemd lo relanza a las 14:47:09 (10 s, `NRestarts` 1). Arranca con la MISMA foto (10:16:28); las dos posiciones, iguales; la primera pasada (14:47:14) **cuadra** sin ninguna accion; 0 peticiones a OKX nuevas; las 2 OCO siguen vivas; equity 49,87 -> 49,88 $; 0 errores. Sin aviso de parada ni de arranque (un KILL no es una parada limpia: lo cubre Healthchecks si no volviera) | no |
| 5 | 03/10 ~14:50 (el propietario) | el propietario cancela desde la web del demo la OCO de SOL (a OKX le queda 1 viva). Pasada de las 14:52:22: `crear_oco` de SOL con el mismo `algoClOrdId` y la misma cantidad (`enviada`), SOL en `sin_oco` de esa pasada, **cuadra**; pasada de las 14:57:29: **cuadra**, sin acciones; 2 OCO vivas. **Hallazgo:** el objetivo volvio como 134 y no 134,1 (ccxt redondea al mas cercano; podria bajar un stop): arreglado el mismo dia, la OCO rehecha va al tick hacia arriba | no |
| 6 | | | |
| 8 | 06/10 21:56:06-21:56:12 | Hecho A PROPOSITO (no hacia falta esperar a un reinicio de las 07:15). `systemctl restart ploutos-exec` con ETH y SOL abiertas y sus 2 OCO vivas: "parado limpiamente" a las 21:56:06, en marcha a las 21:56:12 (6 s), la MISMA foto (03/10 10:16:28); la primera pasada (21:56:12) **cuadra** sin ninguna accion y sin posiciones sin OCO; equity 50,089 $ antes y despues (identico); hueco entre pasadas 3 min 18 s (< 15); los dos avisos de Telegram ("parado" y "en marcha de nuevo") enviados al momento | no |

**Visto en el 3 y arreglado el mismo dia:** el ejecutor mandaba "ploutos-exec parado" al pararse limpiamente, pero no
el "en marcha de nuevo" al volver (los servicios de papel si). Desde el 03/10 lo manda como ellos.
