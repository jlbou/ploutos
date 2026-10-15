"""Que avisos produce cada vela, y como se mandan (PRD seccion 9; 24/09/2026).

Dos mitades separadas a proposito:

1. `avisos_de_la_vela` (PURA): de lo que paso en una vela, los avisos. Quien
   guarda la vela los mete en la MISMA transaccion (`store.save_step`).
2. `enviar_pendientes`: los manda despues, en cada vuelta del bucle. NUNCA
   lanza, manda como mucho unos pocos por vuelta, para en el primer fallo y
   con un timeout corto: si Telegram esta caido, el bucle pierde unos segundos
   por vuelta, no la vela.

Los que llevan mas de `MAX_EDAD_MS` sin salir (Telegram caido horas, o sin
credenciales hasta que se ponen) se descartan en vez de mandarse: llegarian
como si fueran de ahora.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from core.config import DrawdownTier, Settings
from core.modes import ModeChange
from notify import messages as m
from notify.resumen import resumen_desde_base
from notify.telegram import send_message
from portfolio import store
from portfolio.paper import PaperTrade

MAX_POR_VUELTA = 5
TIMEOUT_S = 10.0
MAX_EDAD_MS = 12 * 3600 * 1000
PAUSA_S = 1.1
# El resumen de AYER se manda a partir de esta hora UTC (da tiempo a que se
# procese la vela de las 20:00, que cierra a las 00:00).
HORA_RESUMEN = 0
MINUTO_RESUMEN = 10

Aviso = tuple[str, str, str]      # (tipo, clave unica, texto)


def avisos_de_la_vela(
    *,
    ts_ms: int,
    cartera: str,
    cerradas: Sequence[PaperTrade],
    cambios: Sequence[ModeChange],
    canceladas: int,
    equity_anterior: float | None,
    equity: float,
    escalones: Sequence[DrawdownTier],
    journal: Sequence[tuple[dict[str, Any], list]] = (),
    paridad: tuple[bool | None, bool, str, float] | None = None,
) -> list[Aviso]:
    """Los avisos de una vela. `paridad` = (bloqueaba antes, bloquea ahora, detalle, limite %) de la regla 17;
    `bloqueaba antes` None si no hay lectura anterior (la primera vela de la cartera)."""
    avisos: list[Aviso] = []
    for t in cerradas:
        avisos.append(("operacion", f"{cartera}:operacion:{t.decision_id}", m.operacion_cerrada(t, cartera)))
    primera_entrada = True
    for c in cambios:
        n = canceladas if (c.activated and primera_entrada) else 0
        if c.activated:
            primera_entrada = False
        avisos.append((
            "modo", f"{cartera}:modo:{ts_ms}:{c.mode.name}:{int(c.activated)}",
            m.cambio_de_modo(c, cartera, canceladas=n),
        ))
    cruce = m.escalon_cruzado(equity_anterior, equity, escalones)
    if cruce is not None:
        escalon, bajando = cruce
        avisos.append((
            "escalon", f"{cartera}:escalon:{ts_ms}:{escalon.equity_below_usd}:{int(bajando)}",
            m.aviso_escalon(cartera, equity, escalon, bajando),
        ))
    for fila, _decisiones in journal:
        if fila.get("outcome") == "auth":
            avisos.append((
                "auth", f"{cartera}:auth:{fila['called_ms']}",
                m.error_autenticacion("la IA", str(fila.get("reason", ""))),
            ))
    if paridad is not None:
        # Solo al CAMBIAR (como los escalones): un aviso cada 4 h mientras dura deja de leerse.
        antes, ahora, detalle, limite = paridad
        if (antes is None and ahora) or (antes is not None and antes != ahora):
            avisos.append((
                "paridad", f"{cartera}:paridad:{ts_ms}:{int(ahora)}",
                m.aviso_paridad(cartera, ahora, detalle, limite),
            ))
    return avisos


def resumen_si_toca(conn: sqlite3.Connection, cartera: str, ahora_ms: int, settings: Settings) -> Aviso | None:
    """El resumen de AYER (dia UTC), si ya es la hora. La clave es del dia: aunque
    se pida en cada vuelta, entra una sola vez (INSERT OR IGNORE)."""
    ahora = datetime.fromtimestamp(ahora_ms / 1000, tz=UTC)
    if (ahora.hour, ahora.minute) < (HORA_RESUMEN, MINUTO_RESUMEN):
        return None
    ayer: date = ahora.date() - timedelta(days=1)
    clave = f"{cartera}:resumen:{ayer.isoformat()}"
    ya = conn.execute("SELECT 1 FROM paper_avisos WHERE clave = ?", (clave,)).fetchone()
    if ya is not None:
        return None
    # Sin ninguna vela antes de que acabara ayer, la cartera no existia ayer: un
    # resumen diria "50,00 $" de un dia inventado (el primer dia tras arrancar;
    # revision del 24/09/2026).
    fin_de_ayer = int(datetime.combine(ahora.date(), datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    primera = conn.execute("SELECT MIN(ts_ms) FROM paper_equity").fetchone()[0]
    if primera is None or primera >= fin_de_ayer:
        return None
    r = resumen_desde_base(conn, cartera, ayer, settings)
    extra = []
    # El token de Claude, solo en el resumen de la IA (es la que lo usa) y solo en
    # los ultimos 14 dias: un aviso que sale todos los dias del anyo no se lee.
    caduca = settings.claude.token_expires_on
    if cartera == "ai" and caduca is not None:
        aviso_token = m.token_por_caducar(caduca, ahora.date())
        if aviso_token is not None:
            extra.append(aviso_token)
    return ("resumen", clave, m.resumen_diario(ayer, [r], extra=extra))


def enviar_pendientes(
    conn: sqlite3.Connection, token: str | None, chat_id: str | None, ahora_ms: int,
    *, max_por_vuelta: int = MAX_POR_VUELTA, _send: Any = send_message,
    _dormir: Any = None,
) -> tuple[int, str | None]:
    """Manda los pendientes, los mas viejos primero. Devuelve (enviados, error).

    Para en el PRIMER fallo: si Telegram no contesta, insistir con el resto solo
    alarga la vuelta. Sin credenciales no intenta nada (quedan en la tabla).
    """
    if not token or not chat_id:
        return 0, "sin credenciales de Telegram"
    if not store.avisos_pendientes(conn, 1):
        return 0, None                     # lo normal: nada que mandar, y sin escribir
    store.descartar_avisos_viejos(conn, ahora_ms - MAX_EDAD_MS)
    enviados = 0
    for i, fila in enumerate(store.avisos_pendientes(conn, max_por_vuelta)):
        if i:
            # Telegram corta las rafagas al mismo chat (429): uno por segundo.
            (_dormir or time.sleep)(PAUSA_S)
        envio = _send(token, chat_id, fila["texto"], timeout=TIMEOUT_S)
        if envio.ok:
            store.marcar_aviso(conn, fila["id"], enviado_ms=ahora_ms, error=None)
            enviados += 1
        else:
            store.marcar_aviso(conn, fila["id"], enviado_ms=None, error=envio.detalle)
            return enviados, envio.detalle
    return enviados, None
