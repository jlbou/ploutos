"""Indicadores tecnicos.

Dos tipos de prueba, porque cada una atrapa cosas distintas:

* **Vectores calculados a mano**: series pequenyas cuyo resultado correcto se
  puede verificar con una calculadora. Atrapan errores de formula.
* **Propiedades**: cosas que deben cumplirse con CUALQUIER serie (el RSI vive
  en [0,100], el ATR nunca es negativo...). Atrapan los casos raros que no se
  me ocurrieron.

Un test que solo comprueba "no lanza excepcion" no sirve: una formula mal
escrita tampoco lanza excepcion.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from features.indicators import (
    adx,
    atr,
    atr_pct,
    bollinger_width_pct,
    ema,
    ema_slope_pct,
    macd_histogram,
    obv,
    realized_volatility_pct,
    roc,
    rsi,
    sma,
    true_range,
    volume_zscore,
    vwap,
)


def serie(*values: float) -> pd.Series:
    return pd.Series([float(v) for v in values])


def creciente(n: int, start: float = 100.0, step: float = 1.0) -> pd.Series:
    return serie(*[start + i * step for i in range(n)])


def constante(n: int, value: float = 100.0) -> pd.Series:
    return serie(*[value] * n)


# --------------------------------------------------------------------------
# EMA y SMA
# --------------------------------------------------------------------------


def test_sma_calculada_a_mano():
    """Media de [1,2,3] = 2; de [2,3,4] = 3."""
    out = sma(serie(1, 2, 3, 4), 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(3.0)


def test_ema_de_una_serie_constante_es_esa_constante():
    out = ema(constante(50, 100.0), 20)
    assert out.iloc[-1] == pytest.approx(100.0)


def test_ema_calculada_a_mano():
    """Con span=3, alpha = 2/(3+1) = 0,5.
    Arranca en 10; luego 0,5*20 + 0,5*10 = 15; luego 0,5*30 + 0,5*15 = 22,5."""
    out = ema(serie(10, 20, 30), 3)
    assert out.iloc[2] == pytest.approx(22.5)


def test_ema_sin_datos_suficientes_es_nan():
    out = ema(serie(1, 2, 3), 20)
    assert out.isna().all()


def test_ema_rapida_reacciona_antes_que_la_lenta():
    close = pd.concat([constante(60, 100.0), creciente(20, 101.0)], ignore_index=True)
    assert ema(close, 10).iloc[-1] > ema(close, 50).iloc[-1]


def test_la_pendiente_de_una_serie_plana_es_cero():
    out = ema_slope_pct(constante(80, 100.0), 20)
    assert out.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_la_pendiente_es_positiva_si_sube():
    assert ema_slope_pct(creciente(80), 20).iloc[-1] > 0


def test_la_pendiente_es_negativa_si_baja():
    assert ema_slope_pct(creciente(80, 200.0, -1.0), 20).iloc[-1] < 0


# --------------------------------------------------------------------------
# Rango verdadero y ATR
# --------------------------------------------------------------------------


def test_true_range_sin_hueco_es_el_rango_de_la_vela():
    h, low, c = serie(10, 12), serie(8, 9), serie(9, 11)
    # Segunda vela: max(12-9, |12-9|, |9-9|) = 3
    assert true_range(h, low, c).iloc[1] == pytest.approx(3.0)


def test_true_range_con_hueco_al_alza_usa_el_cierre_anterior():
    h, low, c = serie(10, 20), serie(8, 18), serie(9, 19)
    # max(20-18, |20-9|, |18-9|) = 11, no 2. El hueco cuenta.
    assert true_range(h, low, c).iloc[1] == pytest.approx(11.0)


def test_true_range_con_hueco_a_la_baja():
    h, low, c = serie(20, 10), serie(18, 8), serie(19, 9)
    # max(10-8, |10-19|, |8-19|) = 11
    assert true_range(h, low, c).iloc[1] == pytest.approx(11.0)


def test_el_atr_de_velas_identicas_es_su_rango():
    n = 60
    h, low, c = constante(n, 102.0), constante(n, 98.0), constante(n, 100.0)
    assert atr(h, low, c, 14).iloc[-1] == pytest.approx(4.0, rel=1e-6)


def test_el_atr_nunca_es_negativo():
    rng = np.random.default_rng(42)
    c = pd.Series(100 + rng.normal(0, 2, 200).cumsum())
    h, low = c + abs(rng.normal(0, 1, 200)), c - abs(rng.normal(0, 1, 200))
    out = atr(h, low, c, 14).dropna()
    assert (out >= 0).all()


def test_atr_pct_es_relativo_al_precio():
    """El mismo movimiento relativo da el mismo ATR% a cualquier precio."""
    n = 60
    barato = atr_pct(constante(n, 102.0), constante(n, 98.0), constante(n, 100.0), 14)
    caro = atr_pct(
        constante(n, 102000.0), constante(n, 98000.0), constante(n, 100000.0), 14
    )
    assert barato.iloc[-1] == pytest.approx(caro.iloc[-1], rel=1e-6)


def test_el_atr_exige_calentamiento():
    """Con pocas velas arrastra el sesgo del arranque: mejor NaN que un numero malo."""
    n = 20  # menos de 3 x 14
    out = atr(constante(n, 102.0), constante(n, 98.0), constante(n, 100.0), 14)
    assert out.isna().all()


# --------------------------------------------------------------------------
# RSI
# --------------------------------------------------------------------------


def test_rsi_de_una_serie_que_solo_sube_es_100():
    assert rsi(creciente(100), 14).iloc[-1] == pytest.approx(100.0)


def test_rsi_de_una_serie_que_solo_baja_es_0():
    assert rsi(creciente(100, 200.0, -1.0), 14).iloc[-1] == pytest.approx(0.0)


def test_rsi_de_una_serie_plana():
    """Sin ganancias ni perdidas. Lo importante es que no sea NaN ni reviente."""
    out = rsi(constante(100, 50.0), 14).iloc[-1]
    assert not np.isnan(out)
    assert 0.0 <= out <= 100.0


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        min_size=60, max_size=200,
    )
)
@hyp_settings(max_examples=200, deadline=None)
def test_el_rsi_siempre_vive_entre_0_y_100(values):
    out = rsi(pd.Series(values), 14).dropna()
    assert ((out >= 0.0) & (out <= 100.0)).all()


# --------------------------------------------------------------------------
# ADX
# --------------------------------------------------------------------------


def test_el_adx_de_una_tendencia_limpia_es_alto():
    """Una subida en linea recta es la tendencia mas fuerte posible."""
    n = 120
    c = creciente(n)
    h, low = c + 0.5, c - 0.5
    assert adx(h, low, c, 14).iloc[-1] > 40


def test_el_adx_de_un_rango_es_bajo():
    """Sierra sin direccion: mucha actividad, ninguna tendencia."""
    n = 150
    c = pd.Series([100 + (2 if i % 2 else -2) for i in range(n)], dtype="float64")
    h, low = c + 0.5, c - 0.5
    assert adx(h, low, c, 14).iloc[-1] < 25


def test_el_adx_no_distingue_direccion():
    """Mide FUERZA, no sentido: subir y bajar igual de limpio da lo mismo."""
    n = 150
    sube = creciente(n)
    baja = creciente(n, 100.0 + n, -1.0)
    a = adx(sube + 0.5, sube - 0.5, sube, 14).iloc[-1]
    b = adx(baja + 0.5, baja - 0.5, baja, 14).iloc[-1]
    assert a == pytest.approx(b, rel=0.10)


@given(
    values=st.lists(
        st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        min_size=60, max_size=150,
    )
)
@hyp_settings(max_examples=150, deadline=None)
def test_el_adx_siempre_vive_entre_0_y_100(values):
    c = pd.Series(values)
    out = adx(c + 0.5, c - 0.5, c, 14).dropna()
    assert ((out >= 0.0) & (out <= 100.0)).all()


# --------------------------------------------------------------------------
# MACD y ROC
# --------------------------------------------------------------------------


def test_el_histograma_del_macd_de_una_serie_plana_es_cero():
    out = macd_histogram(constante(100, 100.0))
    assert out.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_el_histograma_es_positivo_cuando_acelera_al_alza():
    close = pd.concat(
        [constante(60, 100.0), creciente(40, 101.0, 2.0)], ignore_index=True
    )
    assert macd_histogram(close).iloc[-1] > 0


def test_roc_calculado_a_mano():
    """De 100 a 110 en 1 periodo son +10 %."""
    assert roc(serie(100, 110), 1).iloc[1] == pytest.approx(10.0)


def test_roc_negativo():
    assert roc(serie(100, 90), 1).iloc[1] == pytest.approx(-10.0)


# --------------------------------------------------------------------------
# Bollinger y volatilidad
# --------------------------------------------------------------------------


def test_la_anchura_de_bollinger_de_una_serie_plana_es_cero():
    assert bollinger_width_pct(constante(50, 100.0), 20).iloc[-1] == pytest.approx(0.0)


def test_mas_volatilidad_da_bandas_mas_anchas():
    rng = np.random.default_rng(7)
    tranquila = pd.Series(100 + rng.normal(0, 0.1, 100))
    agitada = pd.Series(100 + rng.normal(0, 5.0, 100))
    assert (
        bollinger_width_pct(agitada, 20).iloc[-1]
        > bollinger_width_pct(tranquila, 20).iloc[-1]
    )


def test_la_volatilidad_realizada_de_una_serie_plana_es_cero():
    out = realized_volatility_pct(constante(50, 100.0), 24)
    assert out.iloc[-1] == pytest.approx(0.0)


def test_la_volatilidad_realizada_nunca_es_negativa():
    rng = np.random.default_rng(3)
    c = pd.Series(100 + rng.normal(0, 1, 200).cumsum()).abs() + 1
    assert (realized_volatility_pct(c, 24).dropna() >= 0).all()


# --------------------------------------------------------------------------
# Volumen
# --------------------------------------------------------------------------


def test_el_zscore_de_un_volumen_constante_es_cero():
    """Desviacion cero: el z no es infinito, es cero."""
    out = volume_zscore(constante(50, 1000.0), 20)
    assert out.iloc[-1] == pytest.approx(0.0)
    assert not np.isinf(out.iloc[-1])


def test_un_pico_de_volumen_da_zscore_alto():
    v = pd.concat([constante(40, 1000.0), serie(5000.0)], ignore_index=True)
    assert volume_zscore(v, 20).iloc[-1] > 3


def test_un_volumen_bajo_da_zscore_negativo():
    v = pd.concat([constante(40, 1000.0), serie(100.0)], ignore_index=True)
    assert volume_zscore(v, 20).iloc[-1] < 0


def test_el_vwap_de_precio_constante_es_ese_precio():
    n = 30
    h, low, c = constante(n, 100.0), constante(n, 100.0), constante(n, 100.0)
    assert vwap(h, low, c, constante(n, 500.0)).iloc[-1] == pytest.approx(100.0)


def test_el_vwap_pondera_por_volumen():
    """Dos velas: 100 con volumen 1 y 200 con volumen 9. Media ponderada: 190."""
    h = low = c = serie(100, 200)
    assert vwap(h, low, c, serie(1, 9)).iloc[-1] == pytest.approx(190.0)


def test_el_obv_sube_cuando_sube_el_precio():
    out = obv(serie(100, 101, 102), serie(10, 20, 30))
    assert out.iloc[-1] == pytest.approx(50.0)


def test_el_obv_baja_cuando_baja_el_precio():
    out = obv(serie(100, 99, 98), serie(10, 20, 30))
    assert out.iloc[-1] == pytest.approx(-50.0)


def test_el_obv_ignora_las_velas_sin_cambio():
    out = obv(serie(100, 100, 101), serie(10, 20, 30))
    assert out.iloc[-1] == pytest.approx(30.0)


# --------------------------------------------------------------------------
# Sin datos suficientes: NaN, nunca un numero inventado
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [
        lambda s: ema(s, 20),
        lambda s: sma(s, 20),
        lambda s: rsi(s, 14),
        lambda s: bollinger_width_pct(s, 20),
        lambda s: realized_volatility_pct(s, 24),
        lambda s: volume_zscore(s, 20),
        lambda s: macd_histogram(s),
    ],
)
def test_con_pocos_datos_devuelve_nan_no_un_numero(fn):
    """Rellenar con ceros produce senyales fantasma tras cada arranque."""
    out = fn(serie(100.0, 101.0, 102.0))
    assert out.isna().all()


@pytest.mark.parametrize(
    "fn",
    [
        lambda h, low, c: atr(h, low, c, 14),
        lambda h, low, c: atr_pct(h, low, c, 14),
        lambda h, low, c: adx(h, low, c, 14),
    ],
)
def test_los_indicadores_de_rango_tambien_devuelven_nan(fn):
    out = fn(serie(102, 103), serie(98, 99), serie(100, 101))
    assert out.isna().all()
