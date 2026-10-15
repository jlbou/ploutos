"""El bucle de una pasada: filtros -> candidatos.

Este modulo existe porque `strategy/filters.py` estaba escrito, probado y
**no lo llamaba nadie**. Lo que hay que proteger aqui es que la capa de filtros
siga enchufada, que corra ANTES de lo caro, y que **no cambie ninguna decision**:
es una optimizacion, no una autoridad.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from features.context import CorrelationMatrix
from risk.limits import Limits
from strategy.candidates import generate_for_symbol
from strategy.costs import CostModel, Fees
from strategy.pipeline import MarketData, run
from tests import market_fixtures as mf
from tests.risk_fixtures import INSTRUMENTS, MAKER, PRICES, TAKER, make_position, make_state

NOW = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)


@pytest.fixture
def cost() -> CostModel:
    return CostModel(
        {s: Fees(s, MAKER, TAKER, NOW_MS) for s in INSTRUMENTS}, now_ms=NOW_MS
    )


@pytest.fixture
def limits(settings) -> Limits:
    return Limits.for_state(settings, equity_usd=50.0, slider_level=3)


def data(symbol="ETH/USDC", candles=None, *, spread=0.02, depth=5_000.0, **kw):
    return MarketData(
        symbol=symbol,
        candles=candles if candles is not None else mf.trending_up(pullback=True),
        spread_pct=spread,
        depth_usd=depth,
        **kw,
    )


def go(market, settings, limits, cost, state=None, correlations=None):
    return run(
        market,
        state or make_state(),
        limits,
        settings,
        cost,
        INSTRUMENTS,
        timeframe="4h",
        now=NOW,
        correlations=correlations,
    )


# --------------------------------------------------------------------------
# La capa de filtros esta enchufada
# --------------------------------------------------------------------------


def test_una_moneda_sana_llega_a_candidato(settings, limits, cost):
    result = go({"ETH/USDC": data()}, settings, limits, cost)
    assert result.eligible == ("ETH/USDC",)
    assert len(result.candidates) == 1


def test_una_moneda_cribada_no_genera_candidatos(settings, limits, cost):
    """REGRESION. Antes el recorrido iba directo al generador y los filtros no
    corrian nunca: una moneda con el spread por las nubes generaba candidatos
    igualmente y solo la paraba el motor de riesgo, mucho mas tarde."""
    result = go({"ETH/USDC": data(spread=0.5)}, settings, limits, cost)
    assert result.eligible == ()
    assert result.candidates == ()
    assert len(result.filtered_out) == 1


def test_el_filtro_de_profundidad_corre_de_verdad(settings, limits, cost):
    """Es el filtro que SOSTIENE la suposicion de impacto de mercado cero del
    modelo de costes. Si no corre, esa suposicion no la respalda nada."""
    result = go({"ETH/USDC": data(depth=10.0)}, settings, limits, cost)
    assert result.candidates == ()
    motivos = {r.name for s in result.filtered_out for r in s.rejections}
    assert "profundidad" in motivos


def test_el_guardian_de_frescura_corre_de_verdad(settings, limits, cost):
    result = go(
        {"ETH/USDC": data(data_fresh=False, stale_reason="libro parado")},
        settings, limits, cost,
    )
    assert result.candidates == ()
    motivos = {r.name for s in result.filtered_out for r in s.rejections}
    assert "frescura" in motivos


def test_sin_velas_no_se_inventa_nada(settings, limits, cost):
    import pandas as pd

    vacio = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    result = go({"ETH/USDC": data(candles=vacio)}, settings, limits, cost)
    assert result.candidates == ()


# --------------------------------------------------------------------------
# Lo barato antes que lo caro
# --------------------------------------------------------------------------


def test_a_una_moneda_cribada_no_se_le_calcula_el_regimen(settings, limits, cost):
    """El orden es la razon de ser del modulo: cribar con lo que cuesta poco
    antes de calcular indicadores y buscar setups. Una moneda descartada por
    spread no necesita que se le calcule el ADX."""
    result = go({"ETH/USDC": data(spread=0.5)}, settings, limits, cost)
    assert result.regimes == {}


def test_a_una_moneda_apta_si(settings, limits, cost):
    result = go({"ETH/USDC": data()}, settings, limits, cost)
    assert "ETH/USDC" in result.regimes


# --------------------------------------------------------------------------
# LOS FILTROS NO DECIDEN
# --------------------------------------------------------------------------


def test_los_filtros_no_cambian_ninguna_decision(settings, limits, cost):
    """LA PROPIEDAD QUE IMPORTA.

    Los filtros existen para no gastar cuota de Claude ni CPU, no para decidir.
    Sobre una moneda sana tienen que dar EXACTAMENTE el mismo candidato que se
    obtiene saltandoselos. Si alguna vez difieren, es que los filtros han
    empezado a tomar decisiones por su cuenta.
    """
    candles = mf.trending_up(pullback=True)
    con = go({"ETH/USDC": data(candles=candles)}, settings, limits, cost)
    sin = generate_for_symbol(
        "ETH/USDC", "4h", candles, 0.02, cost, limits, settings, now=NOW
    )

    assert len(con.candidates) == len(sin.candidates) == 1
    a, b = con.candidates[0], sin.candidates[0]
    assert a.decision_id == b.decision_id
    assert (a.entry, a.stop, a.target) == (b.entry, b.stop, b.target)
    assert a.reward_risk == b.reward_risk


# --------------------------------------------------------------------------
# Las correlaciones llegan al motor
# --------------------------------------------------------------------------


def test_las_correlaciones_entran_en_la_foto(settings, limits, cost):
    """REGRESION. La mitad de correlacion de la regla 15 no habia vetado nunca
    nada porque `RiskState.correlations` llegaba vacio."""
    matriz = CorrelationMatrix(
        {("BTC/USDC", "ETH/USDC"): 0.95, ("ETH/USDC", "SOL/USDC"): 0.91}
    )
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("SOL/USDC")),
        marks={s: PRICES[s] for s in ("BTC/USDC", "SOL/USDC")},
    )
    result = go(
        {"ETH/USDC": data()}, settings, limits, cost,
        state=state, correlations=matriz,
    )
    assert result.candidates == ()
    motivos = {r.name for s in result.filtered_out for r in s.rejections}
    assert "correlacion" in motivos


def test_sin_correlaciones_el_filtro_no_puede_vetar(settings, limits, cost):
    """El mismo caso SIN la matriz: nadie ve la correlacion y pasa.

    Es exactamente el agujero que habia, escrito como test para que se vea la
    diferencia entre pasar el dato y no pasarlo.
    """
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("SOL/USDC")),
        marks={s: PRICES[s] for s in ("BTC/USDC", "SOL/USDC")},
    )
    result = go({"ETH/USDC": data()}, settings, limits, cost, state=state)
    motivos = {r.name for s in result.filtered_out for r in s.rejections}
    assert "correlacion" not in motivos


# --------------------------------------------------------------------------
# Varias monedas
# --------------------------------------------------------------------------


def test_una_pasada_sobre_varias_monedas(settings, limits, cost):
    market = {
        "ETH/USDC": data("ETH/USDC"),
        "SOL/USDC": data("SOL/USDC", candles=mf.range_then_breakout()),
        "BTC/USDC": data("BTC/USDC", candles=mf.trending_down()),
        "XRP/USDC": data("XRP/USDC", spread=0.9),
    }
    result = go(market, settings, limits, cost)
    assert "XRP/USDC" not in result.eligible, "cribada por spread"
    assert "BTC/USDC" in result.eligible, "pasa filtros pero no dara candidato"
    assert {c.symbol for c in result.candidates} == {"ETH/USDC", "SOL/USDC"}
    assert len(result.screenings) == 4


def test_el_resumen_cuenta_las_dos_capas(settings, limits, cost):
    market = {"ETH/USDC": data(), "XRP/USDC": data("XRP/USDC", spread=0.9)}
    resumen = go(market, settings, limits, cost).summary()
    assert "1/2 monedas" in resumen


def test_la_generacion_sale_en_el_formato_que_espera_el_baseline(
    settings, limits, cost
):
    from strategy.baseline import choose

    result = go({"ETH/USDC": data()}, settings, limits, cost)
    elegido = choose(result.generation())
    assert elegido is not None
    assert elegido.candidate.symbol == "ETH/USDC"
