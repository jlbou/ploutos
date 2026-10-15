"""Paridad de USDC para la regla 17 (`features/usdc.py`).

Decision del propietario del 01/10/2026: SOLO A = USDC/USDT x USDT/USD (el control C, con
BTC/USD, murio cuando OKX retiro ese par el 30/09). Si falta un precio, la paridad
es DESCONOCIDA, y desconocida = no se entra.
"""

from __future__ import annotations

import math

import pytest

from features.usdc import BOOKS, bloquea_paridad, usdc_parity

# Medido el 22/09/2026 en OKX.
REAL = {"USDC/USDT": 0.99996, "USDT/USD": 0.99989}


def test_con_los_precios_reales_sale_en_paridad():
    r = usdc_parity(REAL)
    assert r.deviation_pct == pytest.approx(-0.015, abs=0.002)
    assert abs(r.deviation_pct) < 1.5


def test_marzo_2023_usdc_a_088_se_detecta():
    """SVB: USDC a 0,88 $. Contra USDT cae; USDT sigue en 1 $."""
    r = usdc_parity(dict(REAL, **{"USDC/USDT": 0.88, "USDT/USD": 1.0}))
    assert r.deviation_pct == pytest.approx(-12.0, abs=0.1)


def test_si_el_que_se_despega_es_usdt_a_no_se_engana():
    """USDT a 0,90 $: USDC/USDT sube a 1/0,9 y USDT/USD baja a 0,9. Se compensan."""
    r = usdc_parity(dict(REAL, **{"USDC/USDT": 1 / 0.90, "USDT/USD": 0.90}))
    assert r.deviation_pct == pytest.approx(0.0, abs=0.01)


def test_ya_no_pide_btc_usd():
    """OKX retiro BTC/USD el 30/09/2026: si se volviera a pedir, la regla 17 bloquearia todo otra vez."""
    assert "BTC/USD" not in BOOKS
    assert usdc_parity(REAL).deviation_pct is not None


@pytest.mark.parametrize("roto", [None, 0.0, -1.0, math.nan])
@pytest.mark.parametrize("libro", ["USDC/USDT", "USDT/USD"])
def test_un_precio_que_falta_la_deja_desconocida(libro, roto):
    r = usdc_parity(dict(REAL, **{libro: roto}))
    assert r.deviation_pct is None
    assert libro in r.detail


def test_sin_ningun_precio_desconocida():
    assert usdc_parity({}).deviation_pct is None


@pytest.mark.parametrize(("desviacion", "bloquea"), [(None, True), (0.0, False), (-0.015, False),
                                                     (1.5, False), (-1.5, False), (1.51, True), (-12.0, True)])
def test_bloquea_igual_que_la_regla_17(desviacion, bloquea):
    """El aviso dice "bloquea" exactamente cuando `risk/rules.rule_17` veta (desconocida o > tope)."""
    assert bloquea_paridad(desviacion, 1.5) is bloquea
