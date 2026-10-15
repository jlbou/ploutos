"""Una prueba por cada regla dura, con su caso limite (PRD seccion 4).

Cada test rompe UNA cosa sobre un estado sano y comprueba que el motor veta por
la regla correcta. Si alguno de estos se pone verde despues de relajar una
regla, el test no protege nada.
"""

from __future__ import annotations


import pytest

from core.modes import Mode
from risk.engine import evaluate_with_limits
from risk.types import Instrument
from tests.risk_fixtures import (
    MAKER,
    TAKER,
    make_pending,
    make_position,
    make_request,
    make_state,
    make_trade,
)


def verdict(settings, request=None, state=None, slider=3):
    return evaluate_with_limits(
        request or make_request(), state or make_state(), settings, slider
    )


def vetoed_by(v, number: int) -> bool:
    return not v.approved and number in v.veto_numbers


# --------------------------------------------------------------------------
# El caso sano
# --------------------------------------------------------------------------


def test_un_candidato_sano_se_aprueba(settings):
    v = verdict(settings)
    assert v.approved, v.reason()
    assert v.qty > 0
    assert v.notional_usd > 0


def test_se_evaluan_las_19_reglas_siempre(settings):
    """Sin cortocircuito: el panel necesita ver todas las causas."""
    v = verdict(settings)
    numeros = {r.number for r in v.results}
    assert numeros == set(range(0, 20))  # 0 es el modo, 1..19 las reglas


def test_un_veredicto_vetado_no_lleva_cantidad(settings):
    """Si no se aprueba, no hay tamanyo. Imposible ejecutar un veto por error."""
    v = verdict(settings, state=make_state(mode=Mode.HALTED))
    assert not v.approved
    assert v.qty == 0
    assert v.notional_usd == 0


# --------------------------------------------------------------------------
# Modo (PRD seccion 5): solo NORMAL abre
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [
        Mode.CLOSE_ONLY_QUOTA,
        Mode.CLOSE_ONLY_DEGRADED,
        Mode.CLOSE_ONLY_DAILY,
        Mode.CLOSE_ONLY_CAPITAL,
        Mode.HALTED,
    ],
)
def test_ningun_modo_salvo_normal_abre(settings, mode):
    v = verdict(settings, state=make_state(mode=mode))
    assert not v.approved
    assert 0 in v.veto_numbers


# --------------------------------------------------------------------------
# Regla 1: sin apalancamiento
# --------------------------------------------------------------------------


def test_regla1_saldo_negativo_es_deuda(settings):
    v = verdict(settings, state=make_state(free_quote=-5.0))
    assert vetoed_by(v, 1)


# --------------------------------------------------------------------------
# Regla 3: whitelist
# --------------------------------------------------------------------------


def _request_for(symbol: str, price: float, tick: float, lot: float, min_amt: float):
    """Construye una peticion para un simbolo cualquiera, este o no en la lista."""
    from risk.types import EntryRequest

    return EntryRequest(
        symbol=symbol,
        entry_price=price,
        stop_price=price * 0.9667,
        target_price=price * 1.0666,
        setup="pullback_trend",
        instrument=Instrument(symbol, tick, lot, min_amt, MAKER, TAKER),
        decision_id="d-test-3",
        spread_pct=0.01,
    )


def test_regla3_moneda_no_listada(settings):
    """ADA se descarto por spread: no puede entrar por la puerta de atras."""
    req = _request_for("ADA/USDC", 0.80, 0.0001, 0.001, 10.0)
    assert vetoed_by(verdict(settings, request=req), 3)


def test_regla3_par_que_no_es_usdc(settings):
    """USDT esta deslistado en el EEE y prohibido por la regla 3."""
    req = _request_for("BTC/USDT", 86000.0, 0.1, 1e-8, 0.0001)
    assert vetoed_by(verdict(settings, request=req), 3)


def test_regla3_par_contra_btc(settings):
    """El informe admitia X/BTC; el PRD no."""
    req = _request_for("ETH/BTC", 0.0319, 1e-6, 1e-6, 0.001)
    assert vetoed_by(verdict(settings, request=req), 3)


