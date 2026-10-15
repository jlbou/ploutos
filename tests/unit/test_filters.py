"""Filtros deterministas.

Tres bloques:

1. cada filtro rechaza por SU motivo y no por otro;
2. los dos umbrales de ATR salen de las formulas que dicen, comprobados con
   los parametros reales de OKX;
3. **coherencia con el motor de riesgo**: lo que el filtro rechaza por una
   regla, el motor lo veta por esa misma regla. Sin este bloque las dos capas
   se separan con el tiempo y los filtros empiezan a tirar cosas buenas (o,
   peor, a dejar pasar candidatos que gastan cuota de Claude para nada).
"""

from __future__ import annotations

import math

import pytest

from core.modes import Mode
from risk.engine import evaluate_with_limits
from risk.limits import Limits
from strategy.costs import CostModel, Fees
from strategy.filters import (
    MarketSnapshot,
    atr_ceiling_pct,
    atr_floor_pct,
    eligible,
    screen,
    screen_all,
)
from tests.risk_fixtures import (
    INSTRUMENTS,
    MAKER,
    NOW,
    PRICES,
    TAKER,
    make_position,
    make_request,
    make_state,
    make_trade,
)

NOW_MS = int(NOW.timestamp() * 1000)


@pytest.fixture
def cost() -> CostModel:
    return CostModel(
        {s: Fees(s, MAKER, TAKER, NOW_MS) for s in INSTRUMENTS},
        now_ms=NOW_MS,
    )


@pytest.fixture
def limits(settings) -> Limits:
    return Limits.for_state(settings, equity_usd=50.0, slider_level=3)


def snap(
    symbol: str = "BTC/USDC",
    *,
    spread_pct: float = 0.02,
    depth_usd: float = 5_000.0,
    atr_pct: float = 1.5,
    **kwargs,
) -> MarketSnapshot:
    """Una moneda sana: spread estrecho, libro hondo, volatilidad normal."""
    return MarketSnapshot(
        symbol=symbol,
        price=PRICES[symbol],
        spread_pct=spread_pct,
        depth_usd=depth_usd,
        atr_pct=atr_pct,
        **kwargs,
    )


def run(snapshot, state, limits, settings, cost):
    return screen(
        snapshot, state, limits, settings, cost, INSTRUMENTS.get(snapshot.symbol)
    )


def rejected_by(screening, name: str) -> bool:
    return not screening.passed and any(r.name == name for r in screening.rejections)


# --------------------------------------------------------------------------
# El caso sano
# --------------------------------------------------------------------------


def test_una_moneda_sana_pasa_todos_los_filtros(settings, limits, cost):
    s = run(snap(), make_state(), limits, settings, cost)
    assert s.passed, s.reason()


def test_se_evaluan_todos_los_filtros_sin_cortocircuito(settings, limits, cost):
    """Cuatro problemas a la vez tienen que verse los cuatro."""
    state = make_state(mode=Mode.CLOSE_ONLY_DAILY, usdc_deviation_pct=3.0)
    s = run(
        snap(spread_pct=0.5, depth_usd=10.0), state, limits, settings, cost
    )
    nombres = {r.name for r in s.rejections}
    assert {"modo", "spread", "profundidad", "paridad de usdc"} <= nombres


# --------------------------------------------------------------------------
# Un filtro, un motivo
# --------------------------------------------------------------------------


def test_fuera_de_whitelist(settings, limits, cost):
    fuera = MarketSnapshot("ADA/USDC", 0.5, 0.02, 5_000.0, 1.5)
    s = screen(fuera, make_state(), limits, settings, cost)
    assert rejected_by(s, "whitelist")


def test_modo_que_no_abre(settings, limits, cost):
    for mode in (Mode.CLOSE_ONLY_DAILY, Mode.CLOSE_ONLY_CAPITAL, Mode.HALTED):
        s = run(snap(), make_state(mode=mode), limits, settings, cost)
        assert rejected_by(s, "modo"), mode


