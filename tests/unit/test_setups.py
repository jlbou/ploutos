"""Los tres setups.

Cada serie sintetica contiene UN setup y solo uno, asi que se puede comprobar
lo que de verdad importa en un generador de senyales: que cada setup se dispare
en lo suyo **y se quede callado en lo de los demas**. Un setup que se dispara
en todo no es una ventaja, es ruido con nombre.
"""

from __future__ import annotations

import pytest

from features.indicators import atr, atr_pct
from features.regime import Regime, classify
from strategy.setups import SetupContext, all_setups, regimes_for, setup_names
from strategy.setups.base import build_signal
from strategy.setups.mean_reversion import MIN_STOP_ATR
from strategy.setups.mean_reversion import detect as detect_mean_reversion
from strategy.setups.pullback_trend import detect as detect_pullback
from strategy.setups.range_breakout import MAX_EXTENSION_ATR
from strategy.setups.range_breakout import detect as detect_breakout
from tests import market_fixtures as mf

ATR_MULTIPLE_4H = 1.9


def context(candles, timeframe: str = "4h", multiple: float = ATR_MULTIPLE_4H):
    reading = classify(candles)
    return SetupContext(
        symbol="TEST/USDC",
        timeframe=timeframe,
        candles=candles,
        regime=reading,
        atr=float(atr(candles["high"], candles["low"], candles["close"]).iloc[-1]),
        atr_pct=float(
            atr_pct(candles["high"], candles["low"], candles["close"]).iloc[-1]
        ),
        atr_multiple=multiple,
    )


def fire(detect, candles):
    """Ejecuta un setup saltandose la puerta del regimen, para poder probar
    las condiciones del setup por separado de su gate."""
    return detect(context(candles))


# --------------------------------------------------------------------------
# El registro
# --------------------------------------------------------------------------


def test_estan_los_tres_setups_del_informe():
    assert setup_names() == ["mean_reversion", "pullback_trend", "range_breakout"]


def test_cada_setup_declara_su_regimen():
    """Informe seccion 2.3[5]: no rupturas en rango, no reversiones en tendencia."""
    assert regimes_for("pullback_trend") == frozenset({Regime.TREND_UP})
    assert regimes_for("mean_reversion") == frozenset({Regime.RANGE})
    assert regimes_for("range_breakout") == frozenset(
        {Regime.TRANSITION, Regime.TREND_UP}
    )


def test_ninguna_ruptura_en_rango():
    """La regla del informe, comprobada sobre el registro y no sobre un fixture.

    El umbral exacto a partir del cual una ruptura deja de leerse como rango es
    fragil y depende de la serie; la REGLA no lo es.
    """
    assert Regime.RANGE not in regimes_for("range_breakout")


def test_ninguna_reversion_en_tendencia():
    for regime in (Regime.TREND_UP, Regime.TREND_DOWN):
        assert regime not in regimes_for("mean_reversion")


def test_nadie_opera_en_alta_volatilidad_ni_en_tendencia_bajista():
    """Son largos de contado (regla 1): en tendencia bajista no se compra.
    Y en volatilidad excepcional el stop no cabe en el tamanyo."""
    for _name, regimes, _fn in all_setups():
        assert Regime.HIGH_VOL not in regimes
        assert Regime.TREND_DOWN not in regimes
        assert Regime.UNKNOWN not in regimes


# --------------------------------------------------------------------------
# Cada setup en lo suyo
# --------------------------------------------------------------------------


def test_pullback_se_dispara_en_un_retroceso():
    signal = fire(detect_pullback, mf.trending_up(pullback=True))
    assert signal is not None
    assert signal.setup == "pullback_trend"
    assert signal.stop < signal.entry < signal.target
    assert signal.reward_risk >= 2.0


def test_pullback_no_se_dispara_sin_retroceso():
    """En plena subida, sin descanso, no hay nada que comprar mas barato."""
    assert fire(detect_pullback, mf.trending_up()) is None


def test_reversion_se_dispara_en_un_rango_sobrevendido():
    signal = fire(detect_mean_reversion, mf.ranging(oversold=True))
    assert signal is not None
    assert signal.setup == "mean_reversion"
    assert signal.stop < signal.entry < signal.target


def test_reversion_no_se_dispara_en_el_medio_del_rango():
    assert fire(detect_mean_reversion, mf.ranging()) is None


def test_ruptura_se_dispara_con_volumen():
    signal = fire(detect_breakout, mf.range_then_breakout())
    assert signal is not None
    assert signal.setup == "range_breakout"
    assert signal.reward_risk >= 2.0


def test_ruptura_sin_volumen_es_una_trampa():
    """Informe seccion 1.3[3]: el volumen esta para confirmar. Sin el, no."""
    assert fire(detect_breakout, mf.range_then_breakout(volume_spike=False)) is None


def test_ruptura_que_no_rompe():
    assert fire(detect_breakout, mf.range_then_breakout(breakout=False)) is None


# --------------------------------------------------------------------------
# Lo que costo un intento
# --------------------------------------------------------------------------


