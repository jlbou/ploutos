# Guion del despliegue de la fase 3

Escrito el 24/09/2026. Se sigue **despues** del cierre del viernes 25/09 y **solo**
si: los dos jueces dan CUMPLIDO, `docs/archivo/cierre-fase-2.md` esta rellenado y el propietario ha
dado el OK a la fase 3. Cada paso dice que comprobar antes de pasar al siguiente
y como volver atras.

**HECHO el 25/09/2026, 17:40-18:00 UTC.** Las dos carteras empezaron en la vela de las 12:00 UTC.
Dos pasos pararon el guion y se arreglaron antes de seguir: el 6 (el instalador no instalaba con
`DISABLE_UPDATES`) y un aviso de systemd en el 9 (`StartLimitIntervalSec` en la seccion equivocada).
Detalle en `docs/hallazgos-fase-3-4.md` (5a).
**Prueba del vigilante (11b), hecha:** `ploutos-paper-ai` parado de 17:51 a 18:10 UTC; el aviso de
Healthchecks llego a Telegram (lo confirmo el propietario) y se volvio a arrancar sin perder ninguna vela.

Regla del guion: **un paso que no da lo que se espera PARA el guion.** No se sigue
"a ver si luego se arregla".

## 0. Lo que hay que tener delante

| Rama | Que lleva | Estado |
|---|---|---|
| `fase-3-integracion` | TODO: piezas 7-11 de la fase 3, juez de la IA, swap, servicio de la IA, copias, **las comisiones** (desde el 24/09) y los avisos | hecha, sin fusionar en `main` |
| `comisiones-settings` | las comisiones | ya incluida en `fase-3-integracion`: no hace falta fusionarla aparte |
| `telegram-avisos` | los avisos de Telegram | ya fusionada en `fase-3-integracion` y enchufada a los dos bucles |

## 1. Juntar las ramas en `main` (portatil)

```bash
git checkout main && git pull
git merge fase-3-integracion
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/mutation_check.py
```

- **Ensayado el 24/09** en una rama temporal: la fusion de las dos ramas dio conflictos en
  `CLAUDE.md` y en `tests/unit/test_run_paper.py` (las dos anyadian tests al final); se
  resolvieron quedandose con todo, y `fase-3-integracion` ya lleva ese resultado. Si `main`
  no se ha movido desde entonces, esta fusion es directa (sin conflictos).
- **Ensayado otra vez el 25/09** (worktree aparte, con todo lo anyadido la noche del 24): fusion
  DIRECTA (la rama ya lleva `main`), 1016 tests, mutacion 16/16. Con la copia real de la base de
  papel del 24/09 03:18: la migracion aplica 005, 006 y 007 sin perder una fila y es idempotente;
  el juez con el codigo nuevo da FALLA en comisiones y equity, lo esperado (paso 2); los jueces de
  la IA y de la fase 6 sobre una base nueva dicen "todavia nada". `52ploutos-reboot.conf`
  leido por el `apt-config` del VPS (desde /tmp, sin instalarlo): las tres lineas bien.
- **Comprobar:** tests en verde (1016 el 25/09) y mutacion 16/16 (las comisiones tocan `risk/`).
- `git push`.
- **Atras:** `git reset --hard origin/main` ANTES del push. Despues, `git revert`.

## 2. Archivar la base de papel de las 72 h (VPS)

Con las comisiones nuevas, el juez recalcula las antiguas y daria FALLA en el
equity (medido el 23/09): la cartera del baseline empieza de cero. La de las 72 h
se GUARDA, no se borra: es la evidencia del cierre de la fase 2.

```bash
ssh ploutos 'systemctl stop ploutos-paper'
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python -c "
import sqlite3; c = sqlite3.connect(\"file:var/ploutos-paper.db?mode=ro\", uri=True)
c.execute(\"VACUUM INTO \x27/var/backups/ploutos/ploutos-paper-cierre-fase2.db\x27\")"'
# Primero volcar el WAL a la base: renombrar la base y borrar el -wal sin esto
# PERDERIA lo ultimo escrito (SQLite en WAL guarda ahi lo aun no volcado).
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos .venv/bin/python -c "
import sqlite3; c = sqlite3.connect(\"var/ploutos-paper.db\")
print(c.execute(\"PRAGMA wal_checkpoint(TRUNCATE)\").fetchone()); c.close()"'
ssh ploutos 'sudo -u ploutos mv /opt/ploutos/var/ploutos-paper.db /opt/ploutos/var/ploutos-paper-fase2.db && sudo -u ploutos rm -f /opt/ploutos/var/ploutos-paper.db-wal /opt/ploutos/var/ploutos-paper.db-shm'
```

- **Comprobar:** el checkpoint devuelve `(0, 0, 0)` o `(0, N, N)` (el primer 0 = sin
  bloqueo), `ls -la /var/backups/ploutos/ploutos-paper-cierre-fase2.db`, y que
  `check_paper.py --paper-db var/ploutos-paper-fase2.db` sigue dando CUMPLIDO.
  **Esto, ANTES del paso 3:** con el codigo nuevo (comisiones de 0,20 %) el juez daria
  FALLA en el equity de esta base, hecha con 0,15 % (medido el 23/09). No es un fallo
  de la base: es que el juez nuevo usa otras comisiones.
