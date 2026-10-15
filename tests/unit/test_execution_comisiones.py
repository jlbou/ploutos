"""Que pares se operan segun las comisiones reales (`execution/comisiones.py`), sin red ni claves."""

from __future__ import annotations

from execution.comisiones import comision_usdc, operables

CONF = (0.10, 0.20)
DEMO = ("BTC/USDC", "ETH/USDC", "SOL/USDC", "DOGE/USDC", "NEAR/USDC")
# Lo que contesto OKX el 02/10 en el demo (grupo 12 y, NEAR, grupo 13), ya pasado a %.
DEMO_02_10 = {**{p: (0.10, 0.20) for p in DEMO[:4]}, "NEAR/USDC": (0.20, 0.35)}


def test_la_comision_de_okx_va_con_el_signo_al_reves_y_se_lee_la_de_usdc():
    r = {"data": [{"maker": "-0.0008", "taker": "-0.001", "makerUSDC": "-0.002", "takerUSDC": "-0.0035"}]}
    maker, taker = comision_usdc(r)
    assert round(maker, 6) == 0.20 and round(taker, 6) == 0.35
    assert comision_usdc({"data": [{}]}) == (None, None) and comision_usdc({}) == (None, None)


def test_en_el_demo_near_se_queda_fuera_y_los_otros_cuatro_se_operan():
    si, motivos = operables(DEMO, DEMO_02_10, CONF)
    assert si == DEMO[:4]
    assert len(motivos) == 2 and all(m.startswith("NEAR/USDC:") for m in motivos)


def test_mas_barata_se_opera_y_un_par_sin_respuesta_no():
    si, motivos = operables(("BTC/USDC", "SOL/USDC"), {"BTC/USDC": (0.08, 0.15)}, CONF)
    assert si == ("BTC/USDC",) and "SOL/USDC" in motivos[0]
    si, motivos = operables(("BTC/USDC",), {"BTC/USDC": (0.10, None)}, CONF)
    assert si == () and "no devolvio la comision taker" in motivos[0]


def test_igual_a_la_configurada_se_opera():
    assert operables(("BTC/USDC",), {"BTC/USDC": (0.1, 0.2)}, CONF)[0] == ("BTC/USDC",)
