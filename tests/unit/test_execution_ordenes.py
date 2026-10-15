"""Enviar, cancelar y consultar (`execution/ordenes.py`, pieza a), contra un OKX FALSO: sin red ni claves.

El falso contesta como OKX en el demo el 02/10 (`docs/preparacion-fase-4.md` 11): `51603` -> `OrderNotFound` para lo
que no existe, `51400` -> `OrderNotFound` al cancelar algo ya llenado. Los errores, las clases de ccxt de verdad.
"""

from __future__ import annotations

import ccxt

from core.config import load_settings
from execution import ids, ordenes, peticiones
from execution.ordenes import Resultado
from strategy.candidates import make_decision_id
from tests.unit.test_execution_peticiones import EX, precios_de

WL = load_settings().whitelist
NEAR = make_decision_id("NEAR/USDC", "pullback_trend", 1_790_035_200_000)
NO_EXISTE = ccxt.OrderNotFound('okx {"code":"51603","data":[],"msg":"Order does not exist"}')
RED = ccxt.RequestTimeout("okx GET https://eea.okx.com/api/v5/trade/order request timeout")


def entrada():
    return peticiones.entrada(EX, decision_id=NEAR, simbolo="NEAR/USDC", precios=precios_de("NEAR/USDC", 1.0),
                              whitelist=WL)


def oco():
    p = precios_de("NEAR/USDC", 1.0)
    return peticiones.proteccion(EX, decision_id=NEAR, simbolo="NEAR/USDC", cantidad=p.cantidad, stop=p.stop,
                                 objetivo=p.objetivo, whitelist=WL)


class OkxFalso:
    """Cada metodo saca su siguiente respuesta de una cola: un dict, o una excepcion que lanza."""

    def __init__(self, **colas):
        self.colas = {k: list(v) for k, v in colas.items()}
        self.llamadas: list[tuple[str, object]] = []

    def __getattr__(self, nombre):
        if nombre.startswith("_") or nombre in ("colas", "llamadas"):
            raise AttributeError(nombre)

        def metodo(peticion):
            self.llamadas.append((nombre, peticion))
            r = self.colas[nombre].pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return metodo

    def enviadas(self):
        return [n for n, _ in self.llamadas if n.startswith("private_post")]


def okx_orden(estado, llenado="0"):
    return {"code": "0", "data": [{"instId": "NEAR-USDC", "clOrdId": ids.cl_ord_id(NEAR), "state": estado,
                                   "sz": "3", "accFillSz": llenado}]}


ACEPTADA = {"code": "0", "data": [{"clOrdId": ids.cl_ord_id(NEAR), "ordId": "1", "sCode": "0"}]}


def enviar(ex, peticion=None):
    return ordenes.enviar_entrada(ex, peticion or entrada(), decision_id=NEAR, simbolo="NEAR/USDC",
                                        whitelist=WL)


# --- Entradas ---------------------------------------------------------------------------------------------------


def test_una_entrada_nueva_se_consulta_y_se_envia():
    ex = OkxFalso(private_get_trade_order=[NO_EXISTE], private_post_trade_order=[ACEPTADA])
    r = enviar(ex)
    assert r.resultado is Resultado.ENVIADA
    assert [n for n, _ in ex.llamadas] == ["private_get_trade_order", "private_post_trade_order"], "consulta ANTES"
    assert ex.llamadas[0][1] == {"instId": "NEAR-USDC", "clOrdId": ids.cl_ord_id(NEAR)}


def test_una_entrada_que_okx_ya_tiene_no_se_reenvia():
    """Prueba 5 del demo: reenviar una llenada crea OTRA orden. Aqui no se manda nada."""
    for estado, que in (("live", Resultado.YA_ESTABA), ("partially_filled", Resultado.YA_ESTABA),
                        ("filled", Resultado.LLENADA), ("canceled", Resultado.NO_REENVIAR)):
        ex = OkxFalso(private_get_trade_order=[okx_orden(estado)])
        r = enviar(ex)
        assert r.resultado is que and ex.enviadas() == [], estado
        assert r.datos["state"] == estado


def test_un_estado_desconocido_no_se_toma_por_no_existe():
    ex = OkxFalso(private_get_trade_order=[okx_orden("estado_nuevo_de_okx")])
    r = enviar(ex)
    assert r.resultado is Resultado.RECHAZADA and ex.enviadas() == []


def test_sin_poder_consultar_no_se_envia():
    ex = OkxFalso(private_get_trade_order=[RED])
    r = enviar(ex)
    assert r.resultado is Resultado.SIN_RESPUESTA and r.error_de_red and ex.enviadas() == []


