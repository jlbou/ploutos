"""Detector de datos obsoletos (informe seccion 1.3[1]).

Un bot que decide sobre precios de hace diez minutos cree que opera el mercado
y opera un recuerdo. Aqui se comprueba que lo nota.
"""

from __future__ import annotations

import pytest

from core.events import EventBus, EventKind
from data.ingest.staleness import (
    SOURCE_ORDERBOOK,
    SOURCE_TICKER,
    StalenessMonitor,
    candle_source,
)

T0 = 1_790_000_000_000
SEC = 1000


@pytest.fixture
def monitor(settings) -> StalenessMonitor:
    return StalenessMonitor(settings=settings)


# --- umbrales ---


def test_umbrales_del_yaml(monitor, settings):
    assert monitor.threshold_ms(SOURCE_TICKER) == (
        settings.data.staleness.ticker_seconds * 1000
    )
    assert monitor.threshold_ms(candle_source("1m")) == (
        settings.data.staleness.candle_1m_seconds * 1000
    )


def test_los_timeframes_grandes_tienen_umbral_proporcional(monitor):
    """Una vela de 4 h no llega cada 90 s: exigirselo seria un falso positivo."""
    assert monitor.threshold_ms(candle_source("4h")) == 4 * 3600 * 1000 * 1.5
    assert monitor.threshold_ms(candle_source("1h")) == 3600 * 1000 * 1.5


def test_fuente_desconocida_falla(monitor):
    with pytest.raises(ValueError, match="fuente desconocida"):
        monitor.threshold_ms("inventada")


# --- deteccion ---


def test_una_fuente_recien_actualizada_no_esta_stale(monitor):
    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0)
    assert monitor.check(T0 + 5 * SEC) == []
    assert not monitor.is_stale(SOURCE_TICKER, "BTC/USDC")


def test_una_fuente_callada_se_pone_stale(monitor):
    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0)
    newly = monitor.check(T0 + 31 * SEC)  # umbral del ticker: 30 s
    assert len(newly) == 1
    assert monitor.is_stale(SOURCE_TICKER, "BTC/USDC")


def test_justo_en_el_umbral_todavia_no_esta_stale(monitor):
    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0)
    assert monitor.check(T0 + 30 * SEC) == []


def test_no_se_avisa_dos_veces_de_lo_mismo(monitor):
    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0)
    assert len(monitor.check(T0 + 31 * SEC)) == 1
    assert monitor.check(T0 + 60 * SEC) == []  # ya lo sabiamos


def test_un_touch_recupera_la_fuente(monitor):
    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0)
    monitor.check(T0 + 31 * SEC)
    assert monitor.is_stale(SOURCE_TICKER, "BTC/USDC")

    recovered = monitor.touch(SOURCE_TICKER, "BTC/USDC", T0 + 40 * SEC)
    assert recovered is True
    assert not monitor.is_stale(SOURCE_TICKER, "BTC/USDC")


def test_una_fuente_desconocida_se_considera_stale(monitor):
    """Conservador a proposito: sin datos no se puede evaluar la regla 16."""
    assert monitor.is_stale(SOURCE_TICKER, "BTC/USDC")


# --- por simbolo ---


def test_un_simbolo_esta_stale_si_cualquier_fuente_lo_esta(monitor):
    """Sin libro no hay spread, y sin spread no se puede aplicar la regla 16."""
    monitor.touch(candle_source("1m"), "BTC/USDC", T0)
    monitor.touch(SOURCE_ORDERBOOK, "BTC/USDC", T0)
    assert not monitor.symbol_is_stale("BTC/USDC")

    monitor.check(T0 + 200 * SEC)  # el libro (60 s) y las velas (90 s) caducan
    assert monitor.symbol_is_stale("BTC/USDC")


def test_un_simbolo_sin_ninguna_fuente_esta_stale(monitor):
    assert monitor.symbol_is_stale("BTC/USDC")


def test_simbolos_sanos_y_caidos(monitor, settings):
    for symbol in settings.whitelist:
        monitor.touch(candle_source("1m"), symbol, T0)
        monitor.touch(SOURCE_ORDERBOOK, symbol, T0)
    assert monitor.healthy_symbols() == set(settings.whitelist)
    assert monitor.stale_symbols() == set()


# --- degradacion del exchange (PRD seccion 5) ---


def test_una_moneda_caida_no_degrada_el_exchange(monitor, settings):
    for symbol in settings.whitelist:
        monitor.touch(candle_source("1m"), symbol, T0)
        monitor.touch(SOURCE_ORDERBOOK, symbol, T0)
    # solo BTC deja de actualizar
    for symbol in settings.whitelist[1:]:
        monitor.touch(candle_source("1m"), symbol, T0 + 100 * SEC)
        monitor.touch(SOURCE_ORDERBOOK, symbol, T0 + 100 * SEC)
    monitor.check(T0 + 101 * SEC)

    assert monitor.symbol_is_stale(settings.whitelist[0])
    assert not monitor.exchange_is_degraded()


def test_media_whitelist_caida_degrada_el_exchange(monitor, settings):
    """Si cae la mitad, no es un par raro: es la conexion."""
    for symbol in settings.whitelist:
        monitor.touch(candle_source("1m"), symbol, T0)
        monitor.touch(SOURCE_ORDERBOOK, symbol, T0)
    half = len(settings.whitelist) // 2
    for symbol in settings.whitelist[half:]:
        monitor.touch(candle_source("1m"), symbol, T0 + 100 * SEC)
        monitor.touch(SOURCE_ORDERBOOK, symbol, T0 + 100 * SEC)
    monitor.check(T0 + 101 * SEC)

    assert monitor.exchange_is_degraded()


def test_todo_caido_degrada_el_exchange(monitor):
    assert monitor.exchange_is_degraded()


# --- eventos ---


def test_se_emite_evento_al_ponerse_stale(settings):
    bus = EventBus()
    queue = bus.subscribe()
    monitor = StalenessMonitor(settings=settings, bus=bus)

    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0)
    monitor.check(T0 + 31 * SEC)

    event = queue.get_nowait()
    assert event.kind == EventKind.SOURCE_STALE
    assert event.symbol == "BTC/USDC"


def test_se_emite_evento_al_recuperarse(settings):
    bus = EventBus()
    monitor = StalenessMonitor(settings=settings, bus=bus)
    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0)
    monitor.check(T0 + 31 * SEC)

    queue = bus.subscribe()
    monitor.touch(SOURCE_TICKER, "BTC/USDC", T0 + 40 * SEC)

    event = queue.get_nowait()
    assert event.kind == EventKind.SOURCE_RECOVERED
