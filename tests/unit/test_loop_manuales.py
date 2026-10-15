"""La pausa (/pause) y la parada (/kill) de Telegram dentro del bucle (pieza 4 del diseno).

- con pausa: no se abre nada y se cancelan las entradas pendientes; las posiciones siguen;
- en HALTED, ademas, el bot no toca las posiciones: ni la venta por noticia critica;
- sin base de control (`manuales=None`) no cambia nada: una pausa guardada sigue.
"""

from __future__ import annotations

from core.config import load_settings
from core.modes import Mode
from portfolio.loop import MANUALES, TradingLoop
from portfolio.paper import Bar, OrderState, PaperBroker, PaperLedger
from tests.risk_fixtures import INSTRUMENTS

H4 = 4 * 3600 * 1000
T0 = 1_790_035_200_000          # 22/09/2026 00:00 UTC
SETTINGS = load_settings()
PAUSA = {Mode.CLOSE_ONLY_MANUAL: "/pause desde Telegram (10:00 UTC)"}
PARADA = {Mode.HALTED: "/kill desde Telegram (10:00 UTC)"}


def bar(i, o, h, low, c):
    return Bar(ts_open_ms=T0 + i * H4, open=o, high=h, low=low, close=c)


def nuevo():
    broker = PaperBroker(INSTRUMENTS)
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    loop = TradingLoop(instruments=INSTRUMENTS, cost=None, settings=SETTINGS, broker=broker, ledger=ledger)
    return broker, loop


def paso(loop, i, bars, **kw):
    return loop.step(T0 + i * H4, {}, bars, {}, usdc_deviation_pct=0.0, **kw)


def test_la_pausa_entra_cancela_las_pendientes_y_avisa():
    broker, loop = nuevo()
    broker.submit("d-sol", "SOL/USDC", 0.3, 50.0, 48.5, 53.0, "pullback_trend", T0)
    r = paso(loop, 1, {"SOL/USDC": bar(1, 51, 52, 50.5, 51)}, manuales=PAUSA)
    assert loop.modes.effective is Mode.CLOSE_ONLY_MANUAL
    assert [(c.mode, c.activated) for c in r.mode_changes] == [(Mode.CLOSE_ONLY_MANUAL, True)]
    assert r.cancelled == 1
    assert broker.orders[0].state is OrderState.CANCELLED


def test_en_pausa_las_posiciones_siguen_con_su_stop():
    broker, loop = nuevo()
    broker.submit("d-eth", "ETH/USDC", 0.1, 100.0, 97.0, 106.0, "pullback_trend", T0)
    paso(loop, 1, {"ETH/USDC": bar(1, 100, 101, 99.5, 100)})             # se llena
    r = paso(loop, 2, {"ETH/USDC": bar(2, 97, 97.5, 96, 96.5)}, manuales=PAUSA)
    assert [t.decision_id for t in r.closed] == ["d-eth"]                 # salta el stop


def test_sin_base_de_control_no_cambia_nada():
    _broker, loop = nuevo()
    paso(loop, 1, {}, manuales=PAUSA)
    r = paso(loop, 2, {}, manuales=None)
    assert loop.modes.effective is Mode.CLOSE_ONLY_MANUAL and r.mode_changes == ()


def test_la_pausa_se_quita_cuando_los_comandos_lo_dicen():
    _broker, loop = nuevo()
    paso(loop, 1, {}, manuales=PAUSA)
    r = paso(loop, 2, {}, manuales={})
    assert loop.modes.effective is Mode.NORMAL
    assert [(c.mode, c.activated, c.reason) for c in r.mode_changes] == \
        [(Mode.CLOSE_ONLY_MANUAL, False, MANUALES[Mode.CLOSE_ONLY_MANUAL])]


def test_la_pausa_no_levanta_otros_modos():
    _broker, loop = nuevo()
    loop.modes.activate(Mode.CLOSE_ONLY_CAPITAL, "regla 7")
    paso(loop, 1, {}, manuales=PAUSA)
    paso(loop, 2, {}, manuales={})
    assert loop.modes.effective is Mode.CLOSE_ONLY_CAPITAL


def test_en_halted_no_se_vende_por_noticia_pero_los_stops_siguen():
    broker, loop = nuevo()
    broker.submit("d-eth", "ETH/USDC", 0.1, 100.0, 97.0, 106.0, "pullback_trend", T0)
    broker.submit("d-sol", "SOL/USDC", 0.3, 50.0, 48.5, 53.0, "pullback_trend", T0)
    paso(loop, 1, {"ETH/USDC": bar(1, 100, 101, 99.5, 100), "SOL/USDC": bar(1, 50, 51, 49.9, 50)})
    assert len(broker.positions) == 2

    r = paso(loop, 2, {"ETH/USDC": bar(2, 100, 101, 99, 100), "SOL/USDC": bar(2, 49, 49.5, 48, 48.2)},
             manuales=PARADA, salir_ya=frozenset({"ETH/USDC"}))
    assert loop.modes.effective is Mode.HALTED
    assert "ETH/USDC" in broker.positions                                # no se vende
    assert [t.decision_id for t in r.closed] == ["d-sol"]               # el stop de SOL, si


def test_sin_halted_la_venta_por_noticia_si_sale():
    broker, loop = nuevo()
    broker.submit("d-eth", "ETH/USDC", 0.1, 100.0, 97.0, 106.0, "pullback_trend", T0)
    paso(loop, 1, {"ETH/USDC": bar(1, 100, 101, 99.5, 100)})
    paso(loop, 2, {"ETH/USDC": bar(2, 100, 101, 99, 100)}, manuales=PAUSA,
         salir_ya=frozenset({"ETH/USDC"}))
    assert "ETH/USDC" not in broker.positions


def test_halted_se_levanta_con_su_motivo():
    _broker, loop = nuevo()
    paso(loop, 1, {}, manuales=PARADA)
    r = paso(loop, 2, {}, manuales={})
    assert loop.modes.effective is Mode.NORMAL
    assert r.mode_changes[0].reason == MANUALES[Mode.HALTED]
