# Parada de mantenimiento antes de la fase 4 (guion, preparado el 28/09/2026)

Lo decidido con el propietario el 27/09 (primer aviso de actualizaciones): **ccxt, justo ANTES de empezar la fase 4, con los
tests; los paquetes de Ubuntu que no son de seguridad, en una parada elegida**, porque `needrestart` reiniciaria los
servicios. **El programa de la IA (2.1.266) NO se toca** hasta el veredicto de la fase 6: partiria la muestra.

Cuando: despues del OK del propietario a la fase 4 (02/10) y antes de desplegarla. Duracion: 30-40 min.

## 1. Que se actualiza

| Pieza | De | A | Probado |
|---|---|---|---|
| ccxt (el `.venv` del bot) | 4.5.82 | 4.5.84 | 28/09, en el portatil (seccion 2) |
| apparmor, libapparmor1 | 4.0.1really4.0.1-0ubuntu0.24.04.7 | ...24.04.8 | no hace falta: no los usa el bot |
| dmidecode | 3.5-3ubuntu0.1 | 3.5-3ubuntu0.2 | idem |
| libaudit-common, libaudit1 | 1:3.1.2-2.1build1.1 | 1:3.1.2-2.1ubuntu0.1 | idem |
| linux-firmware-amd-graphics | ...0ubuntu3.2 | ...0ubuntu3.3 | idem (el VPS no tiene grafica) |

Los de SEGURIDAD que estaban pendientes el 28/09 (`dracut-install`, `python3-jwt`, `python3-requests`) los instalan
solas las actualizaciones automaticas: no entran aqui. `python3-jwt` y `python3-requests` son del Python del sistema;
el bot usa su `.venv` y no los carga. **Repetir `apt list --upgradable` el dia de la parada**: la lista cambia.

## 2. ccxt 4.5.84: lo que se probo (28/09, portatil, `.venv` aparte en `var/prueba-ccxt/`)

- **Tests:** `main` 1308 en verde y la rama `fase-4-piezas-puras` 1392 en verde, con 4.5.82 y con 4.5.84.
- **Las peticiones a OKX, identicas:** las 48 que construye `execution/peticiones.py` (compra post-only y OCO de las
  8 monedas a tres precios cada una) salen byte a byte iguales con las dos versiones: `tdMode: cash`, `ordType: oco`,
  `slOrdPx: -1`, los mismos ids y el mismo redondeo al tick.
- **Lo que cambia en `okx.py`** (diff de los dos paquetes): casi todo, anotaciones de tipos. Cambios de conducta:
  1. el parametro `trigger`/`stop` de `cancel_order`, `fetch_order` y `fetch_open_orders` solo cuenta si es el
     booleano `True` (antes valia cualquier cosa no nula: `trigger=False` se tomaba por orden trigger en
     `cancel_orders`). El bot no lo usa: cancela con `algoClOrdId`/`clOrdId` (`peticiones.cancelar_*`);
  2. `stopLoss`/`takeProfit` como parametro tienen que ser diccionarios. El bot no los usa: la OCO va con
     `stopLossPrice`/`takeProfitPrice`;
  3. `create_orders` lee cantidad y precio como numeros. El bot no lo usa.
- **No parte la muestra de la fase 6:** ccxt no entra en la huella del camino (`ai.journal.camino`). Se comprueba en
  el paso 6 igualmente.
- **Aviso que NO es de ccxt** (sigue pendiente, `preparacion-fase-4.md` seccion 6): la OCO sale con `tpOrdPx: -1`, el
  objetivo a mercado (taker), y el modelo lo cobra como maker. Probar `tpOrdKind = limit` en el demo.

## 3. Antes de empezar

1. **La ventana:** justo despues de que las DOS carteras procesen una vela de 4 h (se hace a las HH:00:30 de las 00,
   04, 08, 12, 16 y 20 UTC) y la IA haya contestado (hasta ~1 min). Quedan ~3 h 50 min hasta la siguiente. Evitar
   las 00:30 (jueces), las 03:15 (copia), el domingo a las 07:30 (actualizaciones) y las 07:15 (posible reinicio).
   ```bash
   ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/run_paper.py --status | head -5'
   ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python scripts/run_paper_ai.py --status | head -5'
   ```
2. **Copia a mano de las cinco bases** y comprobar que ha ido bien:
   `ssh ploutos 'systemctl start ploutos-backup && ls -lt /var/backups/ploutos | head -6'`
