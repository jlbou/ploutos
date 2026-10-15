# Diseno: comandos de Telegram

Estado: **DECIDIDO por el propietario el 25/09/2026: 1a, 2a y 3a** (seccion 6): `/status`, `/pause` (con
`/closeonly` como sinonimo), `/kill` y `/resume`; desde el movil solo se levanta la pausa, con
confirmacion; se despliega con la pieza de noticias.
PRD seccion 9 (comandos opcionales), seccion 10 (controles de seguridad) y fase 5.

## 1. Lo que dice el PRD y lo que falta

PRD 9: "Comandos opcionales, restringidos a tu `chat_id`: `/status`, `/pause`, `/closeonly`, `/kill`."
PRD 10: los controles del panel son "pausar, solo cierre, cerrar todo con doble confirmacion, kill
switch", y "sus comandos pasan por el motor de riesgo y se auditan".

Lo que el PRD **no dice**:

1. **Que diferencia hay entre `/pause` y `/closeonly`.** La tabla de modos (PRD 5) no tiene ningun
   modo de pausa ni de solo cierre manual: solo `HALTED` es manual ("kill switch"). En este bot, las
   dos cosas acaban siendo lo mismo: no abrir nada nuevo y dejar que las posiciones terminen en su
   stop o su objetivo. La unica diferencia posible seria si las entradas pendientes se cancelan o no,
   y una entrada pendiente vive como mucho una vela: no merece un comando propio.
2. **Como se sale.** No hay `/resume`. Sin el, una pausa desde el movil solo se levanta entrando en
   el VPS.
3. **A que cartera afecta.** Desde la fase 3 hay DOS (baseline e IA) y la fase 6 las compara.

## 2. La propuesta

### Comandos

| Comando | Que hace | Modo | Como se sale |
|---|---|---|---|
| `/status` | Solo lectura (ver abajo). No cambia nada | - | - |
| `/pause` | No abre nada nuevo; cancela las entradas pendientes; las posiciones siguen con sus stops y objetivos (y la venta por noticia critica). Es "solo cierre" | `CLOSE_ONLY_MANUAL` (nuevo) | `/resume` |
| `/kill` | Parada: no abre, cancela las entradas pendientes y deja de gestionar. **Las OCO siguen en el exchange** (decision 4 de la fase 4) | `HALTED` | solo en el VPS (o el panel, fase 5) |
| `/resume` | Levanta la pausa, con confirmacion (responder `/si` en 60 s). **Solo levanta lo que puso `/pause`**: nunca `HALTED`, `CAPITAL`, `DAILY`, `QUOTA` ni `DEGRADED` | - | - |

- `/closeonly` se acepta como sinonimo de `/pause` (es el nombre del PRD) o se quita: lo decide el propietario.
- **Cerrar todo NO va por Telegram**: el PRD lo pone en el panel con doble confirmacion, y desde el
  movil es demasiado facil de pulsar sin querer.
- **La asimetria es a proposito:** todo lo que hace el bot MAS prudente es inmediato (en una
  emergencia cuenta cada minuto); lo que lo hace MENOS prudente pide confirmacion, y lo que es grave
  (`HALTED`, el suelo de capital) no se levanta desde el movil.
- `CLOSE_ONLY_MANUAL` es un modo nuevo en `core/modes.py`, entre `DAILY` y `CAPITAL`. Se comporta como
  todos los `CLOSE_ONLY_*` (PRD 5: cancelar entradas pendientes, verificar las OCO, avisar).
- **Las dos carteras a la vez, siempre.** Un comando nunca pausa solo una: la fase 6 compara IA
  contra baseline con los MISMOS candidatos, y pausar una sola romperia la comparacion. Las velas en
  pausa no generan candidatos en ninguna de las dos, asi que simplemente no cuentan.

### Que ensenya `/status`

Un mensaje, en castellano y sin nombrar a Claude:

