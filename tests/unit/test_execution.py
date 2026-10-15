"""Las dos piezas puras de la fase 4: los ids para OKX y la guardia.

Las peticiones de la guardia las construye `ccxt` DE VERDAD
(`create_order_request`, sin red, con un mercado de prueba): lo que se prueba es
lo que saldria hacia OKX, no lo que se le pidio a ccxt. Por eso hay un test que
fija el comportamiento de ccxt que motivo la guardia: si una version nueva lo
cambia, ese test lo dice.
"""

from __future__ import annotations

import ccxt
import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.config import load_settings
from execution import guardia, ids
from execution.guardia import CANCELACION, ENTRADA, PROTECCION, SALIDA, PeticionRechazada, revisar
from strategy.candidates import make_decision_id

T0 = 1_790_035_200_000
DID = make_decision_id("BTC/USDC", "pullback_trend", T0)          # d-20260922T0000-btc-pb
WHITELIST = load_settings().whitelist


# --------------------------------------------------------------------------
# ids
# --------------------------------------------------------------------------


def test_el_decision_id_da_ids_que_okx_acepta():
    assert DID == "d-20260922T0000-btc-pb"
    assert ids.cl_ord_id(DID) == "d20260922T0000btcpb"
    assert ids.algo_cl_ord_id(DID) == "d20260922T0000btcpbOCO"
    assert ids.es_id_okx(ids.cl_ord_id(DID)) and ids.es_id_okx(ids.algo_cl_ord_id(DID))


@given(
    simbolo=st.sampled_from(sorted(load_settings().whitelist)),
    setup=st.sampled_from(["pullback_trend", "range_breakout", "mean_reversion"]),
    velas=st.integers(min_value=0, max_value=6 * 365 * 5),
)
def test_ida_y_vuelta_para_cualquier_decision(simbolo, setup, velas):
    """Deterministas, <= 32, distintos para entrada y OCO, y reversibles (trazabilidad)."""
    did = make_decision_id(simbolo, setup, T0 + velas * 4 * 3600 * 1000)
    entrada, oco = ids.cl_ord_id(did), ids.algo_cl_ord_id(did)
    assert len(oco) <= ids.MAX_LEN and entrada != oco
    assert ids.decision_id_de(entrada) == did == ids.decision_id_de(oco)
    assert ids.cl_ord_id(did) == entrada, "determinista"


@pytest.mark.parametrize("malo", ["", "d-20260922-btc-pb", "hola", "d-20260922T0000-BTC-pb"])
def test_lo_que_no_es_un_decision_id_se_rechaza(malo):
    with pytest.raises(ids.IdInvalido):
        ids.cl_ord_id(malo)


def test_un_id_que_no_es_nuestro_no_se_confunde_con_una_decision():
    """El de broker que pondria ccxt, por ejemplo."""
    with pytest.raises(ids.IdInvalido):
        ids.decision_id_de("6b9ad766b55dBCDE1b2d8ac3998c7b54")


# --------------------------------------------------------------------------
# La guardia, con peticiones construidas por ccxt
# --------------------------------------------------------------------------


def _mercado(simbolo):
    base, quote = simbolo.split("/")
    return {"id": f"{base}-{quote}", "symbol": simbolo, "base": base, "quote": quote,
            "baseId": base, "quoteId": quote, "type": "spot", "spot": True, "margin": False,
            "swap": False, "future": False, "option": False, "contract": False, "linear": None,
            "inverse": None, "settle": None, "active": True,
            "precision": {"amount": 1e-8, "price": 0.1},
            "limits": {"amount": {"min": 1e-5}, "cost": {"min": None}}, "info": {}}


def okx(opciones=None):
    ex = ccxt.okx({"hostname": "eea.okx.com", "options": dict(opciones or {})})
    ex.set_markets([_mercado("BTC/USDC"), _mercado("ADA/USDC")])
    return ex


def adjunto(stop="60000", objetivo="70000", **cambios):
    return {"attachAlgoClOrdId": ids.algo_cl_ord_id(DID), "tpTriggerPx": objetivo, "tpOrdPx": "-1",
            "slTriggerPx": stop, "slOrdPx": "-1", **cambios}


def entrada(ex=None, **cambios):
    params = {"postOnly": True, "clOrdId": ids.cl_ord_id(DID), "tdMode": "cash", "tradeQuoteCcy": "USDC",
              "attachAlgoOrds": [adjunto()], **cambios.pop("params", {})}
    lado, simbolo = cambios.pop("side", "buy"), cambios.pop("simbolo", "BTC/USDC")
    return (ex or okx(guardia.OPCIONES_EXCHANGE)).create_order_request(
        simbolo, "limit", lado, 0.0002, 65000, params)