def test_datos_no_frescos(settings, limits, cost):
    s = run(
        snap(data_fresh=False, stale_reason="libro parado 5 min"),
        make_state(), limits, settings, cost,
    )
    assert rejected_by(s, "frescura")
    assert "libro parado" in s.reason()


def test_atr_en_nan_no_pasa(settings, limits, cost):
    """Sin calentamiento suficiente el ATR es NaN, y un NaN no se compara."""
    s = run(snap(atr_pct=math.nan), make_state(), limits, settings, cost)
    assert rejected_by(s, "frescura")


def test_sin_comisiones_no_hay_candidato(settings, limits):
    vacio = CostModel({}, now_ms=NOW_MS)
    s = run(snap(), make_state(), limits, settings, vacio)
    assert rejected_by(s, "coste conocido")
    assert rejected_by(s, "atr")


def test_spread_por_encima_del_limite(settings, limits, cost):
    s = run(snap(spread_pct=0.11), make_state(), limits, settings, cost)
    assert rejected_by(s, "spread")


def test_spread_justo_en_el_limite_pasa(settings, limits, cost):
    s = run(snap(spread_pct=0.10), make_state(), limits, settings, cost)
    assert not rejected_by(s, "spread")


def test_profundidad_insuficiente(settings, limits, cost):
    """Hacen falta 20 x 15 $ = 300 $ hasta el 0,5 %."""
    s = run(snap(depth_usd=299.0), make_state(), limits, settings, cost)
    assert rejected_by(s, "profundidad")
    s = run(snap(depth_usd=300.0), make_state(), limits, settings, cost)
    assert not rejected_by(s, "profundidad")


def test_evento_activo(settings, limits, cost):
    state = make_state()
    state = type(state)(
        **{
            **{f: getattr(state, f) for f in state.__slots__},
            "event_flags": {"BTC/USDC": ("deslistado",)},
        }
    )
    s = run(snap(), state, limits, settings, cost)
    assert rejected_by(s, "evento")


def test_simbolo_ya_en_cartera(settings, limits, cost):
    state = make_state(positions=(make_position("BTC/USDC"),))
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "hueco libre")


def test_huecos_llenos_contando_pendientes(settings, limits, cost):
    """Regla 4: las entradas pendientes CUENTAN."""
    from tests.risk_fixtures import make_pending

    state = make_state(
        positions=(make_position("ETH/USDC"), make_position("XRP/USDC")),
        pending=(make_pending("SOL/USDC"),),
    )
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "hueco libre")


def test_limite_de_correlacion(settings, limits, cost):
    state = make_state(
        positions=(make_position("ETH/USDC"), make_position("SOL/USDC")),
        correlations={
            ("BTC/USDC", "ETH/USDC"): 0.95,
            ("BTC/USDC", "SOL/USDC"): 0.91,
        },
    )
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "correlacion")


def test_cooldown_tras_un_stop(settings, limits, cost):
    state = make_state(
        recent_closed=(make_trade("BTC/USDC", hit_stop=True, minutes_ago=30),)
    )
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "cooldown")


def test_cooldown_caducado_deja_pasar(settings, limits, cost):
    state = make_state(
        recent_closed=(make_trade("BTC/USDC", hit_stop=True, minutes_ago=121),)
    )
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert not rejected_by(s, "cooldown")


def test_pausa_por_tres_perdidas_seguidas(settings, limits, cost):
    state = make_state(
        recent_closed=tuple(
            make_trade("ETH/USDC", pnl=-0.5, hit_stop=False, minutes_ago=m)
            for m in (10, 20, 30)
        )
    )
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "cooldown")


def test_cupo_diario_de_operaciones(settings, limits, cost):
    state = make_state(
        closed_today=tuple(
            make_trade("ETH/USDC", pnl=0.1, hit_stop=False, minutes_ago=m)
            for m in range(10, 70, 10)
        )
    )
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "cupo diario")


