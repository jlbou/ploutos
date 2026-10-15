"""Equity con datos de OKX y la regla 7 (`execution/equity.py`), sin red."""

from __future__ import annotations

import ccxt
import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.config import load_settings
from execution.equity import SaldoOKX, Vigia, lectura, saldo_de_ccxt

S = load_settings()
WL = S.whitelist
# La taker de la cuenta desde el 25/09 (decision del propietario del 23/09). En esta rama aun no esta
# `exchange.fees` de settings.yaml (vive en fase-3-integracion): quien llame pasara esa.
TAKER = 0.002
SUELO = S.capital.floor_usd


def leer(usdc, monedas=None, bids=None):
    return lectura(SaldoOKX(usdc, monedas or {}), bids or {}, whitelist=WL, taker=TAKER)


def test_la_comision_de_salida_es_la_que_se_pasa():
    e = leer(35.0, {"NEAR": 5.0}, {"NEAR/USDC": 3.0})
    assert e.equity_usd == pytest.approx(35.0 + 15.0 - 15.0 * TAKER)


def _balance_de_okx(detalles):
    """Una respuesta de /api/v5/account/balance, pasada por el parser DE VERDAD de ccxt."""
    return ccxt.okx().parse_trading_balance({"data": [{"uTime": "1790035200000", "details": detalles}]})


def test_el_usdc_congelado_en_una_entrada_pendiente_cuenta():
    """Con una entrada de 15 $ pendiente, el equity NO baja 15 $: el dinero sigue ahi."""
    balance = _balance_de_okx([
        {"ccy": "USDC", "eq": "50", "cashBal": "50", "availBal": "35", "frozenBal": "15"},
        {"ccy": "NEAR", "eq": "0", "cashBal": "0", "availBal": "0", "frozenBal": "0"},
    ])
    assert balance["USDC"]["free"] == 35.0, "la trampa: ccxt da 35 en free"
    saldo = saldo_de_ccxt(balance, WL)
    assert saldo.usdc_total == 50.0
    assert lectura(saldo, {}, whitelist=WL, taker=TAKER).equity_usd == 50.0


def test_las_monedas_bloqueadas_en_su_oco_tambien_cuentan():
    """La OCO congela la moneda que protege: sigue siendo nuestra."""
    balance = _balance_de_okx([
        {"ccy": "USDC", "eq": "35", "cashBal": "35", "availBal": "35", "frozenBal": "0"},
        {"ccy": "NEAR", "eq": "5", "cashBal": "5", "availBal": "0", "frozenBal": "5"},
    ])
    saldo = saldo_de_ccxt(balance, WL)
    assert saldo.monedas["NEAR"] == 5.0 and saldo.monedas["BTC"] == 0.0
    e = lectura(saldo, {"NEAR/USDC": 3.0}, whitelist=WL, taker=TAKER)
    assert e.equity_usd == pytest.approx(35.0 + 15.0 * (1 - TAKER))


def test_solo_cuentan_las_monedas_de_la_whitelist():
    e = leer(40.0, {"NEAR": 1.0, "OKB": 100.0}, {"NEAR/USDC": 3.0, "OKB/USDC": 50.0})
    assert e.positions_value_usd == pytest.approx(3.0)


def test_sin_bid_de_una_moneda_que_tenemos_la_lectura_no_es_fiable():
    e = leer(35.0, {"NEAR": 5.0}, {})
    assert not e.is_reliable and e.stale_symbols == ("NEAR/USDC",)


@given(usdc=st.floats(0, 100), cantidad=st.floats(0, 50), bid=st.floats(0.01, 1000))
def test_nunca_cuenta_mas_de_lo_que_se_podria_vender(usdc, cantidad, bid):
    e = leer(usdc, {"SOL": cantidad}, {"SOL/USDC": bid})
    assert e.equity_usd <= usdc + cantidad * bid + 1e-9


# --------------------------------------------------------------------------
# Regla 7: dos lecturas seguidas
# --------------------------------------------------------------------------


def test_dos_lecturas_seguidas_bajo_el_suelo_enclavan():
    v = Vigia()
    dispara, v = v.con(leer(SUELO - 1), SUELO)
    assert not dispara and v.lecturas_bajo_suelo == 1
    dispara, v = v.con(leer(SUELO - 1), SUELO)
    assert dispara


def test_una_buena_en_medio_vuelve_a_empezar():
    v = Vigia()
    _, v = v.con(leer(SUELO - 1), SUELO)
    _, v = v.con(leer(SUELO + 5), SUELO)
    dispara, v = v.con(leer(SUELO - 1), SUELO)
    assert not dispara and v.lecturas_bajo_suelo == 1


def test_una_lectura_no_fiable_ni_enclava_ni_borra_la_mala_anterior():
    malo_sin_bid = leer(10.0, {"NEAR": 5.0}, {})   # sin bid: parece bajisimo, pero no es fiable
    v = Vigia()
    dispara, v = v.con(malo_sin_bid, SUELO)
    dispara, v = v.con(malo_sin_bid, SUELO)
    assert not dispara and v.lecturas_bajo_suelo == 0, "un libro vacio no enclava"
    _, v = v.con(leer(SUELO - 1), SUELO)
    _, v = v.con(malo_sin_bid, SUELO)
    dispara, v = v.con(leer(SUELO - 1), SUELO)
    assert dispara, "la no fiable no borra la primera lectura mala de verdad"


def test_justo_en_el_suelo_cuenta_como_bajo():
    """Regla 7: equity <= 25 $."""
    v = Vigia()
    _, v = v.con(leer(SUELO), SUELO)
    dispara, _ = v.con(leer(SUELO), SUELO)
    assert dispara
