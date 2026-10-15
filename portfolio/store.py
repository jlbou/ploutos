"""Persistencia del bucle de papel.

POR QUE HACE FALTA: el criterio de avance pide 72 h de operaciones coherentes.
Si un reinicio del servicio perdiera las posiciones abiertas, esas 72 h no
demostrarian nada: el simulador arrancaria vacio cada vez y nunca llegaria a
cerrar una operacion que dure mas que el uptime.

Y los reinicios van a pasar: la unidad de systemd lleva `Restart=always`
precisamente para que pasen sin que nadie mire.

QUE SE GUARDA Y QUE NO. Se guarda lo que no se puede reconstruir: ordenes,
posiciones, operaciones cerradas, la curva de equity y **hasta que vela se ha
procesado**. No se guardan los candidatos descartados ni las correlaciones:
eso se recalcula desde las velas, que estan en la base principal.

El cursor es lo que impide que un reinicio vuelva a procesar velas ya vistas y
duplique decisiones.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.modes import Mode, ModeMachine
from portfolio.paper import (
    ExitReason,
    OrderState,
    PaperBroker,
    PaperLedger,
    PaperOrder,
    PaperPosition,
    PaperTrade,
)

MIGRATIONS = Path(__file__).resolve().parent.parent / "data" / "store" / "paper_migrations"


def connect(path: Path | str) -> sqlite3.Connection:
    """Abre (y crea si hace falta) la base del bucle de papel."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    for pragma in (
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA foreign_keys=ON",
        "PRAGMA busy_timeout=5000",
    ):
        conn.execute(pragma)
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Aplica el esquema. Idempotente."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
    )
    done = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    applied: list[str] = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in done:
            continue
        with conn:
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                (version, path.name),
            )
        applied.append(path.name)
    return applied


# --------------------------------------------------------------------------
# Guardar
# --------------------------------------------------------------------------


def _write_state(
    conn: sqlite3.Connection,
    broker: PaperBroker,
    ledger: PaperLedger,
    timeframe: str,
    last_ts_ms: int,
    decider: str = "baseline",
) -> None:
    """Vuelca el estado entero. SIN transaccion propia: la pone quien llama.

    Se reescribe completo en vez de llevar la cuenta de lo que cambio: son
    decenas de filas, el coste es irrelevante y elimina toda una familia de
    fallos (guardar la posicion y olvidar la orden, por ejemplo). Si el
    proceso muere a media escritura, la transaccion se deshace y al arrancar
    se lee el estado de la vela anterior, que es consistente.
    """
    conn.execute("DELETE FROM paper_orders")
    conn.executemany(
        "INSERT INTO paper_orders (decision_id, symbol, qty, limit_price,"
        " stop_price, target_price, setup, created_ts_ms, state, bars_waited)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                o.decision_id, o.symbol, o.qty, o.limit_price, o.stop_price,
                o.target_price, o.setup, o.created_ts_ms, str(o.state),
                o.bars_waited,
            )
            for o in broker.orders
        ],
    )

    conn.execute("DELETE FROM paper_positions")
    conn.executemany(
        "INSERT INTO paper_positions (symbol, decision_id, qty, entry_price,"
        " stop_price, target_price, setup, opened_ts_ms, entry_fee_usd,"
        " worst_price, best_price) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                p.symbol, p.decision_id, p.qty, p.entry_price, p.stop_price,
                p.target_price, p.setup, p.opened_ts_ms, p.entry_fee_usd,
                p.worst_price, p.best_price,
            )
            for p in broker.positions.values()
        ],
    )

    conn.executemany(
        "INSERT OR REPLACE INTO paper_trades (decision_id, symbol, setup,"
        " decider, qty, entry_price, exit_price, stop_price, target_price,"
        " opened_ts_ms, closed_ts_ms, reason, entry_fee_usd, exit_fee_usd,"
        " exit_was_maker, mae_pct, mfe_pct, net_pnl_usd, r_multiple)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                t.decision_id, t.symbol, t.setup, decider, t.qty,
                t.entry_price, t.exit_price, t.stop_price, t.target_price,
                t.opened_ts_ms, t.closed_ts_ms, str(t.reason),
                t.entry_fee_usd, t.exit_fee_usd, int(t.exit_was_maker),
                t.mae_pct, t.mfe_pct, t.net_pnl_usd, t.r_multiple,
            )
            for t in broker.trades
        ],
    )

    # La curva de equity. Los contadores de posiciones y pendientes son
    # los de AHORA, asi que solo valen para la fila de ESTA vela (al
    # cierre de la vela, despues de decidir). Hasta el 22/09/2026 se
    # escribian en TODAS las filas con INSERT OR REPLACE, y cada guardado
    # machacaba los contadores de la historia entera con los del momento.
    # Ahora las filas anteriores se insertan solo si faltan y NUNCA se
    # reescriben: lo que ya esta guardado es historia.
    if ledger.history:
        *anteriores, (ts_ultimo, eq_ultimo) = ledger.history[-500:]
        conn.executemany(
            "INSERT OR IGNORE INTO paper_equity (ts_ms, equity_usd, positions,"
            " pending) VALUES (?,?,?,?)",
            [
                (ts, eq, len(broker.positions), len(broker.pending))
                for ts, eq in anteriores
            ],
        )
        conn.execute(
            "INSERT OR REPLACE INTO paper_equity (ts_ms, equity_usd, positions,"
            " pending) VALUES (?,?,?,?)",
            (ts_ultimo, eq_ultimo, len(broker.positions), len(broker.pending)),
        )

    conn.execute(
        "INSERT OR REPLACE INTO paper_cursor (timeframe, last_ts_ms)"
        " VALUES (?, ?)",
        (timeframe, last_ts_ms),
    )