```
Ploutos · 14:05 UTC
                 Baseline     IA
Modo             NORMAL       NORMAL
Equity           50,42 $      49,87 $
Hoy              +0,42 $      -0,13 $
Operaciones hoy  1/6          0/6
Posiciones       2/3          1/3
Llamadas IA      -            3/40
Ultima vela      12:00        12:00
Noticias: sin avisos activos
```

Sin posiciones detalladas (para eso esta el panel): corto, para mirarlo en el movil.

## 3. Como funciona por dentro

- **Un servicio propio, `ploutos-telegram`**, que escucha con `getUpdates` (sondeo largo). Sin webhook:
  un webhook necesita una direccion publica y el cortafuegos del VPS solo deja entrar SSH. Telegram
  solo admite UN lector de `getUpdates` por bot, asi que no puede ir dentro de las dos carteras.
- **Base propia** (`var/ploutos-control.db`), con la tabla de comandos. Las carteras la leen en
  `mode=ro`, igual que la de noticias: **un escritor por base** (SQLite en WAL). El modo manual
  activo se DERIVA de la tabla (el ultimo `/pause` sin un `/resume` confirmado despues), no se
  guarda en memoria: sobrevive a reinicios.
- **Cuando cuenta un comando:** en papel, desde la siguiente DECISION de cada cartera (al cierre de
  la vela), como las noticias: asi el juez lo puede rederivar vela a vela. En papel no se decide
  nada entre velas, asi que no se abre nada tarde; lo unico es que una entrada ya puesta puede
  llenarse en la vela en curso. **En la fase 4** (ordenes de verdad) el ejecutor tendra que
  cancelar las entradas pendientes EN EL MOMENTO de recibir la pausa.
- **Si la base de control no se puede leer**, las carteras usan el ultimo estado visto. Una pausa ya
  vista no se levanta porque la base falle.
- **Seguridad:**
  - solo se atiende un mensaje de un chat PRIVADO cuyo remitente y chat sean el `chat_id` del `.env`;
    lo demas se ignora sin responder (al log solo va "ignorado", nunca el texto);
  - un comando con mas de 2 minutos se ignora y se responde que ha llegado tarde (un `/resume` que
    llega una hora despues no puede ejecutarse);
  - el token nunca sale en un error (`scrub_url`, como el resto de `notify/`).
- **Auditoria:** cada comando queda en la base con la hora, quien, el texto, el resultado y la
  respuesta. Cada comando recibe respuesta.
- **Coste:** un proceso de Python mas (~50 MB). Late en Healthchecks como los demas (una
  comprobacion mas, la sexta).

## 4. El juez

Un criterio sin juez no es un criterio. `check_paper.py` lee tambien la base de control y comprueba
que **ninguna cartera abrio nada mientras habia una pausa o un `HALTED` activo** (como ya hace con las
flags de noticias). Y un juez del servicio comprueba que cada comando recibio respuesta y que ningun
`/resume` se ejecuto sin su `/si` (`scripts/check_control.py`, abajo).

## 5. Las piezas

| # | Pieza | Pura |
|---|---|---|
| 1 | `notify/comandos.py`: mensaje de Telegram -> orden o "ignorar" (chat, edad, comando) | si |
| 2 | El modo manual activo a partir del historial de comandos (con la confirmacion del `/resume`) | si |
| 3 | El texto de `/status` a partir del estado de las dos carteras | si |
| 4 | `CLOSE_ONLY_MANUAL` en `core/modes.py` y en el bucle (el mismo camino que `DAILY`) | no |
| 5 | La base de control y el servicio `ploutos-telegram` (sondeo, respuestas, latido) | no |
| 6 | Las carteras leen la base de control; el juez de papel lo audita | no |
| 7 | El juez del servicio | no |

Las piezas 1-3 se pueden escribir ya (puras, sin enchufar, como las de la fase 4). Las 4-7 tocan el
bucle de las dos carteras.

**Estado (25/09): LAS SIETE HECHAS y probadas, sin desplegar**, en la rama `comandos` (que sale de
`noticias-servicio`, porque se despliegan juntas):

