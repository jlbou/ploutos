"""Bus de eventos.

Lo importante: un suscriptor lento (la UI de la fase 5, por ejemplo) no puede
atascar la ingesta. Es preferible perder una linea de log que dejar de recibir
precios.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from core.events import Event, EventBus, EventKind


def test_un_suscriptor_recibe_lo_publicado():
    bus = EventBus()
    queue = bus.subscribe()
    bus.emit(EventKind.CANDLE_CLOSED, symbol="BTC/USDC", close=100.0)

    event = queue.get_nowait()
    assert event.kind == EventKind.CANDLE_CLOSED
    assert event.symbol == "BTC/USDC"
    assert event.payload["close"] == 100.0


def test_todos_los_suscriptores_reciben_lo_mismo():
    bus = EventBus()
    queues = [bus.subscribe() for _ in range(3)]
    bus.emit(EventKind.GAP_DETECTED, symbol="ETH/USDC")
    assert all(q.get_nowait().kind == EventKind.GAP_DETECTED for q in queues)


def test_sin_suscriptores_no_falla():
    EventBus().emit(EventKind.STARTUP)


def test_desuscribirse_deja_de_recibir():
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    bus.emit(EventKind.STARTUP)
    assert queue.empty()


def test_un_suscriptor_lento_no_bloquea_al_productor():
    """El caso que importa: la cola se llena y la ingesta sigue."""
    bus = EventBus(maxsize=5)
    bus.subscribe()  # nadie lo consume
    for i in range(100):
        bus.emit(EventKind.CANDLE_CLOSED, seq=i)
    assert bus.dropped > 0


def test_al_llenarse_se_pierde_lo_viejo_no_lo_nuevo():
    """En trading, el precio de hace un minuto importa menos que el de ahora."""
    bus = EventBus(maxsize=3)
    queue = bus.subscribe()
    for i in range(10):
        bus.emit(EventKind.CANDLE_CLOSED, seq=i)

    seen = []
    while not queue.empty():
        seen.append(queue.get_nowait().payload["seq"])
    assert seen[-1] == 9


def test_todo_evento_lleva_timestamp_utc():
    event = Event(kind=EventKind.STARTUP)
    assert event.ts.tzinfo is not None


def test_el_decision_id_viaja_en_el_evento():
    bus = EventBus()
    queue = bus.subscribe()
    bus.emit(EventKind.GAP_DETECTED, decision_id="d-7")
    assert queue.get_nowait().decision_id == "d-7"


def test_to_row_serializa_para_la_base_de_datos():
    event = Event(kind="x", symbol="BTC/USDC", payload={"a": 1, "b": [1, 2]})
    row = event.to_row()
    assert json.loads(row["payload"]) == {"a": 1, "b": [1, 2]}
    assert row["symbol"] == "BTC/USDC"


def test_to_row_aguanta_objetos_no_serializables():
    """Un payload con un objeto raro no puede tumbar el journal."""
    from datetime import UTC, datetime

    event = Event(kind="x", payload={"cuando": datetime(2026, 9, 22, tzinfo=UTC)})
    assert "2026-09-22" in event.to_row()["payload"]


async def test_stream_itera_eventos():
    bus = EventBus()
    received = []

    async def consume():
        async for event in bus.stream():
            received.append(event)
            if len(received) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    bus.emit(EventKind.STARTUP)
    bus.emit(EventKind.SHUTDOWN)
    await asyncio.wait_for(task, timeout=1.0)

    assert [e.kind for e in received] == [EventKind.STARTUP, EventKind.SHUTDOWN]


async def test_subscription_da_de_baja_al_salir():
    """La API recomendada: la baja ocurre pase lo que pase."""
    bus = EventBus()
    async with bus.subscription() as queue:
        bus.emit(EventKind.STARTUP)
        assert queue.get_nowait().kind == EventKind.STARTUP
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_subscription_da_de_baja_aunque_haya_excepcion():
    bus = EventBus()
    with pytest.raises(RuntimeError):
        async with bus.subscription():
            raise RuntimeError("algo revienta dentro")
    assert bus.subscriber_count == 0


async def test_stream_se_desuscribe_al_cerrarlo():
    """Salir del `async for` con return NO basta: hay que cerrar el generador.

    Es el motivo de que `subscription()` sea la API recomendada. Sin este
    cierre explicito, cada desconexion de la UI en la fase 5 dejaria una cola
    muerta que el bus seguiria llenando.
    """
    bus = EventBus()
    agen = bus.stream()

    async def consume():
        async for _ in agen:
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    bus.emit(EventKind.STARTUP)
    await asyncio.wait_for(task, timeout=1.0)

    await agen.aclose()
    assert bus.subscriber_count == 0
