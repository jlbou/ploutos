"""Los modos del PRD seccion 5 dentro del bucle de papel.

BUG REAL (22/09/2026): el bucle vivia siempre en NORMAL. La maquina de modos
(`core/modes.py`) existia y estaba probada, pero nadie la usaba, asi que:
- la regla 7 no ENCLAVABA: con el equity rebotando a 26 $ el bot volvia a abrir;
- al llegar a la perdida diaria no se entraba en CLOSE_ONLY_DAILY ni se
  cancelaban las entradas pendientes, que es lo que manda el PRD seccion 5.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import load_settings
from core.modes import Mode
from portfolio import store
from portfolio.loop import TradingLoop
from portfolio.paper import Bar, OrderState, PaperBroker, PaperLedger
from tests.risk_fixtures import INSTRUMENTS

H4 = 4 * 3600 * 1000
T0 = 1_790_035_200_000          # 22/09/2026 00:00 UTC
SETTINGS = load_settings()


def bar(i, o, h, low, c):
    return Bar(ts_open_ms=T0 + i * H4, open=o, high=h, low=low, close=c)


def nuevo(starting=50.0):
    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=starting, broker=broker)
    loop = TradingLoop(
        instruments=INSTRUMENTS, cost=None, settings=SETTINGS, broker=broker, ledger=ledger,
    )
    return broker, ledger, loop


def paso(loop, i, bars):
    return loop.step(T0 + i * H4, {}, bars, {}, usdc_deviation_pct=0.0)


def _perder_4_dolares_hoy(broker, loop):
    """ETH: se llena en la vela 1 y salta el stop en la 2 (en la vela 0 se crea)."""
    broker.submit("d-eth", "ETH/USDC", 1.5, 100.0, 97.0, 106.0, "pullback_trend", T0)
    paso(loop, 1, {"ETH/USDC": bar(1, 100, 101, 99.5, 100)})
    return paso(loop, 2, {"ETH/USDC": bar(2, 97, 97.5, 96, 96.5)})


# --------------------------------------------------------------------------
# CLOSE_ONLY_DAILY
# --------------------------------------------------------------------------


def test_la_perdida_del_dia_activa_daily_y_cancela_las_pendientes():
    broker, _ledger, loop = nuevo()
    broker.submit("d-sol", "SOL/USDC", 0.3, 50.0, 48.5, 53.0, "pullback_trend", T0)
    r = _perder_4_dolares_hoy(broker, loop)

    assert loop.modes.effective is Mode.CLOSE_ONLY_DAILY
    assert [c.mode for c in r.mode_changes] == [Mode.CLOSE_ONLY_DAILY]
    assert r.cancelled == 1
    sol = next(o for o in broker.orders if o.symbol == "SOL/USDC")
    assert sol.state is OrderState.CANCELLED


def test_daily_se_levanta_sola_al_cambiar_de_dia():
    broker, _ledger, loop = nuevo()
    _perder_4_dolares_hoy(broker, loop)
    r = paso(loop, 6, {})          # 23/09 00:00 UTC
    assert loop.modes.effective is Mode.NORMAL
    assert [(c.mode, c.activated) for c in r.mode_changes] == [(Mode.CLOSE_ONLY_DAILY, False)]


def test_en_daily_el_motor_ve_el_modo():
    broker, _ledger, loop = nuevo()
    _perder_4_dolares_hoy(broker, loop)
    from features.context import CorrelationMatrix
    from datetime import UTC, datetime

    st = loop._state(datetime.fromtimestamp((T0 + 2 * H4) / 1000, tz=UTC), {}, CorrelationMatrix())
    assert st.mode is Mode.CLOSE_ONLY_DAILY


# --------------------------------------------------------------------------
# CLOSE_ONLY_CAPITAL: enclavado
# --------------------------------------------------------------------------


def test_una_sola_lectura_bajo_el_suelo_no_enclava():
    _b, ledger, loop = nuevo(starting=24.9)
    paso(loop, 0, {})
    assert Mode.CLOSE_ONLY_CAPITAL not in loop.modes.active


def test_dos_lecturas_seguidas_enclavan_y_cancelan():
    broker, ledger, loop = nuevo(starting=24.9)
    paso(loop, 0, {})
    broker.submit("d-sol", "SOL/USDC", 0.3, 50.0, 48.5, 53.0, "pullback_trend", T0)
    r = paso(loop, 1, {})
    assert loop.modes.effective is Mode.CLOSE_ONLY_CAPITAL
    assert r.cancelled == 1


def test_el_rebote_NO_saca_de_capital():
    """Lo que la regla 7 existe para impedir: oscilar alrededor del suelo."""
    _b, ledger, loop = nuevo(starting=24.9)
    paso(loop, 0, {})
    paso(loop, 1, {})
    ledger.starting_usd = 26.0     # el equity rebota por encima del suelo
    paso(loop, 2, {})
    paso(loop, 3, {})
    assert loop.modes.effective is Mode.CLOSE_ONLY_CAPITAL


@pytest.fixture
def conn(tmp_path: Path):
    c = store.connect(tmp_path / "paper.db")
    store.migrate(c)
    yield c
    c.close()


def _guardar(conn, loop, broker, ledger, i, r):
    store.save_step(
        conn, broker, ledger, "4h", T0 + i * H4, [],
        mode_changes=[(c.mode.name, c.activated, c.reason, c.effective_after.name)
                      for c in r.mode_changes],
    )


def test_capital_sobrevive_al_reinicio_y_solo_sale_a_mano(conn):
    broker, ledger, loop = nuevo(starting=24.9)
    for i in range(2):
        _guardar(conn, loop, broker, ledger, i, paso(loop, i, {}))
    assert store.load_modes(conn).effective is Mode.CLOSE_ONLY_CAPITAL

    store.record_manual_reset(conn, T0 + 3 * H4, "CLOSE_ONLY_CAPITAL", "revisado", "NORMAL")
    assert store.load_modes(conn).effective is Mode.NORMAL


def test_daily_guardado_y_levantado_se_reconstruye_bien(conn):
    broker, ledger, loop = nuevo()
    broker.submit("d-eth", "ETH/USDC", 1.5, 100.0, 97.0, 106.0, "pullback_trend", T0)
    for i, bars in ((1, {"ETH/USDC": bar(1, 100, 101, 99.5, 100)}),
                    (2, {"ETH/USDC": bar(2, 97, 97.5, 96, 96.5)}),
                    (6, {})):
        _guardar(conn, loop, broker, ledger, i, paso(loop, i, bars))
    assert store.load_modes(conn).effective is Mode.NORMAL


# --------------------------------------------------------------------------
# El juez de papel entiende los modos, y los deduce por su cuenta
# --------------------------------------------------------------------------

ETH_BARS = [bar(1, 100, 101, 99.5, 100), bar(2, 97, 97.5, 96, 96.5)]


@pytest.fixture
def base_con_daily(conn):
    """El bucle real: perdida del dia en la vela 2, entra DAILY y cancela SOL."""
    broker, ledger, loop = nuevo()
    r0 = paso(loop, 0, {})
    # Como el bucle real: se envia DURANTE la vela y se guarda al final.
    broker.submit("d-eth", "ETH/USDC", 1.5, 100.0, 97.0, 106.0, "pullback_trend", T0)
    broker.submit("d-sol", "SOL/USDC", 0.3, 50.0, 48.5, 53.0, "pullback_trend", T0)
    _guardar(conn, loop, broker, ledger, 0, r0)
    for i, b in ((1, ETH_BARS[0]), (2, ETH_BARS[1])):
        _guardar(conn, loop, broker, ledger, i, paso(loop, i, {"ETH/USDC": b}))
    return conn


def _auditar(conn):
    from portfolio.audit import Audit, PaperRecord

    return Audit(
        record=PaperRecord.from_db(conn, "4h"), bars={"ETH/USDC": ETH_BARS},
        instruments=INSTRUMENTS, settings=SETTINGS, timeframe_ms=H4,
    )


def test_el_juez_da_por_buena_la_cancelacion(base_con_daily):
    a = _auditar(base_con_daily)
    assert a.cancel_at == {"d-sol": T0 + 2 * H4}
    for check in (a.modos(), a.resimulacion(), a.equity()):
        assert check.ok, check.fallos


def test_el_juez_ve_una_pendiente_que_no_se_cancelo(base_con_daily):
    with base_con_daily:
        base_con_daily.execute("UPDATE paper_orders SET state = 'pending' WHERE decision_id = 'd-sol'")
    a = _auditar(base_con_daily)
    assert not a.modos().ok
    assert not a.resimulacion().ok


def test_el_juez_ve_una_cancelacion_sin_motivo(base_con_daily):
    with base_con_daily:
        base_con_daily.execute("DELETE FROM paper_trades")   # sin perdida, sin DAILY
        base_con_daily.execute("UPDATE paper_orders SET state = 'filled' WHERE decision_id = 'd-eth'")
    assert not _auditar(base_con_daily).resimulacion().ok


def test_el_juez_ve_una_entrada_en_solo_cierre(base_con_daily):
    with base_con_daily:
        base_con_daily.execute(
            "INSERT INTO paper_orders VALUES ('d-xrp', 'XRP/USDC', 10, 1.0, 0.97, 1.1,"
            f" 'pullback_trend', {T0 + 2 * H4}, 'pending', 0)"
        )
    assert not _auditar(base_con_daily).modos().ok