- Bajar la copia al portatil (`bash deploy/fetch-backup.sh ploutos`).
- **Atras:** volver a renombrar `ploutos-paper-fase2.db` a `ploutos-paper.db`.

## 3. Copiar el codigo (portatil)

```bash
bash deploy/sync.sh ploutos
```

- `sync.sh` NO reinicia nada y NO copia `.env`.

## 4. Memoria: swap y prioridad de la ingesta (VPS)

```bash
ssh ploutos 'sudo bash /opt/ploutos/deploy/swap.sh'
```

- **Comprobar:** `free -m` con `Swap: 1023` (aprox.) y
  `cat /proc/sys/vm/swappiness` = 10.
- **Atras:** `swapoff /swapfile`, quitar la linea de `/etc/fstab`, borrar
  `/swapfile` y `/etc/sysctl.d/90-ploutos-swap.conf`.

## 4b. Reiniciar la maquina: el nucleo nuevo (VPS)

Pendiente desde el 25/09 07:00 UTC: las actualizaciones instalaron el nucleo 6.8.0-142 y la
maquina sigue con el 139 (`/var/run/reboot-required`). Este es el momento limpio: la medicion de
las 72 h ya esta juzgada, el papel esta parado (paso 2) y el codigo nuevo aun no ha arrancado.
Ademas prueba que el swap del paso 4 sobrevive a un reinicio.

```bash
# El papel sigue habilitado: sin esto arrancaria solo al volver, antes del paso 9, y la
# cartera del baseline empezaria en otra vela que la de la IA.
ssh ploutos 'systemctl disable ploutos-paper && sudo reboot'
# ~1 min despues:
ssh ploutos 'uname -r; ls /var/run/reboot-required 2>/dev/null; free -m | grep -i swap; systemctl is-active ploutos-ingest ploutos-paper'
```

- **Comprobar:** `6.8.0-142-generic` (o posterior), sin `reboot-required`, `Swap:` ~1023,
  `ploutos-ingest` = `active` y `ploutos-paper` = `inactive`. La ingesta rellena sola lo del
  minuto parado (backfill); el paso 10 lo confirma con `check_gaps.py`.
- En el paso 9, `systemctl enable --now ploutos-paper` en vez de `start` (se deshabilito aqui).
- **Atras:** si la maquina no vuelve, consola del proveedor del VPS (SCP) y arrancar con el nucleo anterior
  desde el menu de GRUB.

## 5. Reinstalar servicios y copias (VPS)

```bash
ssh ploutos 'sudo bash /opt/ploutos/deploy/install.sh'
ssh ploutos 'systemctl restart ploutos-ingest'
```

- Reinstala: `ploutos-ingest` (con `OOMScoreAdjust=-900`), `ploutos-paper`,
  `ploutos-paper-ai` (copiado, **NO habilitado**) y `/usr/local/bin/ploutos-backup`
  (el arreglo del recuento y la tercera familia de copias).
- La ingesta se reinicia para que coja la prioridad: el backfill cubre el hueco.
- **Comprobar:**
  `cat /proc/$(systemctl show -p MainPID --value ploutos-ingest)/oom_score_adj` = -900,
  y `check_gaps.py --hours 2` sin huecos a los 10 minutos.

## 6. El CLI de Claude (VPS)

```bash
ssh ploutos 'sudo bash /opt/ploutos/deploy/install-claude.sh'
```

- **Comprobar** en la salida: la firma del manifiesto valida, el sha256 cuadra,
  `claude --version` = `2.1.266`, y el aviso de memoria (esperado: 2 GB).

## 7. Los secretos (el propietario, a mano)