def oco(ex=None, stop=60000, objetivo=70000, **params):
    base = {"stopLossPrice": stop, "takeProfitPrice": objetivo,
            "algoClOrdId": ids.algo_cl_ord_id(DID), "tdMode": "cash", "tradeQuoteCcy": "USDC", **params}
    return (ex or okx(guardia.OPCIONES_EXCHANGE)).create_order_request(
        "BTC/USDC", "limit", "sell", 0.0002, None, base)


def rechaza(peticion, tipo, texto):
    with pytest.raises(PeticionRechazada) as e:
        revisar(peticion, tipo, decision_id=DID, whitelist=WHITELIST)
    assert any(texto in m for m in e.value.motivos), e.value.motivos


def test_ccxt_manda_la_oco_de_spot_como_margen_por_defecto():
    """EL HECHO que motivo la guardia (ccxt 4.5.82, 23/09/2026). Si una version nueva
    de ccxt lo cambia, este test lo dice y hay que revisar docs/preparacion-fase-4.md."""
    peticion = okx().create_order_request("BTC/USDC", "limit", "sell", 0.0002, None,
                                          {"stopLossPrice": 60000, "takeProfitPrice": 70000})
    assert peticion["tdMode"] == "cross"
    assert "tag" in peticion, "y le pone su id de broker"


def test_la_trampa_no_sale():
    """La OCO tal cual la construye ccxt por defecto: margen y con su id de broker."""
    peticion = okx().create_order_request("BTC/USDC", "limit", "sell", 0.0002, None,
                                          {"stopLossPrice": 60000, "takeProfitPrice": 70000})
    rechaza(peticion, PROTECCION, "regla 1")
    rechaza(peticion, PROTECCION, "tag")


def test_con_las_opciones_de_la_fase_4_salen_bien():
    revisar(entrada(), ENTRADA, decision_id=DID, whitelist=WHITELIST)
    revisar(oco(), PROTECCION, decision_id=DID, whitelist=WHITELIST)


def test_las_opciones_solas_ya_dan_cash_y_sin_broker():
    """Dos sitios, como pide la convencion de las reglas duras: las opciones del
    exchange y la guardia. Aqui, que las opciones hacen su parte sin ayuda."""
    peticion = okx(guardia.OPCIONES_EXCHANGE).create_order_request(
        "BTC/USDC", "limit", "sell", 0.0002, None,
        {"stopLossPrice": 60000, "takeProfitPrice": 70000, "algoClOrdId": ids.algo_cl_ord_id(DID)})
    assert peticion["tdMode"] == "cash" and "tag" not in peticion and "clOrdId" not in peticion


def test_par_fuera_de_la_whitelist():
    rechaza(entrada(simbolo="ADA/USDC"), ENTRADA, "regla 3")


def test_una_entrada_no_vende():
    rechaza(entrada(side="sell"), ENTRADA, "solo compra")


def test_una_entrada_que_puede_cruzar_el_libro_no_sale():
    peticion = okx(guardia.OPCIONES_EXCHANGE).create_order_request(
        "BTC/USDC", "limit", "buy", 0.0002, 65000, {"clOrdId": ids.cl_ord_id(DID), "tdMode": "cash"})
    rechaza(peticion, ENTRADA, "post-only")


def test_el_id_tiene_que_ser_el_de_esta_decision():
    otro = make_decision_id("BTC/USDC", "pullback_trend", T0 + 4 * 3600 * 1000)
    rechaza(entrada(params={"clOrdId": ids.cl_ord_id(otro)}), ENTRADA, "clOrdId")


def test_parametros_de_margen_no_salen():
    peticion = dict(entrada(), ccy="USDC")
    rechaza(peticion, ENTRADA, "no permitido: ccy")


def test_una_entrada_sin_stop_y_objetivo_adjuntos_no_sale():
    """Regla 13: creados al abrir. Prueba 3 del demo (02/10): OKX crea la OCO al llenarse."""
    sin = dict(entrada())
    del sin["attachAlgoOrds"]
    rechaza(sin, ENTRADA, "UN stop y objetivo adjuntos")
    rechaza(entrada(params={"attachAlgoOrds": [adjunto(), adjunto()]}), ENTRADA, "UN stop y objetivo adjuntos")


def test_el_adjunto_de_ccxt_no_vale_sin_nuestro_id():
    """Con `stopLoss`/`takeProfit`, ccxt construye el adjunto SIN `attachAlgoClOrdId`: la OCO no se encontraria."""
    peticion = okx(guardia.OPCIONES_EXCHANGE).create_order_request(
        "BTC/USDC", "limit", "buy", 0.0002, 65000,
        {"postOnly": True, "clOrdId": ids.cl_ord_id(DID), "tdMode": "cash", "tradeQuoteCcy": "USDC",
         "stopLoss": {"triggerPrice": 60000}, "takeProfit": {"triggerPrice": 70000}})
    rechaza(peticion, ENTRADA, "attachAlgoClOrdId")


