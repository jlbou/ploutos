"""Todas las peticiones del bot, construidas por ccxt DE VERDAD (sin red) con los ticks reales.

Lo que pide docs/preparacion-fase-4.md: "un test que construya en local TODAS las peticiones que el
bot hace (entrada, OCO, cancelacion) y compruebe tdMode == cash". Aqui, para las 8 monedas y precios
cualquiera, y ademas que todas pasan la guardia y llevan nuestros ids.
"""

from __future__ import annotations

import ccxt
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.config import load_settings
from execution import guardia, ids, peticiones
from execution.guardia import PeticionRechazada
from execution.peticiones import EstadoDesconocido, TrasConsultar, tras_consultar
from execution.precios import al_tick
from strategy.candidates import make_decision_id
from tests.risk_fixtures import INSTRUMENTS

WHITELIST = load_settings().whitelist
T0 = 1_790_035_200_000
PRECIO = {"BTC/USDC": 65000.0, "ETH/USDC": 2600.0, "SOL/USDC": 150.0, "XRP/USDC": 0.6,
          "DOGE/USDC": 0.1, "AVAX/USDC": 25.0, "TRX/USDC": 0.15, "NEAR/USDC": 5.0}


def _mercado(simbolo, tick, lote, minimo):
    base, quote = simbolo.split("/")
    return {"id": f"{base}-{quote}", "symbol": simbolo, "base": base, "quote": quote,
            "baseId": base, "quoteId": quote, "type": "spot", "spot": True, "margin": False,
            "swap": False, "future": False, "option": False, "contract": False, "linear": None,
            "inverse": None, "settle": None, "active": True,
            "precision": {"amount": lote, "price": tick},
            "limits": {"amount": {"min": minimo}, "cost": {"min": None}}, "info": {}}


def okx(opciones=guardia.OPCIONES_EXCHANGE):
    ex = ccxt.okx({"hostname": "eea.okx.com", "options": dict(opciones)})
    ex.set_markets([_mercado(s, i.tick_size, i.lot_size, i.min_amount) for s, i in INSTRUMENTS.items()]
                   + [_mercado("ADA/USDC", 0.0001, 0.01, 1.0)])
    return ex


EX = okx()


def precios_de(simbolo, factor):
    """Una orden de ~15 $ con un stop al 3,3 % y un objetivo a 2,4 R, al tick de verdad."""
    ins = INSTRUMENTS[simbolo]
    entrada = PRECIO[simbolo] * factor
    stop, objetivo = entrada * (1 - 0.033), entrada * (1 + 0.08)
    cantidad = 15.0 / entrada
    return al_tick(ins, entrada=entrada, stop=stop, objetivo=objetivo, cantidad=cantidad,
                   riesgo_aprobado_usd=cantidad * (entrada - stop) * 1.01)


@settings(max_examples=150)
@given(simbolo=st.sampled_from(sorted(PRECIO)), factor=st.floats(0.5, 2.0),
       velas=st.integers(0, 6 * 365))
def test_toda_entrada_y_toda_oco_salen_en_cash_con_nuestros_ids(simbolo, factor, velas):
    did = make_decision_id(simbolo, "pullback_trend", T0 + velas * 4 * 3600_000)
    p = precios_de(simbolo, factor)
    e = peticiones.entrada(EX, decision_id=did, simbolo=simbolo, precios=p, whitelist=WHITELIST)
    o = peticiones.proteccion(EX, decision_id=did, simbolo=simbolo, cantidad=p.cantidad, stop=p.stop,
                              objetivo=p.objetivo, whitelist=WHITELIST)
    assert e["tdMode"] == o["tdMode"] == "cash"
    assert e["clOrdId"] == ids.cl_ord_id(did) and o["algoClOrdId"] == ids.algo_cl_ord_id(did)
    assert e["ordType"] == "post_only" and e["side"] == "buy"
    assert o["ordType"] == "oco" and o["side"] == "sell" and str(o["slOrdPx"]) == "-1"
    # Los precios al tick no los mueve ccxt, y la cantidad nunca sube.
    assert float(e["px"]) == p.entrada
    assert float(o["slTriggerPx"]) == p.stop and float(o["tpTriggerPx"]) == p.objetivo
    assert float(e["sz"]) <= p.cantidad + 1e-12 and float(o["sz"]) <= p.cantidad + 1e-12
    # Lo que dijo el demo (02/10): stop y objetivo adjuntos a la entrada, a mercado, con nuestro id y los mismos
    # precios que la OCO; y la moneda con que se paga, explicita.
    (a,) = e["attachAlgoOrds"]
    assert a["attachAlgoClOrdId"] == o["algoClOrdId"]
    assert float(a["slTriggerPx"]) == p.stop and float(a["tpTriggerPx"]) == p.objetivo
    assert a["slOrdPx"] == a["tpOrdPx"] == "-1" and str(o["tpOrdPx"]) == "-1"
    assert e["tradeQuoteCcy"] == o["tradeQuoteCcy"] == "USDC"