def save_state(
    conn: sqlite3.Connection,
    broker: PaperBroker,
    ledger: PaperLedger,
    timeframe: str,
    last_ts_ms: int,
    decider: str = "baseline",
) -> None:
    """Vuelca el estado entero en una transaccion, todo o nada."""
    with conn:
        _write_state(conn, broker, ledger, timeframe, last_ts_ms, decider)


def save_step(
    conn: sqlite3.Connection,
    broker: PaperBroker,
    ledger: PaperLedger,
    timeframe: str,
    ts_ms: int,
    decisions: list[tuple[Any, ...]],
    decider: str = "baseline",
    market: list[tuple[str, float, float]] = (),
    correlations: list[tuple[str, str, float]] = (),
    usdc: tuple[float | None, float | None, float | None, str] | None = None,
    mode_changes: list[tuple[str, bool, str, str]] = (),
    ai_calls: list[tuple[dict[str, Any], list[dict[str, Any]]]] = (),
    avisos: list[tuple[str, str, str]] = (),
) -> None:
    """Lo que produce UNA vela: el journal de decisiones y el estado, JUNTOS.

    En una sola transaccion, y es a proposito. Antes iban en dos: si el
    proceso moria entre una y otra, el journal quedaba escrito pero el cursor
    no avanzaba, y al reintentar la vela las mismas decisiones se apuntaban
    dos veces. Ahora o se guarda la vela entera o no se guarda nada.
    """
    with conn:
        _write_decisions(conn, ts_ms, decisions)
        _write_context(conn, ts_ms, market, correlations)
        _write_mode_changes(conn, ts_ms, mode_changes)
        for call, decisiones in ai_calls:
            _write_ai_call(conn, call, decisiones)
        _write_avisos(conn, ts_ms, avisos)
        if usdc is not None:
            conn.execute(
                "INSERT OR REPLACE INTO paper_usdc (ts_ms, primary_usd, check_usd,"
                " deviation_pct, detail) VALUES (?,?,?,?,?)",
                (ts_ms, *usdc),
            )
        _write_state(conn, broker, ledger, timeframe, ts_ms, decider)


