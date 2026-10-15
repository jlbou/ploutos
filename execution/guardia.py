"""La guardia: lo ultimo que mira una peticion antes de salir hacia OKX (fase 4, pieza 2).

Recibe la peticion YA CONSTRUIDA (lo que `ccxt` va a mandar, de
`create_order_request`) y dice si sale o no. Mira la peticion final y no lo que
se le pidio a ccxt a proposito: ccxt la transforma por el camino, y la trampa
que motivo esta pieza es justo esa (ver docs/preparacion-fase-4.md):

- **Regla 1.** ccxt 4.5.82 manda las OCO y los stops de spot con
  `tdMode: "cross"`, es decir, como orden de MARGEN. Aqui, cualquier peticion de
  entrada o de proteccion sin `tdMode == "cash"` no sale, ni con parametros
  propios de margen (`ccy`, `posSide`, `lever`, `reduceOnly`...).
- **Regla 3, cuarto punto:** el par, de la whitelist, justo antes de enviar.
- **Solo largos:** una entrada solo compra; una proteccion solo vende.
- **Decisiones del propietario del 24/09:** entrada post-only; stop a mercado.
- **Ids propios y deterministas** (`execution.ids`): sin ellos ccxt pone el suyo
  de broker, y la idempotencia ("consultar antes de reenviar") no tendria que
  consultar.

Lo que dijeron las 9 pruebas del demo (02/10, `docs/preparacion-fase-4.md` 11) y decidio el propietario:
- **`tradeQuoteCcy: "USDC"` explicito** en la entrada y en la OCO (libro unificado en dolares del 30/09): si OKX
  cambiara el valor por defecto, el bot pagaria con otra moneda sin decirlo.
- **Toda entrada lleva su stop y su objetivo ADJUNTOS** (`attachAlgoOrds`, prueba 3: OKX crea la OCO al llenarse, con
  nuestro `algoClOrdId`). Uno solo, con nuestro id, stop < entrada < objetivo, las dos patas a mercado. Lleno a medias,
  el ejecutor cancela el resto y OKX crea la OCO por lo llenado (prueba 4, decision del propietario del 02/10).
- **El objetivo, a mercado** (`tpOrdPx = -1`): OKX no admite objetivo limit en spot (prueba 7, `51094`).
- **La SALIDA a mercado** (decision del propietario del 02/10: flag critica de noticias o "cerrar todo"): una venta `market`,
  en `cash`, por la cantidad en moneda base, con el id de salida de la decision (`ids.cl_ord_id_salida`).

PURO: no manda nada, no tiene claves.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from execution import ids

# Las opciones con las que se crea el exchange de ccxt en la fase 4. Con ellas,
# ccxt construye las OCO en `cash` y no anyade su id de broker (comprobado en
# local el 24/09/2026). La guardia no se fia: mira la peticion igualmente.
OPCIONES_EXCHANGE = {"defaultMarginMode": "cash", "brokerId": None}

ENTRADA, PROTECCION, CANCELACION, SALIDA = "entrada", "proteccion", "cancelacion", "salida"
# Parametros que solo existen para margen o derivados, o que no son nuestros.
PROHIBIDOS = ("ccy", "posSide", "lever", "reduceOnly", "closeFraction", "tag", "tpOrdKind")
COTIZACION = "USDC"
# Lo unico que puede llevar el stop y objetivo adjuntos a una entrada (la forma probada en el demo el 02/10).
CLAVES_ADJUNTO = frozenset({"attachAlgoClOrdId", "slTriggerPx", "slOrdPx", "tpTriggerPx", "tpOrdPx"})


class PeticionRechazada(Exception):
    def __init__(self, motivos: list[str]) -> None:
        super().__init__("; ".join(motivos))
        self.motivos = motivos


def _numero(valor: Any) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def revisar(peticion: dict[str, Any], tipo: str, *, decision_id: str, whitelist: Iterable[str]) -> None:
    """No devuelve nada si la peticion puede salir; si no, `PeticionRechazada` con TODOS los motivos."""
    motivos: list[str] = []
    if tipo not in (ENTRADA, PROTECCION, CANCELACION, SALIDA):
        raise ValueError(f"tipo de peticion desconocido: {tipo}")

    simbolo = str(peticion.get("instId", "")).replace("-", "/")
    if simbolo not in set(whitelist):
        motivos.append(f"regla 3: {simbolo or '(sin par)'} no esta en la whitelist")

    if tipo == CANCELACION:
        propio = peticion.get("clOrdId") or peticion.get("algoClOrdId")
        esperados = {ids.cl_ord_id(decision_id), ids.algo_cl_ord_id(decision_id)}
        if propio not in esperados:
            motivos.append(f"cancelacion de un id que no es de {decision_id}: {propio!r}")
        if motivos:
            raise PeticionRechazada(motivos)
        return

    if peticion.get("tdMode") != "cash":
        motivos.append(f"regla 1: tdMode {peticion.get('tdMode')!r}, tiene que ser 'cash' (spot, sin margen)")
    for clave in PROHIBIDOS:
        if clave in peticion:
            motivos.append(f"parametro no permitido: {clave}")
    if peticion.get("tradeQuoteCcy") != COTIZACION:
        motivos.append(f"tradeQuoteCcy {peticion.get('tradeQuoteCcy')!r}: tiene que ser {COTIZACION!r} explicito "
                       "(libro unificado en dolares)")
    tamanyo = _numero(peticion.get("sz"))
    if tamanyo is None or tamanyo <= 0:
        motivos.append(f"tamanyo invalido: {peticion.get('sz')!r}")

    if tipo == ENTRADA:
        if peticion.get("side") != "buy":
            motivos.append("una entrada solo compra (spot, solo largos)")
        if peticion.get("ordType") != "post_only":
            motivos.append(f"la entrada tiene que ser post-only, no {peticion.get('ordType')!r}")
        if peticion.get("clOrdId") != ids.cl_ord_id(decision_id):
            motivos.append(f"clOrdId {peticion.get('clOrdId')!r}: tiene que ser el de {decision_id}")
        precio = _numero(peticion.get("px"))
        if precio is None or precio <= 0:
            motivos.append(f"precio invalido: {peticion.get('px')!r}")
        motivos += _adjuntos(peticion.get("attachAlgoOrds"), decision_id, precio)

    if tipo == SALIDA:
        if peticion.get("side") != "sell" or peticion.get("ordType") != "market":
            motivos.append(f"la salida es una venta a mercado, no '{peticion.get('side')} {peticion.get('ordType')}'")
        if peticion.get("clOrdId") != ids.cl_ord_id_salida(decision_id):
            motivos.append(f"clOrdId {peticion.get('clOrdId')!r}: tiene que ser el de salida de {decision_id}")
        if peticion.get("tgtCcy", "base_ccy") != "base_ccy":
            motivos.append(f"tgtCcy {peticion.get('tgtCcy')!r}: la salida vende una cantidad de la moneda base")
        if "attachAlgoOrds" in peticion:
            motivos.append("parametro no permitido: attachAlgoOrds (solo en la entrada)")

    if tipo == PROTECCION:
        if "attachAlgoOrds" in peticion:
            motivos.append("parametro no permitido: attachAlgoOrds (solo en la entrada)")
        if str(peticion.get("tpOrdPx")) != "-1":
            motivos.append("el objetivo tiene que salir a mercado (tpOrdPx = -1): en spot OKX no admite limit")
        if peticion.get("side") != "sell":
            motivos.append("una proteccion solo vende (cierra un largo)")
        if peticion.get("ordType") != "oco":
            motivos.append(f"la proteccion tiene que ser una OCO, no {peticion.get('ordType')!r}")
        if peticion.get("algoClOrdId") != ids.algo_cl_ord_id(decision_id):
            motivos.append(f"algoClOrdId {peticion.get('algoClOrdId')!r}: tiene que ser el de {decision_id}")
        if "clOrdId" in peticion:
            motivos.append("una OCO no lleva clOrdId (seria el de broker de ccxt)")
        if str(peticion.get("slOrdPx")) != "-1":
            motivos.append("el stop tiene que salir a mercado (slOrdPx = -1): un stop limit puede no llenarse")
        stop, objetivo = _numero(peticion.get("slTriggerPx")), _numero(peticion.get("tpTriggerPx"))
        if stop is None or objetivo is None or not (0 < stop < objetivo):
            motivos.append(f"stop {peticion.get('slTriggerPx')!r} y objetivo {peticion.get('tpTriggerPx')!r}: "
                           f"hace falta 0 < stop < objetivo")

    if motivos:
        raise PeticionRechazada(motivos)


def _adjuntos(adjuntos: Any, decision_id: str, precio: float | None) -> list[str]:
    """El stop y el objetivo adjuntos a una entrada (regla 13: creados al abrir)."""
    if not isinstance(adjuntos, list) or len(adjuntos) != 1 or not isinstance(adjuntos[0], dict):
        return ["la entrada tiene que llevar UN stop y objetivo adjuntos (attachAlgoOrds, regla 13)"]
    a = adjuntos[0]
    motivos = []
    sobran = sorted(set(a) - CLAVES_ADJUNTO)
    if sobran:
        motivos.append(f"adjunto con parametros no permitidos: {sobran}")
    if a.get("attachAlgoClOrdId") != ids.algo_cl_ord_id(decision_id):
        motivos.append(f"attachAlgoClOrdId {a.get('attachAlgoClOrdId')!r}: tiene que ser el de {decision_id}")
    if str(a.get("slOrdPx")) != "-1" or str(a.get("tpOrdPx")) != "-1":
        motivos.append("las dos patas adjuntas a mercado (slOrdPx = tpOrdPx = -1)")
    stop, objetivo = _numero(a.get("slTriggerPx")), _numero(a.get("tpTriggerPx"))
    if stop is None or objetivo is None or precio is None or not (0 < stop < precio < objetivo):
        motivos.append(f"adjunto: stop {a.get('slTriggerPx')!r}, entrada {precio!r} y objetivo "
                       f"{a.get('tpTriggerPx')!r}: hace falta 0 < stop < entrada < objetivo")
    return motivos
