"""Las metricas del simulador del paso 2 (plan, secciones 2, 4 y 9). Escritos ANTES del codigo, con valores conocidos."""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "estudios" / "paso2"))
from sim import metricas as me  # noqa: E402


def test_rendimiento_anual_y_caida():
    curva = [100.0 * 1.10 ** (i / 365) for i in range(366)]                  # +10 % en 365 dias
    assert math.isclose(me.anual(curva), 0.10, rel_tol=1e-9)
    assert me.caida_maxima([100.0, 120.0, 60.0, 90.0, 130.0]) == 0.5        # de 120 a 60


def test_sharpe_y_probabilistico():
    r = random.Random(1)
    rend = [r.gauss(0.001, 0.02) for _ in range(1000)]
    sr = me.sharpe_diario(rend)
    assert math.isclose(sr, (sum(rend) / 1000) / (math.fsum((x - sum(rend) / 1000) ** 2 for x in rend) / 1000) ** 0.5)
    # Probabilistico frente a 0: con un Sharpe diario de 0,05 y 1.000 dias, z ~ 1,58 -> ~0,94
    assert 0.90 < me.probabilistico(0.05, 1000, 0.0, 3.0) < 0.97
    assert me.probabilistico(0.0, 1000, 0.0, 3.0) == 0.5


def test_deflactado_es_mas_exigente_cuantos_mas_intentos():
    d10 = me.deflactado(0.06, 1000, 10, 0.30 / math.sqrt(365), 0.0, 3.0)
    d40 = me.deflactado(0.06, 1000, 40, 0.30 / math.sqrt(365), 0.0, 3.0)
    assert d40 < d10 < me.probabilistico(0.06, 1000, 0.0, 3.0)


def test_tipo_de_mercado_con_el_cierre_de_ayer():
    cierres = [100.0 + i for i in range(250)]                               # sube siempre
    tipos = me.tipos_de_mercado(cierres)
    assert tipos[199] is None and tipos[200] is None                         # la media de 200 de AYER no existe aun
    assert tipos[201] == "alcista"
    baja = [400.0 - i for i in range(250)]
    assert me.tipos_de_mercado(baja)[230] == "bajista"


def test_rendimiento_por_tipo_anualizado():
    curva = [100.0, 110.0, 99.0, 99.0]
    tipos = [None, "alcista", "bajista", "lateral"]
    por = me.por_tipo(curva, tipos)
    assert math.isclose(por["alcista"]["total"], 0.10) and math.isclose(por["bajista"]["total"], -0.10)
    assert por["lateral"]["dias"] == 1


def test_pbo_sin_ventaja_cerca_de_medio_y_con_una_buena_bajo():
    r = random.Random(3)
    ruido = [[r.gauss(0, 0.02) for _ in range(800)] for _ in range(5)]
    assert 0.0 <= me.pbo(ruido, trozos=8) <= 1.0
    buena = [[r.gauss(0.004 if k == 0 else 0.0, 0.02) for _ in range(800)] for k in range(5)]
    assert me.pbo(buena, trozos=8) < 0.25
