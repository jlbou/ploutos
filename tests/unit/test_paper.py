"""Ejecucion en papel.

La mitad de estos tests comprueban las SUPOSICIONES del simulador, una por una.
Es donde un backtest se miente a si mismo, y un simulador optimista no falla:
simplemente da buenas noticias. Si alguno de estos se pone verde despues de
"mejorar" el simulador, lo que ha pasado es que ahora regala dinero.
"""

from __future__ import annotations

import pytest

from portfolio.paper import (
    ENTRY_BARS_TO_LIVE,
    Bar,
    ExitReason,
    OrderState,
    PaperBroker,
    PaperLedger,
)
from tests.risk_fixtures import INSTRUMENTS, MAKER, TAKER

SYMBOL = "ETH/USDC"
BAR_MS = 4 * 60 * 60 * 1000
T0 = 1_756_000_000_000

# Una operacion de referencia: entrada 100, stop 97, objetivo 106.
ENTRY, STOP, TARGET, QTY = 100.0, 97.0, 106.0, 0.15


@pytest.fixture
def broker() -> PaperBroker:
    return PaperBroker(INSTRUMENTS)


def bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(ts_open_ms=T0 + i * BAR_MS, open=o, high=h, low=low, close=c)


def submit(broker, entry=ENTRY, stop=STOP, target=TARGET, qty=QTY, ts=T0):
    return broker.submit(
        "d-test", SYMBOL, qty, entry, stop, target, "pullback_trend", ts
    )


# --------------------------------------------------------------------------
# Llenado de la entrada
# --------------------------------------------------------------------------


def test_la_entrada_se_llena_cuando_el_precio_baja_hasta_el_limite(broker):
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    assert SYMBOL in broker.positions
    assert broker.positions[SYMBOL].entry_price == ENTRY


def test_la_entrada_no_se_llena_si_el_precio_no_baja(broker):
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 103, 100.5, 102))
    assert SYMBOL not in broker.positions
    assert len(broker.pending) == 1


def test_la_vela_que_genera_la_senyal_no_puede_llenarla(broker):
    """El candidato nace del CIERRE de su vela, asi que la minima de esa vela
    ya ha pasado. Llenar con ella seria mirar el pasado desde el futuro."""
    submit(broker, ts=T0 + BAR_MS)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 90.0, 101))
    assert SYMBOL not in broker.positions


def test_la_entrada_se_llena_a_su_precio_aunque_el_mercado_abra_mas_abajo(broker):
    """SUPOSICION 2. En la realidad te llenarian a 95 y saldrias ganando. Aqui
    no se regalan mejoras de precio: si algun dia este test se pone rojo porque
    "ahora el simulador es mas realista", lo que se ha hecho es inflar los
    resultados."""
    submit(broker)
    # Abre en 98, por debajo del limite de 100, pero sin llegar al stop de 97.
    broker.on_bar(SYMBOL, bar(1, 98.0, 99.0, 97.5, 98.5))
    assert broker.positions[SYMBOL].entry_price == ENTRY


def test_la_entrada_caduca(broker):
    submit(broker)
    for i in range(1, ENTRY_BARS_TO_LIVE + 2):
        broker.on_bar(SYMBOL, bar(i, 105, 106, 104, 105))
    assert broker.orders[0].state is OrderState.EXPIRED
    assert not broker.pending


def test_una_entrada_cancelada_no_se_llena(broker):
    """PRD seccion 5: al entrar en modo de solo cierre se cancelan pendientes."""
    submit(broker)
    assert broker.cancel_pending() == 1
    broker.on_bar(SYMBOL, bar(1, 101, 102, 95.0, 101))
    assert SYMBOL not in broker.positions


# --------------------------------------------------------------------------
# Salidas
# --------------------------------------------------------------------------


