"""El saldo virtual del demo (`execution.equity.virtual`, pieza c0; decision del propietario del 02/10), sin red.

La cuenta demo trae los fondos de OKX (los de abajo son los leidos el 02/10 con `comprobar_cuenta_demo.py`). El bot
cuenta como suyo 50 USDC + lo que haya cambiado desde la FOTO del arranque; el equity (regla 6), la regla 7 y la
conciliacion reciben ese saldo ya virtualizado.
"""

from __future__ import annotations

import ccxt
import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.config import load_settings
from execution import ids
from execution.conciliacion import Descuadre, Exchange, Local, OcoEx, PosicionLocal, conciliar
from execution.equity import Foto, SaldoOKX, Vigia, lectura, saldo_de_ccxt, virtual
from strategy.candidates import make_decision_id
from tests.risk_fixtures import INSTRUMENTS

S = load_settings()
WL = S.whitelist
CAPITAL = S.capital.initial_capital_usd
SUELO = S.capital.floor_usd
TAKER = 0.002
LOTES = {s: i.lot_size for s, i in INSTRUMENTS.items()}
NEAR = make_decision_id("NEAR/USDC", "pullback_trend", 1_790_035_200_000)


def _balance(detalles):
    """Una respuesta de /api/v5/account/balance, pasada por el parser DE VERDAD de ccxt."""
    filas = [{"ccy": c, "eq": str(v), "cashBal": str(v), "availBal": str(v), "frozenBal": "0"}
             for c, v in detalles.items()]
    return ccxt.okx().parse_trading_balance({"data": [{"uTime": "1790035200000", "details": filas}]})


DEMO_02_10 = {"USDC": 5000, "BTC": 1, "ETH": 1, "XRP": 50000, "USD": 5000, "EUR": 4600}
FOTO = Foto.de_saldo(saldo_de_ccxt(_balance(DEMO_02_10), WL))


def bot(detalles) -> SaldoOKX:
    return virtual(saldo_de_ccxt(_balance(detalles), WL), FOTO, capital_inicial=CAPITAL)


def test_recien_hecha_la_foto_el_bot_tiene_50_y_nada_mas():
    """Sin la foto, el equity del demo saldria > 100.000 $ y las reglas 7, 8, 9 y 15 no medirian nada."""
    s = bot(DEMO_02_10)
    assert s.usdc_total == CAPITAL and all(v == 0 for v in s.monedas.values())
    e = lectura(s, {"BTC/USDC": 84400.0, "ETH/USDC": 4000.0, "XRP/USDC": 2.5}, whitelist=WL, taker=TAKER)
    assert e.equity_usd == CAPITAL and e.is_reliable, "BTC, ETH y XRP de la foto no son del bot"


def test_una_compra_del_bot_cambia_solo_lo_suyo():
    """La compra de NEAR de la prueba 6 del 02/10: 2,139 NEAR por 10,0316 USDC (comision incluida)."""
    s = bot({**DEMO_02_10, "USDC": 5000 - 10.03160215, "NEAR": 2.139})
    assert s.usdc_total == pytest.approx(CAPITAL - 10.03160215)
    assert s.monedas["NEAR"] == pytest.approx(2.139) and s.monedas["BTC"] == 0
    e = lectura(s, {"NEAR/USDC": 4.67}, whitelist=WL, taker=TAKER)
    assert e.equity_usd == pytest.approx(CAPITAL - 10.03160215 + 2.139 * 4.67 * (1 - TAKER))


def test_el_usdc_de_una_venta_a_mano_no_infla_el_equity():
    """Alguien vende el BTC del demo desde la web: entran 84.400 USDC que no son del bot."""
    s = bot({**DEMO_02_10, "USDC": 5000 + 84400 * 0.998, "BTC": 0})
    assert s.monedas["BTC"] == -1
    e = lectura(s, {"BTC/USDC": 84400.0}, whitelist=WL, taker=TAKER)
    assert e.equity_usd == pytest.approx(CAPITAL - 84400 * 0.002), "neto: solo la comision de esa venta"


