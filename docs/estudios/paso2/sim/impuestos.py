"""Impuestos del ahorro (plan, seccion 4; propietario, 15/10/2026): tramos de cada anyo natural, coste por FIFO, y las
perdidas netas de un anyo compensan las ganancias de los 4 siguientes. Estudio, no asesoria fiscal."""
from __future__ import annotations

from collections import deque

TRAMOS = ((6_000.0, 0.19), (50_000.0, 0.21), (200_000.0, 0.23), (300_000.0, 0.27), (float("inf"), 0.30))
ANYOS_COMPENSACION = 4


def cuota(base: float) -> float:
    if base <= 0:
        return 0.0
    total, desde = 0.0, 0.0
    for hasta, tipo in TRAMOS:
        if base <= desde:
            break
        total += (min(base, hasta) - desde) * tipo
        desde = hasta
    return total


class Lotes:
    """Las compras de una moneda, por orden. `coste` es el total pagado (con comision)."""

    def __init__(self) -> None:
        self._lotes: deque[list[float]] = deque()            # [cantidad, coste]

    @property
    def cantidad(self) -> float:
        return sum(q for q, _ in self._lotes)

    def comprar(self, cantidad: float, coste: float) -> None:
        if cantidad > 0:
            self._lotes.append([cantidad, coste])

    def vender(self, cantidad: float, neto: float) -> float:
        """Vende `cantidad` (las primeras compras primero) por `neto` (lo cobrado, sin la comision) y devuelve la
        ganancia (o perdida) realizada."""
        coste, falta = 0.0, cantidad
        while falta > 1e-15 and self._lotes:
            q, c = self._lotes[0]
            usa = min(q, falta)
            coste += c * usa / q
            if usa >= q - 1e-15:
                self._lotes.popleft()
            else:
                self._lotes[0] = [q - usa, c * (q - usa) / q]
            falta -= usa
        return neto - coste


def anual(anyo: int, neto: float, pendientes: list[tuple[int, float]]) -> tuple[float, list[tuple[int, float]]]:
    """(impuesto del anyo, perdidas pendientes despues). `pendientes`: (anyo de origen, importe positivo)."""
    vivas = [(a, x) for a, x in pendientes if anyo - a <= ANYOS_COMPENSACION and x > 0]
    if neto < 0:
        return 0.0, vivas + [(anyo, -neto)]
    base, quedan = neto, []
    for a, x in vivas:
        usa = min(base, x)
        base -= usa
        if x - usa > 1e-9:
            quedan.append((a, x - usa))
    return cuota(base), quedan
