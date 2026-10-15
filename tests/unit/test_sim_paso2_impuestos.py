"""Los impuestos del simulador (plan, seccion 4): tramos del ahorro, FIFO y perdidas de 4 anyos. Hechos a mano, ANTES
del codigo."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2"))
from sim import impuestos as imp  # noqa: E402


def test_los_tramos():
    assert imp.cuota(0) == 0 and imp.cuota(-100) == 0
    assert math.isclose(imp.cuota(6_000), 1_140)                       # 6.000 al 19 %
    assert math.isclose(imp.cuota(10_000), 1_140 + 4_000 * 0.21)       # 1.980
    assert math.isclose(imp.cuota(250_000), 1_140 + 44_000 * 0.21 + 150_000 * 0.23 + 50_000 * 0.27)
    assert math.isclose(imp.cuota(400_000), imp.cuota(300_000) + 100_000 * 0.30)


def test_fifo_vende_primero_lo_primero():
    l = imp.Lotes()
    l.comprar(1.0, 100.0)          # 1 a 100 (coste total, con comision)
    l.comprar(1.0, 200.0)          # 1 a 200
    assert math.isclose(l.vender(1.5, 450.0), 450.0 - (100.0 + 100.0))   # 1 del primer lote + 0,5 del segundo
    assert math.isclose(l.cantidad, 0.5)
    assert math.isclose(l.vender(0.5, 50.0), 50.0 - 100.0)              # perdida de 50


def test_las_perdidas_compensan_cuatro_anyos():
    pend: list[tuple[int, float]] = []
    t, pend = imp.anual(2018, -1_000.0, pend)
    assert t == 0 and pend == [(2018, 1_000.0)]
    t, pend = imp.anual(2019, 400.0, pend)                               # compensa 400
    assert t == 0 and pend == [(2018, 600.0)]
    t, pend = imp.anual(2023, 1_000.0, pend)                             # 2018 + 4 = 2022: ya caduco
    assert math.isclose(t, imp.cuota(1_000.0)) and pend == []
