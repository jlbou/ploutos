"""Decide cuando una vela del WebSocket esta cerrada.

EL PROBLEMA (medido el 22/09/2026 contra OKX): `watch_ohlcv` de ccxt devuelve
SOLO la vela en curso, no el historial. Cuando una vela cierra, el siguiente
mensaje ya trae la siguiente. La vela cerrada no vuelve a aparecer nunca.

Fiarse de nuestro reloj para decidir "ya ha cerrado" tampoco vale: con el reloj
atrasado (la maquina de desarrollo iba 10 s por detras) llegariamos tarde, y
con el adelantado marcariamos como cerrada una vela viva. Look-ahead bias.

LA SOLUCION: usar la secuencia del propio exchange. Cuando llega una vela con
timestamp MAYOR, la anterior esta cerrada por definicion: el exchange ha pasado
pagina. Es inmune al desfase de reloj porque no consulta el reloj para nada.

El reloj solo se usa como red de seguridad, para no quedarse con una vela
colgada si una moneda deja de emitir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.clock import timeframe_ms

# Si una vela lleva pendiente mas de este multiplo de su timeframe, se da por
# cerrada aunque no haya llegado la siguiente. Margen amplio a proposito: es
# una red de seguridad, no el mecanismo principal.
STALE_PENDING_MULTIPLE = 3


@dataclass
class CandleSequencer:
    """Convierte el flujo de velas en curso en velas cerradas.

    Una instancia por (simbolo, timeframe).
    """

    timeframe: str
    _pending: list[Any] | None = field(default=None, init=False)

    @property
    def pending_ts(self) -> int | None:
        return None if self._pending is None else int(self._pending[0])

    def feed(self, rows: list[list[Any]]) -> list[list[Any]]:
        """Procesa un mensaje del WebSocket.

        Devuelve las velas que acaban de cerrarse (normalmente 0 o 1).
        """
        closed: list[list[Any]] = []
        for row in sorted(rows, key=lambda r: int(r[0])):
            ts = int(row[0])
            if self._pending is None:
                self._pending = row
                continue
            pending_ts = int(self._pending[0])
            if ts > pending_ts:
                # El exchange ha pasado pagina: la anterior esta cerrada.
                closed.append(self._pending)
                self._pending = row
            elif ts == pending_ts:
                # Misma vela, valores actualizados.
                self._pending = row
            # ts < pending_ts: mensaje viejo o desordenado. Se ignora.
        return closed

    def flush_if_stale(self, now_ms: int) -> list[Any] | None:
        """Red de seguridad: cierra la vela pendiente si lleva demasiado.

        Cubre el caso de una moneda que deja de emitir justo despues de abrir
        una vela. Sin esto, esa vela se quedaria pendiente para siempre.
        """
        if self._pending is None:
            return None
        step = timeframe_ms(self.timeframe)
        age = now_ms - int(self._pending[0])
        if age > step * STALE_PENDING_MULTIPLE:
            stale = self._pending
            self._pending = None
            return stale
        return None