def test_error_de_red_al_enviar_y_la_orden_llego():
    ex = OkxFalso(private_get_trade_order=[NO_EXISTE, okx_orden("live")], private_post_trade_order=[RED])
    r = enviar(ex)
    assert r.resultado is Resultado.ENVIADA and "llego pese" in r.detalle
    assert ex.enviadas() == ["private_post_trade_order"], "una sola vez"


def test_error_de_red_al_enviar_y_okx_no_la_tiene_no_se_reenvia_a_ciegas():
    """Podria estar aun en camino: la siguiente vuelta consulta otra vez antes de nada."""
    ex = OkxFalso(private_get_trade_order=[NO_EXISTE, NO_EXISTE], private_post_trade_order=[RED])
    r = enviar(ex)
    assert r.resultado is Resultado.SIN_RESPUESTA and ex.enviadas() == ["private_post_trade_order"]


def test_okx_la_rechaza():
    no = ccxt.InvalidOrder('okx {"code":"1","data":[{"sCode":"51008","sMsg":"Insufficient balance"}]}')
    ex = OkxFalso(private_get_trade_order=[NO_EXISTE], private_post_trade_order=[no])
    r = enviar(ex)
    assert r.resultado is Resultado.RECHAZADA and "51008" in r.detalle


def test_la_guardia_mira_otra_vez_justo_antes_de_enviar():
    """Una peticion tocada despues de construirla (margen, sin el stop adjunto...) no sale ni se consulta."""
    ex = OkxFalso()
    mala = dict(entrada(), tdMode="cross")
    r = enviar(ex, mala)
    assert r.resultado is Resultado.RECHAZADA and "regla 1" in r.detalle and ex.llamadas == []
    sin_adjunto = {k: v for k, v in entrada().items() if k != "attachAlgoOrds"}
    assert (enviar(ex, sin_adjunto)).resultado is Resultado.RECHAZADA and ex.llamadas == []


# --- OCO --------------------------------------------------------------------------------------------------------


def okx_oco(estado):
    return {"code": "0", "data": [{"instId": "NEAR-USDC", "algoClOrdId": ids.algo_cl_ord_id(NEAR), "state": estado,
                                   "sz": "3"}]}


def crear(ex, peticion=None):
    return ordenes.crear_oco(ex, peticion or oco(), decision_id=NEAR, whitelist=WL)


def test_una_oco_nueva_se_crea():
    ex = OkxFalso(private_get_trade_order_algo=[NO_EXISTE], private_post_trade_order_algo=[ACEPTADA])
    assert (crear(ex)).resultado is Resultado.ENVIADA
    assert ex.llamadas[0] == ("private_get_trade_order_algo", {"algoClOrdId": ids.algo_cl_ord_id(NEAR)})


def test_con_una_oco_viva_no_se_crea_otra():
    ex = OkxFalso(private_get_trade_order_algo=[okx_oco("live")])
    assert (crear(ex)).resultado is Resultado.YA_ESTABA and ex.enviadas() == []


def test_una_oco_cancelada_o_que_salto_deja_reutilizar_el_id():
    """Prueba 8 del demo: cancelada, se recrea con el mismo algoClOrdId."""
    for estado in ("canceled", "effective"):
        ex = OkxFalso(private_get_trade_order_algo=[okx_oco(estado)], private_post_trade_order_algo=[ACEPTADA])
        assert (crear(ex)).resultado is Resultado.ENVIADA, estado


def test_error_de_red_al_crear_la_oco():
    ex = OkxFalso(private_get_trade_order_algo=[NO_EXISTE, okx_oco("live")], private_post_trade_order_algo=[RED])
    assert (crear(ex)).resultado is Resultado.ENVIADA
    ex = OkxFalso(private_get_trade_order_algo=[NO_EXISTE, okx_oco("canceled")], private_post_trade_order_algo=[RED])
    assert (crear(ex)).resultado is Resultado.SIN_RESPUESTA, "una cancelada no es la que se acaba de mandar"


def test_la_guardia_tambien_para_la_oco():
    ex = OkxFalso()
    r = crear(ex, dict(oco(), tpOrdKind="limit"))
    assert r.resultado is Resultado.RECHAZADA and ex.llamadas == []


# --- Cancelar ---------------------------------------------------------------------------------------------------