**YA PUESTOS** (con el permiso del propietario): las 4 `HEALTHCHECK_*` el 24/09 y `CLAUDE_CODE_OAUTH_TOKEN`,
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` el 25/09, copiadas del `.env` del portatil por ssh sin
ensenyarlas y comprobadas por huella. En este paso solo se COMPRUEBA que siguen ahi (11 claves:
4 de OKX, 4 de Healthchecks, 3 de IA y Telegram):

```bash
ssh ploutos "sudo grep -oE '^[A-Z_]+=' /opt/ploutos/.env | tr '
' ' '"
```

Lo de abajo queda como referencia de que es cada una.

En `/opt/ploutos/.env` (propietario `ploutos`, permisos 600):
- `CLAUDE_CODE_OAUTH_TOKEN=` (el del portatil vale: se probo sin sesion).
- `TELEGRAM_BOT_TOKEN=` y `TELEGRAM_CHAT_ID=` (los mismos del portatil). Los avisos ya
  van enchufados a los dos bucles: sin estas dos lineas se quedan en la base sin salir.
  Al ponerlas, los de mas de 12 h se descartan en vez de llegar de golpe.
- `HEALTHCHECK_INGESTA=`, `HEALTHCHECK_PAPEL=`, `HEALTHCHECK_PAPEL_IA=` y `HEALTHCHECK_COPIA=`: las
  cuatro URL de Healthchecks.io (una por comprobacion). Son secretas: quien las tenga puede
  mandar latidos falsos y tapar una caida.

**Nunca por el chat.** Comprobar solo que estan, sin ensenyarlos:
`install-claude.sh` lo dice al volver a ejecutarlo.

## 8. Medir la memoria de una llamada real (VPS, 1 llamada de la cuota)

```bash
ssh ploutos 'cd /opt/ploutos && sudo -u ploutos /usr/bin/time -v .venv/bin/python scripts/verify_claude_cli.py --sin-sesion 2>&1 | tail -40'
```

- **Comprobar:** "Maximum resident set size". En el portatil fueron 382-409 MB.
- **PARAR si pasa de ~700 MB**: con `MemoryMax=900M` y el Python del bucle (~170 MB)
  no cabria. Decision del propietario (tope mayor o VPS mayor).
- **Comprobar tambien la linea `modelo`**: si dice un modelo (`claude-sonnet-...`), el journal
  lo guardara en cada decision. Si dice "NO LO DICE", no para el guion (la huella del camino
  ya guarda el modelo PEDIDO), pero apuntarlo: el alias `sonnet` podria cambiar por debajo sin
  que se viera (protocolo de la fase 6).

## 9. Arrancar las DOS carteras a la vez (VPS)

Las dos empiezan en "la ultima vela cerrada" en su primer arranque. Arrancarlas
dentro de la misma ventana de 4 h hace que empiecen en la MISMA vela, que es lo
que necesita la comparacion de la fase 6.

```bash
ssh ploutos 'systemctl enable --now ploutos-paper && systemctl enable --now ploutos-paper-ai'
```

- **Comprobar:**
  - `systemctl is-active ploutos-paper ploutos-paper-ai` = `active active`.
  - `run_paper.py --status` y `run_paper_ai.py --status`: la MISMA ultima vela.
  - `journalctl -u ploutos-paper-ai -n 30`: ni errores de token ni de memoria.
- **Atras:** `systemctl disable --now ploutos-paper-ai`. El baseline no se entera.

## 10. Los jueces, sobre las dos carteras (VPS, tras la primera vela nueva)

```bash
cd /opt/ploutos
sudo -u ploutos .venv/bin/python scripts/check_paper.py
sudo -u ploutos .venv/bin/python scripts/check_paper.py --decider ai --paper-db var/ploutos-paper-ai.db
```

- **Comprobar:** los dos "coherente" (con pocas horas dan "aun no", salida 2: eso es
  lo esperado, no un fallo).
- En la de la IA, cuando haya candidatos: una fila en `ai_calls` por vela con
  candidatos y `called_ms` al cierre de la vela.

```bash
sudo -u ploutos .venv/bin/python scripts/check_fase6.py
```

- **El juez de la fase 6, desde el primer dia** (la muestra cuenta desde aqui, decision 1 de
  el propietario): tiene que dar los datos "OK" y "VEREDICTO: todavia no" (salida 2). Hasta la primera
  decision de la IA dice que no hay ninguna; es lo esperado. Un "FALLA" PARA el guion: lo que
  no se guarda bien desde el principio no se recupera despues.

## 11. Copias con la tercera base

```bash
ssh ploutos 'systemctl start ploutos-backup && journalctl -u ploutos-backup -n 12 --no-pager'
```

- **Comprobar:** tres familias copiadas (`ploutos`, `ploutos-paper`, `ploutos-paper-ai`)
  y el recuento correcto por familia.
- **Y el reinicio automatico** (decision del propietario del 25/09): `apt-config dump | grep Automatic-Reboot`
  tiene que dar `"true"` y `"07:15"`. Lo pone `install.sh` del paso 5. La prueba de verdad sera
  el primer reinicio real: `last reboot` y, si la maquina no volviera, el aviso de Healthchecks.

## 11b. El vigilante externo

En la web de Healthchecks.io, a los 10-15 min de arrancar: las comprobaciones de la ingesta y de
las dos carteras en verde ("up"). La de la copia se pone verde tras la copia de la noche (o
tras el `systemctl start ploutos-backup` del paso 11).

- **Prueba de que avisa de verdad:** parar un momento `ploutos-paper-ai`
  (`systemctl stop ploutos-paper-ai`); a los ~20 min (5 de periodo + 15 de margen) tiene que llegar
  el aviso por Telegram. Volver a arrancarlo. Mejor probarlo que suponerlo.

## 12. Apuntarlo

- `CLAUDE.md`, "Estado ahora": fase 3 en marcha desde la vela X, dos carteras.
- `docs/archivo/plan-fase-3.md`: el criterio de avance de la fase 3 ("1 semana estable;
  consumo de cuota medido") empieza a contar aqui.