def test_salida_por_objetivo(broker):
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    cerradas = broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))
    assert len(cerradas) == 1
    t = cerradas[0]
    assert t.reason is ExitReason.TARGET
    assert t.exit_price == TARGET
    assert t.exit_was_maker
    assert t.net_pnl_usd > 0


def test_salida_por_stop(broker):
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    cerradas = broker.on_bar(SYMBOL, bar(2, 100, 100.5, 96.0, 96.5))
    t = cerradas[0]
    assert t.reason is ExitReason.STOP
    assert t.exit_price == STOP
    assert not t.exit_was_maker
    assert t.net_pnl_usd < 0


def test_si_la_vela_toca_stop_y_objetivo_gana_el_stop(broker):
    """SUPOSICION 1, LA MAS IMPORTANTE DE TODAS.

    Con OHLC no se sabe cual toco primero. Suponer el objetivo infla los
    resultados de forma brutal y es la trampa mas comun del backtesting
    casero. Ante la duda, la version mala.
    """
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    cerradas = broker.on_bar(SYMBOL, bar(2, 100, 110.0, 95.0, 104.0))
    assert cerradas[0].reason is ExitReason.STOP


def test_el_stop_sufre_los_huecos(broker):
    """SUPOSICION 3. Si la vela abre por debajo del stop, se sale ahi.

    Es lo que hace visible el riesgo de hueco de los setups con stop estrecho,
    que es justo lo que habia que poder medir despues de darle a la reversion
    a la media un stop propio.
    """
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    cerradas = broker.on_bar(SYMBOL, bar(2, 92.0, 93.0, 91.0, 92.0))
    t = cerradas[0]
    assert t.exit_price == 92.0, "tiene que salir en la apertura, no en el stop"
    assert t.r_multiple < -1.0, "un hueco pierde MAS de 1R, y eso hay que verlo"


def test_el_objetivo_no_se_beneficia_de_los_huecos(broker):
    """SUPOSICION 4, la simetrica de la anterior. Asimetria a proposito: el
    hueco malo cuenta y el bueno no."""
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    cerradas = broker.on_bar(SYMBOL, bar(2, 112.0, 115.0, 111.0, 114.0))
    assert cerradas[0].exit_price == TARGET


def test_una_entrada_puede_llenarse_y_saltar_en_la_misma_vela(broker):
    """SUPOSICION 5. Te llenan en la minima y el precio sigue. Pasa en vivo."""
    submit(broker)
    cerradas = broker.on_bar(SYMBOL, bar(1, 101, 101.5, 96.0, 96.5))
    assert len(cerradas) == 1
    assert cerradas[0].reason is ExitReason.STOP


def test_en_la_vela_que_llena_no_cuenta_el_objetivo(broker):
    """SUPOSICION 7 (revision del 15/10/2026). Dentro de la vela no se sabe el orden: el maximo pudo pasar ANTES de que
    el precio bajara al limite. Como el stop (gana el stop), lo prudente: el objetivo empieza a contar en la siguiente."""
    submit(broker)
    assert broker.on_bar(SYMBOL, bar(1, 101, 107.0, 99.5, 103.0)) == []      # llena a 100 y toca 107: no cuenta
    assert SYMBOL in broker.positions
    (t,) = broker.on_bar(SYMBOL, bar(2, 103, 106.5, 102.0, 104.0))
    assert t.reason is ExitReason.TARGET and t.exit_price == TARGET


# --------------------------------------------------------------------------
# Comisiones
# --------------------------------------------------------------------------


def test_comisiones_por_pata(broker):
    """SUPOSICION 6. Entrada limit = maker. Objetivo = limit = maker.
    Stop = cruza el libro = taker."""
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    t = broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))[0]
    assert t.entry_fee_usd == pytest.approx(QTY * ENTRY * MAKER)
    assert t.exit_fee_usd == pytest.approx(QTY * TARGET * MAKER)

    otro = PaperBroker(INSTRUMENTS)
    submit(otro)
    otro.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    t2 = otro.on_bar(SYMBOL, bar(2, 100, 100.5, 96.0, 96.5))[0]
    assert t2.exit_fee_usd == pytest.approx(QTY * STOP * TAKER)