def test_cancelar_el_resto_de_una_entrada():
    p = peticiones.cancelar_entrada(decision_id=NEAR, simbolo="NEAR/USDC", whitelist=WL)
    ex = OkxFalso(private_post_trade_cancel_order=[ACEPTADA])
    r = ordenes.cancelar_entrada(ex, p, decision_id=NEAR, whitelist=WL)
    assert r.resultado is Resultado.CANCELADA and ex.llamadas == [("private_post_trade_cancel_order", p)]


def test_cancelar_algo_ya_llenado_no_es_un_error():
    """51400 en el demo (02/10): "the order has been filled, canceled or does not exist"."""
    p = peticiones.cancelar_entrada(decision_id=NEAR, simbolo="NEAR/USDC", whitelist=WL)
    ya = ccxt.OrderNotFound('okx {"code":"1","data":[{"sCode":"51400","sMsg":"Order cancellation failed"}]}')
    ex = OkxFalso(private_post_trade_cancel_order=[ya])
    assert (ordenes.cancelar_entrada(ex, p, decision_id=NEAR, whitelist=WL)).resultado is Resultado.YA_NO_ESTABA


def test_cancelar_la_oco_va_en_lista_y_con_red_caida_no_se_sabe():
    p = peticiones.cancelar_oco(decision_id=NEAR, simbolo="NEAR/USDC", whitelist=WL)
    ex = OkxFalso(private_post_trade_cancel_algos=[ACEPTADA, RED])
    assert (ordenes.cancelar_oco(ex, p, decision_id=NEAR, whitelist=WL)).resultado is Resultado.CANCELADA
    assert ex.llamadas[0] == ("private_post_trade_cancel_algos", [p])
    assert (ordenes.cancelar_oco(ex, p, decision_id=NEAR, whitelist=WL)).resultado is Resultado.SIN_RESPUESTA


def test_no_se_cancela_lo_que_no_es_nuestro():
    otro = make_decision_id("NEAR/USDC", "range_breakout", 1_790_035_200_000)
    p = peticiones.cancelar_entrada(decision_id=otro, simbolo="NEAR/USDC", whitelist=WL)
    ex = OkxFalso()
    r = ordenes.cancelar_entrada(ex, p, decision_id=NEAR, whitelist=WL)
    assert r.resultado is Resultado.RECHAZADA and ex.llamadas == []


# --- De OKX a la conciliacion -----------------------------------------------------------------------------------


def test_la_orden_y_la_oco_de_okx_se_leen_como_las_espera_la_conciliacion():
    """Campos tal como vinieron en el demo el 02/10 (`docs/archivo/pruebas-demo/resultado-02-10.json`, prueba 4)."""
    o = ordenes.orden_ex({"instId": "BTC-USDC", "clOrdId": "d20261002T2035btcpi", "state": "partially_filled",
                          "sz": "0.00018202", "accFillSz": "0.00012135"})
    assert (o.simbolo, o.cantidad, o.llenado, o.estado) == ("BTC/USDC", 0.00018202, 0.00012135, "partially_filled")
    a = ordenes.oco_ex({"instId": "BTC-USDC", "algoClOrdId": "d20261002T2035btcpiOCO", "state": "live",
                        "sz": "0.00012135", "actualSide": "", "actualPx": ""})
    assert (a.simbolo, a.cantidad, a.estado, a.pata, a.precio_salida) == ("BTC/USDC", 0.00012135, "live", None, None)


# --- La salida a mercado ----------------------------------------------------------------------------------------


def salida():
    return peticiones.salida(EX, decision_id=NEAR, simbolo="NEAR/USDC", cantidad=3.0, whitelist=WL)


def vender(ex):
    return ordenes.enviar_salida(ex, salida(), decision_id=NEAR, simbolo="NEAR/USDC", whitelist=WL)


def test_la_salida_se_consulta_por_su_propio_id_y_se_envia_una_vez():
    ex = OkxFalso(private_get_trade_order=[NO_EXISTE], private_post_trade_order=[ACEPTADA])
    assert (vender(ex)).resultado is Resultado.ENVIADA
    assert ex.llamadas[0][1] == {"instId": "NEAR-USDC", "clOrdId": ids.cl_ord_id_salida(NEAR)}
    ex = OkxFalso(private_get_trade_order=[okx_orden("filled")])
    assert (vender(ex)).resultado is Resultado.LLENADA and ex.enviadas() == []


def test_error_de_red_al_vender_no_se_vende_dos_veces():
    ex = OkxFalso(private_get_trade_order=[NO_EXISTE, NO_EXISTE], private_post_trade_order=[RED])
    assert (vender(ex)).resultado is Resultado.SIN_RESPUESTA and ex.enviadas() == ["private_post_trade_order"]