def test_regla3_instrumento_que_no_coincide_con_el_simbolo(settings):
    """Defensa contra un cruce de datos: pedir ETH con los filtros de ADA."""
    req = make_request(
        "ETH/USDC", instrument=Instrument("ADA/USDC", 0.0001, 0.001, 10.0, MAKER, TAKER)
    )
    assert vetoed_by(verdict(settings, request=req), 3)


# --------------------------------------------------------------------------
# Regla 4: maximo 3 posiciones, pendientes incluidas
# --------------------------------------------------------------------------


def test_regla4_tres_abiertas_bloquean(settings):
    state = make_state(
        positions=(
            make_position("BTC/USDC"),
            make_position("SOL/USDC"),
            make_position("XRP/USDC"),
        )
    )
    assert vetoed_by(verdict(settings, state=state), 4)


def test_regla4_las_pendientes_cuentan(settings):
    """El caso del informe 4.3: dos abiertas y una pendiente son TRES huecos."""
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("XRP/USDC")),
        pending=(make_pending("SOL/USDC"),),
    )
    v = verdict(settings, state=state)
    assert vetoed_by(v, 4)


def test_regla4_dos_huecos_ocupados_dejan_abrir(settings):
    state = make_state(
        positions=(make_position("BTC/USDC"),),
        pending=(make_pending("SOL/USDC"),),
    )
    assert verdict(settings, state=state).approved


def test_regla4_prohibido_promediar_en_el_mismo_simbolo(settings):
    state = make_state(positions=(make_position("ETH/USDC"),))
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert vetoed_by(v, 4)


def test_regla4_ni_siquiera_con_una_pendiente_en_el_mismo_simbolo(settings):
    state = make_state(pending=(make_pending("ETH/USDC"),))
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert vetoed_by(v, 4)


# --------------------------------------------------------------------------
# Regla 6: equity valido
# --------------------------------------------------------------------------


def test_regla6_equity_nan(settings):
    assert vetoed_by(verdict(settings, state=make_state(equity=float("nan"))), 6)


def test_regla6_posicion_sin_precio_de_mercado(settings):
    """Sin marca no se puede valorar la posicion, y el equity no es fiable."""
    state = make_state(positions=(make_position("BTC/USDC"),), marks={})
    assert vetoed_by(verdict(settings, state=state), 6)


# --------------------------------------------------------------------------
# Regla 7: suelo de 25 $
# --------------------------------------------------------------------------


def test_regla7_equity_exactamente_en_el_suelo(settings):
    """25,00 $ exactos ya dispara: la regla dice "<=", no "<"."""
    assert vetoed_by(verdict(settings, state=make_state(equity=25.0)), 7)


def test_regla7_equity_justo_por_encima_del_suelo(settings):
    v = verdict(settings, state=make_state(equity=25.01))
    assert 7 not in v.veto_numbers


def test_regla7_modo_capital_enclavado(settings):
    """Aunque el equity haya rebotado a 40 $, si el modo sigue activo no se abre."""
    state = make_state(equity=40.0, mode=Mode.CLOSE_ONLY_CAPITAL)
    assert vetoed_by(verdict(settings, state=state), 7)


# --------------------------------------------------------------------------
# Regla 8: preventiva
# --------------------------------------------------------------------------


def test_regla8_no_se_abre_si_el_peor_caso_rompe_el_suelo(settings):
    """Con 27 $ y dos posiciones arriesgando, una tercera romperia el colchon."""
    state = make_state(
        equity=27.0,
        positions=(
            make_position("BTC/USDC", notional=15.0, stop_pct=10.0),
            make_position("SOL/USDC", notional=15.0, stop_pct=10.0),
        ),
    )
    v = verdict(settings, state=state)
    assert not v.approved
    assert 8 in v.veto_numbers


def test_regla8_con_equity_holgado_pasa(settings):
    v = verdict(settings, state=make_state(equity=50.0))
    assert 8 not in v.veto_numbers