def _write_mode_changes(
    conn: sqlite3.Connection, ts_ms: int, changes: list[tuple[str, bool, str, str]]
) -> None:
    """(modo, activado, motivo, modo efectivo despues). Ver 004_modes.sql."""
    if changes:
        conn.executemany(
            "INSERT INTO paper_mode_changes (ts_ms, mode, activated, reason,"
            " effective_after) VALUES (?,?,?,?,?)",
            [(ts_ms, m, int(a), r, e) for m, a, r, e in changes],
        )


def record_mode_changes(
    conn: sqlite3.Connection, ts_ms: int, changes: list[tuple[str, bool, str, str]]
) -> None:
    """Transiciones que pasan FUERA de una vela y hay que guardar ya: la salida de
    CLOSE_ONLY_QUOTA cuando una sonda responde bien (pieza 7 de la fase 3). Sin
    esto, un reinicio antes de la vela siguiente volveria a dejar el modo puesto."""
    with conn:
        _write_mode_changes(conn, ts_ms, changes)


# Columnas del journal del analista (005_ai.sql). Mundo cerrado: una clave que no
# este aqui es un error, no algo que se descarta en silencio.
AI_CALL_COLUMNS = (
    "ts_ms", "called_ms", "kind", "outcome", "valid", "reason", "n_candidates",
    "latency_s", "input_tokens", "output_tokens", "cache_created", "cost_usd_equiv",
    "num_turns", "prompt", "structured", "result_text", "camino", "modelo",
)
AI_DECISION_COLUMNS = (
    "ref", "type", "size_multiplier", "confidence", "reasons", "risks", "executed",
)
# Las NOT NULL de 005_ai.sql. Si falta una, error claro aqui, antes de tocar la
# base: dentro de `save_step` un IntegrityError tumbaria la vela entera y el bucle
# la reintentaria cada minuto sin decir que columna faltaba (revision del 23/09).
AI_CALL_REQUIRED = ("ts_ms", "called_ms", "kind", "outcome", "valid", "reason", "n_candidates")
AI_DECISION_REQUIRED = ("ref", "type", "reasons", "risks", "executed")


def _write_ai_call(
    conn: sqlite3.Connection, call: dict[str, Any], decisions: list[dict[str, Any]]
) -> int:
    extra = set(call) - set(AI_CALL_COLUMNS)
    extra_d = set().union(*(set(d) for d in decisions)) - set(AI_DECISION_COLUMNS) if decisions else set()
    if extra or extra_d:
        raise ValueError(f"columnas desconocidas en el journal del analista: {sorted(extra | extra_d)}")
    faltan = [c for c in AI_CALL_REQUIRED if call.get(c) is None]
    faltan += [f"decision.{c}" for d in decisions for c in AI_DECISION_REQUIRED if d.get(c) is None]
    if faltan:
        raise ValueError(f"faltan columnas obligatorias en el journal del analista: {sorted(set(faltan))}")
    cols = [c for c in AI_CALL_COLUMNS if c in call]
    cur = conn.execute(
        f"INSERT INTO ai_calls ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [call[c] for c in cols],
    )
    call_id = int(cur.lastrowid)
    conn.executemany(
        f"INSERT INTO ai_decisions (call_id, {', '.join(AI_DECISION_COLUMNS)})"
        f" VALUES (?, {', '.join('?' * len(AI_DECISION_COLUMNS))})",
        [[call_id, *(d.get(c) for c in AI_DECISION_COLUMNS)] for d in decisions],
    )
    return call_id


def record_ai_call(
    conn: sqlite3.Connection, call: dict[str, Any], decisions: list[dict[str, Any]] = ()
) -> int:
    """Una llamada fuera de una vela (una sonda), en su propia transaccion."""
    with conn:
        return _write_ai_call(conn, call, list(decisions))


# --- avisos de Telegram (006_avisos.sql) ---------------------------------