def test_perdida_diaria(settings, limits, cost):
    state = make_state(
        closed_today=(make_trade("ETH/USDC", pnl=-3.0, minutes_ago=20),)
    )
    s = run(snap("BTC/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "cupo diario")


def test_usdc_despegado(settings, limits, cost):
    s = run(snap(), make_state(usdc_deviation_pct=-2.0), limits, settings, cost)
    assert rejected_by(s, "paridad de usdc")


def test_usdc_desconocido_tambien_cribado(settings, limits, cost):
    s = run(snap(), make_state(usdc_deviation_pct=None), limits, settings, cost)
    assert rejected_by(s, "paridad de usdc")


# --------------------------------------------------------------------------
# Los umbrales de ATR, deducidos y no elegidos
# --------------------------------------------------------------------------


def test_suelo_de_atr_sale_del_coste(settings, limits, cost):
    """objetivo_minimo / (multiplo_atr x R:R) = 0,7835 / (1,9 x 2,0)."""
    s = snap()
    esperado = cost.min_target_pct("BTC/USDC", 0.02, ratio=3.0) / (1.9 * 2.0)
    assert atr_floor_pct(s, cost, limits, settings) == pytest.approx(esperado)
    assert esperado == pytest.approx(0.20619, abs=1e-5)


def test_techo_de_atr_sale_del_minimo_por_orden(settings, limits, cost):
    """BTC: minimo 0,0001 x 86.000 $ = 8,60 $. Con 0,50 $ de riesgo el stop no
    puede pasar del 5,81 %, o sea 3,06 % de ATR con el multiplo de 1,9x."""
    s = snap("BTC/USDC")
    techo = atr_ceiling_pct(s, INSTRUMENTS["BTC/USDC"], limits, settings)
    assert techo == pytest.approx(100 * 0.5 / (0.0001 * 86_000) / 1.9)
    assert techo == pytest.approx(3.0600, abs=1e-4)


# ATR% medio medido el 22/09/2026 en velas de 4 h sobre las 8 monedas.
ATR_MEDIDO_4H = 1.779


def test_btc_es_al_que_mas_le_aprieta_el_techo(settings, limits, cost):
    """El minimo por orden de BTC son 8,60 $, nueve veces el de las demas.

    Consecuencia: con posiciones de 15 $, BTC es la unica moneda cuyo techo de
    ATR queda cerca de lo que se ha medido de verdad (3,06 % de techo frente a
    un 1,78 % medio: menos del doble de margen). En el resto el margen es de
    3x para arriba. O sea que en una racha volatil, BTC es la primera que se
    queda fuera, y no por la moneda sino por el tamanyo minimo de orden.
    """
    techos = {
        symbol: atr_ceiling_pct(snap(symbol), INSTRUMENTS[symbol], limits, settings)
        for symbol in PRICES
    }
    assert min(techos, key=techos.get) == "BTC/USDC"
    assert techos["BTC/USDC"] / ATR_MEDIDO_4H < 2.0
    otros = {k: v for k, v in techos.items() if k != "BTC/USDC"}
    assert all(v / ATR_MEDIDO_4H > 3.0 for v in otros.values()), otros


def test_atr_demasiado_bajo(settings, limits, cost):
    s = run(snap(atr_pct=0.15), make_state(), limits, settings, cost)
    assert rejected_by(s, "atr")
    assert "no llegaria a 3.0x el coste" in s.reason()


def test_atr_demasiado_alto(settings, limits, cost):
    s = run(snap(atr_pct=3.5), make_state(), limits, settings, cost)
    assert rejected_by(s, "atr")
    assert "minimo por orden" in s.reason()


def test_el_atr_medido_en_4h_cae_dentro_de_la_banda(settings, limits, cost):
    """1,779 % es el ATR% medio medido el 22/09/2026 en velas de 4 h. Si la
    banda deducida lo dejase fuera, la banda estaria mal, no el mercado."""
    s = run(snap(atr_pct=1.779), make_state(), limits, settings, cost)
    assert not rejected_by(s, "atr"), s.reason()


def test_sin_instrumento_no_hay_techo(settings, limits, cost):
    """Se puede cribar sin conocer el instrumento; solo se pierde el techo."""
    s = screen(snap(), make_state(), limits, settings, cost, None)
    assert s.atr_max_pct == float("inf")
    assert s.passed


def test_un_spread_mas_ancho_sube_el_suelo_de_atr(settings, limits, cost):
    """Mas coste, mas tiene que moverse la moneda para que compense."""
    estrecho = atr_floor_pct(snap(spread_pct=0.01), cost, limits, settings)
    ancho = atr_floor_pct(snap(spread_pct=0.09), cost, limits, settings)
    assert ancho > estrecho


# --------------------------------------------------------------------------
# La pasada completa
# --------------------------------------------------------------------------


def test_screen_all_devuelve_tambien_los_descartados(settings, limits, cost):
    snapshots = [snap("BTC/USDC"), snap("ETH/USDC", spread_pct=0.5)]
    resultados = screen_all(
        snapshots, make_state(), limits, settings, cost, INSTRUMENTS
    )
    assert len(resultados) == 2
    assert eligible(resultados) == ["BTC/USDC"]


# --------------------------------------------------------------------------
# Coherencia con el motor de riesgo
# --------------------------------------------------------------------------


def _engine_vetoes(settings, symbol, state, **request_kwargs):
    v = evaluate_with_limits(
        make_request(symbol, **request_kwargs), state, settings, 3
    )
    return set(v.veto_numbers)


@pytest.mark.parametrize(
    "filtro,regla,estado,peticion",
    [
        ("modo", 0, {"mode": Mode.CLOSE_ONLY_DAILY}, {}),
        ("spread", 16, {}, {"spread_pct": 0.5}),
        ("paridad de usdc", 17, {"usdc_deviation_pct": 3.0}, {}),
    ],
    ids=["modo", "spread", "depeg"],
)
def test_lo_que_el_filtro_rechaza_el_motor_tambien_lo_veta(
    settings, limits, cost, filtro, regla, estado, peticion
):
    """Las dos capas tienen que estar de acuerdo.

    El filtro existe para ahorrar llamadas a Claude, no para decidir. Si
    rechazase algo que el motor aprobaria, estaria tirando operaciones buenas
    por su cuenta; y eso es una decision, no una optimizacion.
    """
    state = make_state(**estado)
    s = run(snap("ETH/USDC", **{k: v for k, v in peticion.items() if k == "spread_pct"}),
            state, limits, settings, cost)
    assert rejected_by(s, filtro)
    assert regla in _engine_vetoes(settings, "ETH/USDC", state, **peticion)


def test_hueco_ocupado_lo_ven_las_dos_capas(settings, limits, cost):
    state = make_state(positions=(make_position("ETH/USDC"),))
    s = run(snap("ETH/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "hueco libre")
    assert 4 in _engine_vetoes(settings, "ETH/USDC", state)


def test_cooldown_lo_ven_las_dos_capas(settings, limits, cost):
    state = make_state(
        recent_closed=(make_trade("ETH/USDC", hit_stop=True, minutes_ago=30),)
    )
    s = run(snap("ETH/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "cooldown")
    assert 14 in _engine_vetoes(settings, "ETH/USDC", state)


def test_cupo_diario_lo_ven_las_dos_capas(settings, limits, cost):
    state = make_state(
        closed_today=(make_trade("SOL/USDC", pnl=-3.0, minutes_ago=20),)
    )
    s = run(snap("ETH/USDC"), state, limits, settings, cost)
    assert rejected_by(s, "cupo diario")
    assert 10 in _engine_vetoes(settings, "ETH/USDC", state)


def test_el_filtro_no_es_mas_laxo_que_el_motor_en_el_caso_sano(
    settings, limits, cost
):
    """Un candidato que pasa los filtros tambien tiene que pasar el motor.

    No es una garantia general (el motor mira cosas que el filtro no puede
    saber, como el tamanyo real), pero en el caso sano de referencia si: si
    esto se rompe, es que una de las dos capas ha cambiado de criterio.
    """
    state = make_state()
    s = run(snap("ETH/USDC"), state, limits, settings, cost)
    assert s.passed, s.reason()
    v = evaluate_with_limits(make_request("ETH/USDC"), state, settings, 3)
    assert v.approved, v.reason()
