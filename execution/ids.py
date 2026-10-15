"""Los identificadores que OKX ve, sacados del `decision_id` (fase 4, pieza 1).

OKX: `clOrdId` y `algoClOrdId` son "alfanumericos (mayusculas y minusculas),
solo numeros o solo letras, de HASTA 32 caracteres" (documentacion leida el
23/09/2026, ver docs/preparacion-fase-4.md). El `decision_id` lleva guiones
(`d-20260922T0000-near-pb`): no vale tal cual.

Tres propiedades que no hay que perder:

1. **Deterministas.** El mismo `decision_id` da siempre los mismos ids: es lo que
   permite "consultar antes de reenviar" (idempotencia) y, al arrancar, que la
   conciliacion encuentre en el exchange las ordenes de esta decision.
2. **Reversibles.** Del `clOrdId` se vuelve al `decision_id`: la cadena
   candidato -> IA -> orden -> fill -> cierre (PRD seccion 13) sigue trazable a
   mano, tambien mirando la web de OKX.
3. **Distintos** para la entrada y para su OCO (sufijo `OCO`), que en OKX son dos
   ordenes con su propio id. El sufijo va en mayusculas (`OCO`): la entrada acaba
   siempre en minusculas, asi que ninguna entrada se puede leer como una OCO.
   Y para la VENTA A MERCADO de una salida que no es stop ni objetivo (flag critica de noticias, "cerrar todo";
   decision del propietario del 02/10): sufijo `SAL`, tambien en mayusculas.

PURO: sin red, sin claves, sin reloj.
"""

from __future__ import annotations

import re

MAX_LEN = 32
SUFIJO_OCO = "OCO"   # en MAYUSCULAS: el resto va en minusculas, asi no se confunde nunca
SUFIJO_SALIDA = "SAL"
SUFIJOS = (SUFIJO_OCO, SUFIJO_SALIDA)
_ALFANUMERICO = re.compile(r"^[A-Za-z0-9]{1,32}$")
# Formato de `strategy.candidates.make_decision_id`: d-AAAAMMDDTHHMM-<base>-<setup de 2>.
_DECISION_ID = re.compile(r"^d-(\d{8}T\d{4})-([a-z0-9]+)-([a-z]{2})$")
_CL_ORD_ID = re.compile(r"^d(\d{8}T\d{4})([a-z0-9]+)([a-z]{2})$")


class IdInvalido(ValueError):
    pass


def es_id_okx(valor: str) -> bool:
    """Si OKX lo aceptaria como `clOrdId` / `algoClOrdId`."""
    return bool(_ALFANUMERICO.match(valor or ""))


def cl_ord_id(decision_id: str) -> str:
    """El `clOrdId` de la orden de ENTRADA de esta decision."""
    m = _DECISION_ID.match(decision_id)
    if m is None:
        raise IdInvalido(f"no es un decision_id: {decision_id!r}")
    cid = "d" + "".join(m.groups())
    if not es_id_okx(cid):
        raise IdInvalido(f"{decision_id!r} da {cid!r}, que OKX no aceptaria")
    return cid


def algo_cl_ord_id(decision_id: str) -> str:
    """El `algoClOrdId` de la OCO (stop y objetivo) de esta decision."""
    aid = cl_ord_id(decision_id) + SUFIJO_OCO
    if not es_id_okx(aid):
        raise IdInvalido(f"{decision_id!r} da {aid!r} para la OCO, que OKX no aceptaria")
    return aid


def cl_ord_id_salida(decision_id: str) -> str:
    """El `clOrdId` de la venta a mercado que cierra esta decision fuera de su OCO."""
    sid = cl_ord_id(decision_id) + SUFIJO_SALIDA
    if not es_id_okx(sid):
        raise IdInvalido(f"{decision_id!r} da {sid!r} para la salida, que OKX no aceptaria")
    return sid


def es_salida(id_okx: str) -> bool:
    return (id_okx or "").endswith(SUFIJO_SALIDA)


def decision_id_de(id_okx: str) -> str:
    """El camino de vuelta: de un `clOrdId` o `algoClOrdId` nuestro al `decision_id`."""
    base = next((id_okx[: -len(x)] for x in SUFIJOS if id_okx.endswith(x)), id_okx)
    m = _CL_ORD_ID.match(base)
    if m is None:
        raise IdInvalido(f"no es un id nuestro: {id_okx!r}")
    stamp, simbolo, setup = m.groups()
    return f"d-{stamp}-{simbolo}-{setup}"