def _write_avisos(conn: sqlite3.Connection, ts_ms: int, avisos: list[tuple[str, str, str]]) -> None:
    """(tipo, clave, texto). La clave es UNICA: el mismo aviso no entra dos veces."""
    if avisos:
        conn.executemany(
            "INSERT OR IGNORE INTO paper_avisos (ts_ms, tipo, clave, texto) VALUES (?,?,?,?)",
            [(ts_ms, tipo, clave, texto) for tipo, clave, texto in avisos],
        )


def ultima_paridad(conn: sqlite3.Connection, antes_de_ms: int) -> tuple[float | None, str] | None:
    """La ultima lectura de la regla 17 guardada ANTES de esa vela: (desviacion %, detalle), o None si no hay.

    Sale de la base y no de la memoria: tras un reinicio, el aviso de "bloqueada" o "recuperada" tiene que
    comparar con lo que habia antes de parar.
    """
    fila = conn.execute(
        "SELECT deviation_pct, detail FROM paper_usdc WHERE ts_ms < ? ORDER BY ts_ms DESC LIMIT 1", (antes_de_ms,)
    ).fetchone()
    return None if fila is None else (fila[0], fila[1])


def encolar_avisos(conn: sqlite3.Connection, ts_ms: int, avisos: list[tuple[str, str, str]]) -> None:
    """Avisos que no son de una vela (la salida de QUOTA por sonda, el resumen)."""
    with conn:
        _write_avisos(conn, ts_ms, avisos)


def avisos_pendientes(conn: sqlite3.Connection, limite: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, ts_ms, tipo, clave, texto, intentos FROM paper_avisos"
        " WHERE enviado_ms IS NULL AND descartado = 0 ORDER BY id LIMIT ?", (limite,),
    ).fetchall()


def marcar_aviso(conn: sqlite3.Connection, aviso_id: int, *, enviado_ms: int | None, error: str | None) -> None:
    with conn:
        if enviado_ms is not None:
            conn.execute("UPDATE paper_avisos SET enviado_ms = ?, intentos = intentos + 1,"
                         " ultimo_error = NULL WHERE id = ?", (enviado_ms, aviso_id))
        else:
            conn.execute("UPDATE paper_avisos SET intentos = intentos + 1, ultimo_error = ?"
                         " WHERE id = ?", (error, aviso_id))


def descartar_avisos_viejos(conn: sqlite3.Connection, antes_de_ms: int) -> int:
    """Los pendientes generados antes de `antes_de_ms` ya no se mandan: llegarian
    como si fueran de ahora. Quedan en la tabla, marcados, para saber que existieron."""
    with conn:
        return conn.execute(
            "UPDATE paper_avisos SET descartado = 1 WHERE enviado_ms IS NULL"
            " AND descartado = 0 AND ts_ms < ?", (antes_de_ms,),
        ).rowcount


def record_manual_reset(
    conn: sqlite3.Connection, ts_ms: int, mode: str, reason: str, effective_after: str
) -> None:
    """El reset manual de un modo enclavado. Solo lo hace el propietario, a mano."""
    with conn:
        _write_mode_changes(
            conn, ts_ms, [(mode, False, f"RESET MANUAL: {reason}", effective_after)]
        )


def load_modes(conn: sqlite3.Connection) -> ModeMachine:
    """Reconstruye los modos activos reproduciendo las transiciones guardadas."""
    machine = ModeMachine()
    for r in conn.execute("SELECT * FROM paper_mode_changes ORDER BY id"):
        mode = Mode[r["mode"]]
        if r["activated"]:
            machine.activate(mode, r["reason"])
        else:
            machine.manual_reset(mode, r["reason"])
    return machine


