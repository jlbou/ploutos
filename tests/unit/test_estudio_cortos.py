"""El paso de un largo sobre precios invertidos a un CORTO real (docs/estudios/revision-estrategia/cortos.py).

Todo el estudio de los cortos depende de esta cuenta: se comprueba con un corto hecho a mano.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "docs" / "estudios" / "revision-estrategia" / "cortos.py"
_spec = importlib.util.spec_from_file_location("estudio_cortos", SCRIPT)
ec = importlib.util.module_from_spec(_spec)
sys.modules["estudio_cortos"] = ec
_spec.loader.exec_module(ec)

H = 3600_000
K = 10_000.0                      # precio invertido = K / precio real


def test_un_corto_que_llega_al_objetivo_hecho_a_mano():
    # Corto real: entrada 100, stop 103, sale en 97 (objetivo). Riesgo planificado 0,5 $, comisiones maker 0,1 %.
    e_inv, s_inv, x_inv = K / 100, K / 103, K / 97
    q_inv = 0.5 / (e_inv - s_inv)
    fee_ent, fee_sal = q_inv * e_inv * 0.001, q_inv * x_inv * 0.001
    c = ec.a_corto(K, e_inv, x_inv, s_inv, q_inv, fee_ent, fee_sal, 7 * H, 7 * H + 30 * 60_000)
    q = 0.5 / 3
    neto = q * 3 - q * 100 * 0.001 - q * 97 * 0.001
    assert abs(c["neto_usd"] - neto) < 1e-9 and abs(c["r"] - neto / 0.5) < 1e-9
    assert abs(c["entrada"] - 100) < 1e-9 and abs(c["stop"] - 103) < 1e-9 and abs(c["salida"] - 97) < 1e-9
    assert c["r_con_financiacion"] == c["r"]          # 30 min abierta, sin cobro por medio


def test_un_corto_que_salta_en_el_stop_pierde_algo_mas_de_1r():
    e_inv, s_inv = K / 100, K / 103
    q_inv = 0.5 / (e_inv - s_inv)
    c = ec.a_corto(K, e_inv, s_inv, s_inv, q_inv, q_inv * e_inv * 0.001, q_inv * s_inv * 0.002, 0, H)
    q = 0.5 / 3                                      # -1 R mas las comisiones: 0,1 % al entrar, 0,2 % al salir
    assert abs(c["r"] - (-0.5 - q * 100 * 0.001 - q * 103 * 0.002) / 0.5) < 1e-9 and c["r"] < -1.0


def test_la_financiacion_pesimista_se_cobra_a_las_00_08_y_16():
    assert ec.cobros_entre(7 * H, 17 * H) == 2       # las 08 y las 16
    assert ec.cobros_entre(8 * H, 8 * H + 1) == 0     # abierta justo en el cobro: no paga ese
    e_inv, s_inv, x_inv = K / 100, K / 103, K / 97
    q_inv = 0.5 / (e_inv - s_inv)
    c = ec.a_corto(K, e_inv, x_inv, s_inv, q_inv, 0.0, 0.0, 7 * H, 17 * H)
    q = 0.5 / 3
    assert abs((c["r"] - c["r_con_financiacion"]) * 0.5 - q * 100 * ec.FINANCIACION * 2) < 1e-12
