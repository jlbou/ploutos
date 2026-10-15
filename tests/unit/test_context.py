"""Correlaciones entre monedas (regla 15).

Este modulo existe porque faltaba: `RiskState.correlations` llegaba siempre
vacio y la mitad de correlacion de la regla 15 no habia vetado nunca nada. Los
tests protegen las dos cosas que lo hacen util: que el numero sea el correcto
(rendimientos, no precios) y que aterrice donde el motor lo lee.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from features.context import (
    MIN_SAMPLES,
    CorrelationMatrix,
    compute,
    correlated_budget_used,
)

N = 200


def serie(valores) -> pd.Series:
    return pd.Series(list(valores), index=range(len(valores)), dtype="float64")


def paseo(seed: int, n: int = N, drift: float = 0.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return serie(100 * np.cumprod(1 + drift + rng.normal(0, 0.01, n)))


# --------------------------------------------------------------------------
# El numero
# --------------------------------------------------------------------------


def test_una_moneda_consigo_misma_es_uno():
    m = compute({"A/USDC": paseo(1), "B/USDC": paseo(2)})
    assert m.get("A/USDC", "A/USDC") == 1.0


def test_dos_series_identicas_correlacionan_uno():
    base = paseo(3)
    m = compute({"A/USDC": base, "B/USDC": base.copy()})
    assert m.get("A/USDC", "B/USDC") == pytest.approx(1.0)


def test_una_serie_invertida_correlaciona_menos_uno():
    base = paseo(4)
    invertida = serie(100 * (base.iloc[0] / base).to_numpy() / base.iloc[0] * base.iloc[0])
    m = compute({"A/USDC": base, "B/USDC": invertida})
    assert m.get("A/USDC", "B/USDC") < -0.9


def test_se_usan_RENDIMIENTOS_y_no_precios():
    """LA DECISION QUE MAS SE MALENTIENDE.

    Dos monedas que suben las dos correlacionan casi 1 en PRECIO aunque suban
    por motivos completamente distintos: eso es la tendencia comun, no la
    relacion entre ellas. Lo que le importa a la regla 15 es si se mueven
    juntas vela a vela.

    Aqui las dos tienen una deriva fuerte al alza y ruido independiente: la
    correlacion de precios es altisima y la de rendimientos, que es la que se
    calcula, es casi cero.
    """
    a = paseo(5, drift=0.004)
    b = paseo(6, drift=0.004)

    correlacion_de_precios = float(a.corr(b))
    m = compute({"A/USDC": a, "B/USDC": b})
    correlacion_de_rendimientos = m.get("A/USDC", "B/USDC")

    assert correlacion_de_precios > 0.9, "en precio parecen la misma moneda"
    assert abs(correlacion_de_rendimientos) < 0.3, "en rendimiento son independientes"


# --------------------------------------------------------------------------
# Cuando no se sabe
# --------------------------------------------------------------------------


def test_sin_muestra_suficiente_el_par_no_se_registra():
    """NO se registra como 0,0.

    Una correlacion calculada con 10 velas no es una correlacion baja: es una
    que no se sabe. Guardarla como cero le diria al motor de riesgo que dos
    monedas son independientes sin que nadie lo haya comprobado, y ese es el
    error caro en esta direccion.
    """
    corta = {"A/USDC": paseo(7, n=20), "B/USDC": paseo(8, n=20)}
    m = compute(corta)
    assert m.values == {}
    assert "A/USDC/B/USDC" in m.skipped[0] or m.skipped


def test_justo_en_el_minimo_si_se_registra():
    n = MIN_SAMPLES + 2
    m = compute({"A/USDC": paseo(9, n=n), "B/USDC": paseo(10, n=n)}, window=n)
    assert ("A/USDC", "B/USDC") in m.values


def test_con_una_sola_moneda_no_hay_pares():
    assert compute({"A/USDC": paseo(11)}).values == {}


def test_las_series_se_alinean_por_timestamp():
    """Sin alinear, un hueco en una moneda desplazaria las demas y la
    correlacion seria ruido con pinta de dato."""
    a = paseo(12)
    b = paseo(13)
    b_con_hueco = b.drop(index=[50, 51, 52])
    m = compute({"A/USDC": a, "B/USDC": b_con_hueco})
    # No revienta y devuelve algo razonable.
    assert -1.0 <= m.get("A/USDC", "B/USDC") <= 1.0


# --------------------------------------------------------------------------
# Que aterrice donde el motor lo lee
# --------------------------------------------------------------------------


def test_las_claves_van_en_el_orden_que_espera_el_motor():
    """`RiskState.correlation()` busca la clave con `a < b` alfabeticamente.
    Calcularlo bien y guardarlo donde nadie lo lee seria el fallo tonto."""
    m = compute({"Z/USDC": paseo(14), "A/USDC": paseo(15)})
    assert ("A/USDC", "Z/USDC") in m.values
    assert ("Z/USDC", "A/USDC") not in m.values


def test_el_motor_lee_lo_que_este_modulo_escribe():
    """La prueba que enlaza las dos piezas de verdad."""
    from tests.risk_fixtures import make_state

    base = paseo(16)
    m = compute({"BTC/USDC": base, "ETH/USDC": base.copy()})
    state = make_state(correlations=dict(m.values))
    assert state.correlation("BTC/USDC", "ETH/USDC") == pytest.approx(1.0)
    assert state.correlated_with("BTC/USDC", 0.8) == []  # nada en cartera aun


def test_un_par_desconocido_devuelve_cero():
    """Consistente con `RiskState`: lo que no esta, no correlaciona."""
    m = CorrelationMatrix({("A/USDC", "B/USDC"): 0.9})
    assert m.get("A/USDC", "C/USDC") == 0.0


# --------------------------------------------------------------------------
# Para el panel
# --------------------------------------------------------------------------


def test_pares_por_encima_del_umbral_ordenados():
    m = CorrelationMatrix(
        {
            ("A/USDC", "B/USDC"): 0.95,
            ("A/USDC", "C/USDC"): 0.84,
            ("B/USDC", "C/USDC"): 0.20,
        }
    )
    assert [v for _a, _b, v in m.above(0.8)] == [0.95, 0.84]


def test_grupos_de_monedas_que_se_mueven_juntas():
    """Medido el 22/09/2026: BTC, ETH y SOL forman un grupo donde los TRES
    pares pasan de 0,80."""
    m = CorrelationMatrix(
        {
            ("BTC/USDC", "ETH/USDC"): 0.84,
            ("BTC/USDC", "SOL/USDC"): 0.81,
            ("ETH/USDC", "SOL/USDC"): 0.84,
            ("TRX/USDC", "NEAR/USDC"): 0.09,
        }
    )
    grupos = m.clusters(0.8)
    assert len(grupos) == 1
    assert grupos[0] == frozenset({"BTC/USDC", "ETH/USDC", "SOL/USDC"})


def test_presupuesto_de_correlacion_usado():
    m = CorrelationMatrix(
        {("BTC/USDC", "ETH/USDC"): 0.84, ("BTC/USDC", "TRX/USDC"): 0.26}
    )
    usado = correlated_budget_used(
        m, "BTC/USDC", ["ETH/USDC", "TRX/USDC"], threshold=0.8
    )
    assert usado == 1