3. **Jueces limpios ANTES** (tardan ~10 min en el VPS): `sudo -u ploutos .venv/bin/python scripts/jueces_diarios.py --seco`
4. **Apuntar el estado de partida:** versiones y huella.
   ```bash
   ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python -c "import ccxt; print(ccxt.__version__)"'
   ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python -c "from core.config import load_settings; from ai.journal import camino; print(camino(load_settings()))"'
   ```
   La huella tiene que ser `f063d80147a9` (el tramo de la fase 6).

## 4. ccxt

1. En el portatil, fijar la version en `pyproject.toml` (`"ccxt==4.5.84"` en vez de `>=4.5.0`): asi `install.sh`
   instala la probada y no la ultima. Commit, push y `sync.sh` (o `scp` por Tailscale).
2. En el VPS: `sudo -u ploutos /opt/ploutos/.venv/bin/python -m pip install ccxt==4.5.84`
3. Tests en el VPS: `cd /opt/ploutos && sudo -u ploutos .venv/bin/python -m pytest -q` (ruff se salta alli). Todo en
   verde o se vuelve atras (seccion 8) sin reiniciar nada.

## 5. Paquetes de Ubuntu

Con `needrestart` en modo LISTA, para que no reinicie los servicios por su cuenta y en cualquier orden:
```bash
ssh ploutos 'NEEDRESTART_MODE=l apt-get install -y --only-upgrade apparmor libapparmor1 dmidecode libaudit-common libaudit1 linux-firmware-amd-graphics'
ssh ploutos 'needrestart -b; ls /var/run/reboot-required 2>/dev/null'
```
Si aparece `/var/run/reboot-required`, reiniciar AHORA el VPS, a mano y con la ventana abierta, y no esperar al de
las 07:15 (seccion 7 comprueba que todo vuelve).

## 6. Reiniciar, en orden

La ingesta primero (el resto lee su base) y las carteras despues:
```bash
ssh ploutos 'systemctl restart ploutos-ingest'
# esperar a que las 8 monedas tengan velas de 1 m frescas (el backfill las rellena solo)
ssh ploutos 'systemctl restart ploutos-paper ploutos-paper-ai ploutos-news ploutos-telegram ploutos-panel'
ssh ploutos 'systemctl restart ploutos-spread-extra'     # solo hasta el 09/10
```

## 7. Comprobar

1. Los servicios, arrancados DESPUES de empezar la parada (`NRestarts` no cuenta estos reinicios):
   `ssh ploutos 'systemctl show ploutos-{ingest,paper,paper-ai,news,telegram,panel} -p Id -p ActiveState -p ActiveEnterTimestamp'`
2. `ccxt.__version__` = 4.5.84 y **la huella sigue siendo `f063d80147a9`** (paso 3.4). Si cambia, parar y avisar: se
   habria partido la muestra.
3. El panel responde (`curl -s -o /dev/null -w "%{http_code}" http://ploutos.example.ts.net:8765/api/foto` = 200)
   y las seis comprobaciones de Healthchecks siguen en verde.
4. La siguiente vela se procesa en las dos carteras con las ocho monedas (sin la fila "sin la vela de esta hora").
5. Jueces en seco, limpios otra vez.

## 8. Volver atras

- ccxt: `sudo -u ploutos /opt/ploutos/.venv/bin/python -m pip install ccxt==4.5.82` y reiniciar ingesta, carteras y
  noticias. Deshacer el cambio de `pyproject.toml`.
- Los paquetes de Ubuntu no se desinstalan: no los usa el bot. Si uno rompe algo del sistema, `apt-get install
  <paquete>=<version anterior>` con la version de la tabla de la seccion 1.
- Las bases, con la copia del paso 3.2 (nunca con `cp` de una base en uso: `VACUUM INTO` o la copia comprimida).

## 9. Hecha el 02/10/2026 (13:56 - 14:03 UTC, a peticion del propietario, tras su OK a la fase 4)

- **Antes:** las dos carteras al dia (vela de las 08:00), en NORMAL, sin entradas pendientes; copia a mano de las
  cinco bases (13:57); jueces en seco sin FALLA; ccxt 4.5.82; huella `f063d80147a9`.
- **ccxt 4.5.84:** fijada en `pyproject.toml` (`==4.5.84`); portatil 1365 tests y VPS 1355 en verde ANTES de
  reiniciar nada.
- **Los 6 paquetes** de la seccion 1, con `NEEDRESTART_MODE=l`: instalados; sin `reboot-required` (el nucleo no
  cambio). `needrestart` lista servicios DEL SISTEMA con librerias viejas en memoria (cron, dbus, ssh, journald,
  logind, systemd, networkd, resolved, unattended-upgrades): **no se reiniciaron**, a proposito: no son de seguridad
  y reiniciar la red o dbus podia cortar Tailscale con la sesion dentro. Se ponen al dia en el proximo reinicio.