def test_el_filtro_de_coste_es_mas_pesimista_que_la_ejecucion(broker):
    """`strategy/costs.py` supone taker en la salida SIEMPRE; aqui una salida
    por objetivo es maker. Que el filtro sea mas duro que la realidad es la
    direccion segura: descarta de mas, nunca de menos."""
    from strategy.costs import CostModel, Fees

    cost = CostModel({SYMBOL: Fees(SYMBOL, MAKER, TAKER, 0)}, now_ms=0)
    estimado = cost.round_trip(SYMBOL, 0.0).total_pct

    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    t = broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))[0]
    real = t.fees_usd / (QTY * ENTRY) * 100.0
    assert real < estimado


def test_el_resultado_en_R_va_neto_de_comisiones(broker):
    """Una operacion que gana 1R bruto y 0,2R neto no gana 1R."""
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    t = broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))[0]
    bruto = t.gross_pnl_usd / t.planned_risk_usd
    assert t.r_multiple < bruto
    assert t.r_multiple == pytest.approx(t.net_pnl_usd / t.planned_risk_usd)


# --------------------------------------------------------------------------
# Lo que el simulador se niega a hacer
# --------------------------------------------------------------------------


def test_no_se_abren_dos_posiciones_en_el_mismo_simbolo(broker):
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    assert submit(broker) is None
    assert "ya hay algo vivo" in broker.rejected_submissions[0][1]


def test_precios_en_desorden_se_rechazan(broker):
    assert broker.submit("d", SYMBOL, QTY, 100, 105, 110, "x", T0) is None
    assert broker.submit("d", SYMBOL, QTY, 100, 97, 99, "x", T0) is None


def test_cantidad_cero_se_rechaza(broker):
    assert broker.submit("d", SYMBOL, 0.0, 100, 97, 106, "x", T0) is None


def test_instrumento_desconocido_se_rechaza(broker):
    assert broker.submit("d", "FOO/USDC", QTY, 100, 97, 106, "x", T0) is None


# --------------------------------------------------------------------------
# Metricas
# --------------------------------------------------------------------------


def test_sin_operaciones_no_hay_ratios(broker):
    """Un win rate sobre cero operaciones no es 100 %, es nada."""
    assert broker.stats() == {"trades": 0}


def test_las_metricas_cuadran(broker):
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    broker.on_bar(SYMBOL, bar(2, 101, 107, 100.5, 106.5))
    s = broker.stats()
    assert s["trades"] == 1
    assert s["targets"] == 1 and s["stops"] == 0
    assert s["win_rate_pct"] == 100.0
    assert s["net_pnl_usd"] == pytest.approx(s["gross_pnl_usd"] - s["fees_usd"])
    assert "profit_factor" not in s, "sin perdidas no hay profit factor"


def test_mae_y_mfe(broker):
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    broker.on_bar(SYMBOL, bar(2, 100, 103, 98.0, 102))
    t = broker.on_bar(SYMBOL, bar(3, 102, 107, 101, 106.5))[0]
    assert t.mae_pct == pytest.approx((98.0 - ENTRY) / ENTRY * 100.0)
    assert t.mfe_pct == pytest.approx((107.0 - ENTRY) / ENTRY * 100.0)


def test_huecos_ocupados_cuentan_pendientes(broker):
    """Regla 4."""
    submit(broker)
    assert broker.occupied_slots == 1
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    assert broker.occupied_slots == 1


# --------------------------------------------------------------------------
# Equity
# --------------------------------------------------------------------------


