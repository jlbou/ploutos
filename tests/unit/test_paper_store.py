"""Persistencia del bucle de papel.

LO QUE HAY QUE PROTEGER: el criterio de avance pide 72 h de operaciones
coherentes, y la unidad de systemd lleva `Restart=always`, o sea que los
reinicios van a pasar. Si uno perdiera las posiciones abiertas, esas 72 h no
demostrarian nada: el simulador arrancaria vacio cada vez y nunca cerraria una
operacion que dure mas que el uptime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio import store
from portfolio.paper import (
    Bar,
    ExitReason,
    OrderState,
    PaperBroker,
    PaperLedger,
)
from tests.risk_fixtures import INSTRUMENTS

SYMBOL = "ETH/USDC"
BAR_MS = 4 * 60 * 60 * 1000
T0 = 1_756_000_000_000
ENTRY, STOP, TARGET, QTY = 100.0, 97.0, 106.0, 0.15


@pytest.fixture
def conn(tmp_path: Path):
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    yield c
    c.close()


def bar(i, o, h, low, c):
    return Bar(ts_open_ms=T0 + i * BAR_MS, open=o, high=h, low=low, close=c)


def fresh() -> tuple[PaperBroker, PaperLedger]:
    b = PaperBroker(INSTRUMENTS)
    return b, PaperLedger(starting_usd=50.0, broker=b)


# --------------------------------------------------------------------------
# Ida y vuelta
# --------------------------------------------------------------------------


def test_el_esquema_es_idempotente(conn):
    assert store.migrate(conn) == [], "aplicar dos veces no hace nada"


def test_una_entrada_pendiente_sobrevive_al_reinicio(conn):
    broker, ledger = fresh()
    broker.submit("d-1", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    store.save_state(conn, broker, ledger, "4h", T0)

    otro, otro_ledger = fresh()
    store.load_state(conn, otro, otro_ledger)

    assert len(otro.pending) == 1
    o = otro.pending[0]
    assert (o.decision_id, o.symbol, o.qty) == ("d-1", SYMBOL, QTY)
    assert (o.limit_price, o.stop_price, o.target_price) == (ENTRY, STOP, TARGET)
    assert o.state is OrderState.PENDING


def test_una_posicion_abierta_sobrevive_al_reinicio(conn):
    """EL CASO QUE IMPORTA. Sin esto, una posicion abierta antes de un
    reinicio quedaria huerfana: el simulador no sabria que existe y nunca la
    cerraria ni en el stop ni en el objetivo."""
    broker, ledger = fresh()
    broker.submit("d-1", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    assert SYMBOL in broker.positions
    store.save_state(conn, broker, ledger, "4h", T0 + BAR_MS)

    otro, otro_ledger = fresh()
    store.load_state(conn, otro, otro_ledger)

    p = otro.positions[SYMBOL]
    assert p.decision_id == "d-1"
    assert p.entry_price == ENTRY
    assert p.stop_price == STOP
    assert p.entry_fee_usd > 0

    # Y sigue funcionando: la vela siguiente la cierra en el objetivo.
    cerradas = otro.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))
    assert len(cerradas) == 1
    assert cerradas[0].reason is ExitReason.TARGET


def test_las_operaciones_cerradas_sobreviven(conn):
    broker, ledger = fresh()
    broker.submit("d-1", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))
    original = broker.trades[0]
    store.save_state(conn, broker, ledger, "4h", T0 + 2 * BAR_MS)

    otro, otro_ledger = fresh()
    store.load_state(conn, otro, otro_ledger)

    t = otro.trades[0]
    assert t.decision_id == original.decision_id
    assert t.net_pnl_usd == pytest.approx(original.net_pnl_usd)
    assert t.r_multiple == pytest.approx(original.r_multiple)
    assert t.mae_pct == pytest.approx(original.mae_pct)
    assert otro.stats()["trades"] == 1


def test_la_curva_de_equity_sobrevive(conn):
    broker, ledger = fresh()
    for i in range(5):
        ledger.record(T0 + i * BAR_MS, {})
    store.save_state(conn, broker, ledger, "4h", T0)

    otro, otro_ledger = fresh()
    store.load_state(conn, otro, otro_ledger)
    assert len(otro_ledger.history) == 5
    assert otro_ledger.max_drawdown_pct() == ledger.max_drawdown_pct()


def test_guardar_dos_veces_no_duplica(conn):
    """`save_state` reescribe el estado entero, asi que tiene que ser
    idempotente: si no, cada pasada duplicaria las operaciones."""
    broker, ledger = fresh()
    broker.submit("d-1", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))

    store.save_state(conn, broker, ledger, "4h", T0)
    store.save_state(conn, broker, ledger, "4h", T0)

    otro, otro_ledger = fresh()
    store.load_state(conn, otro, otro_ledger)
    assert len(otro.trades) == 1
    assert len(otro.orders) == 1


# --------------------------------------------------------------------------
# El cursor
# --------------------------------------------------------------------------


def test_sin_cursor_es_un_arranque_limpio(conn):
    assert store.cursor(conn, "4h") is None


def test_el_cursor_dice_hasta_donde_se_proceso(conn):
    broker, ledger = fresh()
    store.save_state(conn, broker, ledger, "4h", T0 + 7 * BAR_MS)
    assert store.cursor(conn, "4h") == T0 + 7 * BAR_MS


def test_cada_timeframe_lleva_su_cursor(conn):
    broker, ledger = fresh()
    store.save_state(conn, broker, ledger, "4h", T0)
    store.save_state(conn, broker, ledger, "1h", T0 + BAR_MS)
    assert store.cursor(conn, "4h") == T0
    assert store.cursor(conn, "1h") == T0 + BAR_MS


# --------------------------------------------------------------------------
# El journal
# --------------------------------------------------------------------------


def test_las_decisiones_quedan_apuntadas(conn):
    """PRD seccion 10: hay que poder contestar "por que esta moneda lleva un
    dia sin producir nada"."""
    store.record_decisions(
        conn, T0,
        [
            ("d-1", "ETH/USDC", "pullback_trend", "candidate", "R:R 3.4"),
            ("d-1", "ETH/USDC", "pullback_trend", "submitted", "mejor R:R"),
            (None, "BTC/USDC", None, "filtered", "spread 0.5 %"),
        ],
    )
    filas = list(conn.execute("SELECT * FROM paper_decisions ORDER BY id"))
    assert len(filas) == 3
    assert {f["kind"] for f in filas} == {"candidate", "submitted", "filtered"}
    assert filas[2]["decision_id"] is None