def test_regla8_cuenta_tambien_las_pendientes(settings):
    """Una entrada pendiente tambien puede saltar a su stop."""
    sin_pendiente = make_state(equity=27.5)
    con_pendiente = make_state(
        equity=27.5, pending=(make_pending("SOL/USDC", notional=15.0, stop_pct=15.0),)
    )
    v1 = verdict(settings, state=sin_pendiente)
    v2 = verdict(settings, state=con_pendiente)
    assert 8 not in v1.veto_numbers
    assert 8 in v2.veto_numbers


def _peor_caso_sin_comisiones(settings, state):
    from risk.engine import build_limits
    lim = build_limits(settings, state)
    return state.equity_usd - state.total_risk_to_stops_usd() - lim.risk_per_trade_usd, lim


def test_regla8_cuenta_la_comision_de_salida_de_los_stops(settings):
    """Revision del 15/10/2026: si todo salta a su stop, cada venta paga la comision taker. Se busca un equity en el
    que SIN comision el peor caso queda por encima del suelo + colchon y CON ella por debajo: ahi tiene que vetar."""
    taker = settings.exchange.fees.taker_pct / 100
    hallado = None
    for centimos in range(2600, 3000):
        equity = centimos / 100
        state = make_state(equity=equity, positions=(make_position("BTC/USDC", notional=15.0, stop_pct=10.0),))
        sin, lim = _peor_caso_sin_comisiones(settings, state)
        comision = taker * (sum(p.qty * p.stop_price for p in state.positions) + lim.max_notional_usd)
        if sin >= lim.min_equity_after_stops_usd > sin - comision:
            hallado = state
            break
    assert hallado is not None, "no hay ningun equity entre 26 y 30 $ en la franja de la comision"
    assert 8 in verdict(settings, state=hallado).veto_numbers


def test_regla8_con_margen_para_la_comision_pasa(settings):
    state = make_state(equity=40.0, positions=(make_position("BTC/USDC", notional=15.0, stop_pct=10.0),))
    assert 8 not in verdict(settings, state=state).veto_numbers


# --------------------------------------------------------------------------
# Regla 9: escalones de drawdown
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "equity,max_positions",
    [(50.0, 3), (44.0, 3), (39.0, 2), (34.0, 1)],
)
def test_regla9_los_escalones_aprietan_las_posiciones(settings, equity, max_positions):
    from risk.limits import Limits

    lim = Limits.for_state(settings, equity)
    assert lim.max_positions == max_positions


def test_regla9_por_debajo_de_45_el_riesgo_se_parte_por_la_mitad(settings):
    from risk.limits import Limits

    normal = Limits.for_state(settings, 50.0)
    reducido = Limits.for_state(settings, 44.0)
    assert reducido.risk_per_trade_pct == pytest.approx(normal.risk_per_trade_pct / 2)


def test_regla9_con_39_dolares_la_tercera_posicion_se_bloquea(settings):
    state = make_state(
        equity=39.0,
        positions=(make_position("BTC/USDC"), make_position("SOL/USDC")),
    )
    assert vetoed_by(verdict(settings, state=state), 4)


# --------------------------------------------------------------------------
# Regla 10: limite diario
# --------------------------------------------------------------------------


def test_regla10_perdida_exacta_de_3_dolares_dispara(settings):
    state = make_state(closed_today=(make_trade(pnl=-3.0),))
    assert vetoed_by(verdict(settings, state=state), 10)


def test_regla10_perdida_de_2_99_todavia_no(settings):
    state = make_state(closed_today=(make_trade(pnl=-2.99),))
    assert 10 not in verdict(settings, state=state).veto_numbers


def test_regla10_modo_diario_bloquea(settings):
    state = make_state(mode=Mode.CLOSE_ONLY_DAILY)
    assert vetoed_by(verdict(settings, state=state), 10)


def test_regla10_las_ganancias_no_bloquean(settings):
    state = make_state(closed_today=tuple(make_trade(pnl=1.0, hit_stop=False) for _ in range(2)))
    assert 10 not in verdict(settings, state=state).veto_numbers


