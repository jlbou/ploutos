"""Generador de candidatos.

Lo que se comprueba aqui son las CUATRO PUERTAS (whitelist, regimen, R:R y
coste) y la trazabilidad. Que cada setup detecte lo suyo ya esta probado en
`test_setups.py`; aqui importa lo que pasa despues.

Los descartes se comprueban tanto como los candidatos: `Generation.rejections`
es lo que alimenta el panel del PRD seccion 10, y una lista de descartes que
miente es peor que no tenerla.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from features.regime import Regime
from risk.limits import Limits
from strategy.candidates import (
    Candidate,
    generate_all,
    generate_for_symbol,
    make_decision_id,
)
from strategy.costs import CostModel, Fees
from strategy.setups import setup_names
from tests import market_fixtures as mf
from tests.risk_fixtures import INSTRUMENTS, MAKER, TAKER

NOW = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)
SYMBOL = "ETH/USDC"


@pytest.fixture
def cost() -> CostModel:
    return CostModel(
        {s: Fees(s, MAKER, TAKER, NOW_MS) for s in INSTRUMENTS}, now_ms=NOW_MS
    )


@pytest.fixture
def limits(settings) -> Limits:
    return Limits.for_state(settings, equity_usd=50.0, slider_level=3)


def run(candles, settings, limits, cost, *, symbol=SYMBOL, spread=0.02, tf="4h"):
    return generate_for_symbol(
        symbol, tf, candles, spread, cost, limits, settings, now=NOW
    )


def gates(result) -> set[str]:
    return {r.gate for r in result.rejections}


# --------------------------------------------------------------------------
# El camino feliz
# --------------------------------------------------------------------------


def test_un_retroceso_en_tendencia_produce_candidato(settings, limits, cost):
    result = run(mf.trending_up(pullback=True), settings, limits, cost)
    assert len(result.candidates) == 1
    c = result.candidates[0]
    assert c.setup == "pullback_trend"
    assert c.symbol == SYMBOL
    assert c.regime is Regime.TREND_UP
    assert c.stop < c.entry < c.target
    assert c.reward_risk >= settings.strategy.min_reward_risk
    assert c.target_cost_ratio >= limits.min_target_cost_ratio


def test_una_ruptura_produce_candidato(settings, limits, cost):
    result = run(mf.range_then_breakout(), settings, limits, cost)
    setups = {c.setup for c in result.candidates}
    assert "range_breakout" in setups


def test_los_descartes_se_devuelven_con_su_motivo(settings, limits, cost):
    """Un mercado sin nada que ofrecer tiene que explicar por que."""
    result = run(mf.trending_down(), settings, limits, cost)
    assert not result.candidates
    assert len(result.rejections) == len(setup_names())
    assert gates(result) == {"regimen"}
    for r in result.rejections:
        assert "trend_down" in r.reason


# --------------------------------------------------------------------------
# Puerta 1: whitelist (regla 3, punto 2 de 5)
# --------------------------------------------------------------------------


def test_fuera_de_whitelist_no_genera_nada(settings, limits, cost):
    result = run(
        mf.trending_up(pullback=True), settings, limits, cost, symbol="ADA/USDC"
    )
    assert not result.candidates
    assert gates(result) == {"whitelist"}


# --------------------------------------------------------------------------
# Puerta 2: regimen y slider
# --------------------------------------------------------------------------


def test_en_alta_volatilidad_no_opera_nadie(settings, limits, cost):
    result = run(mf.high_volatility(), settings, limits, cost)
    assert not result.candidates
    assert gates(result) == {"regimen"}


def test_sin_regimen_clasificable_no_se_genera_nada(settings, limits, cost):
    result = run(mf.trending_up(n=40), settings, limits, cost)
    assert not result.candidates
    assert gates(result) == {"regimen"}
    assert "no clasificable" in result.rejections[0].reason


def test_el_slider_de_nivel_1_solo_deja_pullbacks(settings, cost):
    """Informe seccion 4.6: el nivel conservador solo opera pullbacks."""
    conservador = Limits.for_state(settings, 50.0, slider_level=1)
    result = run(mf.range_then_breakout(), settings, conservador, cost)
    assert not result.candidates
    descartes = {r.setup: r.gate for r in result.rejections}
    assert descartes["range_breakout"] == "slider"
    assert descartes["mean_reversion"] == "slider"


def test_el_slider_de_nivel_3_deja_los_tres(settings, cost):
    normal = Limits.for_state(settings, 50.0, slider_level=3)
    result = run(mf.range_then_breakout(), settings, normal, cost)
    assert "slider" not in gates(result)


# --------------------------------------------------------------------------
# Puerta 3: R:R
# --------------------------------------------------------------------------


def test_la_reversion_a_la_media_produce_candidato_con_su_stop(
    settings, limits, cost
):
    """Con el stop estructural (decision del propietario del 22/09/2026) este setup pasa.

    Con el stop uniforme de 1,9xATR no producia NI UNO: 285 velas reales en
    regimen `RANGE` daban 7 senyales con R:R mediano 0,91 y maximo 1,06.
    """
    result = run(mf.ranging(oversold=True), settings, limits, cost)
    reversion = [c for c in result.candidates if c.setup == "mean_reversion"]
    assert len(reversion) == 1
    assert reversion[0].reward_risk >= settings.strategy.min_reward_risk


def test_el_stop_propio_no_rompe_el_limite_de_riesgo(settings, limits, cost):
    """LO QUE HABIA QUE COMPROBAR al dar un stop propio a un setup.

    Un stop mas estrecho da una posicion MAYOR. Si el dimensionado no lo
    tuviera en cuenta, la regla 12 se saltaria por la puerta de atras. No pasa
    porque `risk/sizing.py` calcula el nocional desde el stop real, pero eso
    hay que verlo, no suponerlo.
    """
    from risk.engine import evaluate_with_limits
    from tests.risk_fixtures import make_state

    c = [
        x
        for x in run(mf.ranging(oversold=True), settings, limits, cost).candidates
        if x.setup == "mean_reversion"
    ][0]
    verdict = evaluate_with_limits(
        c.to_entry_request(INSTRUMENTS[SYMBOL]), make_state(), settings, 3
    )
    assert verdict.approved, verdict.reason()
    assert verdict.risk_usd <= limits.risk_per_trade_usd + 1e-9
    assert verdict.notional_usd <= limits.max_notional_usd + 1e-9


def test_un_R_R_mas_exigente_descarta_mas(settings, limits, cost, settings_dict,
                                          write_settings):
    from core.config import load_settings

    settings_dict["strategy"]["min_reward_risk"] = 10.0
    duro = load_settings(write_settings(settings_dict))
    result = run(mf.trending_up(pullback=True), duro, limits, cost)
    assert not result.candidates
    assert "R:R" in gates(result)


# --------------------------------------------------------------------------
# Puerta 4: coste (regla 16)
# --------------------------------------------------------------------------


def test_un_spread_enorme_mata_el_candidato(settings, limits, cost):
    """Con el spread por las nubes, el objetivo deja de pagar 3x el coste."""
    result = run(mf.trending_up(pullback=True), settings, limits, cost, spread=8.0)
    assert not result.candidates
    assert "coste" in gates(result)


def test_sin_comisiones_no_hay_candidatos(settings, limits):
    vacio = CostModel({}, now_ms=NOW_MS)
    result = run(mf.trending_up(pullback=True), settings, limits, vacio)
    assert not result.candidates
    assert gates(result) == {"coste"}
    assert "instruments" in result.rejections[0].reason


def test_el_coste_del_candidato_usa_el_movimiento_al_objetivo(
    settings, limits, cost
):
    """La comision de salida se cobra sobre el nocional de salida."""
    result = run(mf.trending_up(pullback=True), settings, limits, cost)
    c = result.candidates[0]
    esperado = cost.round_trip(SYMBOL, 0.02, exit_move_pct=c.target_pct).total_pct
    assert c.cost_rt_pct == pytest.approx(esperado)


# --------------------------------------------------------------------------
# Trazabilidad
# --------------------------------------------------------------------------


def test_el_decision_id_es_estable():
    """Si el proceso se reinicia y vuelve a mirar la misma vela, la misma idea
    tiene que llamarse igual y no duplicarse con otro nombre."""
    a = make_decision_id("ETH/USDC", "pullback_trend", mf.START_MS)
    b = make_decision_id("ETH/USDC", "pullback_trend", mf.START_MS)
    assert a == b
    assert a.startswith("d-")
    assert "eth" in a


def test_el_decision_id_distingue_setup_simbolo_y_vela():
    base = make_decision_id("ETH/USDC", "pullback_trend", mf.START_MS)
    assert base != make_decision_id("BTC/USDC", "pullback_trend", mf.START_MS)
    assert base != make_decision_id("ETH/USDC", "range_breakout", mf.START_MS)
    assert base != make_decision_id("ETH/USDC", "pullback_trend", mf.START_MS + mf.BAR_MS)


def test_el_candidato_se_convierte_en_peticion_para_el_motor(
    settings, limits, cost
):
    c = run(mf.trending_up(pullback=True), settings, limits, cost).candidates[0]
    request = c.to_entry_request(INSTRUMENTS[SYMBOL])
    assert request.decision_id == c.decision_id
    assert request.symbol == c.symbol
    assert request.entry_price == c.entry
    assert request.stop_price == c.stop
    assert request.spread_pct == c.spread_pct


def test_el_motor_de_riesgo_aprueba_un_candidato_sano(settings, limits, cost):
    """La prueba que enlaza las dos mitades de la fase 2: lo que el generador
    produce tiene que poder pasar por el motor de riesgo."""
    from risk.engine import evaluate_with_limits
    from tests.risk_fixtures import make_state

    c = run(mf.trending_up(pullback=True), settings, limits, cost).candidates[0]
    verdict = evaluate_with_limits(
        c.to_entry_request(INSTRUMENTS[SYMBOL]), make_state(), settings, 3
    )
    assert verdict.approved, verdict.reason()
    assert verdict.qty > 0
    assert verdict.risk_usd <= limits.risk_per_trade_usd + 1e-9


def test_el_bloque_para_el_prompt_lleva_lo_que_pide_el_informe(
    settings, limits, cost
):
    """Informe seccion 1.5: el JSON que ve la IA."""
    c = run(mf.trending_up(pullback=True), settings, limits, cost).candidates[0]
    d = c.to_prompt_dict()
    assert set(d) == {
        "cid", "symbol", "setup", "tf", "entry", "stop", "target", "rr",
        "cost_rt_pct", "regime", "reasons", "features",
    }
    assert d["cid"] == c.cid
    assert isinstance(d["reasons"], list) and d["reasons"]


# --------------------------------------------------------------------------
# Varias monedas a la vez
# --------------------------------------------------------------------------


def test_generate_all_recorre_todas_y_ordena_por_R_R(settings, limits, cost):
    market = {
        "ETH/USDC": mf.trending_up(pullback=True),
        "SOL/USDC": mf.range_then_breakout(),
        "BTC/USDC": mf.trending_down(),
    }
    result = generate_all(
        market, {s: 0.02 for s in market}, "4h", cost, limits, settings, now=NOW
    )
    simbolos = {c.symbol for c in result.candidates}
    assert "BTC/USDC" not in simbolos
    mejor = result.best()
    assert isinstance(mejor, Candidate)
    assert mejor.reward_risk == max(c.reward_risk for c in result.candidates)


def test_sin_candidatos_best_devuelve_nada(settings, limits, cost):
    result = generate_all(
        {"BTC/USDC": mf.trending_down()}, {"BTC/USDC": 0.02}, "4h",
        cost, limits, settings, now=NOW,
    )
    assert result.best() is None