def _write_context(
    conn: sqlite3.Connection,
    ts_ms: int,
    market: list[tuple[str, float, float]],
    correlations: list[tuple[str, str, float]],
) -> None:
    """Con que spread y que correlaciones se decidio esta vela (002_context.sql)."""
    if market:
        conn.executemany(
            "INSERT OR REPLACE INTO paper_market (ts_ms, symbol, spread_pct, depth_usd)"
            " VALUES (?,?,?,?)",
            [(ts_ms, s, spread, depth) for s, spread, depth in market],
        )
    if correlations:
        conn.executemany(
            "INSERT OR REPLACE INTO paper_correlations (ts_ms, a, b, corr)"
            " VALUES (?,?,?,?)",
            [(ts_ms, a, b, c) for a, b, c in correlations],
        )


def _write_decisions(
    conn: sqlite3.Connection, ts_ms: int, rows: list[tuple[Any, ...]]
) -> None:
    if rows:
        conn.executemany(
            "INSERT INTO paper_decisions (ts_ms, decision_id, symbol, setup,"
            " kind, detail) VALUES (?,?,?,?,?,?)",
            [(ts_ms, *row) for row in rows],
        )


def record_decisions(
    conn: sqlite3.Connection, ts_ms: int, rows: list[tuple[Any, ...]]
) -> None:
    """Apunta candidatos, ordenes, vetos y cribados (PRD seccion 10)."""
    with conn:
        _write_decisions(conn, ts_ms, rows)


# --------------------------------------------------------------------------
# Cargar
# --------------------------------------------------------------------------


def cursor(conn: sqlite3.Connection, timeframe: str) -> int | None:
    row = conn.execute(
        "SELECT last_ts_ms FROM paper_cursor WHERE timeframe = ?", (timeframe,)
    ).fetchone()
    return int(row[0]) if row else None


def load_state(conn: sqlite3.Connection, broker: PaperBroker, ledger: PaperLedger) -> None:
    """Rellena el simulador con lo guardado. Al reves de `save_state`."""
    broker.orders = [
        PaperOrder(
            decision_id=r["decision_id"],
            symbol=r["symbol"],
            qty=r["qty"],
            limit_price=r["limit_price"],
            stop_price=r["stop_price"],
            target_price=r["target_price"],
            setup=r["setup"],
            created_ts_ms=r["created_ts_ms"],
            state=OrderState(r["state"]),
            bars_waited=r["bars_waited"],
        )
        for r in conn.execute("SELECT * FROM paper_orders")
    ]

    broker.positions = {
        r["symbol"]: PaperPosition(
            decision_id=r["decision_id"],
            symbol=r["symbol"],
            qty=r["qty"],
            entry_price=r["entry_price"],
            stop_price=r["stop_price"],
            target_price=r["target_price"],
            setup=r["setup"],
            opened_ts_ms=r["opened_ts_ms"],
            entry_fee_usd=r["entry_fee_usd"],
            worst_price=r["worst_price"],
            best_price=r["best_price"],
        )
        for r in conn.execute("SELECT * FROM paper_positions")
    }

    broker.trades = [
        PaperTrade(
            decision_id=r["decision_id"],
            symbol=r["symbol"],
            setup=r["setup"],
            qty=r["qty"],
            entry_price=r["entry_price"],
            exit_price=r["exit_price"],
            stop_price=r["stop_price"],
            target_price=r["target_price"],
            opened_ts_ms=r["opened_ts_ms"],
            closed_ts_ms=r["closed_ts_ms"],
            reason=ExitReason(r["reason"]),
            entry_fee_usd=r["entry_fee_usd"],
            exit_fee_usd=r["exit_fee_usd"],
            exit_was_maker=bool(r["exit_was_maker"]),
            mae_pct=r["mae_pct"],
            mfe_pct=r["mfe_pct"],
        )
        for r in conn.execute("SELECT * FROM paper_trades ORDER BY closed_ts_ms")
    ]

    ledger.history = [
        (int(r["ts_ms"]), float(r["equity_usd"]))
        for r in conn.execute("SELECT * FROM paper_equity ORDER BY ts_ms")
    ]