- **Fuera del guion, sin instalar:** el 02/10 la lista traia ademas el nucleo 6.8.0-146 (y sus cabeceras),
  `sosreport` y `thermald`, todos de `noble-updates` y NO de `noble-security`. Si llegan como seguridad, los instala
  `unattended-upgrade` y el VPS se reinicia a las 07:15 UTC (decision del 25/09).
- **Reinicio en orden:** ingesta 14:01:54 (las 8 monedas con velas de 1 m nuevas a los ~25 s; backfill de 301 velas
  por timeframe); despues papel, IA, noticias, comandos y panel (14:02:40-42) y `spread-extra`.
- **Despues:** todos activos, ccxt 4.5.84, **huella `f063d80147a9` (la muestra no se parte)**, panel 200, jueces en
  seco sin FALLA, las carteras con el mismo estado que antes. Queda por ver la vela de las 12:00 (se procesa a las
  16:00 UTC) con las ocho monedas.

## 11. ccxt 4.5.85: INSTALADA el 10/10/2026 (10:39 - 10:46 UTC, a peticion del propietario, con la fase 4 cerrada)

- **Antes:** `pyproject.toml` a `==4.5.85` (`88111d3`); portatil y VPS, **1634 tests en verde** con 4.5.85 antes de
  reiniciar nada. Las dos carteras en NORMAL, vela de las 04:00 procesada, una posicion cada una (AVAX), sin
  pendientes; el demo en NORMAL, 49,13 $, cuadra.
- **Reinicio en orden:** ingesta 10:43:19 (backfill de 301 velas por timeframe, 0 huecos, WebSocket a las 10:43:56);
  papel, IA, noticias, comandos y panel (10:44:01-04); el ejecutor del demo 10:44:15 (parado ~10 s; conciliacion a
  las 10:44:20, cuadra). `ploutos-medios` no usa ccxt: no se toco.
- **Despues:** todos activos; **huella `f063d80147a9`** (la muestra no se parte); los diez jueces en seco sin FALLA;
  panel 200; las carteras con el mismo estado que antes.

## 10. ccxt 4.5.85: probada el 06-07/10 en el portatil (instalada el 10/10: seccion 11)

Aplazada hasta DESPUES de la semana del demo (decision del 04/10). Probada en `var/prueba-ccxt/venv` (el `.venv` del
proyecto sigue en 4.5.84; ese entorno se borro el 07/10 para liberar espacio: se rehace con `python -m venv` y
`pip install -e . ccxt==4.5.85`):
- **Tests:** 1604 en verde con 4.5.85 (los mismos que con 4.5.84).
- **Peticiones a OKX, identicas** (`scripts/comparar_peticiones_ccxt.py`, mercados de los datos publicos guardados una
  vez y el envio interceptado, sin claves de verdad): 24 casos (las 8 monedas a tres precios) y **144 peticiones ya
  SERIALIZADAS** (entrada con stop y objetivo adjuntos, OCO, venta a mercado, las dos cancelaciones y la consulta):
  metodo, URL y cuerpo byte a byte iguales, y el redondeo de precio y cantidad. La cabecera del demo
  (`x-simulated-trading: 1`) sale igual en las dos.
- **Lo que cambia por dentro** (`scripts/diff_ccxt.py`, solo las funciones que usa el bot, sin anotaciones): una
  reescritura que deja de modificar `params` en sitio, y guardas nuevas (`nonce()` exige `timeDifference` numerico,
  por defecto 0; `parse_market` descarta mercados sin base o cotizacion; errores de precision con `BadSymbol` si falta
  la precision). `fetch2` sigue con **0 reintentos por defecto** (el bot nunca reintenta a ciegas). Iguales:
  `fetch_ticker`, `fetch_time`, `set_sandbox_mode`, `load_markets`, `request`, `fetch`, `safe_balance`, el manejo de
  errores y las excepciones. **Ninguna cambia lo que hace el bot.**
- **Para instalarla** (tras la semana del demo, en una ventana como la de la seccion 3): `pyproject.toml` a
  `==4.5.85`, `pip install ccxt==4.5.85` en el `.venv` del portatil y del VPS, tests en los dos, y reiniciar en el
  orden de la seccion 9 (ingesta primero; avisar al propietario antes de parar `ploutos-exec`). ccxt no entra en la huella.