| Pieza | Donde |
|---|---|
| 1-3 | `notify/comandos.py` (`interpretar`, `aplicar`/`reconstruir`, `texto_estado`) |
| 4 | `CLOSE_ONLY_MANUAL` en `core/modes.py`; `portfolio/loop.py` (`step(..., manuales=)`, `MANUALES`) |
| 5 | `notify/control.py`, `data/store/control_migrations/`, `scripts/run_telegram.py`, `deploy/ploutos-telegram.service` |
| 6 | `scripts/run_paper.py` (`_manuales`), `portfolio/audit.py` y `check_paper.py --control-db` |
| 7 | `scripts/check_control.py` |

- En papel, `HALTED` sigue resolviendo los stops y objetivos (en real son OCO que el exchange
  ejecuta aunque el bot este parado); lo que deja de hacer es abrir, gestionar y vender por noticia.
- Probado con las bases que escribe el servicio de VERDAD (Telegram falso) y el juez de papel de
  verdad sobre una cartera en pausa. Diez mutaciones a mano, las diez en rojo (ver el commit).
- De paso: las copias de la noche incluyen ahora la base de noticias y la de control, e
  `install.sh` copia (sin habilitar) los servicios `ploutos-news` y `ploutos-telegram`.

**DESPLEGADOS el 25/09/2026 ~18:20 UTC**, junto con las noticias, con el OK del propietario (dos veces el
mismo dia que la fase 3, para que la muestra de la fase 6 se parta con solo 2 velas en el primer tramo).
Faltan las dos comprobaciones de Healthchecks (paso 1): los servicios corren sin latido hasta entonces.
Todos los jueces sin FALLA. **`/status` probado desde el movil del propietario el 25/09 a las 22:06 UTC**: guardado,
contestado al primer intento en menos de 1 s, la tabla bien en el movil. Los pasos, como quedaron:

**Para desplegarlos** (con el OK del propietario, junto con las noticias, entre la fase 3 y la 6):
1. El propietario crea en Healthchecks la QUINTA (`ploutos-news`, periodo 10 min) y la SEXTA comprobacion
   (`ploutos-telegram`, periodo 5 min); sus URL van al `.env` del VPS como `HEALTHCHECK_NOTICIAS`
   y `HEALTHCHECK_TELEGRAM`.
2. Fusionar la rama `comandos` (lleva `noticias-servicio`), `sync.sh`, `install.sh` (reinstala
   `backup.sh` y copia los servicios).
3. `systemctl enable --now ploutos-news ploutos-telegram`; reiniciar las dos carteras.
4. Probar desde el movil: `/status`; `/pause` y ver el aviso de cambio de modo de las DOS carteras
   en su siguiente vela; `/resume` + `/si`.
5. `check_paper.py` (las dos carteras), `check_news.py` y `check_control.py` sin FALLA; a los 7 dias,
   `check_news.py` y `check_control.py` con salida 0 cierran las dos piezas.

## 6. Decisiones para el propietario

**1. Que comandos.**
- a) **`/status`, `/pause`, `/kill` y `/resume`** (recomendado), con `/closeonly` como sinonimo de `/pause`.
- b) Los cuatro del PRD tal cual, con `/pause` y `/closeonly` distintos (la diferencia seria solo las
  entradas pendientes).
- c) Solo `/status`: nada que cambie el bot desde el movil.

**2. Que se puede levantar desde el movil.**
- a) **Solo la pausa, con `/resume` y confirmacion** (recomendado). `HALTED` y el suelo, solo en el VPS.
- b) Tambien `HALTED`.
- c) Nada: cualquier salida, en el VPS.

**3. Cuando se despliega.**
- a) **Con la pieza de noticias** (recomendado): las dos tocan el bucle de las carteras; si entran a la
  vez, el bucle cambia UNA vez durante la muestra de la fase 6 en vez de dos.
- b) En la fase 5, como dice el PRD.
- c) `/status` ya con la fase 3 (es solo lectura) y el resto en la fase 5.
