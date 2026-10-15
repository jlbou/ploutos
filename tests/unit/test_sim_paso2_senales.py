"""Las senyales H1, H2, H3 y la capa de volatilidad (plan del paso 2, seccion 8). Escritos ANTES del codigo."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2"))
from sim import senales as sen  # noqa: E402

DIA = 86_400


def _dias(n, desde=datetime(2021, 1, 4, tzinfo=UTC)):        # 04/01/2021 es lunes
    t0 = int(desde.timestamp())
    return [t0 + i * DIA for i in range(n)]


def test_h1_dentro_solo_sobre_las_cuatro_medias():
    n = 260
    subiendo = [100.0 + i for i in range(n)]
    f = sen.h1(subiendo)
    assert f[198] == 0.0 and f[199] == 1.0                 # hasta tener la media de 200, fuera
    cae = subiendo[:250] + [subiendo[249] - 60.0] * 10    # cae por debajo de la de 20
    assert sen.h1(cae)[255] == 0.0


def test_h2_media_de_cuatro_plazos():
    n = 450
    altos = [100.0 + i for i in range(n)]
    bajos = [99.0 + i for i in range(n)]
    cierres = [100.5 + i for i in range(n)]
    f = sen.h2(altos, bajos, cierres)
    assert f[25] == 0.25                                   # solo el plazo de 20 tiene historia y rompe
    assert f[449] == 1.0                                   # los cuatro dentro
    # Sale el de 20 al bajar del minimo de los 10 anteriores; los largos siguen.
    cierres2 = cierres[:440] + [cierres[439] - 50.0] * 10
    bajos2 = bajos[:440] + [bajos[439] - 50.5] * 10
    altos2 = altos[:440] + [altos[439] - 49.5] * 10
    assert 0.0 < sen.h2(altos2, bajos2, cierres2)[441] < 1.0


def test_h3_solo_cambia_con_el_cierre_del_domingo():
    t = _dias(60)
    cierres = [100.0 + i for i in range(60)]
    f = sen.h3(t, cierres)
    domingos = [i for i, x in enumerate(t) if datetime.fromtimestamp(x, UTC).weekday() == 6]
    assert domingos[0] == 6                                # el 10/01/2021 es domingo
    assert f[domingos[4]] == 1.0                           # dia 34: las 4 semanas tienen historia, todas positivas
    lunes = domingos[4] + 1
    assert f[lunes] == f[domingos[4]]                      # entre domingos no cambia
    assert f[domingos[3]] == 0.75                          # dia 27: la de 4 semanas (28 dias) aun sin dato = 0
    assert f[5] == 0.0                                     # antes del primer domingo, fuera


def test_capa_de_volatilidad():
    assert sen.capa_volatilidad([1.0, 1.0, 0.5], [0.3, 1.2, None]) == [1.0, 0.5, 0.0]