def test_sin_las_opciones_la_oco_sigue_en_cash_pero_lleva_ids_de_ccxt_y_no_sale():
    """Si alguien crea el exchange sin `OPCIONES_EXCHANGE` (medido el 26/09 con ccxt 4.5.82):
    - el `tdMode: cash` que pasamos en CADA peticion la mantiene en cash (primera proteccion de la
      regla 1; la segunda son las opciones del exchange);
    - pero ccxt le mete su `clOrdId` y su `tag` de broker, y la guardia no la deja salir."""
    did = make_decision_id("BTC/USDC", "pullback_trend", T0)
    p = precios_de("BTC/USDC", 1.0)
    crudo = okx({}).create_order_request("BTC/USDC", "limit", "sell", p.cantidad, None, {
        "stopLossPrice": p.stop, "takeProfitPrice": p.objetivo,
        "algoClOrdId": ids.algo_cl_ord_id(did), "tdMode": "cash"})
    assert crudo["tdMode"] == "cash" and "tag" in crudo and "clOrdId" in crudo
    with pytest.raises(PeticionRechazada) as e:
        peticiones.proteccion(okx({}), decision_id=did, simbolo="BTC/USDC", cantidad=p.cantidad,
                              stop=p.stop, objetivo=p.objetivo, whitelist=WHITELIST)
    assert any("tag" in m for m in e.value.motivos) and any("clOrdId" in m for m in e.value.motivos)
    # Y NO por la regla 1: el tdMode explicito de `peticiones.proteccion` la mantiene en cash.
    assert not any("regla 1" in m for m in e.value.motivos)


def test_una_moneda_fuera_de_la_whitelist_no_sale():
    did = make_decision_id("ADA/USDC", "pullback_trend", T0)
    p = precios_de("XRP/USDC", 1.0)          # precios de una moneda parecida: lo que se mira es el par
    with pytest.raises(PeticionRechazada) as e:
        peticiones.entrada(EX, decision_id=did, simbolo="ADA/USDC", precios=p, whitelist=WHITELIST)
    assert any("regla 3" in m for m in e.value.motivos)
    with pytest.raises(PeticionRechazada):
        peticiones.cancelar_entrada(decision_id=did, simbolo="ADA/USDC", whitelist=WHITELIST)


def test_las_cancelaciones_llevan_nuestros_ids():
    did = make_decision_id("ETH/USDC", "range_breakout", T0)
    assert peticiones.cancelar_entrada(decision_id=did, simbolo="ETH/USDC", whitelist=WHITELIST) == \
        {"instId": "ETH-USDC", "clOrdId": ids.cl_ord_id(did)}
    assert peticiones.cancelar_oco(decision_id=did, simbolo="ETH/USDC", whitelist=WHITELIST) == \
        {"instId": "ETH-USDC", "algoClOrdId": ids.algo_cl_ord_id(did)}


@pytest.mark.parametrize("estado, que", [
    (None, TrasConsultar.ENVIAR),
    ("live", TrasConsultar.YA_ESTA),
    ("partially_filled", TrasConsultar.YA_ESTA),
    ("filled", TrasConsultar.LLENADA),
    ("canceled", TrasConsultar.NO_REENVIAR),
    ("mmp_canceled", TrasConsultar.NO_REENVIAR),
])
def test_consultar_antes_de_reenviar(estado, que):
    assert tras_consultar(estado) is que


def test_un_estado_desconocido_no_se_toma_por_no_existe():
    """Tomarlo por "no existe" enviaria una orden repetida: se para."""
    with pytest.raises(EstadoDesconocido):
        tras_consultar("partially_canceled")