def test_el_adjunto_con_las_patas_a_mercado_y_el_stop_bajo_la_entrada():
    rechaza(entrada(params={"attachAlgoOrds": [adjunto(tpOrdPx="71000")]}), ENTRADA, "a mercado")
    rechaza(entrada(params={"attachAlgoOrds": [adjunto(stop="66000")]}), ENTRADA, "stop < entrada < objetivo")
    rechaza(entrada(params={"attachAlgoOrds": [adjunto(objetivo="64000")]}), ENTRADA, "stop < entrada < objetivo")
    rechaza(entrada(params={"attachAlgoOrds": [adjunto(tpOrdKind="limit")]}), ENTRADA, "no permitidos")


def test_sin_tradequoteccy_usdc_no_sale_nada():
    """Libro unificado en dolares (30/09): sin el valor explicito, OKX elige la moneda con que se paga."""
    for tipo, p in ((ENTRADA, dict(entrada())), (PROTECCION, dict(oco()))):
        del p["tradeQuoteCcy"]
        rechaza(p, tipo, "tradeQuoteCcy")
    rechaza(entrada(params={"tradeQuoteCcy": "USD"}), ENTRADA, "tradeQuoteCcy 'USD'")


def test_el_objetivo_de_la_oco_a_mercado():
    """Prueba 7 del demo (02/10): OKX contesta 51094 a un objetivo limit en spot."""
    rechaza(oco(tpOrdKind="limit"), PROTECCION, "no permitido: tpOrdKind")
    rechaza(dict(oco(), tpOrdPx="70000"), PROTECCION, "objetivo tiene que salir a mercado")


def test_una_oco_no_lleva_adjuntos():
    rechaza(dict(oco(), attachAlgoOrds=[adjunto()]), PROTECCION, "solo en la entrada")


def test_stop_por_encima_del_objetivo():
    rechaza(oco(stop=71000, objetivo=70000), PROTECCION, "stop <")


def test_stop_limit_no():
    rechaza(oco(slOrdPx=59000), PROTECCION, "a mercado")


def test_la_cancelacion_solo_de_lo_nuestro():
    revisar({"instId": "BTC-USDC", "clOrdId": ids.cl_ord_id(DID)}, CANCELACION,
            decision_id=DID, whitelist=WHITELIST)
    rechaza({"instId": "BTC-USDC", "clOrdId": "otro123"}, CANCELACION, "no es de")


def test_da_todos_los_motivos_a_la_vez():
    """Para arreglarlo de una vez, no motivo a motivo."""
    peticion = dict(okx().create_order_request("BTC/USDC", "limit", "sell", 0.0002, None,
                                               {"stopLossPrice": 71000, "takeProfitPrice": 70000}))
    with pytest.raises(PeticionRechazada) as e:
        revisar(peticion, PROTECCION, decision_id=DID, whitelist=WHITELIST)
    assert len(e.value.motivos) >= 4


# --------------------------------------------------------------------------
# La salida a mercado (flag critica de noticias, "cerrar todo"; decision del propietario del 02/10)
# --------------------------------------------------------------------------


def salida(**cambios):
    params = {"clOrdId": ids.cl_ord_id_salida(DID), "tdMode": "cash", "tradeQuoteCcy": "USDC", "tgtCcy": "base_ccy",
              **cambios.pop("params", {})}
    return okx(guardia.OPCIONES_EXCHANGE).create_order_request("BTC/USDC", "market", cambios.pop("side", "sell"),
                                                                0.0002, None, params)


def test_el_id_de_salida_es_distinto_y_vuelve_a_la_decision():
    sal = ids.cl_ord_id_salida(DID)
    assert ids.es_id_okx(sal) and sal not in (ids.cl_ord_id(DID), ids.algo_cl_ord_id(DID))
    assert ids.decision_id_de(sal) == DID and ids.es_salida(sal)
    assert not ids.es_salida(ids.cl_ord_id(DID)) and not ids.es_salida(ids.algo_cl_ord_id(DID))


def test_la_salida_buena_sale():
    revisar(salida(), SALIDA, decision_id=DID, whitelist=WHITELIST)


def test_la_salida_solo_vende_a_mercado_con_su_id_y_en_cash():
    rechaza(salida(side="buy"), SALIDA, "venta a mercado")
    rechaza(salida(params={"clOrdId": ids.cl_ord_id(DID)}), SALIDA, "el de salida")
    rechaza(dict(salida(), tdMode="cross"), SALIDA, "regla 1")
    rechaza(dict(salida(), tgtCcy="quote_ccy"), SALIDA, "moneda base")
    rechaza(salida(params={"tradeQuoteCcy": "USD"}), SALIDA, "tradeQuoteCcy")
    rechaza(dict(salida(), instId="ADA-USDC"), SALIDA, "regla 3")