def test_el_equity_descuenta_la_salida_como_taker(broker):
    """Regla 6: el peor caso, igual que `risk/equity.py` con dinero real."""
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    submit(broker)
    broker.on_bar(SYMBOL, bar(1, 101, 102, 99.5, 101))
    equity = ledger.equity_usd({SYMBOL: ENTRY})
    assert equity < 50.0, "aun sin moverse el precio, la salida costaria comision"
    # La entrada ya se pago (maker) y la salida se estima como taker. Este test
    # daba por buena la version que olvidaba la de entrada: el test tenia el
    # bug escrito como comportamiento esperado.
    assert equity == pytest.approx(50.0 - QTY * ENTRY * MAKER - QTY * ENTRY * TAKER)


def test_drawdown_maximo(broker):
    ledger = PaperLedger(starting_usd=50.0, broker=broker)
    for i, equity in enumerate((50.0, 52.0, 48.0, 51.0)):
        ledger.history.append((T0 + i * BAR_MS, equity))
    assert ledger.max_drawdown_pct() == pytest.approx((52.0 - 48.0) / 52.0 * 100.0)


# --------------------------------------------------------------------------
# Propiedades sobre secuencias aleatorias
# --------------------------------------------------------------------------

from hypothesis import given, settings as hyp_settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

velas = st.lists(
    st.tuples(
        st.floats(min_value=80.0, max_value=130.0),
        st.floats(min_value=80.0, max_value=130.0),
        st.floats(min_value=80.0, max_value=130.0),
    ),
    min_size=1,
    max_size=12,
)


def _run(secuencia) -> PaperBroker:
    broker = PaperBroker(INSTRUMENTS)
    submit(broker)
    for i, (a, b, c) in enumerate(secuencia, start=1):
        low, high = min(a, b, c), max(a, b, c)
        broker.on_bar(SYMBOL, bar(i, a, high, low, c))
    return broker


@given(secuencia=velas)
@hyp_settings(max_examples=200, deadline=None)
def test_una_salida_por_stop_nunca_es_una_ganancia(secuencia):
    """En largo, el stop esta por debajo de la entrada y ademas se paga
    comision. Si alguna vez saliera positiva, el simulador estaria regalando
    dinero por algun lado."""
    for t in _run(secuencia).trades:
        if t.hit_stop:
            assert t.gross_pnl_usd < 0
            assert t.net_pnl_usd < 0
            assert t.r_multiple < 0


@given(secuencia=velas)
@hyp_settings(max_examples=200, deadline=None)
def test_una_salida_por_objetivo_siempre_gana_en_bruto(secuencia):
    for t in _run(secuencia).trades:
        if t.reason is ExitReason.TARGET:
            assert t.exit_price == TARGET
            assert t.gross_pnl_usd > 0


@given(secuencia=velas)
@hyp_settings(max_examples=200, deadline=None)
def test_las_cuentas_siempre_cuadran(secuencia):
    for t in _run(secuencia).trades:
        assert t.net_pnl_usd == pytest.approx(t.gross_pnl_usd - t.fees_usd)
        assert t.fees_usd > 0, "toda operacion paga comision en las dos patas"
        assert t.mae_pct <= 0.0 or t.mae_pct == pytest.approx(0.0)
        assert t.mfe_pct >= 0.0 or t.mfe_pct == pytest.approx(0.0)


@given(secuencia=velas)
@hyp_settings(max_examples=200, deadline=None)
def test_nunca_hay_mas_de_una_posicion_por_simbolo(secuencia):
    """Regla 4, comprobada tambien en el simulador."""
    broker = _run(secuencia)
    assert len(broker.positions) <= 1
    assert len(broker.trades) <= 1, "una sola orden no puede dar dos operaciones"


@given(secuencia=velas)
@hyp_settings(max_examples=200, deadline=None)
def test_el_precio_de_salida_esta_dentro_de_lo_posible(secuencia):
    """Ni por encima del objetivo ni por debajo de la minima de la vela."""
    for t in _run(secuencia).trades:
        assert t.exit_price <= t.target_price + 1e-9
        assert t.exit_price > 0
