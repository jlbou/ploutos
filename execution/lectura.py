"""Lo que el ejecutor LEE de OKX (fase 4, pieza c): saldo, ordenes, OCO y mejores bids. Sin escribir nada en OKX.

Los errores de OKX o de red SUBEN: quien llama los cuenta para DEGRADED (3 seguidos, decision 6 del 26/09) y no se
corrige nada con una foto a medias.

- **Solo lo posterior a la foto del saldo** (`desde_ms`): las ordenes de las pruebas del 02/10 llevan ids con nuestro
  formato y ya estan dentro de la foto.
- Ordenes: las pendientes siempre; el historial (las llenadas y canceladas: explican llenados y cierres) en la pasada
  completa de la conciliacion. OKX guarda 7 dias de historial de ordenes y 3 meses de OCO.
- Los bids, del libro del DEMO (regla 6: "con datos del exchange"); en el demo el libro es artificial
  (`preparacion-fase-4.md` 12) pero es el que valora lo que hay.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from execution.equity import SaldoOKX, saldo_de_ccxt

LIMITE = "100"


@dataclass
class Ordenes:
    ordenes: list[dict[str, Any]] = field(default_factory=list)   # tal como las da OKX
    ocos: list[dict[str, Any]] = field(default_factory=list)

    def orden(self, cl_ord_id: str) -> dict[str, Any] | None:
        return next((o for o in self.ordenes if o.get("clOrdId") == cl_ord_id), None)

    def oco(self, algo_cl_ord_id: str) -> dict[str, Any] | None:
        """La ultima con ese id (se puede cancelar y volver a crear con el mismo)."""
        mias = [a for a in self.ocos if a.get("algoClOrdId") == algo_cl_ord_id]
        return max(mias, key=lambda a: int(a.get("cTime") or 0)) if mias else None


def _datos(r: dict[str, Any]) -> list[dict[str, Any]]:
    return list((r or {}).get("data") or [])


def _desde(filas: Iterable[dict[str, Any]], desde_ms: int) -> list[dict[str, Any]]:
    return [f for f in filas if int(f.get("cTime") or 0) >= desde_ms]


def saldo(ex: Any, whitelist: Iterable[str]) -> SaldoOKX:
    return saldo_de_ccxt(ex.fetch_balance(), tuple(whitelist))


def ordenes(ex: Any, *, desde_ms: int, completo: bool) -> Ordenes:
    out = Ordenes()
    vistas: set[str] = set()
    fuentes = [ex.private_get_trade_orders_pending({"instType": "SPOT", "limit": LIMITE})]
    if completo:
        fuentes.append(ex.private_get_trade_orders_history({"instType": "SPOT", "limit": LIMITE}))
    for r in fuentes:
        for o in _desde(_datos(r), desde_ms):
            if o.get("ordId") not in vistas:
                vistas.add(o.get("ordId"))
                out.ordenes.append(o)
    algos = [ex.private_get_trade_orders_algo_pending({"ordType": "oco", "instType": "SPOT", "limit": LIMITE})]
    if completo:
        for estado in ("effective", "canceled"):
            algos.append(ex.private_get_trade_orders_algo_history(
                {"ordType": "oco", "state": estado, "instType": "SPOT", "limit": LIMITE}))
    vistas = set()
    for r in algos:
        for a in _desde(_datos(r), desde_ms):
            if a.get("algoId") not in vistas:
                vistas.add(a.get("algoId"))
                out.ocos.append(a)
    return out


def bids(ex: Any, simbolos: Iterable[str]) -> dict[str, float]:
    """El mejor bid de cada simbolo; uno que no responda se queda fuera (la lectura de equity sale no fiable)."""
    out = {}
    for s in sorted(set(simbolos)):
        libro = ex.fetch_order_book(s, 1)
        if libro.get("bids"):
            out[s] = float(libro["bids"][0][0])
    return out
