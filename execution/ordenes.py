"""Enviar, cancelar y consultar en OKX (fase 4, pieza a): la UNICA pieza que habla con el exchange para ordenes.

SINCRONO, como el resto de servicios de papel (el ejecutor no tiene WebSocket: una vuelta cada 15 s). Recibe
peticiones ya construidas por `execution/peticiones.py` y, JUSTO ANTES de mandarlas, las vuelve a pasar por la
guardia (regla 3, cuarto punto: "justo antes de enviar la orden"; y cada regla dura en dos sitios). Devuelve una
`Respuesta` y nunca lanza por un error de OKX ni de red: quien llama decide (contar errores para DEGRADED, avisar).

**Consultar antes de enviar** (preparacion-fase-4 seccion 3, prueba 5 del demo del 02/10): el `clOrdId` solo es unico
entre ordenes PENDIENTES; reenviar una entrada ya llenada crea OTRA. Por eso:
- antes de enviar una entrada, se consulta su `clOrdId`; solo se envia si OKX no la conoce (`peticiones.tras_consultar`);
- antes de crear una OCO, se consulta su `algoClOrdId`; si hay una viva, no se crea otra (una OCO cancelada o que ya
  salto deja reutilizar el id: prueba 8);
- **un error de red al ENVIAR no se reintenta a ciegas**: se consulta; si OKX la tiene, llego; si no, `SIN_RESPUESTA`
  y la siguiente vuelta vuelve a consultar antes de nada (la peticion podria estar aun en camino).

Verificado en el demo el 02/10 (`docs/preparacion-fase-4.md` 11): una orden o una OCO que no existe contesta `51603`
("Order does not exist"), que ccxt da como `OrderNotFound`; cancelar una orden ya llenada contesta `51400`, tambien
`OrderNotFound`; una OCO cancelada se sigue pudiendo consultar por nuestro `algoClOrdId` (estado `canceled`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import ccxt

from execution import guardia, ids
from execution.conciliacion import OcoEx, OrdenEx
from execution.guardia import CANCELACION, ENTRADA, PROTECCION, SALIDA
from execution.peticiones import TrasConsultar, tras_consultar


class Resultado(StrEnum):
    ENVIADA = "enviada"              # OKX la acepto (o, tras un error de red, resulta que llego)
    YA_ESTABA = "ya_estaba"          # viva en OKX: no se manda otra
    LLENADA = "llenada"              # la entrada ya se lleno: apuntarla, no reenviar
    NO_REENVIAR = "no_reenviar"      # la entrada acabo cancelada: una decision vale UNA vez
    CANCELADA = "cancelada"
    YA_NO_ESTABA = "ya_no_estaba"    # cancelar algo que ya estaba llenado, cancelado o no existia
    RECHAZADA = "rechazada"          # OKX dijo que no (o la guardia): no se reintenta igual
    SIN_RESPUESTA = "sin_respuesta"  # error de red: no se sabe; la siguiente vuelta consulta


@dataclass(frozen=True, slots=True)
class Respuesta:
    resultado: Resultado
    decision_id: str
    detalle: str = ""
    datos: dict[str, Any] | None = None    # la orden u OCO tal como la da OKX, si se consulto

    @property
    def error_de_red(self) -> bool:
        return self.resultado is Resultado.SIN_RESPUESTA


def _texto(exc: Exception) -> str:
    """Tipo y cuerpo de OKX (sin URL ni cabeceras: ccxt no las mete en el mensaje de estos errores)."""
    return f"{type(exc).__name__}: {str(exc)[:300]}"


def _dato(respuesta: dict[str, Any]) -> dict[str, Any] | None:
    datos = (respuesta or {}).get("data") or []
    return datos[0] if datos else None


# --- Consultas --------------------------------------------------------------------------------------------------


def consultar_orden(ex: Any, *, simbolo: str, decision_id: str, salida: bool = False) -> dict[str, Any] | None:
    """La entrada (o la venta de salida) por su `clOrdId`; `None` si OKX no la conoce. Los errores de red SUBEN."""
    cid = ids.cl_ord_id_salida(decision_id) if salida else ids.cl_ord_id(decision_id)
    try:
        return _dato(ex.private_get_trade_order({"instId": simbolo.replace("/", "-"), "clOrdId": cid}))
    except ccxt.OrderNotFound:
        return None


def consultar_oco(ex: Any, *, decision_id: str) -> dict[str, Any] | None:
    """La OCO por su `algoClOrdId` (la ultima con ese id); `None` si OKX no la conoce."""
    try:
        return _dato(ex.private_get_trade_order_algo({"algoClOrdId": ids.algo_cl_ord_id(decision_id)}))
    except ccxt.OrderNotFound:
        return None


# --- Envios -----------------------------------------------------------------------------------------------------


def _guardia(peticion: dict[str, Any], tipo: str, decision_id: str, whitelist: Iterable[str]) -> Respuesta | None:
    try:
        guardia.revisar(peticion, tipo, decision_id=decision_id, whitelist=whitelist)
    except guardia.PeticionRechazada as exc:
        return Respuesta(Resultado.RECHAZADA, decision_id, f"guardia: {exc}")
    return None


_TRAS_CONSULTAR = {TrasConsultar.YA_ESTA: Resultado.YA_ESTABA, TrasConsultar.LLENADA: Resultado.LLENADA,
                   TrasConsultar.NO_REENVIAR: Resultado.NO_REENVIAR}


def enviar_entrada(ex: Any, peticion: dict[str, Any], *, decision_id: str, simbolo: str,
                         whitelist: Iterable[str]) -> Respuesta:
    """La compra post-only con su stop y objetivo adjuntos, si OKX no la tiene ya."""
    if (rechazo := _guardia(peticion, ENTRADA, decision_id, whitelist)) is not None:
        return rechazo
    try:
        antes = consultar_orden(ex, simbolo=simbolo, decision_id=decision_id)
        que = tras_consultar(antes["state"] if antes else None)
    except ccxt.NetworkError as exc:
        return Respuesta(Resultado.SIN_RESPUESTA, decision_id, f"al consultar: {_texto(exc)}")
    except Exception as exc:  # noqa: BLE001 - un estado desconocido o un error de OKX: no se envia nada
        return Respuesta(Resultado.RECHAZADA, decision_id, f"al consultar: {_texto(exc)}")
    if que is not TrasConsultar.ENVIAR:
        return Respuesta(_TRAS_CONSULTAR[que], decision_id, f"OKX ya la tiene: {antes['state']}", antes)
    try:
        r = ex.private_post_trade_order(peticion)
        return Respuesta(Resultado.ENVIADA, decision_id, datos=_dato(r))
    except ccxt.NetworkError as exc:
        return _llego(lambda: consultar_orden(ex, simbolo=simbolo, decision_id=decision_id), decision_id, exc)
    except ccxt.BaseError as exc:
        return Respuesta(Resultado.RECHAZADA, decision_id, _texto(exc))


def enviar_salida(ex: Any, peticion: dict[str, Any], *, decision_id: str, simbolo: str,
                        whitelist: Iterable[str]) -> Respuesta:
    """La venta a mercado de una salida que no es stop ni objetivo, una sola vez (consulta antes, como la entrada).

    Quien llama cancela ANTES la OCO de esa decision: si no, la OCO podria saltar despues y vender otra vez.
    """
    if (rechazo := _guardia(peticion, SALIDA, decision_id, whitelist)) is not None:
        return rechazo
    try:
        antes = consultar_orden(ex, simbolo=simbolo, decision_id=decision_id, salida=True)
        que = tras_consultar(antes["state"] if antes else None)
    except ccxt.NetworkError as exc:
        return Respuesta(Resultado.SIN_RESPUESTA, decision_id, f"al consultar: {_texto(exc)}")
    except Exception as exc:  # noqa: BLE001
        return Respuesta(Resultado.RECHAZADA, decision_id, f"al consultar: {_texto(exc)}")
    if que is not TrasConsultar.ENVIAR:
        return Respuesta(_TRAS_CONSULTAR[que], decision_id, f"OKX ya la tiene: {antes['state']}", antes)
    try:
        r = ex.private_post_trade_order(peticion)
        return Respuesta(Resultado.ENVIADA, decision_id, datos=_dato(r))
    except ccxt.NetworkError as exc:
        return _llego(lambda: consultar_orden(ex, simbolo=simbolo, decision_id=decision_id, salida=True),
                      decision_id, exc)
    except ccxt.BaseError as exc:
        return Respuesta(Resultado.RECHAZADA, decision_id, _texto(exc))


def crear_oco(ex: Any, peticion: dict[str, Any], *, decision_id: str, whitelist: Iterable[str]) -> Respuesta:
    """La OCO de venta (regla 13), si no hay ya una viva con nuestro `algoClOrdId`."""
    if (rechazo := _guardia(peticion, PROTECCION, decision_id, whitelist)) is not None:
        return rechazo
    try:
        antes = consultar_oco(ex, decision_id=decision_id)
    except ccxt.NetworkError as exc:
        return Respuesta(Resultado.SIN_RESPUESTA, decision_id, f"al consultar: {_texto(exc)}")
    except ccxt.BaseError as exc:
        return Respuesta(Resultado.RECHAZADA, decision_id, f"al consultar: {_texto(exc)}")
    if antes is not None and antes.get("state") == "live":
        return Respuesta(Resultado.YA_ESTABA, decision_id, "ya hay una OCO viva con este id", antes)
    try:
        r = ex.private_post_trade_order_algo(peticion)
        return Respuesta(Resultado.ENVIADA, decision_id, datos=_dato(r))
    except ccxt.NetworkError as exc:
        return _llego(lambda: consultar_oco(ex, decision_id=decision_id), decision_id, exc, viva=True)
    except ccxt.BaseError as exc:
        return Respuesta(Resultado.RECHAZADA, decision_id, _texto(exc))


def _llego(consulta: Callable[[], dict[str, Any] | None], decision_id: str, exc: Exception, *,
           viva: bool = False) -> Respuesta:
    """Tras un error de red al enviar: si OKX la tiene (viva, para una OCO), llego. Si no se sabe, no se reenvia."""
    try:
        dato = consulta()
    except Exception as exc2:  # noqa: BLE001
        return Respuesta(Resultado.SIN_RESPUESTA, decision_id, f"{_texto(exc)}; y al consultar: {_texto(exc2)}")
    if dato is not None and (not viva or dato.get("state") == "live"):
        return Respuesta(Resultado.ENVIADA, decision_id, f"llego pese al error de red ({type(exc).__name__})", dato)
    return Respuesta(Resultado.SIN_RESPUESTA, decision_id, f"{_texto(exc)}; OKX aun no la tiene")


def cancelar_entrada(ex: Any, peticion: dict[str, Any], *, decision_id: str,
                           whitelist: Iterable[str]) -> Respuesta:
    """Caducada, pausa, o el resto de una entrada a medias (OKX crea entonces la OCO adjunta por lo llenado)."""
    if (rechazo := _guardia(peticion, CANCELACION, decision_id, whitelist)) is not None:
        return rechazo
    return _cancelar(lambda: ex.private_post_trade_cancel_order(peticion), decision_id)


def cancelar_oco(ex: Any, peticion: dict[str, Any], *, decision_id: str, whitelist: Iterable[str]) -> Respuesta:
    if (rechazo := _guardia(peticion, CANCELACION, decision_id, whitelist)) is not None:
        return rechazo
    return _cancelar(lambda: ex.private_post_trade_cancel_algos([peticion]), decision_id)


def _cancelar(llamada: Callable[[], dict[str, Any]], decision_id: str) -> Respuesta:
    try:
        r = llamada()
        return Respuesta(Resultado.CANCELADA, decision_id, datos=_dato(r))
    except ccxt.OrderNotFound as exc:
        return Respuesta(Resultado.YA_NO_ESTABA, decision_id, _texto(exc))
    except ccxt.NetworkError as exc:
        return Respuesta(Resultado.SIN_RESPUESTA, decision_id, _texto(exc))
    except ccxt.BaseError as exc:
        return Respuesta(Resultado.RECHAZADA, decision_id, _texto(exc))


# --- De lo que da OKX a lo que mira la conciliacion -------------------------------------------------------------


def _num(valor: Any) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def orden_ex(dato: dict[str, Any]) -> OrdenEx:
    """Una orden de OKX (`/trade/order`, `orders-pending`, `orders-history`)."""
    return OrdenEx(cl_ord_id=str(dato.get("clOrdId") or ""), simbolo=str(dato["instId"]).replace("-", "/"),
                   cantidad=_num(dato.get("sz")), llenado=_num(dato.get("accFillSz")), estado=str(dato.get("state")))


def oco_ex(dato: dict[str, Any]) -> OcoEx:
    """Una OCO de OKX (`/trade/order-algo`, `orders-algo-pending`, `orders-algo-history`).

    De una OCO que SALTO (`effective`) se leen `actualSide` (sl | tp) y `actualPx` (prueba 10, 03/10: `actualPx` llega
    VACIO). La conciliacion solo los usa para el texto; el precio de salida de verdad sale de la orden lanzada.
    """
    pata = str(dato.get("actualSide") or "") or None
    precio = _num(dato.get("actualPx")) or None
    return OcoEx(algo_cl_ord_id=str(dato.get("algoClOrdId") or ""), simbolo=str(dato["instId"]).replace("-", "/"),
                 cantidad=_num(dato.get("sz")), estado=str(dato.get("state")), pata=pata, precio_salida=precio)