def test_la_venta_a_mano_es_un_descuadre_en_la_conciliacion():
    s = bot({**DEMO_02_10, "USDC": 5000 + 84400, "BTC": 0})
    ex = Exchange(saldos=s.monedas, usdc=s.usdc_total)
    r = conciliar(Local(usdc=CAPITAL), ex, lotes=LOTES)
    assert Descuadre.SALDO_BASE in [f.tipo for f in r.descuadres]
    assert Descuadre.SALDO_USDC in [f.tipo for f in r.descuadres]


def test_con_saldo_virtual_la_posicion_del_bot_cuadra():
    """Los 50.000 XRP y el BTC de la foto no salen como descuadre: no son del bot."""
    s = bot({**DEMO_02_10, "USDC": 5000 - 10.03160215, "NEAR": 2.139})
    ex = Exchange(saldos=s.monedas, usdc=s.usdc_total,
                  ocos=(OcoEx(ids.algo_cl_ord_id(NEAR), "NEAR/USDC", 2.139, "live"),))
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 2.139),), usdc=CAPITAL - 10.03160215)
    r = conciliar(local, ex, lotes=LOTES)
    assert r.cuadra and r.acciones == []


def test_sin_saldo_virtual_el_demo_daria_descuadres():
    """El control: con los saldos absolutos, la misma cuenta no cuadra (por eso hace falta la foto)."""
    s = saldo_de_ccxt(_balance({**DEMO_02_10, "USDC": 5000 - 10.03160215, "NEAR": 2.139}), WL)
    ex = Exchange(saldos=s.monedas, usdc=s.usdc_total,
                  ocos=(OcoEx(ids.algo_cl_ord_id(NEAR), "NEAR/USDC", 2.139, "live"),))
    local = Local(posiciones=(PosicionLocal(NEAR, "NEAR/USDC", 2.139),), usdc=CAPITAL - 10.03160215)
    assert not conciliar(local, ex, lotes=LOTES).cuadra


def test_la_regla_7_se_mide_sobre_el_saldo_del_bot():
    """El demo tiene 5.000 USDC, pero si el bot ha perdido 26 $, esta bajo el suelo."""
    s = bot({**DEMO_02_10, "USDC": 5000 - 26})
    v = Vigia()
    _, v = v.con(lectura(s, {}, whitelist=WL, taker=TAKER), SUELO)
    dispara, _ = v.con(lectura(s, {}, whitelist=WL, taker=TAKER), SUELO)
    assert dispara


def test_la_foto_sobrevive_a_guardarla_y_leerla():
    assert Foto.de_dict(FOTO.a_dict()) == FOTO
    assert FOTO.a_dict()["monedas"]["XRP"] == 50000 and "USD" not in FOTO.a_dict()["monedas"]


def test_una_moneda_que_no_estaba_en_la_foto_empieza_en_cero():
    foto = Foto(5000.0, {"BTC": 1.0})
    s = virtual(SaldoOKX(5000.0, {"BTC": 1.0, "SOL": 0.5}), foto, capital_inicial=CAPITAL)
    assert s.monedas == {"BTC": 0.0, "SOL": 0.5}


@given(usdc=st.floats(0, 1e6), btc=st.floats(0, 100), gasto=st.floats(0, 50), compra=st.floats(0, 1))
def test_el_equity_del_bot_no_depende_de_lo_que_ya_habia(usdc, btc, gasto, compra):
    """Mismas operaciones del bot sobre cuentas con fondos distintos: el mismo equity."""
    def equity(fondos_usdc, fondos_btc):
        foto = Foto(fondos_usdc, {"BTC": fondos_btc})
        s = virtual(SaldoOKX(fondos_usdc - gasto, {"BTC": fondos_btc + compra}), foto, capital_inicial=CAPITAL)
        return lectura(s, {"BTC/USDC": 84400.0}, whitelist=WL, taker=TAKER).equity_usd
    assert equity(usdc, btc) == pytest.approx(equity(0.0, 0.0), abs=1e-6)