def test_el_decision_id_encadena_candidato_y_operacion(conn):
    """PRD seccion 13: candidato -> veredicto -> orden -> fill -> cierre."""
    broker, ledger = fresh()
    broker.submit("d-abc", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))
    store.save_state(conn, broker, ledger, "4h", T0)
    store.record_decisions(
        conn, T0, [("d-abc", SYMBOL, "pullback_trend", "candidate", "x")]
    )

    fila = conn.execute(
        "SELECT t.net_pnl_usd, d.kind FROM paper_trades t "
        "JOIN paper_decisions d ON d.decision_id = t.decision_id "
        "WHERE t.decision_id = ?",
        ("d-abc",),
    ).fetchone()
    assert fila is not None, "la cadena tiene que poder recorrerse con un JOIN"


def test_el_decider_queda_registrado(conn):
    """Para poder separar las operaciones del baseline de las de la IA cuando
    se comparen en la fase 6."""
    broker, ledger = fresh()
    broker.submit("d-1", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))
    store.save_state(conn, broker, ledger, "4h", T0, decider="baseline")
    fila = conn.execute("SELECT decider FROM paper_trades").fetchone()
    assert fila["decider"] == "baseline"


# --------------------------------------------------------------------------
# Las reglas con memoria (10, 11 y 14) tambien sobreviven al reinicio
# --------------------------------------------------------------------------
#
# BUG REAL (22/09/2026): el bucle llevaba en memoria las operaciones cerradas
# hoy y las recientes, y no las reconstruia al arrancar. Tras un reinicio, la
# perdida del dia, las operaciones del dia, los cooldowns y la pausa volvian a
# cero aunque las operaciones estuvieran en la base. Con `Restart=always`, un
# reinicio a media tarde habria dejado operar por encima de las reglas 10, 11
# y 14 sin que nada se pusiera en rojo.


