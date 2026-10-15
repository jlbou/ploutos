"""Todas las peticiones que el bot manda a OKX, construidas en UN solo sitio (fase 4, piezas 3 y 4).

PURO: construye con `ccxt` DE VERDAD (`create_order_request`, sin red ni claves: basta con los
mercados cargados) y pasa CADA peticion por la guardia (`execution/guardia.py`) antes de devolverla.
Quien la envie recibe algo que ya ha pasado la guardia, o una excepcion: no hay otro camino.

Por que en un solo sitio (docs/preparacion-fase-4.md): ccxt transforma lo que se le pide (manda las
OCO de spot como margen si no se le dice otra cosa), y una peticion construida a mano en otra parte
del codigo se saltaria esa comprobacion. Con esto, el test "todas las peticiones del bot salen en
`cash`" que pide la preparacion de la fase 4 prueba de verdad todas.

Tambien aqui la regla de la idempotencia: el `clOrdId` de OKX solo es unico entre ordenes PENDIENTES,
asi que antes de reenviar una entrada hay que CONSULTARLA (`tras_consultar`), nunca reenviar a ciegas.

Lo que dijo el demo (02/10, `docs/preparacion-fase-4.md` 11): la entrada lleva su stop y su objetivo ADJUNTOS
(OKX crea la OCO al llenarse, prueba 3), las dos patas a mercado (el objetivo no puede ser limit en spot, prueba 7),
y `tradeQuoteCcy: "USDC"` explicito en la entrada y en la OCO (prueba 9).
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from execution import guardia, ids
from execution.guardia import CANCELACION, ENTRADA, PROTECCION, SALIDA
from execution.precios import PreciosOrden


def entrada(ex: Any, *, decision_id: str, simbolo: str, precios: PreciosOrden,
            whitelist: Iterable[str]) -> dict[str, Any]:
    """Compra limit post-only (decision 3 de la fase 4) con nuestro `clOrdId`, en `cash`, con el stop y el
    objetivo ADJUNTOS (regla 13: creados al abrir; OKX crea la OCO con nuestro `algoClOrdId` al llenarse).

    `precios` ya viene al tick (`execution.precios.al_tick`): ccxt redondea el precio al mas
    cercano y podria subir la entrada un tick; con los precios ya al tick, no cambia nada.
    """
    adjunto = {"attachAlgoClOrdId": ids.algo_cl_ord_id(decision_id),
               "tpTriggerPx": ex.price_to_precision(simbolo, precios.objetivo), "tpOrdPx": "-1",
               "slTriggerPx": ex.price_to_precision(simbolo, precios.stop), "slOrdPx": "-1"}
    peticion = ex.create_order_request(
        simbolo, "limit", "buy", precios.cantidad, precios.entrada,
        {"postOnly": True, "clOrdId": ids.cl_ord_id(decision_id), "tdMode": "cash",
         "tradeQuoteCcy": guardia.COTIZACION, "attachAlgoOrds": [adjunto]})
    guardia.revisar(peticion, ENTRADA, decision_id=decision_id, whitelist=whitelist)
    return peticion


def proteccion(ex: Any, *, decision_id: str, simbolo: str, cantidad: float, stop: float, objetivo: float,
               whitelist: Iterable[str]) -> dict[str, Any]:
    """La OCO de venta por la cantidad que HAY (regla 13), con el stop a mercado y en `cash`.

    `cantidad` es la que de verdad se recibio (con la comision en USDC, decision 2 de la fase 4, es la
    llenada); ccxt la trunca al lote. El stop y el objetivo, ya al tick.
    """
    peticion = ex.create_order_request(
        simbolo, "limit", "sell", cantidad, None,
        {"stopLossPrice": stop, "takeProfitPrice": objetivo,
         "algoClOrdId": ids.algo_cl_ord_id(decision_id), "tdMode": "cash", "tradeQuoteCcy": guardia.COTIZACION})
    guardia.revisar(peticion, PROTECCION, decision_id=decision_id, whitelist=whitelist)
    return peticion


def salida(ex: Any, *, decision_id: str, simbolo: str, cantidad: float, whitelist: Iterable[str]) -> dict[str, Any]:
    """Venta a mercado de lo que HAY de esta decision (flag critica de noticias, "cerrar todo"; decision del 02/10).

    Antes hay que cancelar su OCO: la OCO no congela la moneda (preparacion seccion 5) y, si saltara despues, venderia
    otra vez lo mismo.
    """
    peticion = ex.create_order_request(
        simbolo, "market", "sell", cantidad, None,
        {"clOrdId": ids.cl_ord_id_salida(decision_id), "tdMode": "cash", "tradeQuoteCcy": guardia.COTIZACION,
         "tgtCcy": "base_ccy"})
    guardia.revisar(peticion, SALIDA, decision_id=decision_id, whitelist=whitelist)
    return peticion


def cancelar_entrada(*, decision_id: str, simbolo: str, whitelist: Iterable[str]) -> dict[str, Any]:
    peticion = {"instId": simbolo.replace("/", "-"), "clOrdId": ids.cl_ord_id(decision_id)}
    guardia.revisar(peticion, CANCELACION, decision_id=decision_id, whitelist=whitelist)
    return peticion


def cancelar_oco(*, decision_id: str, simbolo: str, whitelist: Iterable[str]) -> dict[str, Any]:
    peticion = {"instId": simbolo.replace("/", "-"), "algoClOrdId": ids.algo_cl_ord_id(decision_id)}
    guardia.revisar(peticion, CANCELACION, decision_id=decision_id, whitelist=whitelist)
    return peticion


# --- Consultar antes de reenviar --------------------------------------------------------------


class TrasConsultar(StrEnum):
    ENVIAR = "enviar"              # OKX no la conoce: se envia (primera vez, o no llego)
    YA_ESTA = "ya_esta"            # viva o llenada a medias: no se envia otra
    LLENADA = "llenada"            # se lleno mientras no mirabamos: apuntar el llenado, no reenviar
    NO_REENVIAR = "no_reenviar"    # acabo cancelada: una decision vale UNA vez


# Estados de orden de OKX (GET /api/v5/trade/order, campo `state`).
_ESTADOS = {
    "live": TrasConsultar.YA_ESTA,
    "partially_filled": TrasConsultar.YA_ESTA,
    "filled": TrasConsultar.LLENADA,
    "canceled": TrasConsultar.NO_REENVIAR,
    "mmp_canceled": TrasConsultar.NO_REENVIAR,
}


class EstadoDesconocido(Exception):
    pass


def tras_consultar(estado: str | None) -> TrasConsultar:
    """Que hacer con una entrada segun lo que OKX dice de su `clOrdId`. `None` = no existe.

    Un estado que no conocemos NO se toma por "no existe": eso llevaria a enviar una orden repetida.
    Se para y se avisa (la conciliacion lo cuenta).
    """
    if estado is None:
        return TrasConsultar.ENVIAR
    try:
        return _ESTADOS[estado]
    except KeyError:
        raise EstadoDesconocido(f"estado de orden de OKX desconocido: {estado!r}") from None