# --------------------------------------------------------------------------
# Regla 11: 6 operaciones al dia
# --------------------------------------------------------------------------


def test_regla11_la_septima_operacion_se_bloquea(settings):
    state = make_state(
        closed_today=tuple(
            make_trade(pnl=0.1, hit_stop=False, decision_id=f"d{i}") for i in range(6)
        )
    )
    assert vetoed_by(verdict(settings, state=state), 11)


def test_regla11_la_sexta_todavia_pasa(settings):
    state = make_state(
        closed_today=tuple(
            make_trade(pnl=0.1, hit_stop=False, decision_id=f"d{i}") for i in range(5)
        )
    )
    assert 11 not in verdict(settings, state=state).veto_numbers


def test_regla11_las_posiciones_vivas_cuentan_como_operaciones_de_hoy(settings):
    state = make_state(
        closed_today=tuple(
            make_trade(pnl=0.1, hit_stop=False, decision_id=f"d{i}") for i in range(4)
        ),
        positions=(make_position("BTC/USDC"),),
        pending=(make_pending("SOL/USDC"),),
    )
    assert vetoed_by(verdict(settings, state=state), 11)


# --------------------------------------------------------------------------
# Regla 12: riesgo por operacion
# --------------------------------------------------------------------------


def test_regla12_la_ia_no_puede_aumentar_el_tamanyo(settings):
    """El multiplicador vive en [0,5; 1,0]: la IA solo REDUCE (PRD seccion 6)."""
    v = verdict(settings, request=make_request(size_multiplier=1.5))
    assert vetoed_by(v, 12)


def test_regla12_multiplicador_por_debajo_de_0_5(settings):
    v = verdict(settings, request=make_request(size_multiplier=0.3))
    assert vetoed_by(v, 12)


@pytest.mark.parametrize("mult", [0.5, 0.75, 1.0])
def test_regla12_multiplicadores_validos(settings, mult):
    v = verdict(settings, request=make_request(size_multiplier=mult))
    assert 12 not in v.veto_numbers


def test_regla12_reducir_el_tamanyo_reduce_el_riesgo(settings):
    completo = verdict(settings, request=make_request(size_multiplier=1.0))
    mitad = verdict(settings, request=make_request(size_multiplier=0.5))
    assert mitad.risk_usd < completo.risk_usd


def test_regla12_stop_por_encima_de_la_entrada(settings):
    req = make_request(stop_pct=-1.0)  # stop POR ENCIMA
    v = verdict(settings, request=req)
    assert not v.approved


# --------------------------------------------------------------------------
# Regla 13: stop y objetivo
# --------------------------------------------------------------------------


def test_regla13_sin_objetivo_por_encima_de_la_entrada(settings):
    req = make_request(target_pct=-1.0)
    assert vetoed_by(verdict(settings, request=req), 13)


def test_regla13_objetivo_igual_a_la_entrada(settings):
    req = make_request(target_pct=0.0)
    assert vetoed_by(verdict(settings, request=req), 13)


# --------------------------------------------------------------------------
# Regla 14: cooldown y pausa
# --------------------------------------------------------------------------


