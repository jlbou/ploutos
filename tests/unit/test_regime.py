"""Clasificador de regimen.

Cada serie sintetica esta construida para tener un regimen y solo uno, asi que
si un test falla la causa es el clasificador y no una vela ambigua.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from features.indicators import atr_pct
from features.regime import (
    ADX_RANGE,
    ADX_TREND,
    ATR_HIGH_RATIO,
    ATR_PERCENTILE_HIGH,
    MIN_HISTORY,
    Regime,
    classify,
)
from tests import market_fixtures as mf


# --------------------------------------------------------------------------
# Cada serie, su regimen
# --------------------------------------------------------------------------


def test_tendencia_alcista():
    r = classify(mf.trending_up())
    assert r.regime is Regime.TREND_UP
    assert r.adx >= ADX_TREND
    assert r.ema_fast > r.ema_slow


def test_tendencia_bajista():
    r = classify(mf.trending_down())
    assert r.regime is Regime.TREND_DOWN
    assert r.ema_fast < r.ema_slow


def test_rango():
    r = classify(mf.ranging())
    assert r.regime is Regime.RANGE
    assert r.adx < ADX_RANGE


def test_alta_volatilidad():
    r = classify(mf.high_volatility())
    assert r.regime is Regime.HIGH_VOL
    assert r.atr_percentile >= ATR_PERCENTILE_HIGH


def test_la_alta_volatilidad_manda_sobre_la_tendencia():
    """Un estallido de volatilidad deja un ADX altisimo, y aun asi gana el ATR:
    con el stop que saldria de ahi, la posicion no vale la pena."""
    r = classify(mf.high_volatility())
    assert r.adx >= ADX_TREND          # habria sido tendencia...
    assert r.regime is Regime.HIGH_VOL  # ...pero manda la volatilidad


# --------------------------------------------------------------------------
# Lo que costo un intento: percentil y empates
# --------------------------------------------------------------------------


def test_volatilidad_constante_no_es_volatilidad_alta():
    """REGRESION. Con el percentil contando los empates enteros (`<=`), una
    serie de volatilidad CONSTANTE daba percentil 100 y se clasificaba
    `HIGH_VOL`: o sea que la moneda mas aburrida posible salia como la mas
    movida. Con el convenio del punto medio da 50."""
    r = classify(mf.flat())
    assert r.atr_percentile == pytest.approx(50.0)
    assert r.regime is not Regime.HIGH_VOL


def test_hace_falta_percentil_Y_distancia_a_la_mediana():
    """REGRESION. El percentil solo no basta.

    Se construye a proposito el caso malo: una moneda cuya volatilidad crece
    despacisimo y de forma monotona. El ultimo valor es el mayor de la serie,
    asi que el percentil es 100... pero esta a un pelo de su propia mediana.
    Eso NO es volatilidad excepcional, es una moneda aburrida.

    Con solo el percentil, este caso se clasificaba `HIGH_VOL` y la moneda se
    quedaba fuera sin motivo. Es el mismo patron que se midio en una serie
    real con el ATR entre 1,06 % y 1,20 %: rango minusculo, percentiles
    extremos por puro ruido.
    """
    n = 200
    # Rango por vela que crece un 0,02 % cada vela: monotono pero plano.
    half_range = np.array([0.5 * (1 + 0.0002 * i) for i in range(n)])
    closes = np.full(n, 100.0)
    df = pd.DataFrame(
        {
            "close": closes,
            "high": closes + half_range,
            "low": closes - half_range,
            "volume": np.full(n, 1000.0),
        }
    )
    r = classify(df)
    serie = atr_pct(df["high"], df["low"], df["close"]).dropna()
    ratio = r.atr_pct / float(serie.median())

    assert r.atr_percentile >= ATR_PERCENTILE_HIGH, "el percentil SI es alto"
    assert ratio < ATR_HIGH_RATIO, "pero la distancia a su mediana NO"
    assert r.regime is not Regime.HIGH_VOL


# --------------------------------------------------------------------------
# `UNKNOWN` no es una etiqueta mas
# --------------------------------------------------------------------------


def test_sin_historia_suficiente_no_se_clasifica():
    r = classify(mf.trending_up(n=MIN_HISTORY - 5))
    assert r.regime is Regime.UNKNOWN
    assert not r.is_known
    assert "velas cerradas" in r.detail


def test_unknown_y_transition_no_son_lo_mismo():
    """`TRANSITION` es una lectura valida; `UNKNOWN` es la ausencia de lectura.

    Confundirlas costaria una de dos cosas: o prohibir las rupturas de rango
    (que viven en la transicion) o dejar operar sobre datos insuficientes.
    """
    sin_datos = classify(mf.trending_up(n=MIN_HISTORY - 5))
    assert sin_datos.regime is Regime.UNKNOWN
    assert not sin_datos.is_known

    transicion = classify(mf.range_then_breakout())
    assert transicion.regime is Regime.TRANSITION
    assert transicion.is_known


def test_faltan_columnas():
    with pytest.raises(ValueError, match="faltan columnas"):
        classify(pd.DataFrame({"close": [1.0] * 100}))


def test_con_nan_en_los_precios_no_se_clasifica():
    df = mf.trending_up()
    df.loc[df.index[-1], "close"] = np.nan
    assert classify(df).regime is Regime.UNKNOWN


# --------------------------------------------------------------------------
# Propiedades
# --------------------------------------------------------------------------


@given(
    n=st.integers(min_value=MIN_HISTORY, max_value=250),
    seed=st.integers(min_value=0, max_value=500),
)
def test_siempre_devuelve_un_regimen_valido(n: int, seed: int):
    """Sobre cualquier serie, una etiqueta del enum y nunca una excepcion."""
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.02, n))
    df = pd.DataFrame(
        {
            "close": closes,
            "high": closes * 1.006,
            "low": closes * 0.994,
            "volume": np.full(n, 1000.0),
        }
    )
    r = classify(df)
    assert isinstance(r.regime, Regime)
    assert r.regime is not Regime.UNKNOWN or not r.is_known


@given(seed=st.integers(min_value=0, max_value=300))
def test_un_regimen_nunca_es_dos_cosas(seed: int):
    """Las condiciones se excluyen entre si: no hay serie que sea a la vez
    tendencia y rango. Suena obvio y es justo lo que se rompe al tocar los
    umbrales sin mirar."""
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, 200))
    df = pd.DataFrame(
        {
            "close": closes,
            "high": closes * 1.006,
            "low": closes * 0.994,
            "volume": np.full(200, 1000.0),
        }
    )
    r = classify(df)
    if r.regime is Regime.RANGE:
        assert r.adx < ADX_RANGE
    if r.is_trend:
        assert r.adx >= ADX_TREND
    if r.regime is Regime.HIGH_VOL:
        assert r.atr_percentile >= ATR_PERCENTILE_HIGH
