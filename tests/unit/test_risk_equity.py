"""`risk/equity.py`: la regla 6 (equity) y la 7 (dos lecturas bajo el suelo).

Hasta el 25/09/2026 `compute_equity` no tenia NI UN test (ni nadie que la llamara: la usara
el ejecutor de la fase 4). `floor_breached` si la usa el bucle, y aqui se prueba suelta.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from risk.equity import compute_equity, floor_breached
from risk.state import Position

AHORA = datetime(2026, 9, 25, tzinfo=UTC)


def pos(simbolo, qty, entrada=100.0):
    return Position(simbolo, qty, entrada, entrada * 0.96, entrada * 1.1, AHORA, f"d-{simbolo}")


def test_suma_el_libre_y_las_posiciones_al_bid_menos_la_comision_de_salida():
    e = compute_equity(35.0, (pos("NEAR/USDC", 5.0, 3.0),), {"NEAR/USDC": 3.1}, taker_fee=0.002)
    assert e.positions_value_usd == pytest.approx(15.5)
    assert e.exit_fees_usd == pytest.approx(15.5 * 0.002)
    assert e.equity_usd == pytest.approx(35.0 + 15.5 * (1 - 0.002))
    assert e.is_reliable


def test_la_comision_es_obligatoria():
    """Llevaba 0,0015 (la generica de ccxt) por defecto; la de la cuenta es 0,002."""
    with pytest.raises(TypeError):
        compute_equity(35.0, (), {})  # type: ignore[call-arg]


def test_sin_bid_de_una_posicion_no_es_fiable_y_no_se_inventa_su_valor():
    e = compute_equity(35.0, (pos("NEAR/USDC", 5.0), pos("SOL/USDC", 0.1)),
                       {"SOL/USDC": 150.0, "NEAR/USDC": 0.0}, taker_fee=0.002)
    assert not e.is_reliable and e.stale_symbols == ("NEAR/USDC",)
    assert e.positions_value_usd == pytest.approx(15.0), "NEAR no suma nada"


def test_sin_posiciones_el_equity_es_el_libre():
    assert compute_equity(50.0, (), {}, taker_fee=0.002).equity_usd == 50.0


@pytest.mark.parametrize("lecturas, dispara", [
    ([24.0], False),
    ([24.0, 24.0], True),
    ([25.0, 25.0], True),          # regla 7: <= 25
    ([24.0, 26.0, 24.0], False),   # una buena en medio vuelve a empezar
    ([26.0, 24.0, 24.0], True),
])
def test_la_regla_7_pide_dos_lecturas_seguidas(lecturas, dispara):
    n, ultimo = 0, False
    for e in lecturas:
        ultimo, n = floor_breached(e, 25.0, n)
    assert ultimo is dispara
