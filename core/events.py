"""Bus de eventos interno (informe seccion 1.2).

Los componentes no se llaman entre si: publican eventos. Eso permite que la
ingesta, el detector de datos obsoletos, el journal y (en la fase 5) el
WebSocket de la UI consuman lo mismo sin acoplarse.

Todo evento lleva timestamp UTC y puede llevar `decision_id` para encadenar
candidato -> IA -> veredicto -> orden -> fill -> cierre (PRD seccion 13).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.clock import utcnow


class EventKind:
    """Tipos de evento. Constantes, no enum, para que anyadir no rompa nada."""

    # Ingesta (fase 1)
    CANDLE_CLOSED = "candle_closed"
    CANDLE_REJECTED = "candle_rejected"
    GAP_DETECTED = "gap_detected"
    GAP_FILLED = "gap_filled"
    SOURCE_STALE = "source_stale"
    SOURCE_RECOVERED = "source_recovered"
    WS_CONNECTED = "ws_connected"
    WS_DISCONNECTED = "ws_disconnected"
    CLOCK_SKEW = "clock_skew"
    # Sistema
    MODE_CHANGE = "mode_change"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=utcnow)
    symbol: str | None = None
    decision_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        """Forma en la que se guarda en la tabla `events`."""
        import json

        return {
            "ts": self.ts.isoformat(),
            "kind": self.kind,
            "symbol": self.symbol,
            "decision_id": self.decision_id,
            "payload": json.dumps(self.payload, ensure_ascii=False, default=str),
        }


class EventBus:
    """Pub/sub en memoria.

    Los suscriptores lentos no bloquean a los productores: cada uno tiene su
    cola acotada y, si se llena, se descartan los eventos mas antiguos y se
    cuenta el descarte. En un bot de trading es preferible perder una linea de
    log que atascar la ingesta.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._maxsize = maxsize
        self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def publish(self, event: Event) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped += 1
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def emit(
        self,
        kind: str,
        symbol: str | None = None,
        decision_id: str | None = None,
        **payload: Any,
    ) -> Event:
        """Atajo: construye y publica en una linea."""
        event = Event(
            kind=kind, symbol=symbol, decision_id=decision_id, payload=payload
        )
        self.publish(event)
        return event

    @contextlib.asynccontextmanager
    async def subscription(self) -> AsyncIterator[asyncio.Queue[Event]]:
        """Suscripcion con baja garantizada. Esta es la forma recomendada.

            async with bus.subscription() as queue:
                event = await queue.get()

        Se prefiere a `stream()` porque la baja ocurre al salir del bloque,
        pase lo que pase.
        """
        queue = self.subscribe()
        try:
            yield queue
        finally:
            self.unsubscribe(queue)

    async def stream(self) -> AsyncIterator[Event]:
        """Itera eventos indefinidamente.

        CUIDADO: salir del `async for` con `break` o `return` NO da de baja al
        suscriptor: el `finally` de un generador asincrono solo corre al
        cerrarlo (`aclose()`) o al recolectarlo. Si no se consume hasta el
        final, hay que cerrarlo a mano:

            agen = bus.stream()
            try:
                async for event in agen:
                    ...
            finally:
                await agen.aclose()

        Para el caso normal, usa `subscription()`, que no tiene esta trampa.
        """
        async with self.subscription() as queue:
            while True:
                yield await queue.get()