def _loop(broker, ledger):
    from core.config import load_settings
    from portfolio.loop import TradingLoop

    return TradingLoop(
        instruments=INSTRUMENTS, cost=None, settings=load_settings(),
        broker=broker, ledger=ledger,
    )


def _stop_en_la_vela_2(broker):
    broker.submit("d-1", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))    # se llena
    broker.on_bar(SYMBOL, bar(2, 99, 99.5, 96.0, 96.5))   # salta el stop
    assert broker.trades[0].reason is ExitReason.STOP


def test_tras_reiniciar_se_recuerda_el_stop_de_hoy(conn):
    from datetime import UTC, datetime

    from features.context import CorrelationMatrix

    broker, ledger = fresh()
    _stop_en_la_vela_2(broker)
    store.save_state(conn, broker, ledger, "4h", T0 + 2 * BAR_MS)

    # "Reinicio": todo nuevo, cargado de la base.
    otro, otro_ledger = fresh()
    store.load_state(conn, otro, otro_ledger)
    loop = _loop(otro, otro_ledger)

    una_hora_despues = datetime.fromtimestamp(
        (T0 + 2 * BAR_MS + 3600 * 1000) / 1000, tz=UTC
    )
    state = loop._state(una_hora_despues, {}, CorrelationMatrix())

    # Regla 10 y 11: la operacion de hoy cuenta.
    assert len(state.closed_today) == 1
    assert state.pnl_today_usd == pytest.approx(broker.trades[0].net_pnl_usd)
    # Regla 14: el simbolo sigue en cooldown una hora despues del stop.
    hasta = state.cooldown_until(SYMBOL, 2)
    assert hasta is not None and state.now < hasta


def test_las_de_ayer_no_cuentan_para_hoy(conn):
    """El reset de las 00:00 UTC tiene que seguir funcionando."""
    from datetime import UTC, datetime, timedelta

    broker, ledger = fresh()
    _stop_en_la_vela_2(broker)
    loop = _loop(broker, ledger)

    cierre = datetime.fromtimestamp((T0 + 2 * BAR_MS) / 1000, tz=UTC)
    manyana = (cierre + timedelta(days=1)).replace(hour=0, minute=30)
    hoy, recientes = loop.closed_trades(manyana)

    assert hoy == ()
    assert len(recientes) == 1, "para los cooldowns sigue contando"


def test_la_historia_de_la_curva_no_se_reescribe(conn):
    """BUG REAL (22/09/2026): cada guardado escribia los contadores de AHORA
    en TODAS las filas de la curva, machacando la historia."""
    broker, ledger = fresh()
    broker.submit("d-1", SYMBOL, QTY, ENTRY, STOP, TARGET, "pullback_trend", T0)
    ledger.record(T0, {})
    store.save_state(conn, broker, ledger, "4h", T0)       # 1 pendiente

    broker.cancel_pending()
    ledger.record(T0 + BAR_MS, {})
    store.save_state(conn, broker, ledger, "4h", T0 + BAR_MS)  # 0 pendientes

    filas = conn.execute(
        "SELECT ts_ms, pending FROM paper_equity ORDER BY ts_ms"
    ).fetchall()
    assert [tuple(f) for f in filas] == [(T0, 1), (T0 + BAR_MS, 0)]