def test_el_objetivo_del_pullback_es_una_maxima_NUEVA():
    """REGRESION, y esta era un error de concepto, no de codigo.

    La primera version ponia el objetivo en la maxima previa del swing. Como
    la entrada esta por debajo de esa maxima justo por el retroceso, la
    distancia al objetivo ERA la profundidad del retroceso, y el R:R salia
    `profundidad / (1,9 x ATR)`. Para llegar a 2:1 habrian hecho falta
    retrocesos de 3,8 ATR, que en una tendencia no son retrocesos sino
    rupturas: el setup no podia producir un candidato valido jamas.

    Es un setup de CONTINUACION: si la tendencia sigue, el precio hace una
    maxima nueva. El objetivo proyecta el impulso.
    """
    signal = fire(detect_pullback, mf.trending_up(pullback=True))
    assert signal is not None
    assert signal.target > signal.features["swing_high"], (
        "el objetivo tiene que estar POR ENCIMA de la maxima previa"
    )
    assert signal.reward_risk > 2.0


def test_la_ruptura_no_se_persigue():
    """REGRESION. Cada punto que el precio ya ha corrido por encima del techo
    se le resta al objetivo y no al stop, asi que el R:R se hunde: medido,
    entrar un 3,5 % por encima bajaba el R:R de 2,4 a 1,6."""
    signal = fire(detect_breakout, mf.range_then_breakout())
    assert signal is not None
    assert signal.features["extension_atr"] <= MAX_EXTENSION_ATR


def test_la_altura_del_rango_manda_en_el_R_R_de_la_ruptura():
    """El objetivo es el movimiento medido, asi que
    `R:R ~= altura_del_rango / (multiplo_atr x ATR)`. Si alguien baja el techo
    de la altura por debajo de `2 x multiplo`, el setup deja de poder producir
    candidatos validos sin que nada avise."""
    from strategy.setups.range_breakout import MAX_RANGE_HEIGHT_ATR

    assert MAX_RANGE_HEIGHT_ATR > 2 * ATR_MULTIPLE_4H, (
        f"con un techo de {MAX_RANGE_HEIGHT_ATR} ATR y un multiplo de "
        f"{ATR_MULTIPLE_4H}, ningun rango podria dar R:R 2:1"
    )


# --------------------------------------------------------------------------
# El contrato comun
# --------------------------------------------------------------------------


def test_el_stop_por_defecto_es_el_uniforme():
    """`multiplo_atr x ATR`. Si cada setup pusiera el stop donde quisiera, el
    tamanyo de posicion dejaria de ser predecible."""
    casos = [
        (detect_pullback, mf.trending_up(pullback=True)),
        (detect_breakout, mf.range_then_breakout()),
    ]
    for detect, candles in casos:
        ctx = context(candles)
        signal = detect(ctx)
        assert signal is not None
        assert signal.entry - signal.stop == pytest.approx(ctx.stop_distance)


def test_la_reversion_tiene_stop_propio_y_por_que():
    """LA EXCEPCION, decidida por el propietario el 22/09/2026 despues de medirla.

    Una reversion a la media se invalida cuando el precio SALE DEL RANGO, no
    cuando recorre una distancia fija en ATR. Con el stop uniforme (1,9xATR
    contra una banda central que esta a ~0,74 ATR) el setup no producia ni un
    candidato en 285 velas reales en rango.

    Que esto no rompa el dimensionado: `risk/sizing.py` saca el nocional del
    stop REAL, asi que un stop mas estrecho da una posicion mayor, topada en
    `max_notional_usd`, y el riesgo permitido no se mueve. Hay un test de eso
    en `test_candidates.py`.
    """
    ctx = context(mf.ranging(oversold=True))
    signal = detect_mean_reversion(ctx)
    assert signal is not None
    assert signal.entry - signal.stop < ctx.stop_distance, (
        "el stop estructural tiene que ser mas estrecho que el uniforme"
    )
    assert signal.features["stop_atr"] >= MIN_STOP_ATR - 1e-9
    assert signal.reward_risk >= 2.0


def test_la_reversion_nunca_pone_el_stop_dentro_del_ruido():
    """Por debajo de medio ATR el stop esta dentro de una sola vela y salta por
    nada. El suelo existe para la cola, no para afinar."""
    ctx = context(mf.ranging(oversold=True))
    signal = detect_mean_reversion(ctx)
    assert signal is not None
    assert (signal.entry - signal.stop) >= MIN_STOP_ATR * ctx.atr - 1e-9


def test_un_objetivo_por_debajo_de_la_entrada_no_es_senyal():
    ctx = context(mf.trending_up())
    assert build_signal(ctx, "x", ctx.close * 0.99, (), {}) is None
    assert build_signal(ctx, "x", ctx.close, (), {}) is None
    assert build_signal(ctx, "x", ctx.close * 1.05, (), {}) is not None


def test_toda_senyal_trae_razones_y_features():
    """El panel del PRD seccion 10 y el prompt de la IA los necesitan."""
    casos = [
        (detect_pullback, mf.trending_up(pullback=True)),
        (detect_mean_reversion, mf.ranging(oversold=True)),
        (detect_breakout, mf.range_then_breakout()),
    ]
    for detect, candles in casos:
        signal = detect(context(candles))
        assert signal is not None
        assert len(signal.reasons) >= 3
        assert "atr_pct" in signal.features


def test_sin_historia_ningun_setup_se_inventa_nada():
    corta = mf.trending_up(n=40)
    for _name, _regimes, detect in all_setups():
        assert detect(context(corta)) is None