def test_regla14_cooldown_tras_un_stop_en_el_mismo_simbolo(settings):
    state = make_state(
        recent_closed=(make_trade("ETH/USDC", hit_stop=True, minutes_ago=30),)
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert vetoed_by(v, 14)


def test_regla14_pasadas_dos_horas_ya_se_puede(settings):
    state = make_state(
        recent_closed=(make_trade("ETH/USDC", hit_stop=True, minutes_ago=121),)
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 14 not in v.veto_numbers


def test_regla14_el_cooldown_es_por_simbolo(settings):
    """Un stop en BTC no bloquea ETH."""
    state = make_state(
        recent_closed=(make_trade("BTC/USDC", hit_stop=True, minutes_ago=30),)
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 14 not in v.veto_numbers


def test_regla14_un_cierre_que_no_es_stop_no_da_cooldown(settings):
    state = make_state(
        recent_closed=(
            make_trade("ETH/USDC", pnl=0.8, hit_stop=False, minutes_ago=10),
        )
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 14 not in v.veto_numbers


def test_regla14_tres_perdidas_seguidas_pausan_todo(settings):
    state = make_state(
        recent_closed=tuple(
            make_trade(f"{s}/USDC", pnl=-0.5, hit_stop=False, minutes_ago=m,
                       decision_id=f"d{m}")
            for s, m in (("BTC", 30), ("SOL", 60), ("XRP", 90))
        )
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert vetoed_by(v, 14)


def test_regla14_una_ganancia_rompe_la_racha(settings):
    state = make_state(
        recent_closed=(
            make_trade("BTC/USDC", pnl=1.0, hit_stop=False, minutes_ago=10, decision_id="d1"),
            make_trade("SOL/USDC", pnl=-0.5, hit_stop=False, minutes_ago=60, decision_id="d2"),
            make_trade("XRP/USDC", pnl=-0.5, hit_stop=False, minutes_ago=90, decision_id="d3"),
            make_trade("DOGE/USDC", pnl=-0.5, hit_stop=False, minutes_ago=120, decision_id="d4"),
        )
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 14 not in v.veto_numbers


def test_regla14_pasadas_cuatro_horas_la_pausa_se_levanta(settings):
    state = make_state(
        recent_closed=tuple(
            make_trade(f"{s}/USDC", pnl=-0.5, hit_stop=False, minutes_ago=m,
                       decision_id=f"d{m}")
            for s, m in (("BTC", 241), ("SOL", 300), ("XRP", 360))
        )
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 14 not in v.veto_numbers


# --------------------------------------------------------------------------
# Regla 15: exposicion y correlacion
# --------------------------------------------------------------------------


def test_regla15_dos_correlacionadas_bloquean_la_tercera(settings):
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("SOL/USDC")),
        correlations={
            ("BTC/USDC", "ETH/USDC"): 0.92,
            ("ETH/USDC", "SOL/USDC"): 0.88,
        },
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert vetoed_by(v, 15)


def test_regla15_una_sola_correlacionada_deja_pasar(settings):
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("TRX/USDC")),
        correlations={
            ("BTC/USDC", "ETH/USDC"): 0.92,
            ("ETH/USDC", "TRX/USDC"): 0.30,
        },
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 15 not in v.veto_numbers


# DECISION DEL PROPIETARIO (22/09/2026, opcion 2): una pareja SIN correlacion medida
# cuenta como correlacionada. Antes contaba como 0,0, o sea independiente, que
# es justo lo que `features/context.py` intentaba evitar al no registrarla.


def test_regla15_sin_correlaciones_medidas_dos_bastan_para_bloquear(settings):
    """Sin 7 dias de historia no se sabe nada: como mucho 2 a la vez."""
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("TRX/USDC")),
        correlations={},
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert vetoed_by(v, 15)
    assert "sin medir" in v.reason()


def test_regla15_una_desconocida_y_una_baja_dejan_pasar(settings):
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("TRX/USDC")),
        correlations={("ETH/USDC", "TRX/USDC"): 0.30},
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 15 not in v.veto_numbers


def test_regla15_una_desconocida_y_una_alta_bloquean(settings):
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("TRX/USDC")),
        correlations={("BTC/USDC", "ETH/USDC"): 0.92},
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert vetoed_by(v, 15)


def test_regla15_justo_en_el_umbral_no_cuenta(settings):
    """La regla dice "> 0,8", asi que 0,80 exacto no correlaciona."""
    state = make_state(
        positions=(make_position("BTC/USDC"), make_position("SOL/USDC")),
        correlations={
            ("BTC/USDC", "ETH/USDC"): 0.80,
            ("ETH/USDC", "SOL/USDC"): 0.80,
        },
    )
    v = verdict(settings, request=make_request("ETH/USDC"), state=state)
    assert 15 not in v.veto_numbers


def test_regla15_sin_margen_de_exposicion_no_se_abre(settings):
    """Con el tope ya agotado no cabe ninguna orden, por pequenya que sea."""
    state = make_state(
        positions=(
            make_position("BTC/USDC", notional=20.0),
            make_position("SOL/USDC", notional=20.0),
        ),
    )
    # 40 $ expuestos de un tope de 45 $: quedan 5 $, y la orden mas pequenya
    # posible en BTC son 8,60 $ (0,0001 BTC).
    v = verdict(settings, request=make_request("BTC/USDC"), state=state)
    assert 15 in v.veto_numbers
    assert "margen de exposicion" in v.reason()


def test_regla15_la_exposicion_real_nunca_pasa_del_90_por_ciento(settings):
    """REGRESION, y esta encontro una brecha de verdad.

    La version antigua proyectaba `exposicion + nocional OBJETIVO` (15 $) para
    decidir, pero el tamanyo que luego calculaba `risk/sizing.py` podia llegar
    a 20 $ (el tope por orden). Con 30 $ ya expuestos, la regla veia 45 $ y
    aprobaba; la exposicion real acababa en 50 $, o sea el 100 % del equity,
    con un tope del 90 %.

    Ahora el tamanyo se recorta contra el MARGEN que queda, y el motor lo
    vuelve a comprobar con el numero real despues de dimensionar.
    """
    state = make_state(
        positions=(
            make_position("BTC/USDC", notional=20.0),
            make_position("ETH/USDC", notional=10.0),
        ),
    )
    assert state.exposure_usd == pytest.approx(30.0)

    # Stop muy estrecho: sin recorte, esto pediria 50 $ y se quedaria en 20 $.
    v = verdict(
        settings,
        request=make_request("SOL/USDC", stop_pct=1.0, target_pct=3.0),
        state=state,
    )
    assert v.approved, v.reason()
    # 15 $ clavados no, porque la cantidad se redondea SIEMPRE hacia abajo
    # al lote del instrumento. Hacia abajo, nunca hacia arriba.
    assert 14.99 < v.notional_usd <= 15.0
    assert state.exposure_usd + v.notional_usd <= 45.0 + 1e-9


def test_regla15_el_motor_veta_si_el_tamanyo_real_se_pasa(settings):
    """La segunda barrera, comprobada por su cuenta.

    `compute_size` ya recorta, asi que esta rama no deberia saltar nunca. Se
    prueba igualmente: una barrera que nadie ha visto funcionar no se sabe si
    funciona.
    """
    from risk.limits import Limits
    from risk.sizing import Sizing

    state = make_state(
        positions=(
            make_position("BTC/USDC", notional=20.0),
            make_position("ETH/USDC", notional=10.0),
        ),
    )
    limits = Limits.for_state(settings, state.equity_usd, 3)
    request = make_request("SOL/USDC", stop_pct=1.0, target_pct=3.0)

    import risk.engine as engine

    original = engine.compute_size
    engine.compute_size = lambda req, lim, **kw: Sizing(
        0.2, 20.0, 0.2, True, "tamanyo sin recortar"
    )
    try:
        v = engine.evaluate(request, state, limits, settings)
    finally:
        engine.compute_size = original

    assert not v.approved
    assert 15 in v.veto_numbers
    assert "tamanyo real" in v.reason()


# --------------------------------------------------------------------------
# Regla 16: spread y coste
# --------------------------------------------------------------------------


def test_regla16_spread_por_encima_del_limite(settings):
    v = verdict(settings, request=make_request(spread_pct=0.11))
    assert vetoed_by(v, 16)


def test_regla16_spread_justo_en_el_limite_pasa(settings):
    v = verdict(settings, request=make_request(spread_pct=0.10))
    assert 16 not in v.veto_numbers


def test_regla16_objetivo_que_no_paga_las_comisiones(settings):
    """Coste maker/taker 0,25 % + medio spread. Un objetivo del 0,3 % no llega."""
    v = verdict(settings, request=make_request(target_pct=0.3))
    assert vetoed_by(v, 16)


def test_regla16_objetivo_tres_veces_el_coste_pasa(settings):
    """Con spread 0,01 % el coste es 0,2561 % y el minimo 3x es 0,7684 %."""
    v = verdict(settings, request=make_request(spread_pct=0.01, target_pct=0.8))
    assert 16 not in v.veto_numbers


def test_regla16_la_salida_es_taker_no_maker(settings):
    """REGRESION. La version antigua suponia maker en las DOS patas y cobraba
    el spread entero, o sea 0,20 % + 0,01 % = 0,21 %, con lo que un objetivo
    del 0,7 % pasaba el filtro de 3x por poco.

    El stop-loss vive en el exchange (regla 13): cuando salta, cruza el libro.
    Esa pata es taker si o si, asi que el coste real es 0,2561 % y ese mismo
    0,7 % NO llega a 3x. Si este test se pone verde, alguien ha vuelto a
    abaratar la salida y la regla 16 esta dejando pasar operaciones que no
    pagan sus comisiones.
    """
    v = verdict(settings, request=make_request(spread_pct=0.01, target_pct=0.7))
    assert vetoed_by(v, 16)


def test_regla16_el_coste_usa_las_comisiones_del_instrumento(settings):
    """Las comisiones salen del `Instrument`, que se llena desde la tabla
    `instruments`. Con un instrumento caro, el mismo objetivo deja de valer."""
    caro = Instrument("ETH/USDC", 0.01, 1e-6, 0.001, 0.004, 0.006)
    barato = make_request(spread_pct=0.01, target_pct=1.5)
    assert 16 not in verdict(settings, request=barato).veto_numbers

    v = verdict(
        settings,
        request=make_request(spread_pct=0.01, target_pct=1.5, instrument=caro),
    )
    assert vetoed_by(v, 16)


# --------------------------------------------------------------------------
# Regla 17: paridad de USDC
# --------------------------------------------------------------------------


def test_regla17_usdc_despegado_bloquea(settings):
    assert vetoed_by(verdict(settings, state=make_state(usdc_deviation_pct=-2.0)), 17)


def test_regla17_despegue_hacia_arriba_tambien(settings):
    assert vetoed_by(verdict(settings, state=make_state(usdc_deviation_pct=2.0)), 17)


def test_regla17_desviacion_pequenya_no_bloquea(settings):
    v = verdict(settings, state=make_state(usdc_deviation_pct=-0.3))
    assert 17 not in v.veto_numbers


def test_regla17_justo_en_el_limite_pasa(settings):
    v = verdict(settings, state=make_state(usdc_deviation_pct=-1.5))
    assert 17 not in v.veto_numbers


# BUG REAL (22/09/2026): nadie calculaba la desviacion y valia 0,0 por defecto,
# o sea "medida y en paridad". La regla 17 no podia saltar nunca. Ahora el
# valor por defecto es None = DESCONOCIDA, y desconocida = no se entra.


def test_regla17_paridad_desconocida_bloquea(settings):
    v = verdict(settings, state=make_state(usdc_deviation_pct=None))
    assert vetoed_by(v, 17)
    assert "desconocida" in v.reason()


def test_regla17_un_estado_sin_desviacion_no_la_da_por_buena():
    """Quien construya un RiskState sin decir la desviacion no obtiene un 0,0."""
    from datetime import UTC, datetime

    from core.modes import Mode
    from risk.state import RiskState

    st = RiskState(
        now=datetime(2026, 9, 22, tzinfo=UTC), equity_usd=50.0, free_quote_usd=50.0,
        mode=Mode.NORMAL,
    )
    assert st.usdc_deviation_pct is None


# --------------------------------------------------------------------------
# Regla 18: cuota de Claude
# --------------------------------------------------------------------------


def test_regla18_sin_cuota_de_claude_no_se_abre(settings):
    assert vetoed_by(verdict(settings, state=make_state(mode=Mode.CLOSE_ONLY_QUOTA)), 18)


# --------------------------------------------------------------------------
# Varias a la vez
# --------------------------------------------------------------------------


def test_se_reportan_todos_los_vetos_no_solo_el_primero(settings):
    """Lo que hace util el panel "veredicto del motor de riesgo"."""
    state = make_state(
        equity=26.0,
        usdc_deviation_pct=-3.0,
        closed_today=(make_trade(pnl=-3.5),),
    )
    v = verdict(settings, request=make_request(spread_pct=0.5), state=state)
    assert not v.approved
    assert len(v.vetoes) >= 3
    assert {10, 16, 17} <= set(v.veto_numbers)


def test_una_regla_que_revienta_veta_en_vez_de_dejar_pasar(settings, monkeypatch):
    """Ante la duda, se veta: es la direccion segura del error."""
    import risk.rules as rules_module

    def explota(req, st, lim, cfg):
        raise RuntimeError("boom")

    original = list(rules_module._REGISTRY)
    monkeypatch.setattr(
        rules_module, "_REGISTRY", [(7, "suelo de capital", explota)] + original[1:]
    )
    v = verdict(settings)
    assert not v.approved
    assert any("boom" in r.detail for r in v.vetoes)


# --------------------------------------------------------------------------
# Regla 9 DENTRO del motor: la segunda barrera
# --------------------------------------------------------------------------
#
# Los tests de arriba comprueban que `Limits.for_state()` aplica bien los
# escalones. Estos comprueban lo otro: que si al motor le llegan unos limites
# que NO los respetan, los rechaza.
#
# Es la defensa en profundidad del informe seccion 4: cada regla dura se
# comprueba en al menos dos sitios. Si solo se comprobara al construir los
# limites, un fallo ahi pasaria al motor sin que nadie lo notase.
#
# Este hueco lo encontro scripts/mutation_check.py: la regla 9 se podia
# desactivar y los 339 tests seguian en verde.


def test_regla9_el_motor_rechaza_limites_que_ignoran_el_escalon_de_posiciones(settings):
    """Con 34 $ el tope es 1 posicion. Unos limites que traigan 3 son invalidos."""
    from dataclasses import replace

    from risk.engine import evaluate
    from risk.limits import Limits

    state = make_state(equity=34.0)
    buenos = Limits.for_state(settings, 34.0)
    assert buenos.max_positions == 1

    malos = replace(buenos, max_positions=3)
    v = evaluate(make_request(), state, malos, settings)
    assert vetoed_by(v, 9), v.reason()


def test_regla9_el_motor_rechaza_limites_que_ignoran_la_reduccion_de_riesgo(settings):
    """Por debajo de 45 $ el riesgo va a la mitad. Unos limites sin reducir son invalidos."""
    from dataclasses import replace

    from risk.engine import evaluate
    from risk.limits import Limits

    state = make_state(equity=44.0)
    buenos = Limits.for_state(settings, 44.0)
    assert buenos.drawdown_multiplier == 0.5

    malos = replace(buenos, drawdown_multiplier=1.0)
    v = evaluate(make_request(), state, malos, settings)
    assert vetoed_by(v, 9), v.reason()


def test_regla9_unos_limites_MAS_conservadores_de_lo_exigido_si_pasan(settings):
    """Apretar de mas siempre se permite; aflojar, nunca."""
    from dataclasses import replace

    from risk.engine import evaluate
    from risk.limits import Limits

    state = make_state(equity=50.0)
    buenos = Limits.for_state(settings, 50.0)
    conservadores = replace(buenos, max_positions=1, drawdown_multiplier=0.5)
    v = evaluate(make_request(), state, conservadores, settings)
    assert 9 not in v.veto_numbers


def test_regla9_los_limites_correctos_pasan_en_cada_escalon(settings):
    from risk.engine import evaluate
    from risk.limits import Limits

    for equity in (50.0, 44.0, 39.0, 34.0, 26.0):
        lim = Limits.for_state(settings, equity)
        v = evaluate(make_request(), make_state(equity=equity), lim, settings)
        assert 9 not in v.veto_numbers, f"con {equity} $: {v.reason()}"
