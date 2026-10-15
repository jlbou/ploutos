"""Los indicadores del simulador del paso 2 (docs/estudios/paso2/sim/): sin futuro y nunca con menos dias de los que
dicen (aclaracion 1, C10). Escritos ANTES del codigo."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2"))
from sim import indicadores as ind  # noqa: E402

CIERRES = [float(x) for x in range(1, 31)]                 # 1, 2, ..., 30


def test_la_media_necesita_n_dias_y_no_mira_el_futuro():
    m = ind.media(CIERRES, 5)
    assert m[:4] == [None] * 4                              # con menos de 5 dias, nada
    assert m[4] == 3.0 and m[29] == 28.0                    # (1..5)/5 y (26..30)/5
    # Anyadir dias futuros no cambia lo ya calculado.
    assert ind.media(CIERRES + [1000.0], 5)[:30] == m


def test_donchian_usa_los_n_dias_anteriores_sin_hoy():
    altos = [10.0, 12.0, 11.0, 15.0, 9.0]
    bajos = [8.0, 9.0, 7.0, 10.0, 6.0]
    mx, mn = ind.maximo_anterior(altos, 3), ind.minimo_anterior(bajos, 3)
    assert mx[:3] == [None] * 3 and mn[:3] == [None] * 3
    assert mx[3] == 12.0 and mx[4] == 15.0                  # el dia 3 compara con 0-2; el 4 con 1-3 (no consigo mismo)
    assert mn[3] == 7.0 and mn[4] == 7.0


def test_el_rendimiento_de_k_dias():
    r = ind.rendimiento(CIERRES, 7)
    assert r[:7] == [None] * 7 and math.isclose(r[7], 8 / 1 - 1)


def test_atr_de_wilder_necesita_n_dias():
    altos, bajos, cierres = [11.0] * 20, [9.0] * 20, [10.0] * 20
    a = ind.atr(altos, bajos, cierres, 14)
    assert a[:13] == [None] * 13 and math.isclose(a[13], 2.0) and math.isclose(a[19], 2.0)


def test_volatilidad_anualizada_de_30_dias():
    cierres = [100.0 * (1.01 if i % 2 else 0.99) ** 0 * (1 + (0.01 if i % 2 else -0.01)) for i in range(40)]
    v = ind.volatilidad(cierres, 30)
    assert v[:30] == [None] * 30 and v[35] is not None and v[35] > 0
    assert ind.volatilidad([100.0] * 40, 30)[35] == 0.0
