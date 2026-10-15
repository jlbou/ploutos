"""Tiempo UTC, velas cerradas y desfase de reloj."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.clock import (
    SkewReading,
    candle_is_closed,
    floor_to_timeframe,
    from_ms,
    next_utc_midnight,
    timeframe_ms,
    to_ms,
    utc_day_start,
    utcnow,
    utcnow_ms,
)


def test_utcnow_siempre_lleva_timezone():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_to_ms_rechaza_datetime_sin_timezone():
    """Un datetime ingenuo es un bug esperando a pasar en produccion."""
    with pytest.raises(ValueError, match="sin timezone"):
        to_ms(datetime(2026, 9, 22, 12, 0, 0))


def test_round_trip_ms():
    dt = datetime(2026, 9, 22, 14, 5, 0, tzinfo=UTC)
    assert from_ms(to_ms(dt)) == dt


@pytest.mark.parametrize(
    "timeframe,expected_ms",
    [("1m", 60_000), ("5m", 300_000), ("15m", 900_000),
     ("1h", 3_600_000), ("4h", 14_400_000)],
)
def test_duracion_de_timeframes(timeframe, expected_ms):
    assert timeframe_ms(timeframe) == expected_ms


def test_timeframe_desconocido():
    with pytest.raises(ValueError, match="timeframe desconocido"):
        timeframe_ms("7m")


# --- velas cerradas (informe 1.3[1]: evita look-ahead bias) ---


def test_vela_en_curso_no_esta_cerrada():
    open_ms = 1_790_000_000_000
    # Un segundo despues de abrir la vela de 1 m: sigue viva.
    assert not candle_is_closed(open_ms, "1m", open_ms + 1_000)


def test_vela_cerrada_justo_al_cumplirse_el_intervalo():
    open_ms = 1_790_000_000_000
    assert candle_is_closed(open_ms, "1m", open_ms + 60_000)


def test_vela_no_cerrada_un_milisegundo_antes():
    """El caso limite importa: aqui es donde se cuela el look-ahead bias."""
    open_ms = 1_790_000_000_000
    assert not candle_is_closed(open_ms, "1m", open_ms + 59_999)


def test_vela_de_4h_necesita_4h():
    open_ms = 1_790_000_000_000
    assert not candle_is_closed(open_ms, "4h", open_ms + 3 * 3_600_000)
    assert candle_is_closed(open_ms, "4h", open_ms + 4 * 3_600_000)


def test_floor_to_timeframe_alinea():
    ts = 1_790_000_123_456
    aligned = floor_to_timeframe(ts, "5m")
    assert aligned <= ts
    assert aligned % timeframe_ms("5m") == 0
    assert ts - aligned < timeframe_ms("5m")


def test_floor_es_idempotente():
    ts = floor_to_timeframe(utcnow_ms(), "15m")
    assert floor_to_timeframe(ts, "15m") == ts


# --- dia UTC (reglas 10 y 11 se resetean a las 00:00 UTC) ---


def test_inicio_de_dia_utc():
    dt = datetime(2026, 9, 22, 23, 59, 59, tzinfo=UTC)
    assert utc_day_start(dt) == datetime(2026, 9, 22, 0, 0, 0, tzinfo=UTC)


def test_proxima_medianoche_utc():
    dt = datetime(2026, 9, 22, 23, 59, 59, tzinfo=UTC)
    assert next_utc_midnight(dt) == datetime(2026, 9, 23, 0, 0, 0, tzinfo=UTC)


def test_medianoche_exacta_avanza_un_dia_entero():
    dt = datetime(2026, 9, 22, 0, 0, 0, tzinfo=UTC)
    assert next_utc_midnight(dt) == datetime(2026, 9, 23, 0, 0, 0, tzinfo=UTC)


# --- desfase de reloj ---


def test_sin_desfase():
    reading = SkewReading(local_ms=1_000_000, remote_ms=1_000_000, round_trip_ms=0)
    assert reading.skew_seconds == 0.0
    assert reading.is_acceptable(2.0)


def test_desfase_corrige_media_latencia():
    """Con 200 ms de ida y vuelta, 100 ms son latencia, no desfase."""
    reading = SkewReading(local_ms=1_000_100, remote_ms=1_000_000, round_trip_ms=200)
    assert reading.skew_seconds == pytest.approx(0.0)


def test_desfase_grande_se_detecta():
    """El caso que encontramos el 22/09/2026: reloj local 10 s atrasado."""
    reading = SkewReading(
        local_ms=1_790_000_000_000,
        remote_ms=1_790_000_010_000,
        round_trip_ms=400,
    )
    assert reading.skew_seconds == pytest.approx(-10.2, abs=0.05)
    assert not reading.is_acceptable(2.0)


def test_el_desfase_se_juzga_en_valor_absoluto():
    adelantado = SkewReading(local_ms=1_005_000, remote_ms=1_000_000, round_trip_ms=0)
    atrasado = SkewReading(local_ms=1_000_000, remote_ms=1_005_000, round_trip_ms=0)
    assert not adelantado.is_acceptable(2.0)
    assert not atrasado.is_acceptable(2.0)
